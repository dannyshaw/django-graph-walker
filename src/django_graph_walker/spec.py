"""GraphSpec definition and override types."""

from __future__ import annotations

from typing import Any, Callable, Optional, Union

from django.db.models import Model, QuerySet


class _FieldOverride:
    """Base class for all field overrides."""


class Follow(_FieldOverride):
    """Force-follow a relationship edge, even if the default would be Ignore.

    Args:
        filter: Optional callable (ctx, instance) -> bool to filter which related instances
            are followed during walking.
        prefetch: Optional callable (queryset) -> queryset to add select_related/prefetch_related.
    """

    def __init__(
        self,
        *,
        filter: Optional[Callable[..., bool]] = None,
        prefetch: Optional[Callable[[QuerySet], QuerySet]] = None,
    ):
        self.filter = filter
        self.prefetch = prefetch


class Ignore(_FieldOverride):
    """Force-ignore a relationship or field, even if the default would be Follow."""


class Override(_FieldOverride):
    """Set a field to a specific value or compute it from the instance.

    Args:
        value: A static value, or a callable (instance, ctx) -> value.
    """

    def __init__(self, value: Any):
        self.value = value

    def resolve(self, instance: Model, ctx: dict) -> Any:
        if callable(self.value):
            return self.value(instance, ctx)
        return self.value


class KeepOriginal(_FieldOverride):
    """For FK fields to in-scope models: keep the original target instead of cloning.

    By default, FK fields pointing to in-scope models will use the cloned target.
    KeepOriginal overrides this to preserve the original reference.

    Args:
        when: Optional callable (instance, ctx) -> bool. If provided, only keeps original
            when the callable returns True; otherwise uses the clone.
    """

    def __init__(self, *, when: Optional[Callable[..., bool]] = None):
        self.when = when


class Anonymize(_FieldOverride):
    """Anonymize a field value using faker or a custom callable.

    Args:
        provider: A faker provider name (e.g., 'email', 'first_name') or a callable
            (instance, ctx) -> anonymized_value.
    """

    def __init__(self, provider: Union[str, Callable[..., Any]]):
        self.provider = provider


class GraphSpec:
    """Define which models to include in a graph walk and how to handle their fields.

    Usage:
        # Simple — just list models, all defaults
        GraphSpec(Branch, Lesson, Chunk)

        # With field overrides
        GraphSpec({
            Branch: {
                'title': Override(lambda m, ctx: ctx['new_title']),
            },
            Lesson: {},
            Chunk: {},
        })

        # Mixed
        GraphSpec(
            {Branch: {'title': Override(...)}},
            Lesson,
            Chunk,
        )
    """

    def __init__(self, *args: Union[type[Model], dict[type[Model], dict[str, _FieldOverride]]]):
        self._models: dict[type[Model], dict[str, _FieldOverride]] = {}

        for arg in args:
            if isinstance(arg, dict):
                for model, overrides in arg.items():
                    self._add_model(model, overrides)
            elif isinstance(arg, type) and issubclass(arg, Model):
                self._add_model(arg, {})
            else:
                raise TypeError(
                    f"GraphSpec arguments must be Django Model classes or dicts, got {type(arg)}"
                )

    def _add_model(self, model: type[Model], overrides: dict[str, _FieldOverride]) -> None:
        if model in self._models:
            raise ValueError(f"Model {model.__name__} specified more than once in GraphSpec")
        self._models[model] = overrides

    @property
    def models(self) -> set[type[Model]]:
        """Set of all models in this spec."""
        return set(self._models.keys())

    def __contains__(self, model: type[Model]) -> bool:
        return model in self._models

    def get_overrides(self, model: type[Model]) -> dict[str, _FieldOverride]:
        """Get field overrides for a model."""
        return self._models.get(model, {})

    def validate(self) -> None:
        """Validate that all overrides reference real fields on their models."""
        from django_graph_walker.discovery import _get_field_name

        for model, overrides in self._models.items():
            field_names = set()
            for f in model._meta.get_fields():
                field_names.add(_get_field_name(f))

            for field_name in overrides:
                if field_name not in field_names:
                    raise ValueError(
                        f"Override for '{field_name}' on {model.__name__}, "
                        f"but no such field exists. "
                        f"Available fields: {sorted(field_names)}"
                    )
