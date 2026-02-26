"""Graphviz DOT visualization for model graphs."""

from __future__ import annotations

from typing import Optional

from django.db.models import Model

from django_graph_walker.discovery import FieldClass, FieldInfo, get_model_fields
from django_graph_walker.result import WalkResult
from django_graph_walker.spec import GraphSpec

# Edge styles by relationship type
_EDGE_STYLES = {
    FieldClass.FK_IN_SCOPE: {"style": "solid", "arrowhead": "normal"},
    FieldClass.O2O_IN_SCOPE: {"style": "bold", "arrowhead": "normal"},
    FieldClass.M2M_IN_SCOPE: {"style": "dashed", "arrowhead": "normal", "dir": "both"},
    FieldClass.REVERSE_FK_IN_SCOPE: {"style": "solid", "arrowhead": "crow"},
    FieldClass.REVERSE_O2O_IN_SCOPE: {"style": "bold", "arrowhead": "normal"},
    FieldClass.REVERSE_M2M_IN_SCOPE: {"style": "dashed", "arrowhead": "normal", "dir": "both"},
    FieldClass.GENERIC_RELATION_IN_SCOPE: {"style": "dotted", "arrowhead": "diamond"},
}

# Model colors (rotate through these)
_MODEL_COLORS = [
    "#4A90D9",
    "#50C878",
    "#E8A838",
    "#D94A4A",
    "#9B59B6",
    "#1ABC9C",
    "#E67E22",
    "#3498DB",
]


def _escape_dot(text: str) -> str:
    """Escape special characters for DOT format."""
    return text.replace('"', '\\"').replace("\n", "\\n")


