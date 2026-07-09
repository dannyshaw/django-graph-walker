"""Generate lens view DDL, role DDL, and LLM schema context from a GraphSpec."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from django_graph_walker.actions.lens import Lens
from django_graph_walker.spec import GraphSpec


class Command(BaseCommand):
    help = "Generate a curated read-only lens (views + role + schema context) from a GraphSpec."

    def add_arguments(self, parser):
        parser.add_argument(
            "--spec",
            required=True,
            help="Dotted path to a GraphSpec object (e.g. myapp.specs.masked_lens).",
        )
        parser.add_argument("--schema", required=True, help="Target lens schema name.")
        parser.add_argument("--role", required=True, help="Read-only role name.")
        parser.add_argument("--salt", default="", help="Salt for hash masking.")
        parser.add_argument("--source-schema", default="public", help="Schema of the base tables.")
        parser.add_argument(
            "--row-filter",
            action="append",
            default=[],
            metavar="Model=SQL",
            help="Per-model WHERE clause, e.g. User=is_test=false. Repeatable.",
        )
        parser.add_argument("--out-ddl", help="Write view DDL to this path.")
        parser.add_argument("--out-role-ddl", help="Write role DDL to this path.")
        parser.add_argument("--out-context", help="Write schema context JSON to this path.")

    def handle(self, *args, **options):
        spec = self._import_spec(options["spec"])
        row_filters = self._parse_row_filters(options["row_filter"], spec)

        lens = Lens(
            spec,
            schema_name=options["schema"],
            role_name=options["role"],
            hash_salt=options["salt"],
            source_schema=options["source_schema"],
            row_filters=row_filters,
        )

        self._emit(options["out_ddl"], lens.to_view_ddl(), "-- View DDL --")
        self._emit(options["out_role_ddl"], lens.to_role_ddl(), "-- Role DDL --")
        self._emit(
            options["out_context"],
            json.dumps(lens.to_schema_context(), indent=2),
            "-- Schema context --",
        )

    def _emit(self, path: str | None, content: str, header: str) -> None:
        if path:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            self.stdout.write(f"Wrote {path}")
        else:
            self.stdout.write(header)
            self.stdout.write(content)

    def _parse_row_filters(self, raw: list[str], spec: GraphSpec) -> dict:
        by_name = {m.__name__: m for m in spec.models}
        filters = {}
        for item in raw:
            model_name, sep, clause = item.partition("=")
            if not sep:
                raise CommandError(f"Invalid --row-filter '{item}'. Use Model=SQL.")
            model = by_name.get(model_name.strip())
            if model is None:
                raise CommandError(
                    f"--row-filter model '{model_name.strip()}' is not in the spec."
                )
            filters[model] = clause.strip()
        return filters

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
