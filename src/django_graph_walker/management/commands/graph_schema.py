"""Management command to visualize model schema graphs."""

from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand, CommandError

from django_graph_walker.discovery import FieldClass, get_model_fields
from django_graph_walker.spec import GraphSpec


class Command(BaseCommand):
    help = "Visualize model relationship schema as DOT, PNG, or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "apps",
            nargs="*",
            help="App labels to include (e.g. books reviews).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            dest="all_apps",
            help="Include all apps (excluding Django internals by default).",
        )
        parser.add_argument(
            "-o",
            "--output",
            help="Output file path. Prints to stdout if omitted.",
        )
        parser.add_argument(
            "--format",
            choices=["dot", "png", "svg", "pdf", "json"],
            default="dot",
            help="Output format (default: dot).",
        )
        parser.add_argument(
            "--exclude",
            action="append",
            default=[],
            help="Exclude specific models (e.g. books.Review). Can be repeated.",
        )
        parser.add_argument(
            "--no-field-names",
            action="store_true",
            help="Hide field names on edges.",
        )

    def handle(self, *args, **options):
        spec = self._build_spec(options)

        if options["format"] == "json":
            output = self._to_json(spec)
        elif options["format"] in ("png", "svg", "pdf"):
            self._render_graphviz(spec, options)
            return
        else:
            output = self._to_dot(spec, options)

        if options["output"]:
            with open(options["output"], "w") as f:
                f.write(output)
            self.stderr.write(self.style.SUCCESS(f"Written to {options['output']}"))
        else:
            self.stdout.write(output)

    def _build_spec(self, options) -> GraphSpec:
        from django.apps import apps

        if options["all_apps"]:
            spec = GraphSpec.all()
        elif options["apps"]:
            # Validate app labels
            for label in options["apps"]:
                try:
                    apps.get_app_config(label)
                except LookupError:
                    raise CommandError(f"No installed app with label '{label}'.")
            spec = GraphSpec.from_apps(*options["apps"])
        else:
            raise CommandError("Provide one or more app labels, or use --all.")

        # Apply --exclude
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

    def _to_dot(self, spec: GraphSpec, options) -> str:
        from django_graph_walker.actions.visualize import Visualize

        show_field_names = not options["no_field_names"]
        viz = Visualize(show_field_names=show_field_names)
        return viz.schema(spec)

    def _to_json(self, spec: GraphSpec) -> str:
        models_list = []
        edges_list = []

        for model in sorted(spec.models, key=lambda m: m._meta.label):
            models_list.append(model._meta.label)

            fields = get_model_fields(model, in_scope=spec.models)
            for fi in fields:
                if fi.field_class not in (
                    FieldClass.FK_IN_SCOPE,
                    FieldClass.O2O_IN_SCOPE,
                    FieldClass.M2M_IN_SCOPE,
                    FieldClass.GENERIC_RELATION_IN_SCOPE,
                ):
                    continue
                if fi.related_model is None or fi.related_model not in spec:
                    continue
                edges_list.append(
                    {
                        "source": model._meta.label,
                        "target": fi.related_model._meta.label,
                        "field": fi.name,
                        "type": fi.field_class.name,
                    }
                )

        return json.dumps({"models": models_list, "edges": edges_list}, indent=2)

    def _render_graphviz(self, spec: GraphSpec, options):
        try:
            import graphviz
        except ImportError:
            raise CommandError(
                "The graphviz Python package is required for image output. "
                "Install it with: pip install django-graph-walker[viz]"
            )

        from django_graph_walker.actions.visualize import Visualize

        show_field_names = not options["no_field_names"]
        dot_str = Visualize(show_field_names=show_field_names).schema(spec)
        source = graphviz.Source(dot_str)

        fmt = options["format"]
        output = options.get("output")
        if output:
            # graphviz.Source.render expects filename without extension
            if output.endswith(f".{fmt}"):
                output = output[: -(len(fmt) + 1)]
            source.render(output, format=fmt, cleanup=True)
            self.stderr.write(self.style.SUCCESS(f"Rendered to {output}.{fmt}"))
        else:
            # Write binary to stdout
            data = source.pipe(format=fmt)
            sys.stdout.buffer.write(data)
