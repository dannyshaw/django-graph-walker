"""Tests for the Mask override and the Lens action (view/role DDL + schema context)."""

import pytest

from django_graph_walker import GraphSpec, Ignore, Mask
from django_graph_walker.actions.lens import Lens
from tests.testapp.models import Article, Author, Category, Tag


class TestMaskOverride:
    def test_default_strategy_is_hash(self):
        assert Mask().strategy == "hash"

    def test_accepts_known_strategies(self):
        assert Mask("redact").strategy == "redact"
        assert Mask("null").strategy == "null"

    def test_rejects_unknown_strategy(self):
        with pytest.raises(ValueError, match="Unknown mask strategy"):
            Mask("shred")

    def test_importable_from_top_level(self):
        from django_graph_walker import Mask as TopMask

        assert TopMask is Mask


class TestViewDDL:
    def test_schema_created_first(self):
        spec = GraphSpec(Tag)
        ddl = Lens(spec, schema_name="staff_lens_masked", role_name="staff_masked").to_view_ddl()
        assert ddl.startswith('CREATE SCHEMA IF NOT EXISTS "staff_lens_masked";')

    def test_plain_view_lists_all_columns(self):
        spec = GraphSpec(Author)
        ddl = Lens(spec, schema_name="lens", role_name="r").to_view_ddl()
        expected = (
            'CREATE OR REPLACE VIEW "lens"."testapp_author" AS\n'
            "SELECT\n"
            '    "id",\n'
            '    "name",\n'
            '    "email"\n'
            'FROM "public"."testapp_author";'
        )
        assert expected in ddl

    def test_source_schema_is_configurable(self):
        spec = GraphSpec(Tag)
        ddl = Lens(spec, schema_name="lens", role_name="r", source_schema="app").to_view_ddl()
        assert 'FROM "app"."testapp_tag";' in ddl

    def test_fk_columns_use_db_column_names(self):
        # Article has FK author -> author_id; only Article in scope so it is a plain column.
        spec = GraphSpec(Article)
        ddl = Lens(spec, schema_name="lens", role_name="r").to_view_ddl()
        assert '    "author_id",' in ddl
        assert '    "category_id",' in ddl

    def test_ignore_drops_column(self):
        spec = GraphSpec({Author: {"email": Ignore()}})
        ddl = Lens(spec, schema_name="lens", role_name="r").to_view_ddl()
        assert '"email"' not in ddl
        assert '"name"' in ddl  # other columns still present


class TestMaskingInView:
    def test_hash_mask_uses_salt(self):
        spec = GraphSpec({Author: {"email": Mask("hash")}})
        ddl = Lens(spec, schema_name="lens", role_name="r", hash_salt="pepper").to_view_ddl()
        assert 'md5(("email")::text || \'pepper\') AS "email"' in ddl

    def test_hash_mask_escapes_quote_in_salt(self):
        spec = GraphSpec({Author: {"email": Mask("hash")}})
        ddl = Lens(spec, schema_name="lens", role_name="r", hash_salt="o'brien").to_view_ddl()
        assert "|| 'o''brien') AS \"email\"" in ddl

    def test_redact_mask(self):
        spec = GraphSpec({Author: {"name": Mask("redact")}})
        ddl = Lens(spec, schema_name="lens", role_name="r").to_view_ddl()
        assert '(left(("name")::text, 1) || \'***\') AS "name"' in ddl

    def test_null_mask(self):
        spec = GraphSpec({Author: {"email": Mask("null")}})
        ddl = Lens(spec, schema_name="lens", role_name="r").to_view_ddl()
        assert 'NULL AS "email"' in ddl


class TestRowFilters:
    def test_row_filter_becomes_where_clause(self):
        spec = GraphSpec(Article)
        ddl = Lens(
            spec,
            schema_name="lens",
            role_name="r",
            row_filters={Article: "published = true"},
        ).to_view_ddl()
        assert 'FROM "public"."testapp_article"\nWHERE published = true;' in ddl

    def test_no_filter_has_no_where(self):
        spec = GraphSpec(Tag)
        ddl = Lens(spec, schema_name="lens", role_name="r").to_view_ddl()
        assert "WHERE" not in ddl

    def test_whitespace_only_filter_is_ignored(self):
        spec = GraphSpec(Tag)
        ddl = Lens(spec, schema_name="lens", role_name="r", row_filters={Tag: "   "}).to_view_ddl()
        assert "WHERE" not in ddl


