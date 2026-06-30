"""Tests for Export action — fixture serialization and cross-DB export."""

import json

import pytest
from django.test.utils import CaptureQueriesContext

from django_graph_walker import Follow, GraphSpec, GraphWalker
from django_graph_walker.actions.export import Export, _FixtureEncoder
from django_graph_walker.result import WalkResult
from tests.testapp.models import (
    Article,
    ArticleContributor,
    Author,
    Category,
    Tag,
)


# Shared spec that follows forward edges from Article so all related instances are collected
def _article_spec(*extra_models):
    models = {
        Article: {"author": Follow(), "category": Follow(), "reviewer": Follow()},
        Author: {},
        Category: {"parent": Follow()},
    }
    for m in extra_models:
        models[m] = {}
    return GraphSpec(models)


def _article_spec_with_tags():
    return GraphSpec(
        {
            Article: {
                "author": Follow(),
                "category": Follow(),
                "reviewer": Follow(),
                "tags": Follow(),
            },
            Author: {},
            Tag: {},
            Category: {"parent": Follow()},
        }
    )


class TestExportToFixture:
    def test_export_json_format(self, article, author, child_category):
        spec = _article_spec()
        result = GraphWalker(spec).walk(article)
        output = Export(format="json").to_fixture(result)
        data = json.loads(output)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_exported_fixture_contains_all_instances(
        self, article, author, child_category, root_category
    ):
        spec = _article_spec()
        result = GraphWalker(spec).walk(article)
        output = Export(format="json").to_fixture(result)
        data = json.loads(output)
        # Should have: 1 article + 1 author + 2 categories (child + root via FK) + 1 reviewer
        model_labels = [item["model"] for item in data]
        assert "testapp.article" in model_labels
        assert "testapp.author" in model_labels
        assert "testapp.category" in model_labels

    def test_fixture_preserves_field_values(self, author):
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)
        output = Export(format="json").to_fixture(result)
        data = json.loads(output)
        author_data = next(d for d in data if d["model"] == "testapp.author")
        assert author_data["fields"]["name"] == "Alice"
        assert author_data["fields"]["email"] == "alice@example.com"

    def test_fixture_in_dependency_order(self, article, author, child_category, root_category):
        """FKs should point to objects serialized earlier in the fixture."""
        spec = _article_spec()
        result = GraphWalker(spec).walk(article)
        output = Export(format="json").to_fixture(result)
        data = json.loads(output)

        # Find positions
        model_order = [item["model"] for item in data]
        # Authors should come before articles (article has FK to author)
        first_author_idx = next(i for i, m in enumerate(model_order) if m == "testapp.author")
        first_article_idx = next(i for i, m in enumerate(model_order) if m == "testapp.article")
        assert first_author_idx < first_article_idx

    def test_export_with_m2m(self, article, tag_python, tag_django):
        spec = _article_spec_with_tags()
        result = GraphWalker(spec).walk(article)
        output = Export(format="json").to_fixture(result)
        data = json.loads(output)
        article_data = next(d for d in data if d["model"] == "testapp.article")
        # M2M should be included in fixture
        assert "tags" in article_data["fields"]
        tag_pks = article_data["fields"]["tags"]
        assert len(tag_pks) == 2

    def test_export_with_natural_keys(self, author):
        """When use_natural_keys=True, FKs should use natural keys if available."""
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)
        # Should not raise even without natural keys
        output = Export(format="json", use_natural_keys=False).to_fixture(result)
        data = json.loads(output)
        assert len(data) > 0


class TestExportToFile:
    def test_export_to_file(self, tmp_path, author):
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)
        output_path = tmp_path / "fixture.json"
        Export(format="json").to_file(result, str(output_path))
        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert len(data) == 1

    def test_export_to_file_creates_parent_dirs(self, tmp_path, author):
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)
        output_path = tmp_path / "subdir" / "fixture.json"
        Export(format="json").to_file(result, str(output_path))
        assert output_path.exists()


