"""Clone action — duplicate a walked subgraph within the same database."""

from __future__ import annotations

import logging
from typing import Any

from django.db import models, transaction

from django_graph_walker.discovery import FieldClass, get_model_fields
from django_graph_walker.result import WalkResult
from django_graph_walker.spec import Anonymize, GraphSpec, Ignore, KeepOriginal, Override

logger = logging.getLogger(__name__)


class Clone:
    """Clone a walked subgraph within the same database.

    Creates new instances with new PKs, remaps all in-scope FKs to point to the
    clones, and applies spec overrides (Override, KeepOriginal, Anonymize).

    Usage:
        spec = GraphSpec({
            Article: {
                'title': Override(lambda inst, ctx: f"Copy of {inst.title}"),
                'author': KeepOriginal(),   # point to original author, don't clone
            },
            Category: {},
            Tag: {},
        })

        result = GraphWalker(spec).walk(article)
        cloned = Clone(spec).execute(result)

        # cloned.instance_map: {(Model, old_pk): new_instance}
        # cloned.result: WalkResult of the new instances
    """

    def __init__(self, spec: GraphSpec):
        self.spec = spec
        self._faker = None

    def _get_faker(self):
        """Lazy-load faker instance."""
        if self._faker is None:
            from faker import Faker

            self._faker = Faker()
        return self._faker

    def execute(
        self,
        walk_result: WalkResult,
        *,
        using: str = "default",
        ctx: dict[str, Any] | None = None,
    ) -> CloneResult:
        """Clone all instances in the walk result.

        Args:
            walk_result: The walked subgraph to clone.
            using: Database alias to create clones in (default: "default").
            ctx: Context dict passed to Override/KeepOriginal/Anonymize callables.

        Returns:
            CloneResult with the mapping from originals to clones.
        """
        ctx = ctx or {}

        ordered_models = walk_result.topological_order()
        by_model = walk_result.by_model()
        in_scope = set(by_model.keys())

        pk_map: dict[tuple[type[models.Model], int], int] = {}
        instance_map: dict[tuple[type[models.Model], int], models.Model] = {}

        with transaction.atomic(using=using):
            # First pass: clone instances with FK remapping
            for model in ordered_models:
                for instance in by_model.get(model, []):
                    new_instance = self._clone_instance(
                        instance, model, using, pk_map, in_scope, ctx
                    )
                    old_key = (model, instance.pk)
                    pk_map[old_key] = new_instance.pk
                    instance_map[old_key] = new_instance

                    # Register MTI parent models in pk_map so FKs targeting a
                    # parent class remap correctly when a child class shares the PK.
                    for parent in model.__mro__:
                        if parent is model or parent is models.Model:
                            continue
                        if not hasattr(parent, "_meta") or parent._meta.abstract:
                            continue
                        if issubclass(parent, models.Model):
                            parent_key = (parent, instance.pk)
                            if parent_key not in pk_map:
                                pk_map[parent_key] = new_instance.pk

            # Fixup pass: remap out-of-scope FKs whose targets were cloned
            # via MTI after the referencing model in topological order.
            self._fixup_mti_fks(ordered_models, by_model, instance_map, pk_map, in_scope, using)

            # Second pass: clone M2M relationships
            for model in ordered_models:
                for instance in by_model.get(model, []):
                    old_key = (model, instance.pk)
                    new_instance = instance_map[old_key]
                    self._clone_m2m(instance, new_instance, model, pk_map, in_scope)

        return CloneResult(instance_map, self.spec.models)

    def _fixup_mti_fks(
        self,
        ordered_models: list[type[models.Model]],
        by_model: dict[type[models.Model], list[models.Model]],
        instance_map: dict[tuple[type[models.Model], int], models.Model],
        pk_map: dict[tuple[type[models.Model], int], int],
        in_scope: set[type[models.Model]],
        using: str,
    ) -> None:
        """Remap out-of-scope FKs whose targets gained pk_map entries via MTI.

        When an in-scope child model is cloned, its out-of-scope parent gets a
        pk_map entry. If a model with an FK to that parent was cloned earlier in
        topological order, it still points to the old PK. This pass fixes those.
        """
        for model in ordered_models:
            fields = get_model_fields(model, in_scope=in_scope)
            out_of_scope_fks = [
                fi
                for fi in fields
                if fi.field_class in (FieldClass.FK_OUT_OF_SCOPE, FieldClass.O2O_OUT_OF_SCOPE)
                and fi.related_model is not None
            ]
            if not out_of_scope_fks:
                continue

            for instance in by_model.get(model, []):
                old_key = (model, instance.pk)
                new_instance = instance_map.get(old_key)
                if new_instance is None:
                    continue

                update_fields = []
                for fi in out_of_scope_fks:
                    col_name = fi.field.attname
                    fk_value = getattr(instance, col_name, None)
                    if fk_value is None:
                        continue
                    related = getattr(instance, fi.name, None)
                    if related is None:
                        continue
                    mti_key = (fi.related_model, related.pk)
                    new_pk = pk_map.get(mti_key)
                    if new_pk is not None and getattr(new_instance, col_name) != new_pk:
                        setattr(new_instance, col_name, new_pk)
                        update_fields.append(col_name)

                if update_fields:
                    new_instance.save(using=using, update_fields=update_fields)

    # Value fields and forward FK/O2O only; reverse relations and M2M
    # are handled in the second pass.
    _COPYABLE = {
        FieldClass.VALUE,
        FieldClass.FK_IN_SCOPE,
        FieldClass.FK_OUT_OF_SCOPE,
        FieldClass.O2O_IN_SCOPE,
        FieldClass.O2O_OUT_OF_SCOPE,
    }

    def _clone_instance(
        self,
        instance: models.Model,
        model: type[models.Model],
        using: str,
        pk_map: dict[tuple[type[models.Model], int], int],
        in_scope: set[type[models.Model]],
        ctx: dict[str, Any],
    ) -> models.Model:
        """Clone a single instance, applying spec overrides and FK remapping.

        Uses model(**kwargs) construction to avoid model_utils FieldTracker
        issues with MTI inherited fields.
        """
        overrides = self.spec.get_overrides(model)
        kwargs: dict[str, Any] = {}

        fields = get_model_fields(model, in_scope=in_scope)
        for fi in fields:
            if fi.field_class not in self._COPYABLE:
                continue

            # Skip O2O parent links (primary_key=True) when target is out of scope.
            # Copying would point the clone to the same parent row, sharing its PK.
            # When in scope, the parent is cloned first and we remap correctly.
            if fi.field_class == FieldClass.O2O_OUT_OF_SCOPE and getattr(
                fi.field, "primary_key", False
            ):
                continue

            override = overrides.get(fi.name)

            # Override: replace the field value entirely
            if isinstance(override, Override):
                kwargs[fi.name] = override.resolve(instance, ctx)
                continue

            # Anonymize: replace with faker or callable
            if isinstance(override, Anonymize):
                kwargs[fi.name] = self._resolve_anonymize(override, instance, ctx)
                continue

            # Value fields: straight copy
            if fi.field_class == FieldClass.VALUE:
                value = getattr(instance, fi.name, None)
                if value is not None:
                    kwargs[fi.name] = value

            # In-scope FK/O2O: remap to clone (or keep original with KeepOriginal)
            elif fi.field_class in (FieldClass.FK_IN_SCOPE, FieldClass.O2O_IN_SCOPE):
                # Use attname to get the raw column value, which handles
                # to_field FKs correctly.
                col_name = fi.field.attname
                fk_value = getattr(instance, col_name, None)
                if fk_value is None:
                    continue

                keep_original = isinstance(override, KeepOriginal) and (
                    override.when is None or override.when(instance, ctx)
                )

                if keep_original:
                    kwargs[col_name] = fk_value
                else:
                    related = getattr(instance, fi.name, None)
                    target_model = fi.related_model
                    old_key = (target_model, related.pk) if related else None
                    new_pk = pk_map.get(old_key) if old_key else None
                    if new_pk is not None:
                        kwargs[col_name] = new_pk
                    else:
                        # Target not in walk result (e.g. self-referential null FK)
                        kwargs[col_name] = fk_value

            # Out-of-scope FK/O2O: keep original reference unless the target
            # was cloned via MTI (a child model was in scope and cloned,
            # registering the parent's PK in pk_map).
            elif fi.field_class in (FieldClass.FK_OUT_OF_SCOPE, FieldClass.O2O_OUT_OF_SCOPE):
                col_name = fi.field.attname
                fk_value = getattr(instance, col_name, None)
                if fk_value is not None:
                    related = getattr(instance, fi.name, None)
                    target_model = fi.related_model
                    mti_key = (target_model, related.pk) if (target_model and related) else None
                    new_pk = pk_map.get(mti_key) if mti_key else None
                    kwargs[col_name] = new_pk if new_pk is not None else fk_value

        # Filter to concrete fields only — virtual fields or reverse relation
        # accessors would cause TypeError in Model.__init__.
        valid_kwargs = set()
        for f in model._meta.concrete_fields:
            valid_kwargs.add(f.name)
            valid_kwargs.add(f.attname)
        kwargs = {k: v for k, v in kwargs.items() if k in valid_kwargs}

        new_instance = model(**kwargs)
        new_instance.save(using=using)
        return new_instance

    def _clone_m2m(
        self,
        original: models.Model,
        new_instance: models.Model,
        model: type[models.Model],
        pk_map: dict[tuple[type[models.Model], int], int],
        in_scope: set[type[models.Model]],
    ) -> None:
        """Clone M2M relationships, remapping to cloned targets where possible."""
        overrides = self.spec.get_overrides(model)
        fields = get_model_fields(model, in_scope=in_scope)
        for fi in fields:
            # Skip Ignore'd M2M fields (e.g. explicit through tables cloned in first pass)
            if isinstance(overrides.get(fi.name), Ignore):
                continue

            if fi.field_class == FieldClass.M2M_IN_SCOPE:
                target_model = fi.related_model
                new_pks = []
                for related in getattr(original, fi.name).all():
                    old_key = (target_model, related.pk)
                    new_pk = pk_map.get(old_key)
                    new_pks.append(new_pk if new_pk is not None else related.pk)

                if new_pks:
                    getattr(new_instance, fi.name).set(new_pks)

            elif fi.field_class == FieldClass.M2M_OUT_OF_SCOPE:
                # Out-of-scope M2M: copy original references (targets aren't cloned)
                original_pks = list(getattr(original, fi.name).values_list("pk", flat=True))
                if original_pks:
                    getattr(new_instance, fi.name).set(original_pks)

    def _resolve_anonymize(
        self,
        anon: Anonymize,
        instance: models.Model,
        ctx: dict[str, Any],
    ) -> Any:
        """Resolve an Anonymize override value."""
        if callable(anon.provider):
            return anon.provider(instance, ctx)
        faker = self._get_faker()
        provider = getattr(faker, anon.provider, None)
        if provider is None:
            raise ValueError(
                f"Unknown faker provider '{anon.provider}'. "
                f"Pass a callable instead, or use a valid faker method name."
            )
        return provider()


class CloneResult:
    """Result of a clone operation.

    Attributes:
        instance_map: Mapping from (original_model, original_pk) to new instance.
    """

    def __init__(
        self,
        instance_map: dict[tuple[type[models.Model], int], models.Model],
        spec_models: set[type[models.Model]],
    ):
        self.instance_map = instance_map
        self._spec_models = spec_models

    @property
    def result(self) -> WalkResult:
        """Get a WalkResult of the cloned instances."""
        visited = {(type(inst), inst.pk): inst for inst in self.instance_map.values()}
        return WalkResult(visited, self._spec_models)

    def get_clone(self, instance: models.Model) -> models.Model | None:
        """Get the clone of a specific original instance."""
        return self.instance_map.get((type(instance), instance.pk))

    @property
    def clone_count(self) -> int:
        return len(self.instance_map)
