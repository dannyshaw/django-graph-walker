"""WalkResult — the collected instance graph from a graph walk."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterator

from django.db.models import Model

from django_graph_walker.discovery import FieldClass, get_model_fields


class WalkResult:
    """Contains all instances collected during a graph walk.

    Provides methods to inspect, iterate, and order the collected data.
    """

    def __init__(
        self,
        visited: dict[tuple[type[Model], int], Model],
        spec_models: set[type[Model]],
    ):
        self._visited = visited
        self._spec_models = spec_models

    @property
    def instance_count(self) -> int:
        return len(self._visited)

    @property
    def model_count(self) -> int:
        models = {model_cls for model_cls, _ in self._visited.keys()}
        return len(models)

    def by_model(self) -> dict[type[Model], list[Model]]:
        """Group collected instances by model class."""
        groups: dict[type[Model], list[Model]] = defaultdict(list)
        for (model_cls, _pk), instance in self._visited.items():
            groups[model_cls].append(instance)
        return dict(groups)

    def instances_of(self, model: type[Model]) -> list[Model]:
        """Get all collected instances of a specific model."""
        return [
            instance for (model_cls, _pk), instance in self._visited.items() if model_cls == model
        ]

    def topological_order(self) -> list[type[Model]]:
        """Return model classes in dependency order (dependencies first).

        A model X depends on model Y if X has a FK to Y and both are in scope.
        """
        models_in_result = {model_cls for model_cls, _ in self._visited.keys()}
        if not models_in_result:
            return []

        # Build dependency graph
        deps: dict[type[Model], set[type[Model]]] = {m: set() for m in models_in_result}
        for model_cls in models_in_result:
            for fi in get_model_fields(model_cls, in_scope=models_in_result):
                if fi.field_class in (FieldClass.FK_IN_SCOPE, FieldClass.O2O_IN_SCOPE):
                    target = fi.related_model
                    if target in models_in_result and target != model_cls:
                        deps[model_cls].add(target)

        # Kahn's algorithm for topological sort
        in_degree: dict[type[Model], int] = {m: 0 for m in models_in_result}
        for model_cls, model_deps in deps.items():
            for dep in model_deps:
                in_degree[model_cls] += 1

        # Hmm, in_degree should be: for each model, count how many models depend on it
        # Actually no — in_degree[X] = number of models X depends on. We want:
        # X comes after all its dependencies. So we use: start with models that have 0 deps.
        from collections import deque

        # Recalculate: in_degree[X] = number of dependencies of X
        in_degree = {m: len(deps[m]) for m in models_in_result}
        queue = deque(m for m in models_in_result if in_degree[m] == 0)
        result = []

        # Reverse adjacency: who depends on me?
        dependents: dict[type[Model], set[type[Model]]] = {m: set() for m in models_in_result}
        for model_cls, model_deps in deps.items():
            for dep in model_deps:
                dependents[dep].add(model_cls)

        while queue:
            model = queue.popleft()
            result.append(model)
            for dependent in dependents[model]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # If there are cycles, append remaining (shouldn't happen in well-formed schemas)
        for m in models_in_result:
            if m not in result:
                result.append(m)

        return result

    def __contains__(self, instance: Model) -> bool:
        key = (type(instance), instance.pk)
        return key in self._visited

    def __iter__(self) -> Iterator[Model]:
        return iter(self._visited.values())

    def __len__(self) -> int:
        return len(self._visited)