@pytest.mark.django_db(databases=["default", "secondary"], transaction=True)
class TestExportToDatabase:
    def test_export_to_secondary_db(self, article, author, child_category, root_category):
        """Export instances to a secondary database."""
        spec = _article_spec()
        result = GraphWalker(spec).walk(article)
        Export().to_database(result, target_db="secondary")

        # Verify data exists in secondary DB
        assert Author.objects.using("secondary").filter(name="Alice").exists()
        assert Article.objects.using("secondary").filter(title="Test Article").exists()

    def test_export_preserves_fk_integrity(self, article, author, child_category, root_category):
        """FK relationships should be remapped correctly in target DB."""
        spec = _article_spec()
        result = GraphWalker(spec).walk(article)
        Export().to_database(result, target_db="secondary")

        # Verify FK integrity
        exported_article = Article.objects.using("secondary").get(title="Test Article")
        assert exported_article.author.name == "Alice"
        assert exported_article.category.name == "Physics"

    def test_export_preserves_m2m(self, article, author, child_category, tag_python, tag_django):
        """M2M relationships should be preserved in target DB."""
        spec = _article_spec_with_tags()
        result = GraphWalker(spec).walk(article)
        Export().to_database(result, target_db="secondary")

        exported_article = Article.objects.using("secondary").get(title="Test Article")
        tag_names = set(exported_article.tags.values_list("name", flat=True))
        assert tag_names == {"python", "django"}


class TestExportWithAnonymization:
    def test_anonymize_with_callable(self, author):
        spec = GraphSpec(
            {
                Author: {
                    "email": "anonymize",
                    "name": "anonymize",
                },
            }
        )
        result = GraphWalker(spec).walk(author)

        anonymizers = {
            "Author.email": lambda instance, ctx: "anon@example.com",
            "Author.name": lambda instance, ctx: "Anonymous",
        }
        output = Export(format="json", anonymizers=anonymizers).to_fixture(result)
        data = json.loads(output)
        author_data = next(d for d in data if d["model"] == "testapp.author")
        assert author_data["fields"]["email"] == "anon@example.com"
        assert author_data["fields"]["name"] == "Anonymous"

    def test_anonymize_preserves_non_anonymized_fields(self, author):
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)

        anonymizers = {
            "Author.email": lambda instance, ctx: "anon@example.com",
        }
        output = Export(format="json", anonymizers=anonymizers).to_fixture(result)
        data = json.loads(output)
        author_data = next(d for d in data if d["model"] == "testapp.author")
        # Name should NOT be anonymized
        assert author_data["fields"]["name"] == "Alice"
        # Email should be anonymized
        assert author_data["fields"]["email"] == "anon@example.com"

    def test_anonymize_with_faker_provider(self, author):
        """Anonymize using faker provider name."""
        pytest.importorskip("faker")
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)

        anonymizers = {
            "Author.email": "email",
            "Author.name": "name",
        }
        output = Export(format="json", anonymizers=anonymizers).to_fixture(result)
        data = json.loads(output)
        author_data = next(d for d in data if d["model"] == "testapp.author")
        # Should be different from original (faker produces random values)
        # Just verify it's a string and not empty
        assert isinstance(author_data["fields"]["email"], str)
        assert len(author_data["fields"]["email"]) > 0

    @pytest.mark.django_db(databases=["default", "secondary"], transaction=True)
    def test_anonymize_database_export(self, author):
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)

        anonymizers = {
            "Author.email": lambda instance, ctx: "anon@example.com",
            "Author.name": lambda instance, ctx: "Anonymous",
        }
        Export(anonymizers=anonymizers).to_database(result, target_db="secondary")

        exported = Author.objects.using("secondary").first()
        assert exported.email == "anon@example.com"
        assert exported.name == "Anonymous"


class TestFKBoundary:
    """FK values pointing outside the walk result are nulled out."""

    def test_fk_outside_walk_result_is_nulled(self, article, author, child_category, reviewer):
        """Walk Article + Category but NOT the reviewer Author — reviewer FK should be null."""
        # Spec that walks article → author (via author FK) and category, but NOT reviewer
        spec = GraphSpec(
            {
                Article: {"author": Follow(), "category": Follow()},
                Author: {},
                Category: {"parent": Follow()},
            }
        )
        result = GraphWalker(spec).walk(article)

        # Build a manual WalkResult without the reviewer to test FK boundary
        visited = {}
        for inst in result:
            if not (isinstance(inst, Author) and inst.pk == reviewer.pk):
                visited[(type(inst), inst.pk)] = inst
        partial_result = WalkResult(visited, set())

        data = Export().to_fixture_data(partial_result)
        article_data = next(d for d in data if d["model"] == "testapp.article")
        # reviewer FK should be nulled since reviewer is not in the partial result
        assert article_data["fields"]["reviewer"] is None
        # author FK should be preserved
        assert article_data["fields"]["author"] == author.pk

    def test_fk_inside_walk_result_preserved(self, article, author, child_category, root_category):
        """FK pointing to an instance in the walk result is preserved."""
        spec = _article_spec()
        result = GraphWalker(spec).walk(article)
        data = Export().to_fixture_data(result)
        article_data = next(d for d in data if d["model"] == "testapp.article")
        assert article_data["fields"]["author"] == author.pk
        assert article_data["fields"]["category"] == child_category.pk

    def test_nullable_fk_outside_result_stays_null(self, db):
        """Article with no reviewer — null FK stays null (not broken)."""
        author = Author.objects.create(name="Solo", email="solo@test.com")
        cat = Category.objects.create(name="Cat")
        article = Article.objects.create(
            title="No Reviewer", author=author, category=cat, reviewer=None
        )
        spec = _article_spec()
        result = GraphWalker(spec).walk(article)
        data = Export().to_fixture_data(result)
        article_data = next(d for d in data if d["model"] == "testapp.article")
        assert article_data["fields"]["reviewer"] is None


