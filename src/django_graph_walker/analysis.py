"""Static fan-out risk detection for GraphSpec configurations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from django.db.models import Model

from django_graph_walker.discovery import FieldClass, get_model_fields
from django_graph_walker.spec import Follow, GraphSpec, Ignore

# Edge types that the walker follows by default (all in-scope edges)
_ALL_IN_SCOPE = {
    FieldClass.FK_IN_SCOPE,
    FieldClass.M2M_IN_SCOPE,
    FieldClass.REVERSE_FK_IN_SCOPE,
    FieldClass.REVERSE_M2M_IN_SCOPE,
    FieldClass.O2O_IN_SCOPE,
    FieldClass.REVERSE_O2O_IN_SCOPE,
    FieldClass.GENERIC_RELATION_IN_SCOPE,
}

_REVERSE_EDGE_TYPES = {
    FieldClass.REVERSE_FK_IN_SCOPE,
    FieldClass.REVERSE_M2M_IN_SCOPE,
    FieldClass.REVERSE_O2O_IN_SCOPE,
}


@dataclass(frozen=True)
class EdgeInfo:
    source_model: type[Model]
    source_label: str
    field_name: str
    target_model: type[Model]
    target_label: str
    field_class: FieldClass
    has_limit: bool
    limit_value: int | None
    is_default: bool

    def __str__(self) -> str:
        parts = [f"{self.source_label}.{self.field_name} -> {self.target_label}"]
        parts.append(f"[{self.field_class.name}]")
        if self.has_limit:
            parts.append(f"(limit={self.limit_value})")
        if self.is_default:
            parts.append("[default]")
        return " ".join(parts)


@dataclass
class CycleInfo:
    models: list[type[Model]]
    edges: list[EdgeInfo]
    suggested_breaks: list[EdgeInfo]


@dataclass
class LimitBypass:
    limited_edge: EdgeInfo
    bypass_path: list[EdgeInfo]


@dataclass
class SharedRef:
    model: type[Model]
    model_label: str
    incoming_edges: list[EdgeInfo]
    outgoing_edges: list[EdgeInfo]
    in_degree: int


@dataclass
class CardinalityEstimate:
    edge: EdgeInfo
    avg_cardinality: float
    max_cardinality: int
    total_count: int


@dataclass
class FanoutReport:
    edges: list[EdgeInfo]
    cycles: list[CycleInfo]
    bidirectional: list[tuple[EdgeInfo, EdgeInfo]]
    limit_bypasses: list[LimitBypass]
    shared_references: list[SharedRef]
    cardinality: list[CardinalityEstimate] | None = None


class FanoutAnalyzer:
    """Analyze a GraphSpec for fan-out risks before running any walks.

    Detects cycles, bidirectional edges, limit bypasses, and shared references
    that can cause unexpected cascading traversal.

    Usage:
        spec = GraphSpec(Author, Article, Tag)
        analyzer = FanoutAnalyzer(spec)
        report = analyzer.analyze()
        for cycle in report.cycles:
            print(cycle.suggested_breaks)
    """

    def __init__(self, spec: GraphSpec):
        self.spec = spec

    def analyze(self, threshold: int = 3) -> FanoutReport:
        """Run all static analyses and return a FanoutReport.

        Args:
            threshold: Minimum incoming edge count from distinct models to flag
                a model as a shared reference. Default 3.
        """
        edges = self._build_traversal_graph()
        cycles = self._detect_cycles(edges)
        bidirectional = self._detect_bidirectional(edges)
        limit_bypasses = self._detect_limit_bypasses(edges)
        shared_refs = self._detect_shared_references(edges, threshold)
        return FanoutReport(
            edges=edges,
            cycles=cycles,
            bidirectional=bidirectional,
            limit_bypasses=limit_bypasses,
            shared_references=shared_refs,
        )

    def estimate_fanout(self, threshold: int = 3) -> FanoutReport:
        """Run all analyses including DB cardinality estimation.

        Args:
            threshold: Minimum incoming edge count from distinct models to flag
                a model as a shared reference. Default 3.
        """
        report = self.analyze(threshold)
        report.cardinality = self._estimate_cardinality(report.edges)
        return report

    # -- Step 1: Build traversal graph --

    def _build_traversal_graph(self) -> list[EdgeInfo]:
        """Build the directed graph of edges the walker will traverse."""
        edges = []
        for model in self.spec.models:
            overrides = self.spec.get_overrides(model)
            fields = get_model_fields(model, in_scope=self.spec.models)

            for fi in fields:
                if fi.field_class not in _ALL_IN_SCOPE:
                    continue
                if fi.related_model is None:
                    continue

                # Replicate walker's _should_follow logic
                is_default = True
                has_limit = False
                limit_value = None

                if fi.name in overrides:
                    override = overrides[fi.name]
                    if isinstance(override, Ignore):
                        continue
                    if isinstance(override, Follow):
                        is_default = False
                        if override.limit is not None:
                            has_limit = True
                            limit_value = override.limit
                    # Other overrides don't affect traversal

                edges.append(
                    EdgeInfo(
                        source_model=model,
                        source_label=model._meta.label,
                        field_name=fi.name,
                        target_model=fi.related_model,
                        target_label=fi.related_model._meta.label,
                        field_class=fi.field_class,
                        has_limit=has_limit,
                        limit_value=limit_value,
                        is_default=is_default,
                    )
                )
        return edges

    # -- Step 2: Cycle detection (iterative Tarjan's SCC) --

    def _detect_cycles(self, edges: list[EdgeInfo]) -> list[CycleInfo]:
        # Build adjacency from model -> [(target_model, edge)]
        adj: dict[type[Model], list[tuple[type[Model], EdgeInfo]]] = defaultdict(list)
        for e in edges:
            adj[e.source_model].append((e.target_model, e))

        all_models = set()
        for e in edges:
            all_models.add(e.source_model)
            all_models.add(e.target_model)

        # Iterative Tarjan's SCC
        index_counter = [0]
        stack: list[type[Model]] = []
        on_stack: set[type[Model]] = set()
        index_map: dict[type[Model], int] = {}
        lowlink: dict[type[Model], int] = {}
        sccs: list[list[type[Model]]] = []

        for model in all_models:
            if model in index_map:
                continue
            # Iterative DFS
            work_stack: list[tuple[type[Model], int]] = [(model, 0)]
            while work_stack:
                v, ni = work_stack[-1]

                if ni == 0:
                    # First visit
                    index_map[v] = index_counter[0]
                    lowlink[v] = index_counter[0]
                    index_counter[0] += 1
                    stack.append(v)
                    on_stack.add(v)

                neighbors = [t for t, _ in adj.get(v, [])]
                if ni < len(neighbors):
                    work_stack[-1] = (v, ni + 1)
                    w = neighbors[ni]
                    if w not in index_map:
                        work_stack.append((w, 0))
                    elif w in on_stack:
                        lowlink[v] = min(lowlink[v], index_map[w])
                else:
                    # Done with v's neighbors
                    work_stack.pop()
                    if work_stack:
                        parent = work_stack[-1][0]
                        lowlink[parent] = min(lowlink[parent], lowlink[v])

                    if lowlink[v] == index_map[v]:
                        scc = []
                        while True:
                            w = stack.pop()
                            on_stack.discard(w)
                            scc.append(w)
                            if w == v:
                                break
                        if len(scc) > 1:
                            sccs.append(scc)
                        elif len(scc) == 1:
                            # Check self-loop
                            m = scc[0]
                            for target, _ in adj.get(m, []):
                                if target == m:
                                    sccs.append(scc)
                                    break

        # Build CycleInfo for each SCC
        cycles = []
        for scc in sccs:
            scc_set = set(scc)
            cycle_edges = [
                e for e in edges if e.source_model in scc_set and e.target_model in scc_set
            ]
            suggested = self._suggest_breaks(cycle_edges)
            cycles.append(
                CycleInfo(
                    models=scc,
                    edges=cycle_edges,
                    suggested_breaks=suggested,
                )
            )

        return cycles

    def _suggest_breaks(self, cycle_edges: list[EdgeInfo]) -> list[EdgeInfo]:
        """Suggest which edges to Ignore() to break a cycle.

        Priority:
        1. Reverse edges followed by default (most common accidental fan-out)
        2. Any default-followed edge
        3. Edges without limits
        """

        def sort_key(e: EdgeInfo) -> tuple[int, str]:
            if e.field_class in _REVERSE_EDGE_TYPES and e.is_default:
                return (0, e.field_name)
            if e.is_default:
                return (1, e.field_name)
            if not e.has_limit:
                return (2, e.field_name)
            return (3, e.field_name)

        sorted_edges = sorted(cycle_edges, key=sort_key)
        # Suggest breaking the highest-priority (lowest sort key) edge
        if sorted_edges:
            return [sorted_edges[0]]
        return []

    # -- Step 3: Bidirectional edge detection --

    def _detect_bidirectional(self, edges: list[EdgeInfo]) -> list[tuple[EdgeInfo, EdgeInfo]]:
        # Index edges by (source, target) model pair
        pair_map: dict[tuple[type[Model], type[Model]], list[EdgeInfo]] = defaultdict(list)
        for e in edges:
            pair_map[(e.source_model, e.target_model)].append(e)

        seen: set[frozenset[type[Model]]] = set()
        result = []
        for e in edges:
            pair_key = frozenset({e.source_model, e.target_model})
            if pair_key in seen:
                continue
            reverse_edges = pair_map.get((e.target_model, e.source_model))
            if reverse_edges:
                seen.add(pair_key)
                forward = pair_map[(e.source_model, e.target_model)][0]
                backward = reverse_edges[0]
                result.append((forward, backward))

        return result

    # -- Step 4: Limit bypass detection --

    def _detect_limit_bypasses(self, edges: list[EdgeInfo]) -> list[LimitBypass]:
        limited_edges = [e for e in edges if e.has_limit]
        if not limited_edges:
            return []

        # Build adjacency for BFS
        adj: dict[type[Model], list[EdgeInfo]] = defaultdict(list)
        for e in edges:
            adj[e.source_model].append(e)

        # Also detect direct bypasses: same source, same target, one limited one not
        source_target_map: dict[tuple[type[Model], type[Model]], list[EdgeInfo]] = defaultdict(
            list
        )
        for e in edges:
            source_target_map[(e.source_model, e.target_model)].append(e)

        bypasses = []
        for le in limited_edges:
            # Direct bypass: another edge from same source to same target without limit
            siblings = source_target_map[(le.source_model, le.target_model)]
            for sibling in siblings:
                if sibling is not le and not sibling.has_limit:
                    bypasses.append(LimitBypass(limited_edge=le, bypass_path=[sibling]))

            # BFS bypass: alternate path from source to target (max depth 4)
            found = self._bfs_bypass(le, adj, max_depth=4)
            for path in found:
                bypasses.append(LimitBypass(limited_edge=le, bypass_path=path))

        return bypasses

    def _bfs_bypass(
        self,
        limited_edge: EdgeInfo,
        adj: dict[type[Model], list[EdgeInfo]],
        max_depth: int,
    ) -> list[list[EdgeInfo]]:
        """BFS from source to target excluding the limited edge, looking for unlimited paths."""
        source = limited_edge.source_model
        target = limited_edge.target_model
        results = []

        # BFS: queue of (current_model, path_of_edges)
        queue: list[tuple[type[Model], list[EdgeInfo]]] = [(source, [])]

        for _ in range(max_depth):
            next_queue: list[tuple[type[Model], list[EdgeInfo]]] = []
            for current, path in queue:
                for e in adj.get(current, []):
                    # Skip the limited edge itself
                    if (
                        e.source_model == limited_edge.source_model
                        and e.field_name == limited_edge.field_name
                    ):
                        continue
                    new_path = path + [e]
                    if e.target_model == target and len(new_path) >= 2:
                        # Check if not every hop is limited
                        if not all(hop.has_limit for hop in new_path):
                            results.append(new_path)
                    elif len(new_path) < max_depth:
                        next_queue.append((e.target_model, new_path))
            queue = next_queue

        return results

    # -- Step 5: Shared reference detection --

    def _detect_shared_references(self, edges: list[EdgeInfo], threshold: int) -> list[SharedRef]:
        # Count incoming edges per target model, grouped by distinct source model
        incoming: dict[type[Model], list[EdgeInfo]] = defaultdict(list)
        outgoing: dict[type[Model], list[EdgeInfo]] = defaultdict(list)

        for e in edges:
            incoming[e.target_model].append(e)
            outgoing[e.source_model].append(e)

        results = []
        for model in self.spec.models:
            inc = incoming.get(model, [])
            distinct_sources = len({e.source_model for e in inc})
            if distinct_sources >= threshold:
                results.append(
                    SharedRef(
                        model=model,
                        model_label=model._meta.label,
                        incoming_edges=inc,
                        outgoing_edges=outgoing.get(model, []),
                        in_degree=distinct_sources,
                    )
                )

        return results

    # -- Step 6: DB cardinality estimation --

    def _estimate_cardinality(self, edges: list[EdgeInfo]) -> list[CardinalityEstimate]:
        estimates = []
        for e in edges:
            # Skip forward FK/O2O (always 0-1 cardinality)
            if e.field_class in (FieldClass.FK_IN_SCOPE, FieldClass.O2O_IN_SCOPE):
                continue

            try:
                estimate = self._estimate_edge(e)
                if estimate is not None:
                    estimates.append(estimate)
            except Exception:
                pass

        return estimates

    def _estimate_edge(self, e: EdgeInfo) -> CardinalityEstimate | None:
        if e.field_class == FieldClass.REVERSE_FK_IN_SCOPE:
            return self._estimate_reverse_fk(e)
        elif e.field_class == FieldClass.REVERSE_O2O_IN_SCOPE:
            # Always 0-1
            total = e.target_model.objects.count()
            avg = 1.0 if total > 0 else 0.0
            return CardinalityEstimate(
                edge=e, avg_cardinality=avg, max_cardinality=1, total_count=total
            )
        elif e.field_class in (FieldClass.M2M_IN_SCOPE, FieldClass.REVERSE_M2M_IN_SCOPE):
            return self._estimate_m2m(e)
        elif e.field_class == FieldClass.GENERIC_RELATION_IN_SCOPE:
            return self._estimate_generic_relation(e)
        return None

    def _estimate_reverse_fk(self, e: EdgeInfo) -> CardinalityEstimate | None:
        from django.db.models import Avg, Count, Max

        # The FK field is on the target model, pointing back to source
        # We need to find the actual FK field name on the target model
        target_model = e.target_model
        source_model = e.source_model

        # Find the FK field on target that points to source
        fk_field_name = None
        for f in target_model._meta.get_fields():
            if hasattr(f, "related_model") and f.related_model == source_model:
                if hasattr(f, "attname"):  # It's a concrete FK field
                    fk_field_name = f.name
                    break

        if fk_field_name is None:
            return None

        total = target_model.objects.count()
        if total == 0:
            return CardinalityEstimate(
                edge=e, avg_cardinality=0.0, max_cardinality=0, total_count=0
            )

        # Group by FK, count per group
        stats = (
            target_model.objects.values(fk_field_name)
            .annotate(cnt=Count("pk"))
            .aggregate(
                avg_cnt=Avg("cnt"),
                max_cnt=Max("cnt"),
            )
        )

        return CardinalityEstimate(
            edge=e,
            avg_cardinality=float(stats["avg_cnt"] or 0),
            max_cardinality=int(stats["max_cnt"] or 0),
            total_count=total,
        )

    def _estimate_m2m(self, e: EdgeInfo) -> CardinalityEstimate | None:
        from django.db.models import Avg, Count, Max

        # For M2M, count via the through table
        source_model = e.source_model

        # Find the M2M field
        m2m_field = None
        for f in source_model._meta.get_fields():
            if hasattr(f, "get_accessor_name") and f.get_accessor_name() == e.field_name:
                m2m_field = f
                break
            if hasattr(f, "name") and f.name == e.field_name:
                m2m_field = f
                break

        if m2m_field is None:
            return None

        # Get through model
        if hasattr(m2m_field, "through"):
            through = m2m_field.through
        elif hasattr(m2m_field, "field") and hasattr(m2m_field.field, "remote_field"):
            through = m2m_field.field.remote_field.through
        else:
            return None

        total = through.objects.count()
        if total == 0:
            return CardinalityEstimate(
                edge=e, avg_cardinality=0.0, max_cardinality=0, total_count=0
            )

        # Find the column that points to the source model
        source_col = None
        for f in through._meta.get_fields():
            if (
                hasattr(f, "related_model")
                and f.related_model == source_model
                and hasattr(f, "attname")
            ):
                source_col = f.name
                break

        if source_col is None:
            return None

        stats = (
            through.objects.values(source_col)
            .annotate(cnt=Count("pk"))
            .aggregate(
                avg_cnt=Avg("cnt"),
                max_cnt=Max("cnt"),
            )
        )

        return CardinalityEstimate(
            edge=e,
            avg_cardinality=float(stats["avg_cnt"] or 0),
            max_cardinality=int(stats["max_cnt"] or 0),
            total_count=total,
        )

    def _estimate_generic_relation(self, e: EdgeInfo) -> CardinalityEstimate | None:
        from django.db.models import Avg, Count, Max

        target_model = e.target_model
        source_model = e.source_model

        # GenericRelation uses content_type + object_id on the target
        from django.contrib.contenttypes.models import ContentType

        try:
            ct = ContentType.objects.get_for_model(source_model)
        except Exception:
            return None

        total = target_model.objects.filter(content_type=ct).count()
        if total == 0:
            return CardinalityEstimate(
                edge=e, avg_cardinality=0.0, max_cardinality=0, total_count=0
            )

        stats = (
            target_model.objects.filter(content_type=ct)
            .values("object_id")
            .annotate(cnt=Count("pk"))
            .aggregate(avg_cnt=Avg("cnt"), max_cnt=Max("cnt"))
        )

        return CardinalityEstimate(
            edge=e,
            avg_cardinality=float(stats["avg_cnt"] or 0),
            max_cardinality=int(stats["max_cnt"] or 0),
            total_count=total,
        )
