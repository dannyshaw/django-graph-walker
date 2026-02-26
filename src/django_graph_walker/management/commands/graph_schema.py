"""Management command to visualize model schema graphs."""

from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand, CommandError

from django_graph_walker.discovery import FieldClass, get_model_fields
from django_graph_walker.spec import GraphSpec


class Command(BaseCommand):
    help = "Visualize model relationship schema as DOT, PNG, JSON, or interactive HTML."

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
            choices=["dot", "png", "svg", "pdf", "json", "html", "3d"],
            default="dot",
            help="Output format (default: dot). html=Cytoscape.js, 3d=3d-force-graph.",
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
        parser.add_argument(
            "--serve",
            action="store_true",
            help="Serve the output via a local HTTP server and open in browser. "
            "Implies --format=html if no format specified. Press Ctrl+C to stop.",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=0,
            help="Port for --serve (default: random available port).",
        )

    def handle(self, *args, **options):
        spec = self._build_spec(options)

        if options["serve"]:
            if options["format"] not in ("html", "3d"):
                options["format"] = "html"
            self._serve(spec, options)
            return

        if options["format"] == "json":
            output = self._to_json(spec)
        elif options["format"] in ("png", "svg", "pdf"):
            self._render_graphviz(spec, options)
            return
        elif options["format"] in ("html", "3d"):
            output = self._to_interactive(spec, options)
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

    def _to_interactive(self, spec: GraphSpec, options) -> str:
        from django_graph_walker.actions.interactive import InteractiveRenderer
        from django_graph_walker.actions.visualize import Visualize

        show_field_names = not options["no_field_names"]
        graph_data = Visualize(show_field_names=show_field_names).schema_to_dict(spec)
        renderer = InteractiveRenderer()

        if options["format"] == "3d":
            return renderer.to_3d_html(graph_data, title="Model Schema")
        return renderer.to_cytoscape_html(graph_data, title="Model Schema")

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

    def _serve(self, spec: GraphSpec, options):
        import http.server
        import socketserver
        import tempfile
        import threading
        import webbrowser
        from pathlib import Path

        html = self._to_interactive(spec, options)

        # Write to -o path if given, otherwise a temp file
        if options["output"]:
            out_path = Path(options["output"]).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(html)
        else:
            tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w")
            tmp.write(html)
            tmp.close()
            out_path = Path(tmp.name)

        serve_dir = str(out_path.parent)
        filename = out_path.name
        port = options["port"]

        handler = http.server.SimpleHTTPRequestHandler
        with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
            httpd.allow_reuse_address = True
            actual_port = httpd.server_address[1]
            url = f"http://127.0.0.1:{actual_port}/{filename}"

            # Serve from the file's directory
            import os

            os.chdir(serve_dir)

            self.stderr.write(self.style.SUCCESS(f"Serving at {url}"))
            self.stderr.write("Press Ctrl+C to stop.")

            threading.Timer(0.5, lambda: webbrowser.open(url)).start()

            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                self.stderr.write("\nStopped.")