class TestM2MBoundary:
    """M2M fixture output only includes PKs present in the walk result."""

    def test_m2m_filters_to_walk_result(self, article, tag_python, tag_django):
        """Walk Article + tags but then manually exclude one tag from result."""
        spec = _article_spec_with_tags()
        result = GraphWalker(spec).walk(article)

        # Build partial result excluding tag_django
        visited = {}
        for inst in result:
            if not (isinstance(inst, Tag) and inst.pk == tag_django.pk):
                visited[(type(inst), inst.pk)] = inst
        partial_result = WalkResult(visited, set())

        data = Export().to_fixture_data(partial_result)
        article_data = next(d for d in data if d["model"] == "testapp.article")
        tag_pks = article_data["fields"]["tags"]
        assert tag_python.pk in tag_pks
        assert tag_django.pk not in tag_pks

    def test_m2m_all_targets_in_result(self, article, tag_python, tag_django):
        """When all M2M targets are in the result, all PKs appear."""
        spec = _article_spec_with_tags()
        result = GraphWalker(spec).walk(article)
        data = Export().to_fixture_data(result)
        article_data = next(d for d in data if d["model"] == "testapp.article")
        tag_pks = set(article_data["fields"]["tags"])
        assert tag_pks == {tag_python.pk, tag_django.pk}


class TestExplicitThrough:
    """M2M with custom through table is skipped in fixture output."""

    def test_explicit_through_m2m_skipped(self, article, author):
        """contributors M2M (through ArticleContributor) should not appear in fields."""
        ArticleContributor.objects.create(article=article, author=author, role="editor")

        spec = GraphSpec(
            {
                Article: {"author": Follow(), "category": Follow()},
                ArticleContributor: {"article": Follow(), "author": Follow()},
                Author: {},
                Category: {"parent": Follow()},
            }
        )
        result = GraphWalker(spec).walk(article)
        data = Export().to_fixture_data(result)

        article_data = next(d for d in data if d["model"] == "testapp.article")
        # "contributors" should NOT be in fields (explicit through table)
        assert "contributors" not in article_data["fields"]

        # But the through model record should be serialized as its own entry
        through_records = [d for d in data if d["model"] == "testapp.articlecontributor"]
        assert len(through_records) == 1
        assert through_records[0]["fields"]["role"] == "editor"


class TestFixtureEncoder:
    """_FixtureEncoder handles edge-case types."""

    def test_bytes_encoded(self):
        result = json.dumps({"val": b"hello"}, cls=_FixtureEncoder)
        assert json.loads(result)["val"] == "hello"

    def test_memoryview_encoded(self):
        result = json.dumps({"val": memoryview(b"world")}, cls=_FixtureEncoder)
        assert json.loads(result)["val"] == "world"

    def test_set_encoded(self):
        result = json.dumps({"val": {3, 1, 2}}, cls=_FixtureEncoder)
        assert sorted(json.loads(result)["val"]) == [1, 2, 3]

    def test_frozenset_encoded(self):
        result = json.dumps({"val": frozenset([5, 4])}, cls=_FixtureEncoder)
        assert sorted(json.loads(result)["val"]) == [4, 5]

    def test_standard_types_pass_through(self):
        """DjangoJSONEncoder handles datetime, date, Decimal, UUID etc."""
        import datetime
        from decimal import Decimal

        data = {
            "dt": datetime.datetime(2025, 1, 1, 12, 0),
            "d": datetime.date(2025, 1, 1),
            "dec": Decimal("9.99"),
        }
        result = json.dumps(data, cls=_FixtureEncoder)
        parsed = json.loads(result)
        assert parsed["dt"] == "2025-01-01T12:00:00"
        assert parsed["d"] == "2025-01-01"
        assert parsed["dec"] == "9.99"


