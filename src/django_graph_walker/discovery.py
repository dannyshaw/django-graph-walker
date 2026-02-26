"""Auto-classification of Django model fields for graph walking."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.db.models import Field, ForeignKey, ManyToManyField, ManyToManyRel, Model
from django.db.models.fields.related import OneToOneField, OneToOneRel
from django.db.models.fields.reverse_related import ForeignObjectRel, ManyToOneRel


class FieldClass(Enum):
    """Classification of a Django model field for graph walking purposes."""

    PK = auto()
    VALUE = auto()

    FK_IN_SCOPE = auto()
    FK_OUT_OF_SCOPE = auto()

    M2M_IN_SCOPE = auto()
    M2M_OUT_OF_SCOPE = auto()

    REVERSE_FK_IN_SCOPE = auto()
    REVERSE_FK_OUT_OF_SCOPE = auto()

    REVERSE_M2M_IN_SCOPE = auto()
    REVERSE_M2M_OUT_OF_SCOPE = auto()

    O2O_IN_SCOPE = auto()
    O2O_OUT_OF_SCOPE = auto()

    REVERSE_O2O_IN_SCOPE = auto()
    REVERSE_O2O_OUT_OF_SCOPE = auto()

    GENERIC_RELATION_IN_SCOPE = auto()
    GENERIC_RELATION_OUT_OF_SCOPE = auto()


@dataclass
class FieldInfo:
    """Information about a model field including its classification."""

    name: str
    field: Field
    field_class: FieldClass
    related_model: type[Model] | None = None


def _get_field_name(field: Field) -> str:
    """Get the accessor name for a field (handles reverse relations)."""
    if isinstance(field, ForeignObjectRel):
        return field.get_accessor_name()
    return field.name


def _get_related_model(field: Field) -> type[Model] | None:
    """Get the model a relationship field points to."""
    if isinstance(field, GenericRelation):
        return field.related_model
    if isinstance(field, ForeignObjectRel):
        # Reverse relation: the related model is the one that holds the FK
        return field.related_model
    if hasattr(field, "related_model"):
        return field.related_model
    return None


def classify_field(field: Field, in_scope: set[type[Model]]) -> FieldClass:
    """Classify a Django field based on its type and whether its target is in scope.

    Args:
        field: A Django field object from model._meta.get_fields().
        in_scope: Set of model classes considered "in scope" for walking.

    Returns:
        FieldClass indicating the field's role in graph traversal.
    """
    # OneToOneFields that are also primary keys (multi-table inheritance parent
    # links, or shared-PK patterns) are both a PK and an FK dependency.
    # Classify as O2O so the topological sort sees the ordering constraint.
    if isinstance(field, OneToOneField) and getattr(field, "primary_key", False):
        related = field.related_model
        if related in in_scope:
            return FieldClass.O2O_IN_SCOPE
        return FieldClass.O2O_OUT_OF_SCOPE

    if hasattr(field, "primary_key") and field.primary_key:
        return FieldClass.PK

    # Must check before ForeignObjectRel
    if isinstance(field, GenericRelation):
        related = field.related_model
        if related in in_scope:
            return FieldClass.GENERIC_RELATION_IN_SCOPE
        return FieldClass.GENERIC_RELATION_OUT_OF_SCOPE

    if isinstance(field, OneToOneRel):
        related = field.related_model
        if related in in_scope:
            return FieldClass.REVERSE_O2O_IN_SCOPE
        return FieldClass.REVERSE_O2O_OUT_OF_SCOPE

    if isinstance(field, ManyToManyRel):
        related = field.related_model
        if related in in_scope:
            return FieldClass.REVERSE_M2M_IN_SCOPE
        return FieldClass.REVERSE_M2M_OUT_OF_SCOPE

    if isinstance(field, ManyToOneRel):
        related = field.related_model
        if related in in_scope:
            return FieldClass.REVERSE_FK_IN_SCOPE
        return FieldClass.REVERSE_FK_OUT_OF_SCOPE

    if isinstance(field, OneToOneField):
        related = field.related_model
        if related in in_scope:
            return FieldClass.O2O_IN_SCOPE
        return FieldClass.O2O_OUT_OF_SCOPE

    if isinstance(field, ForeignKey):
        related = field.related_model
        if related in in_scope:
            return FieldClass.FK_IN_SCOPE
        return FieldClass.FK_OUT_OF_SCOPE

    if isinstance(field, ManyToManyField):
        related = field.related_model
        if related in in_scope:
            return FieldClass.M2M_IN_SCOPE
        return FieldClass.M2M_OUT_OF_SCOPE

    # GenericForeignKey is a virtual composite descriptor (not a real DB column).
    # Its constituent fields (content_type FK + object_id integer) are handled
    # individually. Classify as PK to exclude from clone copying.
    if isinstance(field, GenericForeignKey):
        return FieldClass.PK

    # Catch-all: simple value field
    return FieldClass.VALUE


# All in-scope edge types that are traversable by the walker
ALL_IN_SCOPE = frozenset(
    {
        FieldClass.FK_IN_SCOPE,
        FieldClass.M2M_IN_SCOPE,
        FieldClass.REVERSE_FK_IN_SCOPE,
        FieldClass.REVERSE_M2M_IN_SCOPE,
        FieldClass.O2O_IN_SCOPE,
        FieldClass.REVERSE_O2O_IN_SCOPE,
        FieldClass.GENERIC_RELATION_IN_SCOPE,
    }
)

# Forward in-scope edges (used to avoid drawing each relationship twice in visualization)
FORWARD_IN_SCOPE = frozenset(
    {
        FieldClass.FK_IN_SCOPE,
        FieldClass.O2O_IN_SCOPE,
        FieldClass.M2M_IN_SCOPE,
        FieldClass.GENERIC_RELATION_IN_SCOPE,
    }
)

# Forward in-scope edges that can be resolved via getattr (excludes GenericRelation)
FORWARD_RELATION_IN_SCOPE = frozenset(
    {
        FieldClass.FK_IN_SCOPE,
        FieldClass.O2O_IN_SCOPE,
        FieldClass.M2M_IN_SCOPE,
    }
)


def get_model_fields(
    model: type[Model],
    in_scope: set[type[Model]] | None = None,
) -> list[FieldInfo]:
    """Introspect a Django model and return classified FieldInfo for all fields.

    Args:
        model: The Django model class to introspect.
        in_scope: Set of model classes considered in scope. Defaults to empty set.

    Returns:
        List of FieldInfo objects for every field on the model.
    """
    if in_scope is None:
        in_scope = set()

    result = []
    for field in model._meta.get_fields():
        name = _get_field_name(field)
        fc = classify_field(field, in_scope)
        related = _get_related_model(field)
        result.append(FieldInfo(name=name, field=field, field_class=fc, related_model=related))

    return result
