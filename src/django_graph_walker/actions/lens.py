"""Lens action -- generate a curated read-only view layer + role DDL from a GraphSpec."""

from __future__ import annotations

from django.db.models import Model

from django_graph_walker.spec import GraphSpec, Ignore


def _q(identifier: str) -> str:
    """Double-quote a Postgres identifier, doubling any embedded double-quote."""
    return '"' + identifier.replace('"', '""') + '"'


class Lens:
    """Generate a curated, read-only Postgres lens (views + role) from a GraphSpec.

    The spec's model set is the relation allowlist. Per-field overrides shape each
    view's columns: Ignore() drops a column, Mask(strategy) masks it via a SQL
    expression. The same spec also produces an LLM-facing schema-context dict
    (to_schema_context).

    Usage:
        lens = Lens(
            MASKED_LENS,
            schema_name="staff_lens_masked",
            role_name="staff_masked",
            hash_salt="rotate-me",
        )
        view_sql = lens.to_view_ddl()
        role_sql = lens.to_role_ddl()
        context = lens.to_schema_context()
    """

    def __init__(
        self,
        spec: GraphSpec,
        *,
        schema_name: str,
        role_name: str,
        hash_salt: str = "",
        source_schema: str = "public",
    ):
        self.spec = spec
        self.schema_name = schema_name
        self.role_name = role_name
        self.hash_salt = hash_salt
        self.source_schema = source_schema

    def _ordered_models(self) -> list[type[Model]]:
        return sorted(self.spec.models, key=lambda m: m._meta.db_table)

    def _column_expr(self, column: str, override) -> str | None:
        """SELECT expression for a column, or None if the column is dropped.

        Task 3 extends this method with Mask handling; Task 2 covers plain
        columns and Ignore()-drop only.
        """
        if isinstance(override, Ignore):
            return None
        return _q(column)

    def _view_ddl_for_model(self, model: type[Model]) -> str:
        overrides = self.spec.get_overrides(model)
        db_table = model._meta.db_table
        exprs = []
        for field in model._meta.local_fields:
            expr = self._column_expr(field.column, overrides.get(field.name))
            if expr is not None:
                exprs.append("    " + expr)
        select_list = ",\n".join(exprs)

        view = f"{_q(self.schema_name)}.{_q(db_table)}"
        source = f"{_q(self.source_schema)}.{_q(db_table)}"
        return f"CREATE OR REPLACE VIEW {view} AS\nSELECT\n{select_list}\nFROM {source};"

    def to_view_ddl(self) -> str:
        """DDL that (re)creates the lens schema and one view per allowlisted model."""
        parts = [f"CREATE SCHEMA IF NOT EXISTS {_q(self.schema_name)};"]
        parts.extend(self._view_ddl_for_model(m) for m in self._ordered_models())
        return "\n\n".join(parts) + "\n"
