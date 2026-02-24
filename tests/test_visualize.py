"""Tests for Graphviz visualization action."""

import pytest

from django_graph_walker import Follow, GraphSpec, GraphWalker
from django_graph_walker.actions.visualize import Visualize
from tests.testapp.models import (
    Article,
    ArticleStats,
    Author,
    Category,
    Comment,
    Tag,
)


class TestSchemaVisualization:
    def test_schema_returns_dot_string(self):
        spec = GraphSpec(Author, Article, Category)
        dot = Visualize().schema(spec)
        assert isinstance(dot, str)
        assert "digraph" in dot

    def test_schema_contains_model_nodes(self):
        spec = GraphSpec(Author, Article, Category)
        dot = Visualize().schema(spec)
        assert "Author" in dot
        assert "Article" in dot
        assert "Category" in dot

    def test_schema_contains_edges(self):
        spec = GraphSpec(Author, Article, Category)
        dot = Visualize().schema(spec)
        # Article -> Author (FK)
        assert "Article" in dot and "Author" in dot
        # Should have edge lines
        assert "->" in dot

    def test_schema_excludes_out_of_scope_models(self):
        spec = GraphSpec(Author)
        dot = Visualize().schema(spec)
        assert "Author" in dot
        assert "Article" not in dot

    def test_schema_self_referential(self):
        spec = GraphSpec(Category)
        dot = Visualize().schema(spec)
        # Category -> Category (parent)
        assert "Category" in dot

    def test_schema_m2m_edge(self):
        spec = GraphSpec(Article, Tag, Author, Category)
        dot = Visualize().schema(spec)
        assert "Tag" in dot

    def test_schema_one_to_one_edge(self):
        spec = GraphSpec(Article, ArticleStats, Author, Category)
        dot = Visualize().schema(spec)
        assert "ArticleStats" in dot

    def test_schema_generic_relation_edge(self):
        spec = GraphSpec(Article, Comment, Author, Category)
        dot = Visualize().schema(spec)
        assert "Comment" in dot

    def test_schema_with_field_labels(self):
        """Edge labels should include the field name."""
        spec = GraphSpec(Article, Author, Category)
        dot = Visualize(show_field_names=True).schema(spec)
        # Should see field names like 'author', 'category' on edges
        assert "author" in dot

    def test_schema_without_field_labels(self):
        spec = GraphSpec(Article, Author, Category)
        dot = Visualize(show_field_names=False).schema(spec)
        # Should still have edges but field names may not be labeled
        assert "->" in dot


class TestInstanceVisualization:
    def test_instances_returns_dot_string(self, article, author, child_category):
        spec = GraphSpec(
            {
                Article: {"author": Follow(), "category": Follow()},
                Author: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(article)
        dot = Visualize().instances(result)
        assert isinstance(dot, str)
        assert "digraph" in dot

    def test_instances_contains_instance_nodes(self, article, author, child_category):
        spec = GraphSpec(
            {
                Article: {"author": Follow(), "category": Follow()},
                Author: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(article)
        dot = Visualize().instances(result)
        # Should contain representations of actual instances
        assert "Test Article" in dot or "Article" in dot
        assert "Alice" in dot or "Author" in dot

    def test_instances_contains_edges(self, article, author, child_category):
        spec = GraphSpec(
            {
                Article: {"author": Follow(), "category": Follow()},
                Author: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(article)
        dot = Visualize().instances(result)
        assert "->" in dot


class TestVisualizeToDot:
    """Test the to_dot helper that returns a graphviz.Digraph if available."""

    def test_schema_to_graphviz_object(self):
        graphviz = pytest.importorskip("graphviz")
        spec = GraphSpec(Author, Article, Category)
        source = Visualize().schema_to_graphviz(spec)
        assert isinstance(source, graphviz.Source)

    def test_instances_to_graphviz_object(self, article, author, child_category):
        graphviz = pytest.importorskip("graphviz")
        spec = GraphSpec(
            {
                Article: {"author": Follow(), "category": Follow()},
                Author: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(article)
        source = Visualize().instances_to_graphviz(result)
        assert isinstance(source, graphviz.Source)
