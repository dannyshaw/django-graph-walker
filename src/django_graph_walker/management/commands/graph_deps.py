"""Management command for dependency analysis of Django models."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.db.models import CASCADE, SET_NULL

from django_graph_walker.discovery import FieldClass, get_model_fields
from django_graph_walker.spec import GraphSpec


class Command(BaseCommand):
    help = (
        "Analyze model dependencies: upstream targets, downstream dependents, on_delete behavior."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "target",
            help="Model label (e.g. books.Book) or app label (e.g. books).",
        )
        parser.add_argument(
            "--tree",
            action="store_true",
            help="Show the full dependency tree for an app.",
        )
        parser.add_argument(
            "--orphans",
            action="store_true",
            help="Show models with no relationships to other in-scope models.",
        )
        parser.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help="Output format (default: text).",
        )

    def handle(self, *args, **options):
        from django.apps import apps

        target = options["target"]

        # Determine if target is a model or an app
        try:
            model = apps.get_model(target)
            is_model = True
        except (LookupError, ValueError):
            model = None
            is_model = False

        if is_model:
            self._analyze_model(model, options)
        else:
            # Try as app label
            try:
                apps.get_app_config(target)
            except LookupError:
                raise CommandError(f"'{target}' is not a valid model label or app label.")
            self._analyze_app(target, options)

    def _analyze_model(self, model, options):
        from django.apps import apps

        # Use all models as scope to find all relationships
        all_models = set(apps.get_models())
        fields = get_model_fields(model, in_scope=all_models)

        upstream = []  # FK targets (what this model depends on)
        downstream = []  # Reverse FKs (what depends on this model)

        for fi in fields:
            if fi.field_class in (FieldClass.FK_IN_SCOPE, FieldClass.O2O_IN_SCOPE):
                on_delete = self._get_on_delete(fi)
                upstream.append(
                    {
                        "model": fi.related_model._meta.label,
                        "field": fi.name,
                        "type": fi.field_class.name,
                        "on_delete": on_delete,
                    }
                )
            elif fi.field_class in (
                FieldClass.REVERSE_FK_IN_SCOPE,
                FieldClass.REVERSE_O2O_IN_SCOPE,
            ):
                on_delete = self._get_on_delete(fi)
                downstream.append(
                    {
                        "model": fi.related_model._meta.label,
                        "field": fi.name,
                        "type": fi.field_class.name,
                        "on_delete": on_delete,
                    }
                )
            elif fi.field_class == FieldClass.M2M_IN_SCOPE:
                upstream.append(
                    {
                        "model": fi.related_model._meta.label,
                        "field": fi.name,
                        "type": "M2M",
                    }
                )
            elif fi.field_class == FieldClass.REVERSE_M2M_IN_SCOPE:
                downstream.append(
                    {
                        "model": fi.related_model._meta.label,
                        "field": fi.name,
                        "type": "REVERSE_M2M",
                    }
                )

        if options["format"] == "json":
            data = {
                "model": model._meta.label,
                "depends_on": upstream,
                "depended_on_by": downstream,
            }
            self.stdout.write(json.dumps(data, indent=2))
        else:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{model._meta.label}"))
            self._print_section("Depends on (upstream)", upstream)
            self._print_section("Depended on by (downstream)", downstream)
            if not upstream and not downstream:
                self.stdout.write("  No relationships to other models.")

    def _analyze_app(self, app_label, options):
        spec = GraphSpec.from_app(app_label)
        models = sorted(spec.models, key=lambda m: m._meta.label)

        if options["orphans"]:
            self._show_orphans(models, spec)
            return

        if options["tree"]:
            self._show_tree(models, spec, options)
            return

        # Default: show deps for each model in the app
        for model in models:
            self._analyze_model(model, options)

    def _show_orphans(self, models, spec):
        orphans = []
        for model in models:
            fields = get_model_fields(model, in_scope=spec.models)
            has_relationship = any(
                fi.field_class
                in (
                    FieldClass.FK_IN_SCOPE,
                    FieldClass.O2O_IN_SCOPE,
                    FieldClass.M2M_IN_SCOPE,
                    FieldClass.REVERSE_FK_IN_SCOPE,
                    FieldClass.REVERSE_O2O_IN_SCOPE,
                    FieldClass.REVERSE_M2M_IN_SCOPE,
                    FieldClass.GENERIC_RELATION_IN_SCOPE,
                )
                for fi in fields
            )
            if not has_relationship:
                orphans.append(model)

        if orphans:
            self.stdout.write("Models with no relationships to other in-scope models:")
            for m in orphans:
                self.stdout.write(f"  {m._meta.label}")
        else:
            self.stdout.write("No orphan models found.")

    def _show_tree(self, models, spec, options):
        """Show dependency tree: which models depend on which."""
        deps = {}
        for model in models:
            fields = get_model_fields(model, in_scope=spec.models)
            targets = set()
            for fi in fields:
                if fi.field_class in (FieldClass.FK_IN_SCOPE, FieldClass.O2O_IN_SCOPE):
                    if fi.related_model != model:  # skip self-referential
                        targets.add(fi.related_model._meta.label)
            deps[model._meta.label] = sorted(targets)

        if options["format"] == "json":
            self.stdout.write(json.dumps(deps, indent=2))
        else:
            self.stdout.write("Dependency tree (model -> depends on):")
            for label in sorted(deps):
                targets = deps[label]
                if targets:
                    self.stdout.write(f"  {label} -> {', '.join(targets)}")
                else:
                    self.stdout.write(f"  {label} (no FK dependencies)")

    def _get_on_delete(self, fi) -> str:
        """Extract the on_delete behavior from a field."""
        field = fi.field
        # For reverse relations, the actual field is on the related model
        if hasattr(field, "field"):
            field = field.field
        on_delete = getattr(field, "remote_field", None)
        if on_delete is not None:
            on_delete = getattr(on_delete, "on_delete", None)
        if on_delete is CASCADE:
            return "CASCADE"
        elif on_delete is SET_NULL:
            return "SET_NULL"
        elif on_delete is not None:
            return on_delete.__name__ if hasattr(on_delete, "__name__") else str(on_delete)
        return "UNKNOWN"

    def _print_section(self, title, items):
        if items:
            self.stdout.write(f"  {title}:")
            for item in items:
                on_delete = item.get("on_delete", "")
                delete_str = f" (on_delete={on_delete})" if on_delete else ""
                self.stdout.write(
                    f"    {item['model']}.{item['field']} [{item['type']}]{delete_str}"
                )
