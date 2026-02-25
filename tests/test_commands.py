"""Tests for management commands: graph_schema, graph_walk, graph_deps."""

import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tests.testapp.models import (
    Article,
    Author,
    Category,
    Tag,
)


class TestGraphSchema:
    def test_schema_single_app(self, capsys):
        call_command("graph_schema", "testapp")
        output = capsys.readouterr().out
        assert "digraph ModelGraph" in output
        assert "Author" in output
        assert "Article" in output

    def test_schema_multiple_apps(self, capsys):
        call_command("graph_schema", "testapp", "contenttypes")
        output = capsys.readouterr().out
        assert "Author" in output
        assert "ContentType" in output

    def test_schema_all_apps(self, capsys):
        call_command("graph_schema", "--all")
        output = capsys.readouterr().out
        assert "digraph ModelGraph" in output
        assert "Author" in output

    def test_schema_json_format(self, capsys):
        call_command("graph_schema", "testapp", "--format=json")
        output = capsys.readouterr().out
        data = json.loads(output)
        assert "models" in data
        assert "edges" in data
        assert any("Author" in m for m in data["models"])
        # Check edges exist
        assert len(data["edges"]) > 0

    def test_schema_no_field_names(self, capsys):
        call_command("graph_schema", "testapp", "--no-field-names")
        output = capsys.readouterr().out
        assert "digraph ModelGraph" in output
        # Field name labels should not appear
        assert 'label="author"' not in output

    def test_schema_exclude_model(self, capsys):
        call_command("graph_schema", "testapp", "--exclude=testapp.Comment")
        output = capsys.readouterr().out
        assert "Comment" not in output
        assert "Author" in output

    def test_schema_output_to_file(self, capsys, tmp_path):
        out_file = str(tmp_path / "schema.dot")
        call_command("graph_schema", "testapp", "-o", out_file)
        with open(out_file) as f:
            content = f.read()
        assert "digraph ModelGraph" in content

    def test_schema_no_args_raises(self):
        with pytest.raises(CommandError, match="Provide one or more app labels"):
            call_command("graph_schema")

    def test_schema_invalid_app_raises(self):
        with pytest.raises(CommandError, match="No installed app"):
            call_command("graph_schema", "nonexistent")

    def test_schema_invalid_exclude_raises(self):
        with pytest.raises(CommandError, match="Unknown model"):
            call_command("graph_schema", "testapp", "--exclude=bad.Model")


class TestGraphWalk:
    @pytest.fixture
    def sample_data(self, db):
        author = Author.objects.create(name="Alice", email="alice@example.com")
        cat = Category.objects.create(name="Science")
        tag = Tag.objects.create(name="python")
        article = Article.objects.create(title="Test", body="Body", author=author, category=cat)
        article.tags.add(tag)
        return {"author": author, "article": article, "category": cat, "tag": tag}

    def test_walk_basic(self, capsys, sample_data):
        article = sample_data["article"]
        call_command("graph_walk", "testapp.Article", str(article.pk))
        output = capsys.readouterr().out
        assert "Walked" in output
        assert "instances" in output

    def test_walk_multiple_pks(self, capsys, sample_data):
        author = sample_data["author"]
        # Create another author
        author2 = Author.objects.create(name="Bob", email="bob@example.com")
        cat = Category.objects.create(name="Tech")
        Article.objects.create(title="Art2", body="B", author=author2, category=cat)
        call_command("graph_walk", "testapp.Author", f"{author.pk},{author2.pk}")
        output = capsys.readouterr().out
        assert "Walked" in output

    def test_walk_dry_run(self, capsys, sample_data):
        article = sample_data["article"]
        call_command("graph_walk", "testapp.Article", str(article.pk), "--dry-run")
        output = capsys.readouterr().out
        assert "Walked" in output

    def test_walk_export_to_file(self, capsys, sample_data, tmp_path):
        article = sample_data["article"]
        out_file = str(tmp_path / "fixture.json")
        call_command("graph_walk", "testapp.Article", str(article.pk), "-o", out_file)
        with open(out_file) as f:
            data = json.loads(f.read())
        assert len(data) > 0

    def test_walk_with_apps_scope(self, capsys, sample_data):
        article = sample_data["article"]
        call_command("graph_walk", "testapp.Article", str(article.pk), "--apps=testapp")
        output = capsys.readouterr().out
        assert "Walked" in output

    def test_walk_all_apps(self, capsys, sample_data):
        article = sample_data["article"]
        call_command("graph_walk", "testapp.Article", str(article.pk), "--all")
        output = capsys.readouterr().out
        assert "Walked" in output

    def test_walk_invalid_model_raises(self):
        with pytest.raises(CommandError, match="Unknown model"):
            call_command("graph_walk", "bad.Model", "1")

    def test_walk_no_instances_raises(self, db):
        with pytest.raises(CommandError, match="No Author instances found"):
            call_command("graph_walk", "testapp.Author", "999")


class TestGraphDeps:
    def test_deps_for_model(self, capsys):
        call_command("graph_deps", "testapp.Article")
        output = capsys.readouterr().out
        assert "Article" in output
        assert "Depends on" in output or "depends_on" in output

    def test_deps_for_app(self, capsys):
        call_command("graph_deps", "testapp")
        output = capsys.readouterr().out
        assert "Author" in output
        assert "Article" in output

    def test_deps_json_format(self, capsys):
        call_command("graph_deps", "testapp.Article", "--format=json")
        output = capsys.readouterr().out
        data = json.loads(output)
        assert "model" in data
        assert "depends_on" in data
        assert "depended_on_by" in data

    def test_deps_tree(self, capsys):
        call_command("graph_deps", "testapp", "--tree")
        output = capsys.readouterr().out
        assert "Dependency tree" in output

    def test_deps_tree_json(self, capsys):
        call_command("graph_deps", "testapp", "--tree", "--format=json")
        output = capsys.readouterr().out
        data = json.loads(output)
        assert isinstance(data, dict)

    def test_deps_orphans(self, capsys):
        call_command("graph_deps", "testapp", "--orphans")
        output = capsys.readouterr().out
        # Tag has M2M with Article, so it's not an orphan when testapp is in scope
        # The output should at least have meaningful content
        assert "orphan" in output.lower() or "no relationships" in output.lower()

    def test_deps_invalid_target_raises(self):
        with pytest.raises(CommandError, match="not a valid"):
            call_command("graph_deps", "nonexistent.thing")

    def test_deps_on_delete_shown(self, capsys):
        call_command("graph_deps", "testapp.Article")
        output = capsys.readouterr().out
        assert "CASCADE" in output or "SET_NULL" in output