class Visualize:
    """Generate Graphviz DOT visualizations of model graphs.

    Usage:
        spec = GraphSpec(Author, Book, Publisher)

        # Schema-level (no DB needed)
        dot_string = Visualize().schema(spec)

        # Instance-level (after walking)
        result = GraphWalker(spec).walk(book)
        dot_string = Visualize().instances(result)

        # If graphviz package is installed, get a Digraph object
        digraph = Visualize().schema_to_graphviz(spec)
        digraph.render('output', format='png')
    """

    def __init__(self, *, show_field_names: bool = True):
        self.show_field_names = show_field_names

    def schema(self, spec: GraphSpec) -> str:
        """Generate a DOT string showing model relationships from a spec.

        This only inspects the schema — no database queries are made.
        """
        lines = ["digraph ModelGraph {", "  rankdir=LR;", "  node [shape=record];", ""]

        models = sorted(spec.models, key=lambda m: m.__name__)
        color_map = {m: _MODEL_COLORS[i % len(_MODEL_COLORS)] for i, m in enumerate(models)}

        # Add model nodes
        for model in models:
            color = color_map[model]
            lines.append(
                f"  {model.__name__} "
                f'[label="{model.__name__}" '
                f'style=filled fillcolor="{color}" fontcolor=white];'
            )

        lines.append("")

        # Add edges — only for forward relationships and GenericRelation to avoid duplicates
        seen_edges: set[tuple[str, str, str]] = set()
        for model in models:
            fields = get_model_fields(model, in_scope=spec.models)
            for fi in fields:
                edge_info = self._schema_edge(model, fi, spec)
                if edge_info is None:
                    continue
                source, target, label, attrs = edge_info
                edge_key = (source, target, label)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)

                attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items())
                if self.show_field_names and label:
                    attr_str += f' label="{_escape_dot(label)}"'
                lines.append(f"  {source} -> {target} [{attr_str}];")

        lines.append("}")
        return "\n".join(lines)

    def _schema_edge(
        self,
        model: type[Model],
        fi: FieldInfo,
        spec: GraphSpec,
    ) -> Optional[tuple[str, str, str, dict[str, str]]]:
        """Determine if a field should produce an edge in the schema graph.

        Returns (source_name, target_name, label, style_attrs) or None.
        Only produces edges for forward FK, O2O, M2M, and GenericRelation
        to avoid drawing each relationship twice.
        """
        if fi.field_class not in (
            FieldClass.FK_IN_SCOPE,
            FieldClass.O2O_IN_SCOPE,
            FieldClass.M2M_IN_SCOPE,
            FieldClass.GENERIC_RELATION_IN_SCOPE,
        ):
            return None

        target_model = fi.related_model
        if target_model is None or target_model not in spec:
            return None

        attrs = dict(_EDGE_STYLES.get(fi.field_class, {}))
        return (model.__name__, target_model.__name__, fi.name, attrs)

    def instances(self, walk_result: WalkResult) -> str:
        """Generate a DOT string showing actual instances and their connections."""
        lines = ["digraph InstanceGraph {", "  rankdir=LR;", "  node [shape=box];", ""]

        by_model = walk_result.by_model()
        models = sorted(by_model.keys(), key=lambda m: m.__name__)
        color_map = {m: _MODEL_COLORS[i % len(_MODEL_COLORS)] for i, m in enumerate(models)}

        # Subgraph per model for clustering
        for model in models:
            color = color_map[model]
            lines.append(f"  subgraph cluster_{model.__name__} {{")
            lines.append(f'    label="{model.__name__}";')
            lines.append(f'    style=filled; color="{color}40";')

            for instance in by_model[model]:
                node_id = f"{model.__name__}_{instance.pk}"
                label = _escape_dot(str(instance))
                lines.append(
                    f'    {node_id} [label="{label}" '
                    f'style=filled fillcolor="{color}" fontcolor=white];'
                )
            lines.append("  }")
            lines.append("")

        # Edges — forward FK, O2O, M2M only
        in_scope = set(by_model.keys())
        visited_pks = {(type(i), i.pk) for i in walk_result}

        for model in models:
            fields = get_model_fields(model, in_scope=in_scope)
            for fi in fields:
                if fi.field_class not in (
                    FieldClass.FK_IN_SCOPE,
                    FieldClass.O2O_IN_SCOPE,
                    FieldClass.M2M_IN_SCOPE,
                ):
                    continue

                for instance in by_model[model]:
                    targets = self._get_instance_targets(instance, fi)
                    for target in targets:
                        if (type(target), target.pk) not in visited_pks:
                            continue
                        src_id = f"{model.__name__}_{instance.pk}"
                        tgt_id = f"{type(target).__name__}_{target.pk}"
                        attrs = dict(_EDGE_STYLES.get(fi.field_class, {}))
                        attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items())
                        if self.show_field_names:
                            attr_str += f' label="{fi.name}"'
                        lines.append(f"  {src_id} -> {tgt_id} [{attr_str}];")

        lines.append("}")
        return "\n".join(lines)

    def _get_instance_targets(self, instance: Model, fi: FieldInfo) -> list[Model]:
        """Get the related instances for a forward relationship."""
        if fi.field_class in (FieldClass.FK_IN_SCOPE, FieldClass.O2O_IN_SCOPE):
            related = getattr(instance, fi.name, None)
            return [related] if related is not None else []
        if fi.field_class == FieldClass.M2M_IN_SCOPE:
            manager = getattr(instance, fi.name, None)
            return list(manager.all()) if manager else []
        return []

    def schema_to_dict(self, spec: GraphSpec) -> dict:
        """Return schema graph as structured data for interactive rendering.

        Returns a dict with 'nodes' and 'edges' lists suitable for
        Cytoscape.js, 3d-force-graph, or any JSON-consuming renderer.
        """
        models = sorted(spec.models, key=lambda m: m.__name__)
        color_map = {m: _MODEL_COLORS[i % len(_MODEL_COLORS)] for i, m in enumerate(models)}

        nodes = []
        for model in models:
            fields = get_model_fields(model, in_scope=spec.models)
            field_names = [fi.name for fi in fields if fi.field_class == FieldClass.VALUE]
            nodes.append(
                {
                    "id": model.__name__,
                    "label": model.__name__,
                    "color": color_map[model],
                    "field_count": len(field_names),
                    "fields": field_names,
                }
            )

        edges = []
        seen_edges: set[tuple[str, str, str]] = set()
        for model in models:
            fields = get_model_fields(model, in_scope=spec.models)
            for fi in fields:
                edge_info = self._schema_edge(model, fi, spec)
                if edge_info is None:
                    continue
                source, target, label, attrs = edge_info
                edge_key = (source, target, label)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                edges.append(
                    {
                        "source": source,
                        "target": target,
                        "label": label,
                        "field_class": fi.field_class.name,
                        "style": attrs.get("style", "solid"),
                    }
                )

        return {"nodes": nodes, "edges": edges}

    def instances_to_dict(self, walk_result: WalkResult) -> dict:
        """Return instance graph as structured data for interactive rendering.

        Returns a dict with 'nodes' and 'edges' lists suitable for
        Cytoscape.js, 3d-force-graph, or any JSON-consuming renderer.
        """
        by_model = walk_result.by_model()
        models = sorted(by_model.keys(), key=lambda m: m.__name__)
        color_map = {m: _MODEL_COLORS[i % len(_MODEL_COLORS)] for i, m in enumerate(models)}
        visited_pks = {(type(i), i.pk) for i in walk_result}
        in_scope = set(by_model.keys())

        nodes = []
        for model in models:
            color = color_map[model]
            for instance in by_model[model]:
                nodes.append(
                    {
                        "id": f"{model.__name__}_{instance.pk}",
                        "label": str(instance),
                        "model": model.__name__,
                        "pk": instance.pk,
                        "color": color,
                        "group": model.__name__,
                    }
                )

        edges = []
        for model in models:
            fields = get_model_fields(model, in_scope=in_scope)
            for fi in fields:
                if fi.field_class not in (
                    FieldClass.FK_IN_SCOPE,
                    FieldClass.O2O_IN_SCOPE,
                    FieldClass.M2M_IN_SCOPE,
                ):
                    continue
                for instance in by_model[model]:
                    targets = self._get_instance_targets(instance, fi)
                    for target in targets:
                        if (type(target), target.pk) not in visited_pks:
                            continue
                        edges.append(
                            {
                                "source": f"{model.__name__}_{instance.pk}",
                                "target": f"{type(target).__name__}_{target.pk}",
                                "label": fi.name,
                                "field_class": fi.field_class.name,
                            }
                        )

        return {"nodes": nodes, "edges": edges}

    def schema_to_graphviz(self, spec: GraphSpec):
        """Return a graphviz.Digraph object for the schema. Requires graphviz package."""
        import graphviz

        dot_str = self.schema(spec)
        return graphviz.Source(dot_str, engine="dot")

    def instances_to_graphviz(self, walk_result: WalkResult):
        """Return a graphviz.Digraph object for instances. Requires graphviz package."""
        import graphviz

        dot_str = self.instances(walk_result)
        return graphviz.Source(dot_str, engine="dot")
