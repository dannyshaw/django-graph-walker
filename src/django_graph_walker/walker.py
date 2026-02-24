"""Core graph walking engine."""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Optional

from django.db.models import Model

from django_graph_walker.discovery import FieldClass, FieldInfo, get_model_fields
from django_graph_walker.result import WalkResult
from django_graph_walker.spec import Follow, GraphSpec, Ignore

logger = logging.getLogger(__name__)


# All in-scope edge types that can be traversed with explicit Follow()
_ALL_IN_SCOPE = {
    FieldClass.FK_IN_SCOPE,
    FieldClass.M2M_IN_SCOPE,
    FieldClass.REVERSE_FK_IN_SCOPE,
    FieldClass.REVERSE_M2M_IN_SCOPE,
    FieldClass.O2O_IN_SCOPE,
    FieldClass.REVERSE_O2O_IN_SCOPE,
    FieldClass.GENERIC_RELATION_IN_SCOPE,
}

# Default: only follow ownership/reverse edges (children, not parents/references)
_DEFAULT_FOLLOW = {
    FieldClass.REVERSE_FK_IN_SCOPE,
    FieldClass.REVERSE_O2O_IN_SCOPE,
    FieldClass.GENERIC_RELATION_IN_SCOPE,
}

# These are never traversable by default
_DEFAULT_IGNORE = {
    FieldClass.PK,
    FieldClass.VALUE,
    FieldClass.FK_OUT_OF_SCOPE,
    FieldClass.M2M_OUT_OF_SCOPE,
    FieldClass.REVERSE_FK_OUT_OF_SCOPE,
    FieldClass.REVERSE_M2M_OUT_OF_SCOPE,
    FieldClass.O2O_OUT_OF_SCOPE,
    FieldClass.REVERSE_O2O_OUT_OF_SCOPE,
    FieldClass.GENERIC_RELATION_OUT_OF_SCOPE,
}


class GraphWalker:
    """Walks a Django model graph starting from root instances.

    Uses BFS to traverse relationships according to a GraphSpec, collecting
    all reachable in-scope instances.

    Usage:
        spec = GraphSpec(Author, Article, Category)
        result = GraphWalker(spec).walk(some_article)
        print(result.instance_count)
    """

    def __init__(self, spec: GraphSpec):
        self.spec = spec
        self._field_cache: dict[type[Model], list[FieldInfo]] = {}

    def _get_fields(self, model: type[Model]) -> list[FieldInfo]:
        """Get classified fields for a model (cached)."""
        if model not in self._field_cache:
            self._field_cache[model] = get_model_fields(model, in_scope=self.spec.models)
        return self._field_cache[model]

    def _should_follow(self, model: type[Model], field_info: FieldInfo) -> bool:
        """Determine if an edge should be followed, considering overrides."""
        overrides = self.spec.get_overrides(model)

        # Check for explicit override
        if field_info.name in overrides:
            override = overrides[field_info.name]
            if isinstance(override, Ignore):
                return False
            if isinstance(override, Follow):
                # Follow override enables traversal on any in-scope edge
                return field_info.field_class in _ALL_IN_SCOPE
            # Other overrides (Override, KeepOriginal, Anonymize) don't affect traversal
            return field_info.field_class in _DEFAULT_FOLLOW

        # Default behavior based on classification
        return field_info.field_class in _DEFAULT_FOLLOW

    def _get_filter(self, model: type[Model], field_info: FieldInfo):
        """Get the filter function for an edge, if any."""
        overrides = self.spec.get_overrides(model)
        if field_info.name in overrides:
            override = overrides[field_info.name]
            if isinstance(override, Follow) and override.filter:
                return override.filter
        return None

    def _get_prefetch(self, model: type[Model], field_info: FieldInfo):
        """Get the prefetch function for an edge, if any."""
        overrides = self.spec.get_overrides(model)
        if field_info.name in overrides:
            override = overrides[field_info.name]
            if isinstance(override, Follow) and override.prefetch:
                return override.prefetch
        return None

    def _resolve_related(
        self,
        instance: Model,
        field_info: FieldInfo,
        ctx: Optional[dict[str, Any]],
    ) -> list[Model]:
        """Resolve all related instances for a given edge."""
        fc = field_info.field_class

        if fc in (
            FieldClass.REVERSE_FK_IN_SCOPE,
            FieldClass.REVERSE_M2M_IN_SCOPE,
            FieldClass.GENERIC_RELATION_IN_SCOPE,
        ):
            # Reverse relations: use the manager
            manager = getattr(instance, field_info.name, None)
            if manager is None:
                return []

            qs = manager.all()

            # Apply prefetch
            prefetch = self._get_prefetch(type(instance), field_info)
            if prefetch:
                qs = prefetch(qs)

            instances = list(qs)

            # Apply filter
            filter_fn = self._get_filter(type(instance), field_info)
            if filter_fn:
                instances = [i for i in instances if filter_fn(ctx or {}, i)]

            return instances

        if fc == FieldClass.REVERSE_O2O_IN_SCOPE:
            # Reverse OneToOne: single instance
            try:
                related = getattr(instance, field_info.name)
                return [related] if related is not None else []
            except field_info.field.related_model.DoesNotExist:
                return []

        if fc in (FieldClass.FK_IN_SCOPE, FieldClass.O2O_IN_SCOPE):
            # Forward FK/O2O: single instance
            related = getattr(instance, field_info.name, None)
            if related is not None:
                filter_fn = self._get_filter(type(instance), field_info)
                if filter_fn and not filter_fn(ctx or {}, related):
                    return []
                return [related]
            return []

        if fc == FieldClass.M2M_IN_SCOPE:
            # Forward M2M
            manager = getattr(instance, field_info.name, None)
            if manager is None:
                return []

            qs = manager.all()

            # Apply prefetch
            prefetch = self._get_prefetch(type(instance), field_info)
            if prefetch:
                qs = prefetch(qs)

            instances = list(qs)

            # Apply filter
            filter_fn = self._get_filter(type(instance), field_info)
            if filter_fn:
                instances = [i for i in instances if filter_fn(ctx or {}, i)]

            return instances

        return []

    def walk(self, *roots: Model, ctx: Optional[dict[str, Any]] = None) -> WalkResult:
        """Walk the model graph from one or more root instances.

        Args:
            *roots: One or more Django model instances to start walking from.
            ctx: Optional context dict passed to filter functions.

        Returns:
            WalkResult containing all collected instances.
        """
        visited: dict[tuple[type[Model], int], Model] = {}
        queue: deque[Model] = deque()

        for root in roots:
            if type(root) not in self.spec:
                logger.warning(
                    f"Root instance {root!r} is of type {type(root).__name__} "
                    f"which is not in the spec — skipping."
                )
                continue
            queue.append(root)

        while queue:
            instance = queue.popleft()
            model = type(instance)
            key = (model, instance.pk)

            if key in visited:
                continue
            if model not in self.spec:
                continue

            visited[key] = instance
            logger.debug(f"Visited {model.__name__} pk={instance.pk}")

            # Walk all edges
            for field_info in self._get_fields(model):
                if not self._should_follow(model, field_info):
                    continue

                related_instances = self._resolve_related(instance, field_info, ctx)
                for related in related_instances:
                    related_key = (type(related), related.pk)
                    if related_key not in visited and type(related) in self.spec:
                        queue.append(related)

        return WalkResult(visited, self.spec.models)