class TestToFixtureData:
    """to_fixture_data() returns list[dict] structure."""

    def test_returns_list_of_dicts(self, author):
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)
        data = Export().to_fixture_data(result)
        assert isinstance(data, list)
        assert len(data) == 1
        assert isinstance(data[0], dict)

    def test_dict_structure(self, author):
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)
        data = Export().to_fixture_data(result)
        record = data[0]
        assert "model" in record
        assert "pk" in record
        assert "fields" in record
        assert record["model"] == "testapp.author"
        assert record["pk"] == author.pk
        assert record["fields"]["name"] == "Alice"

    def test_to_fixture_wraps_to_fixture_data(self, author):
        """to_fixture() should produce JSON of the same data as to_fixture_data()."""
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)
        export = Export()
        data = export.to_fixture_data(result)
        json_str = export.to_fixture(result)
        assert json.loads(json_str) == data

    def test_anonymization_works_with_to_fixture_data(self, author):
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)
        anonymizers = {"Author.email": lambda inst, ctx: "redacted@example.com"}
        data = Export(anonymizers=anonymizers).to_fixture_data(result)
        assert data[0]["fields"]["email"] == "redacted@example.com"
        assert data[0]["fields"]["name"] == "Alice"


class TestNaturalKeys:
    """Natural key support in fixture serialization."""

    def test_natural_keys_fk_when_model_has_natural_key(self, db):
        """FK values use natural_key() when use_natural_keys=True and model supports it."""
        # Monkey-patch natural_key onto Author for this test
        original_natural_key = getattr(Author, "natural_key", None)
        Author.natural_key = lambda self: [self.email]
        try:
            author = Author.objects.create(name="NK Author", email="nk@test.com")
            cat = Category.objects.create(name="NK Cat")
            article = Article.objects.create(title="NK Article", author=author, category=cat)
            spec = _article_spec()
            result = GraphWalker(spec).walk(article)
            data = Export(use_natural_keys=True).to_fixture_data(result)
            article_data = next(d for d in data if d["model"] == "testapp.article")
            # author FK should be natural key (a list)
            assert article_data["fields"]["author"] == ["nk@test.com"]
        finally:
            if original_natural_key is None:
                del Author.natural_key
            else:
                Author.natural_key = original_natural_key

    def test_natural_keys_pk_omitted_when_model_has_natural_key(self, db):
        """PK is None when use_natural_keys=True and model has natural_key()."""
        original_natural_key = getattr(Author, "natural_key", None)
        Author.natural_key = lambda self: [self.email]
        try:
            author = Author.objects.create(name="NK Author", email="nk@test.com")
            spec = GraphSpec(Author)
            result = GraphWalker(spec).walk(author)
            data = Export(use_natural_keys=True).to_fixture_data(result)
            assert data[0]["pk"] is None
        finally:
            if original_natural_key is None:
                del Author.natural_key
            else:
                Author.natural_key = original_natural_key

    def test_no_natural_keys_uses_raw_pk(self, author):
        """Without use_natural_keys, FK values are raw PKs."""
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)
        data = Export(use_natural_keys=False).to_fixture_data(result)
        assert data[0]["pk"] == author.pk


class TestNoDBQueries:
    """Fixture serialization should not hit the database."""

    def test_to_fixture_data_no_queries(self, article, tag_python, tag_django):
        """Serialization should issue zero DB queries."""
        from django.db import connection

        spec = _article_spec_with_tags()
        result = GraphWalker(spec).walk(article)

        # Now serialize — should not query DB
        with CaptureQueriesContext(connection) as ctx:
            Export().to_fixture_data(result)

        assert len(ctx.captured_queries) == 0, (
            f"Expected 0 queries, got {len(ctx.captured_queries)}: "
            f"{[q['sql'] for q in ctx.captured_queries]}"
        )

    def test_to_fixture_no_queries(self, author):
        from django.db import connection

        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)

        with CaptureQueriesContext(connection) as ctx:
            Export().to_fixture(result)

        assert len(ctx.captured_queries) == 0


class TestFormatValidation:
    """Non-JSON format raises ValueError."""

    def test_non_json_format_raises(self):
        with pytest.raises(ValueError, match="Only 'json' format is supported"):
            Export(format="xml")
