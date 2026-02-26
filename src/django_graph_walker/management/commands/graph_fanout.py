"""Management command for static fan-out risk analysis."""

from __future__ import annotations

import importlib
import json

from django.core.management.base import BaseCommand, CommandError

from django_graph_walker.analysis import FanoutAnalyzer, FanoutReport
from django_graph_walker.spec import GraphSpec


class Command(BaseCommand):
    help = (
        "Analyze a GraphSpec for fan-out risks: cycles, bidirectional edges,"
        " limit bypasses, shared references."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "apps",
            nargs="*",
            help="App labels to include (e.g. testapp reviews).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            dest="all_apps",
            help="Include all apps (excluding Django internals by default).",
        )
        parser.add_argument(
            "--spec",
            help="Dotted path to a GraphSpec object (e.g. myapp.specs.my_spec).",
        )
        parser.add_argument(
            "--estimate",
            action="store_true",
            help="Run DB queries to estimate cardinality per edge.",
        )
        parser.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help="Output format (default: text).",
        )
        parser.add_argument(
            "--threshold",
            type=int,
            default=3,
            help="Shared-reference sensitivity: min incoming edges from distinct models.",
        )
        parser.add_argument(
            "--exclude",
            action="append",
            default=[],
            help="Exclude specific models (e.g. testapp.Comment). Can be repeated.",
        )

    def handle(self, *args, **options):
        spec = self._build_spec(options)
        analyzer = FanoutAnalyzer(spec)

        if options["estimate"]:
            report = analyzer.estimate_fanout(threshold=options["threshold"])
        else:
            report = analyzer.analyze(threshold=options["threshold"])

        if options["format"] == "json":
            self.stdout.write(self._to_json(report))
        else:
            self._print_text(report, options)

    def _build_spec(self, options) -> GraphSpec:
        from django.apps import apps

        if options["spec"]:
            spec = self._import_spec(options["spec"])
        elif options["all_apps"]:
            spec = GraphSpec.all()
        elif options["apps"]:
            for label in options["apps"]:
                try:
                    apps.get_app_config(label)
                except LookupError:
                    raise CommandError(f"No installed app with label '{label}'.")
            spec = GraphSpec.from_apps(*options["apps"])
        else:
            raise CommandError("Provide app labels, --all, or --spec.")

        if options["exclude"]:
            exclude_models = []
            for model_label in options["exclude"]:
                try:
                    model = apps.get_model(model_label)
                except LookupError:
                    raise CommandError(f"Unknown model '{model_label}'.")
                exclude_models.append(model)
            spec = spec.exclude(*exclude_models)

        if not spec.models:
            raise CommandError("No models found for the given arguments.")

        return spec

    def _import_spec(self, dotted_path: str) -> GraphSpec:
        module_path, _, attr_name = dotted_path.rpartition(".")
        if not module_path:
            raise CommandError(
                f"Invalid spec path '{dotted_path}'. Use format: module.path.attr_name"
            )
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            raise CommandError(f"Could not import module '{module_path}': {e}")

        try:
            spec = getattr(module, attr_name)
        except AttributeError:
            raise CommandError(f"Module '{module_path}' has no attribute '{attr_name}'.")

        if not isinstance(spec, GraphSpec):
            raise CommandError(
                f"'{dotted_path}' is not a GraphSpec instance (got {type(spec).__name__})."
            )
        return spec

    def _print_text(self, report: FanoutReport, options):
        all_models = {e.source_model for e in report.edges}
        all_models |= {e.target_model for e in report.edges}
        model_count = len(all_models)
        self.stdout.write(
            f"\nFan-out Analysis ({model_count} models, {len(report.edges)} followed edges)"
        )
        self.stdout.write("=" * 60)

        # Cycles
        self.stdout.write(f"\nCYCLES ({len(report.cycles)} found)")
        if report.cycles:
            for cycle in report.cycles:
                labels = [m._meta.label for m in cycle.models]
                if len(cycle.models) == 1:
                    self.stdout.write(f"  {labels[0]} (self-referential)")
                else:
                    joined = " \u2194 ".join(labels)
                    self.stdout.write(f"  {joined}")
                for e in cycle.edges:
                    default_str = ", default" if e.is_default else ""
                    self.stdout.write(
                        f"    {e.source_label}.{e.field_name} \u2192 {e.target_label} "
                        f"[{e.field_class.name}{default_str}]"
                    )
                for brk in cycle.suggested_breaks:
                    self.stdout.write(
                        self.style.WARNING(
                            f"    \u2192 Suggest: Ignore '{brk.field_name}' on "
                            f"{brk.source_model.__name__}"
                        )
                    )
        else:
            self.stdout.write("  None detected.")

        # Bidirectional
        self.stdout.write(f"\nBIDIRECTIONAL EDGES ({len(report.bidirectional)} pairs)")
        if report.bidirectional:
            for fwd, bwd in report.bidirectional:
                self.stdout.write(
                    f"  {fwd.source_label} \u2194 {fwd.target_label}: "
                    f"{fwd.field_name} / {bwd.field_name}"
                )
        else:
            self.stdout.write("  None detected.")

        # Limit bypasses
        self.stdout.write(f"\nLIMIT BYPASSES ({len(report.limit_bypasses)} found)")
        if report.limit_bypasses:
            for bypass in report.limit_bypasses:
                le = bypass.limited_edge
                self.stdout.write(
                    f"  {le.source_label}.{le.field_name} (limit={le.limit_value}) bypassed by:"
                )
                path_str = " \u2192 ".join(
                    f"{e.source_label}.{e.field_name}" for e in bypass.bypass_path
                )
                self.stdout.write(f"    {path_str} \u2192 {le.target_label}")
        else:
            self.stdout.write("  None detected.")

        # Shared references
        threshold = options["threshold"]
        self.stdout.write(
            f"\nSHARED REFERENCES ({len(report.shared_references)} found, threshold={threshold})"
        )
        if report.shared_references:
            for ref in report.shared_references:
                self.stdout.write(f"  {ref.model_label} (in-degree: {ref.in_degree})")
                for e in ref.incoming_edges:
                    default_str = ", default" if e.is_default else ""
                    self.stdout.write(
                        f"    \u2190 {e.source_label}.{e.field_name} "
                        f"[{e.field_class.name}{default_str}]"
                    )
                for e in ref.outgoing_edges:
                    default_str = ", default" if e.is_default else ""
                    self.stdout.write(
                        f"    \u2192 {e.field_name} [{e.field_class.name}{default_str}]"
                    )
        else:
            self.stdout.write("  None detected.")

        # Cardinality
        if report.cardinality is not None:
            self.stdout.write(f"\nCARDINALITY ESTIMATES ({len(report.cardinality)} edges)")
            if report.cardinality:
                for est in report.cardinality:
                    self.stdout.write(
                        f"  {est.edge.source_label}.{est.edge.field_name} \u2192 "
                        f"{est.edge.target_label}: "
                        f"avg={est.avg_cardinality:.1f}, max={est.max_cardinality}, "
                        f"total={est.total_count}"
                    )
            else:
                self.stdout.write("  No data.")

        self.stdout.write("")

    def _to_json(self, report: FanoutReport) -> str:
        data = {
            "edges": [
                {
                    "source": e.source_label,
                    "target": e.target_label,
                    "field": e.field_name,
                    "field_class": e.field_class.name,
                    "has_limit": e.has_limit,
                    "limit_value": e.limit_value,
                    "is_default": e.is_default,
                }
                for e in report.edges
            ],
            "cycles": [
                {
                    "models": [m._meta.label for m in c.models],
                    "edges": [
                        {
                            "source": e.source_label,
                            "field": e.field_name,
                            "target": e.target_label,
                        }
                        for e in c.edges
                    ],
                    "suggested_breaks": [
                        {"source": e.source_label, "field": e.field_name}
                        for e in c.suggested_breaks
                    ],
                }
                for c in report.cycles
            ],
            "bidirectional": [
                {
                    "model_a": fwd.source_label,
                    "model_b": fwd.target_label,
                    "field_a": fwd.field_name,
                    "field_b": bwd.field_name,
                }
                for fwd, bwd in report.bidirectional
            ],
            "limit_bypasses": [
                {
                    "limited_edge": {
                        "source": b.limited_edge.source_label,
                        "field": b.limited_edge.field_name,
                        "limit": b.limited_edge.limit_value,
                    },
                    "bypass_path": [
                        {"source": e.source_label, "field": e.field_name, "target": e.target_label}
                        for e in b.bypass_path
                    ],
                }
                for b in report.limit_bypasses
            ],
            "shared_references": [
                {
                    "model": ref.model_label,
                    "in_degree": ref.in_degree,
                    "incoming": [
                        {"source": e.source_label, "field": e.field_name}
                        for e in ref.incoming_edges
                    ],
                    "outgoing": [
                        {"field": e.field_name, "target": e.target_label}
                        for e in ref.outgoing_edges
                    ],
                }
                for ref in report.shared_references
            ],
        }

        if report.cardinality is not None:
            data["cardinality"] = [
                {
                    "source": est.edge.source_label,
                    "field": est.edge.field_name,
                    "target": est.edge.target_label,
                    "avg_cardinality": round(est.avg_cardinality, 2),
                    "max_cardinality": est.max_cardinality,
                    "total_count": est.total_count,
                }
                for est in report.cardinality
            ]

        return json.dumps(data, indent=2)
