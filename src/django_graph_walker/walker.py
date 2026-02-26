"""Core graph walking engine."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Any

from django.db.models import Model, Prefetch, prefetch_related_objects

from django_graph_walker.discovery import ALL_IN_SCOPE, FieldClass, FieldInfo, get_model_fields
from django_graph_walker.result import WalkResult
from django_graph_walker.spec import Follow, GraphSpec, Ignore

logger = logging.getLogger(__name__)


class GraphWalker:
    """Walks a Django model graph starting from root instances.

    Uses BFS to traverse relationships according to a GraphSpec, collecting
    all reachable in-scope instances.

    Usage:
        spec = GraphSpec(Author, Book, Publisher)
        result = GraphWalker(spec).walk(some_book)
        print(result.instance_count)
    """

    def __init__(self, spec: GraphSpec):
        self.spec = spec
        self._field_cache: dict[type[Model], list[FieldInfo]] = {}
        self._prefetch_cache: dict[type[Model], list[str | Prefetch]] = {}

    def _get_fields(self, model: type[Model]) -> list[FieldInfo]:
        """Get classified fields for a model (cached)."""
        if model not in self._field_cache:
            self._field_cache[model] = get_model_fields(model, in_scope=self.spec.models)
        return self._field_cache[model]

    def _get_follow(self, model: type[Model], field_info: FieldInfo) -> Follow | None:
        """Get the Follow override for an edge, if any."""
        override = self.spec.get_overrides(model).get(field_info.name)
        return override if isinstance(override, Follow) else None

    def _should_follow(self, model: type[Model], field_info: FieldInfo) -> bool:
        """Determine if an edge should be followed, considering overrides.

        Default: follow all in-scope edges regardless of direction.
        FK direction is an implementation detail — for graph walking, if both models
        are in scope the edge should be traversed. Use Ignore() to opt out.
        """
        override = self.spec.get_overrides(model).get(field_info.name)

        if isinstance(override, Ignore):
            return False
        if isinstance(override, Follow):
            # Follow override enables traversal on any in-scope edge
            return field_info.field_class in ALL_IN_SCOPE
        # Other overrides (Override, KeepOriginal, Anonymize) don't affect traversal
        return field_info.field_class in ALL_IN_SCOPE

    def _build_prefetch_lookups(self, model: type[Model]) -> list[str | Prefetch]:
        """Build prefetch lookups for all followed edges of a model.

        Results are cached per-model since the spec doesn't change during a walk.
        """
        if model in self._prefetch_cache:
            return self._prefetch_cache[model]

        lookups: list[str | Prefetch] = []
        for field_info in self._get_fields(model):
            if not self._should_follow(model, field_info):
                continue
            if field_info.field_class not in ALL_IN_SCOPE:
                continue

            follow = self._get_follow(model, field_info)
            if follow and follow.prefetch and field_info.related_model is not None:
                base_qs = field_info.related_model.objects.all()
                lookups.append(Prefetch(field_info.name, queryset=follow.prefetch(base_qs)))
            else:
                lookups.append(field_info.name)

        self._prefetch_cache[model] = lookups
        return lookups

    def _apply_filter_and_limit(
        self,
        instances: list[Model],
        model: type[Model],
        field_info: FieldInfo,
        ctx: dict[str, Any] | None,
    ) -> list[Model]:
        """Apply filter and limit to a list of related instances."""
        follow = self._get_follow(model, field_info)
        if not follow:
            return instances

        if follow.filter:
            instances = [i for i in instances if follow.filter(ctx or {}, i)]
        if follow.limit is not None:
            instances = instances[: follow.limit]

        return instances

    def _resolve_related(
        self,
        instance: Model,
        field_info: FieldInfo,
        ctx: dict[str, Any] | None,
    ) -> list[Model]:
        """Resolve all related instances for a given edge."""
        fc = field_info.field_class

        if fc in (
            FieldClass.REVERSE_FK_IN_SCOPE,
            FieldClass.REVERSE_M2M_IN_SCOPE,
            FieldClass.GENERIC_RELATION_IN_SCOPE,
        ):
            # Reverse relations: use the manager (data cached by batch prefetch)
            manager = getattr(instance, field_info.name, None)
            if manager is None:
                return []
            instances = list(manager.all())
            return self._apply_filter_and_limit(instances, type(instance), field_info, ctx)

        if fc == FieldClass.REVERSE_O2O_IN_SCOPE:
            try:
                related = getattr(instance, field_info.name)
                return [related] if related is not None else []
            except field_info.related_model.DoesNotExist:
                return []

        if fc in (FieldClass.FK_IN_SCOPE, FieldClass.O2O_IN_SCOPE):
            related = getattr(instance, field_info.name, None)
            if related is not None:
                follow = self._get_follow(type(instance), field_info)
                if follow and follow.filter and not follow.filter(ctx or {}, related):
                    return []
                return [related]
            return []

        if fc == FieldClass.M2M_IN_SCOPE:
            # Data cached by batch prefetch
            manager = getattr(instance, field_info.name, None)
            if manager is None:
                return []
            instances = list(manager.all())
            return self._apply_filter_and_limit(instances, type(instance), field_info, ctx)

        return []

    def walk(self, *roots: Model, ctx: dict[str, Any] | None = None) -> WalkResult:
        """Walk the model graph from one or more root instances.

        Uses level-order BFS with batch prefetching: each iteration drains the
        queue into model-grouped batches, calls prefetch_related_objects() per
        batch to load all relations in bulk, then resolves edges from cached data.

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
            # Drain queue into model-grouped batch, deduplicating
            batch_by_model: dict[type[Model], list[Model]] = defaultdict(list)
            seen_in_batch: set[tuple[type[Model], int]] = set()
            while queue:
                instance = queue.popleft()
                model = type(instance)
                key = (model, instance.pk)
                if key in visited or key in seen_in_batch:
                    continue
                if model not in self.spec:
                    continue
                batch_by_model[model].append(instance)
                seen_in_batch.add(key)

            # Process each model group with batch prefetch
            for model, instances in batch_by_model.items():
                lookups = self._build_prefetch_lookups(model)
                if lookups:
                    prefetch_related_objects(instances, *lookups)

                for instance in instances:
                    key = (model, instance.pk)
                    if key in visited:
                        continue
                    visited[key] = instance
                    logger.debug(f"Visited {model.__name__} pk={instance.pk}")

                    for field_info in self._get_fields(model):
                        if not self._should_follow(model, field_info):
                            continue

                        related_instances = self._resolve_related(instance, field_info, ctx)
                        for related in related_instances:
                            related_key = (type(related), related.pk)
                            if related_key not in visited and type(related) in self.spec:
                                queue.append(related)

        return WalkResult(visited, self.spec.models)
