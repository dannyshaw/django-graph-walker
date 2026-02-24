"""Export action — serialize walk results to fixtures or write to another database."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional, Union

from django.core import serializers
from django.db import models, transaction

from django_graph_walker.discovery import FieldClass, get_model_fields
from django_graph_walker.result import WalkResult

logger = logging.getLogger(__name__)

# Anonymizer value: either a callable (instance, ctx) -> value, or a faker provider string.
AnonymizerValue = Union[Callable[..., Any], str]


class Export:
    """Export collected instances to fixtures or another database.

    Usage:
        result = GraphWalker(spec).walk(article)

        # Export to JSON fixture
        json_str = Export(format='json').to_fixture(result)

        # Export to file
        Export(format='json').to_file(result, 'dev_data.json')

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
        anonymizers: Optional[dict[str, AnonymizerValue]] = None,
    ):
        self.format = format
        self.use_natural_keys = use_natural_keys
        self.anonymizers = anonymizers or {}
        self._faker = None

    def _get_faker(self):
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

    def _anonymize_instance_data(
        self,
        model: type[models.Model],
        instance: models.Model,
        fields_dict: dict[str, Any],
        ctx: dict,
    ) -> dict[str, Any]:
        """Apply anonymization to a field dict."""
        model_name = model.__name__
        result = dict(fields_dict)
        for field_name in list(result.keys()):
            key = f"{model_name}.{field_name}"
            if key in self.anonymizers:
                result[field_name] = self._resolve_anonymizer(key, instance, ctx)
        return result

    def to_fixture(self, walk_result: WalkResult, ctx: Optional[dict] = None) -> str:
        """Serialize walk result to a JSON fixture string.

        Instances are ordered by dependency (FK targets before FK sources).
        """
        ctx = ctx or {}
        ordered = self._get_ordered_instances(walk_result)

        if not self.anonymizers:
            # Fast path: use Django's built-in serializer
            return serializers.serialize(
                self.format,
                ordered,
                indent=2,
                use_natural_foreign_keys=self.use_natural_keys,
                use_natural_primary_keys=self.use_natural_keys,
            )

        # Slow path: serialize, then apply anonymization
        raw = serializers.serialize(
            self.format,
            ordered,
            indent=2,
            use_natural_foreign_keys=self.use_natural_keys,
            use_natural_primary_keys=self.use_natural_keys,
        )
        data = json.loads(raw)

        # Build instance lookup for anonymizer callbacks
        instance_map = {}
        for instance in ordered:
            model_label = instance._meta.label_lower
            instance_map[(model_label, instance.pk)] = instance

        for item in data:
            model_label = item["model"]
            pk = item["pk"]
            instance = instance_map.get((model_label, pk))
            if instance is None:
                continue
            model = type(instance)
            item["fields"] = self._anonymize_instance_data(model, instance, item["fields"], ctx)

        return json.dumps(data, indent=2)

    def to_file(
        self,
        walk_result: WalkResult,
        path: str,
        ctx: Optional[dict] = None,
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
        ctx: Optional[dict] = None,
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

        fields = get_model_fields(model, in_scope=in_scope)
        for fi in fields:
            if fi.field_class == FieldClass.PK:
                continue

            # Skip reverse relations and M2M (handled separately)
            if fi.field_class in (
                FieldClass.REVERSE_FK_IN_SCOPE,
                FieldClass.REVERSE_FK_OUT_OF_SCOPE,
                FieldClass.REVERSE_O2O_IN_SCOPE,
                FieldClass.REVERSE_O2O_OUT_OF_SCOPE,
                FieldClass.REVERSE_M2M_IN_SCOPE,
                FieldClass.REVERSE_M2M_OUT_OF_SCOPE,
                FieldClass.M2M_IN_SCOPE,
                FieldClass.M2M_OUT_OF_SCOPE,
                FieldClass.GENERIC_RELATION_IN_SCOPE,
                FieldClass.GENERIC_RELATION_OUT_OF_SCOPE,
            ):
                continue

            # Check for anonymization
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
                    # Use the target DB for the M2M relationship
                    new_manager.set(new_pks)

            elif fi.field_class == FieldClass.M2M_OUT_OF_SCOPE:
                # Skip — out-of-scope M2M targets may not exist in target DB.
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
