"""Tests for the Mask override and the Lens action (view/role DDL + schema context)."""

import pytest

from django_graph_walker import GraphSpec, Ignore, Mask
from django_graph_walker.actions.lens import Lens
from tests.testapp.models import Article, Author, Tag


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