class TestRoleDDL:
    def _ddl(self):
        spec = GraphSpec(Tag)
        return Lens(spec, schema_name="staff_lens_masked", role_name="staff_masked").to_role_ddl()

    def test_role_created_idempotently(self):
        ddl = self._ddl()
        assert "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'staff_masked')" in ddl
        assert 'CREATE ROLE "staff_masked" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;' in ddl

    def test_grants_usage_and_select(self):
        ddl = self._ddl()
        assert 'GRANT USAGE ON SCHEMA "staff_lens_masked" TO "staff_masked";' in ddl
        assert 'GRANT SELECT ON ALL TABLES IN SCHEMA "staff_lens_masked" TO "staff_masked";' in ddl

    def test_role_is_read_only(self):
        ddl = self._ddl()
        assert 'ALTER ROLE "staff_masked" SET default_transaction_read_only = on;' in ddl

    def test_default_privileges_for_future_views(self):
        ddl = self._ddl()
        assert (
            'ALTER DEFAULT PRIVILEGES IN SCHEMA "staff_lens_masked" '
            'GRANT SELECT ON TABLES TO "staff_masked";' in ddl
        )


class TestSchemaContext:
    def test_top_level_shape(self):
        spec = GraphSpec(Tag)
        ctx = Lens(spec, schema_name="lens", role_name="r").to_schema_context()
        assert ctx["schema"] == "lens"
        assert ctx["role"] == "r"
        assert [v["view"] for v in ctx["views"]] == ["testapp_tag"]

    def test_columns_report_type_and_mask(self):
        spec = GraphSpec({Author: {"email": Mask("hash")}})
        ctx = Lens(spec, schema_name="lens", role_name="r").to_schema_context()
        cols = {c["name"]: c for c in ctx["views"][0]["columns"]}
        assert cols["email"]["masked"] == "hash"
        assert cols["name"]["masked"] is None
        assert cols["name"]["type"] == "CharField"

    def test_dropped_column_absent(self):
        spec = GraphSpec({Author: {"email": Ignore()}})
        ctx = Lens(spec, schema_name="lens", role_name="r").to_schema_context()
        names = [c["name"] for c in ctx["views"][0]["columns"]]
        assert "email" not in names

    def test_relationships_between_in_scope_models(self):
        # Article + Author in scope -> Article has FK relationship to Author.
        spec = GraphSpec(Article, Author)
        ctx = Lens(spec, schema_name="lens", role_name="r").to_schema_context()
        article = next(v for v in ctx["views"] if v["model"] == "Article")
        rels = {(r["via"], r["to"]) for r in article["relationships"]}
        assert ("author_id", "testapp_author") in rels

    def test_masked_fk_not_advertised_as_relationship(self):
        spec = GraphSpec({Article: {"author": Mask("hash")}, Author: {}, Category: {}})
        ctx = Lens(spec, schema_name="lens", role_name="r").to_schema_context()
        article = next(v for v in ctx["views"] if v["model"] == "Article")
        vias = {r["via"] for r in article["relationships"]}
        assert "author_id" not in vias  # masked FK is not a usable join key
        assert "category_id" in vias  # unmasked FK still advertised
        cols = {c["name"]: c for c in article["columns"]}
        assert cols["author_id"]["masked"] == "hash"  # column still present, flagged

    def test_dropped_fk_not_advertised_as_relationship(self):
        spec = GraphSpec({Article: {"author": Ignore()}, Author: {}, Category: {}})
        ctx = Lens(spec, schema_name="lens", role_name="r").to_schema_context()
        article = next(v for v in ctx["views"] if v["model"] == "Article")
        vias = {r["via"] for r in article["relationships"]}
        assert "author_id" not in vias
        assert "category_id" in vias
        names = {c["name"] for c in article["columns"]}
        assert "author_id" not in names
