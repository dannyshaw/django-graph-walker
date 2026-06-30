"""Export action — serialize walk results to fixtures or write to another database."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction
from django.db.models.fields.files import FieldFile

from django_graph_walker.discovery import FieldClass, get_model_fields
from django_graph_walker.result import WalkResult

logger = logging.getLogger(__name__)

# Anonymizer value: either a callable (instance, ctx) -> value, or a faker provider string.
AnonymizerValue = Callable[..., Any] | str


class _FixtureEncoder(DjangoJSONEncoder):
    """JSON encoder handling Django field edge cases beyond DjangoJSONEncoder.

    Handles: FieldFile, bytes, memoryview, set/frozenset.
    """

    def default(self, o: Any) -> Any:
        if isinstance(o, FieldFile):
            return o.name if o.name else None
        if isinstance(o, bytes):
            return o.decode("utf-8", errors="replace")
        if isinstance(o, memoryview):
            return bytes(o).decode("utf-8", errors="replace")
        if isinstance(o, (set, frozenset)):
            return list(o)
        return super().default(o)


class Export:
    """Export collected instances to fixtures or another database.

    Usage:
        result = GraphWalker(spec).walk(article)

        # Export to JSON fixture (structured data)
        data = Export().to_fixture_data(result)

        # Export to JSON string
        json_str = Export().to_fixture(result)

        # Export to file
        Export().to_file(result, 'dev_data.json')

        # Export to another database
        Export().to_database(result, target_db='dev')

        # With anonymization
        Export(
            anonymizers={'Author.email': 'email', 'Author.name': lambda m, ctx: 'Anon'},
        ).to_fixture(result)
    """

    def __init__(
        self,
        *,
        format: str = "json",
        use_natural_keys: bool = False,
        anonymizers: dict[str, AnonymizerValue] | None = None,
    ):
        if format != "json":
            raise ValueError(
                f"Only 'json' format is supported, got '{format}'. "
                f"Non-JSON formats may be added in a future version."
            )
        self.format = format
        self.use_natural_keys = use_natural_keys
        self.anonymizers = anonymizers or {}
        self._faker: Any = None

    def _get_faker(self) -> Any:
        """Lazy-load faker instance."""
        if self._faker is None:
            from faker import Faker

            self._faker = Faker()
        return self._faker

    def _resolve_anonymizer(self, key: str, instance: models.Model, ctx: dict) -> Any:
        """Resolve an anonymizer value for a field."""
        anon = self.anonymizers[key]
        if callable(anon):
            return anon(instance, ctx)
        # It's a faker provider string
        faker = self._get_faker()
        provider = getattr(faker, anon, None)
        if provider is None:
            raise ValueError(
                f"Unknown faker provider '{anon}'. "
                f"Pass a callable instead, or use a valid faker method name."
            )
        return provider()

    def _build_visited_pks(self, walk_result: WalkResult) -> set[tuple[str, Any]]:
        """Build a set of (model_label_lower, pk) for O(1) membership checks."""
        visited: set[tuple[str, Any]] = set()
        for instance in walk_result:
            visited.add((instance._meta.label_lower, instance.pk))
        return visited

    def _build_visited_instances(
        self, walk_result: WalkResult
    ) -> dict[tuple[str, Any], models.Model]:
        """Build a lookup from (model_label_lower, pk) to instance."""
        lookup: dict[tuple[str, Any], models.Model] = {}
        for instance in walk_result:
            lookup[(instance._meta.label_lower, instance.pk)] = instance
        return lookup

    def _serialize_instance(
        self,
        instance: models.Model,
        visited_pks: set[tuple[str, Any]],
        visited_instances: dict[tuple[str, Any], models.Model],
        ctx: dict,
    ) -> dict[str, Any]:
        """Serialize a single model instance to a fixture dict, entirely from memory.

        - FK/O2O: nulled out if target not in visited_pks
        - M2M (auto-created through only): filtered to PKs in visited_pks
        - Explicit through M2M: skipped (through records are serialized separately)
        - Anonymizers: applied inline
        - Natural keys: supported for FK and PK
        """
        model = type(instance)
        model_name = model.__name__
        model_label = instance._meta.label_lower
        fields_data: dict[str, Any] = {}

        # Local fields (value fields + FK/O2O)
        for field in model._meta.local_fields:
            if field.primary_key:
                continue

            field_name = field.name
            anon_key = f"{model_name}.{field_name}"

            if anon_key in self.anonymizers:
                fields_data[field_name] = self._resolve_anonymizer(anon_key, instance, ctx)
                continue

            if field.remote_field:
                # FK or O2O — read raw attname (e.g. author_id)
                fk_value = getattr(instance, field.attname, None)
                if fk_value is not None:
                    target_label = field.related_model._meta.label_lower
                    if (target_label, fk_value) not in visited_pks:
                        # Target not in walk result — null out
                        fk_value = None
                    elif self.use_natural_keys and fk_value is not None:
                        # Try natural key serialization
                        target_instance = visited_instances.get((target_label, fk_value))
                        if target_instance is not None and hasattr(target_instance, "natural_key"):
                            fk_value = target_instance.natural_key()
                fields_data[field_name] = fk_value
            else:
                fields_data[field_name] = field.value_from_object(instance)

        # M2M fields (only auto-created through tables)
        for field in model._meta.local_many_to_many:
            field_name = field.name
            anon_key = f"{model_name}.{field_name}"

            if anon_key in self.anonymizers:
                fields_data[field_name] = self._resolve_anonymizer(anon_key, instance, ctx)
                continue

            # Skip explicit through tables — they are serialized as their own records
            if not field.remote_field.through._meta.auto_created:
                continue

            target_label = field.related_model._meta.label_lower
            manager = getattr(instance, field_name)

            # Try prefetch cache first (no DB query)
            try:
                cached = manager.all()._result_cache
                if cached is not None:
                    pks = [obj.pk for obj in cached if (target_label, obj.pk) in visited_pks]
                    fields_data[field_name] = pks
                    continue
            except AttributeError:
                pass

            # No prefetch cache — empty list rather than hitting DB
            fields_data[field_name] = []

        # Build the fixture record
        pk = instance.pk
        if self.use_natural_keys and hasattr(instance, "natural_key"):
            pk = None

        return {
            "model": model_label,
            "pk": pk,
            "fields": fields_data,
        }

    def to_fixture_data(
        self, walk_result: WalkResult, ctx: dict | None = None
    ) -> list[dict[str, Any]]:
        """Serialize walk result to a list of fixture dicts.

        Returns structured data suitable for post-processing before JSON encoding.
        Instances are ordered by dependency (FK targets before FK sources).
        Does not query the database — works entirely from in-memory instances.
        """
        ctx = ctx or {}
        visited_pks = self._build_visited_pks(walk_result)
        visited_instances = self._build_visited_instances(walk_result)
        ordered = self._get_ordered_instances(walk_result)

        return [
            self._serialize_instance(instance, visited_pks, visited_instances, ctx)
            for instance in ordered
        ]

    def to_fixture(self, walk_result: WalkResult, ctx: dict | None = None) -> str:
        """Serialize walk result to a JSON fixture string.

        Instances are ordered by dependency (FK targets before FK sources).
        Does not query the database — works entirely from in-memory instances.
        """
        data = self.to_fixture_data(walk_result, ctx)
        return json.dumps(data, indent=2, cls=_FixtureEncoder)

    def to_file(
        self,
        walk_result: WalkResult,
        path: str,
        ctx: dict | None = None,
    ) -> None:
        """Export walk result to a fixture file."""
        output = self.to_fixture(walk_result, ctx)
        filepath = Path(path)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(output)
        logger.info(f"Exported {walk_result.instance_count} instances to {path}")

    def to_database(
        self,
        walk_result: WalkResult,
        *,
        target_db: str,
        ctx: dict | None = None,
    ) -> dict[tuple[type[models.Model], int], models.Model]:
        """Export walk result to another database, remapping PKs and FKs.

        Returns a mapping from (original_model, original_pk) to new instance.
        """
        ctx = ctx or {}

        # Get instances in dependency order
        ordered_models = walk_result.topological_order()
        by_model = walk_result.by_model()
        in_scope = set(by_model.keys())

        # Map from (model, old_pk) -> new_pk
        pk_map: dict[tuple[type[models.Model], int], int] = {}
        # Map from (model, old_pk) -> new instance
        instance_map: dict[tuple[type[models.Model], int], models.Model] = {}

        with transaction.atomic(using=target_db):
            # First pass: create all instances with FK remapping
            for model in ordered_models:
                instances = by_model.get(model, [])
                for instance in instances:
                    new_instance = self._copy_instance_to_db(
                        instance, model, target_db, pk_map, in_scope, ctx
                    )
                    old_key = (model, instance.pk)
                    pk_map[old_key] = new_instance.pk
                    instance_map[old_key] = new_instance

            # Second pass: set M2M relationships
            for model in ordered_models:
                instances = by_model.get(model, [])
                for instance in instances:
                    old_key = (model, instance.pk)
                    new_instance = instance_map[old_key]
                    self._copy_m2m(instance, new_instance, model, target_db, pk_map, in_scope)

        return instance_map

    def _copy_instance_to_db(
        self,
        instance: models.Model,
        model: type[models.Model],
        target_db: str,
        pk_map: dict[tuple[type[models.Model], int], int],
        in_scope: set[type[models.Model]],
        ctx: dict,
    ) -> models.Model:
        """Create a copy of an instance in the target database."""
        new_instance = model()

        # Only copy value fields and forward FK/O2O; reverse relations, M2M,
        # and GenericRelation are handled in the second pass or skipped.
        _COPYABLE = {
            FieldClass.VALUE,
            FieldClass.FK_IN_SCOPE,
            FieldClass.FK_OUT_OF_SCOPE,
            FieldClass.O2O_IN_SCOPE,
            FieldClass.O2O_OUT_OF_SCOPE,
        }

        fields = get_model_fields(model, in_scope=in_scope)
        for fi in fields:
            if fi.field_class not in _COPYABLE:
                continue

            anon_key = f"{model.__name__}.{fi.name}"
            if anon_key in self.anonymizers:
                value = self._resolve_anonymizer(anon_key, instance, ctx)
                setattr(new_instance, fi.name, value)
                continue

            if fi.field_class == FieldClass.VALUE:
                value = getattr(instance, fi.name, None)
                if value is not None:
                    setattr(new_instance, fi.name, value)

            elif fi.field_class in (FieldClass.FK_IN_SCOPE, FieldClass.O2O_IN_SCOPE):
                # Remap FK to new PK in target DB
                related = getattr(instance, fi.name, None)
                if related is not None:
                    target_model = fi.related_model
                    old_key = (target_model, related.pk)
                    new_pk = pk_map.get(old_key)
                    if new_pk is not None:
                        # Set using the _id attribute for efficiency
                        setattr(new_instance, f"{fi.name}_id", new_pk)
                    else:
                        # Target not in walk result — try to keep original reference
                        # This can happen with self-referential null FKs
                        try:
                            setattr(new_instance, fi.name, related)
                        except Exception:
                            pass

            elif fi.field_class in (FieldClass.FK_OUT_OF_SCOPE, FieldClass.O2O_OUT_OF_SCOPE):
                # Out-of-scope FK: skip — target data may not exist in target DB.
                # For nullable FKs this is safe (stays null).
                # For non-nullable FKs, the caller must ensure the target exists.
                pass

        new_instance.save(using=target_db)
        return new_instance

    def _copy_m2m(
        self,
        original: models.Model,
        new_instance: models.Model,
        model: type[models.Model],
        target_db: str,
        pk_map: dict[tuple[type[models.Model], int], int],
        in_scope: set[type[models.Model]],
    ) -> None:
        """Copy M2M relationships to the new instance in the target DB."""
        fields = get_model_fields(model, in_scope=in_scope)
        for fi in fields:
            if fi.field_class == FieldClass.M2M_IN_SCOPE:
                original_manager = getattr(original, fi.name)
                new_manager = getattr(new_instance, fi.name)
                target_model = fi.related_model

                new_pks = []
                for related in original_manager.all():
                    old_key = (target_model, related.pk)
                    new_pk = pk_map.get(old_key)
                    if new_pk is not None:
                        new_pks.append(new_pk)

                if new_pks:
                    new_manager.set(new_pks)

            elif fi.field_class == FieldClass.M2M_OUT_OF_SCOPE:
                # Out-of-scope M2M targets may not exist in target DB
                pass

    def _get_ordered_instances(self, walk_result: WalkResult) -> list[models.Model]:
        """Get all instances ordered by model dependency (FK targets first)."""
        ordered_models = walk_result.topological_order()
        by_model = walk_result.by_model()

        result = []
        for model in ordered_models:
            instances = by_model.get(model, [])
            # Sort by PK for deterministic output
            instances.sort(key=lambda i: i.pk)
            result.extend(instances)

        return result
