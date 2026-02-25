"""Management command to walk model graphs and export results."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from django_graph_walker.spec import GraphSpec
from django_graph_walker.walker import GraphWalker


class Command(BaseCommand):
    help = "Walk a model relationship graph from root instances and optionally export."

    def add_arguments(self, parser):
        parser.add_argument(
            "model",
            help="Model label (e.g. books.Book).",
        )
        parser.add_argument(
            "pks",
            help="Primary key(s), comma-separated (e.g. 42 or 1,2,3).",
        )
        parser.add_argument(
            "--apps",
            help="Comma-separated app labels to scope the walk (default: root model's app).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            dest="all_apps",
            help="Include all apps in scope (excluding Django internals).",
        )
        parser.add_argument(
            "-o",
            "--output",
            help="Export walk result to a JSON fixture file.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Walk and print stats only, do not export.",
        )

    def handle(self, *args, **options):
        from django.apps import apps

        # Resolve model
        model_label = options["model"]
        try:
            model = apps.get_model(model_label)
        except LookupError:
            raise CommandError(f"Unknown model '{model_label}'.")

        # Parse PKs
        pk_str = options["pks"]
        pks = [pk.strip() for pk in pk_str.split(",")]
        if not pks:
            raise CommandError("Provide at least one primary key.")

        # Fetch root instances
        roots = list(model.objects.filter(pk__in=pks))
        if not roots:
            raise CommandError(f"No {model.__name__} instances found for pk(s): {pk_str}")

        found_pks = {str(r.pk) for r in roots}
        missing = [pk for pk in pks if pk not in found_pks]
        if missing:
            msg = f"Warning: no {model.__name__} found for pk(s): {', '.join(missing)}"
            self.stderr.write(self.style.WARNING(msg))

        # Build spec
        spec = self._build_spec(model, options)

        # Walk
        walker = GraphWalker(spec)
        result = walker.walk(*roots)

        # Print stats
        self._print_stats(result)

        # Export
        if options["dry_run"]:
            return

        if options["output"]:
            from django_graph_walker.actions.export import Export

            Export(format="json").to_file(result, options["output"])
            msg = f"Exported {result.instance_count} instances to {options['output']}"
            self.stderr.write(self.style.SUCCESS(msg))

    def _build_spec(self, model, options) -> GraphSpec:
        if options["all_apps"]:
            return GraphSpec.all()
        elif options["apps"]:
            app_labels = [label.strip() for label in options["apps"].split(",")]
            return GraphSpec.from_apps(*app_labels)
        else:
            # Default: root model's app
            app_label = model._meta.app_label
            return GraphSpec.from_app(app_label)

    def _print_stats(self, result):
        count = result.instance_count
        models = result.model_count
        self.stdout.write(f"Walked {count} instances across {models} models:")
        by_model = result.by_model()
        for model_cls in sorted(by_model.keys(), key=lambda m: m.__name__):
            count = len(by_model[model_cls])
            self.stdout.write(f"  {model_cls._meta.label}: {count}")
