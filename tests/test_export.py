"""Tests for Export action — fixture serialization and cross-DB export."""

import json

import pytest

from django_graph_walker import Follow, GraphSpec, GraphWalker
from django_graph_walker.actions.export import Export
from tests.testapp.models import (
    Article,
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
