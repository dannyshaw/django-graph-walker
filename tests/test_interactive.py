"""Tests for interactive HTML visualization."""

import json

from django.core.management import call_command

from django_graph_walker import Follow, GraphSpec, GraphWalker
from django_graph_walker.actions.interactive import InteractiveRenderer
from django_graph_walker.actions.visualize import Visualize
from tests.testapp.models import (
    Article,
    ArticleStats,
    Author,
    Category,
    Comment,
    Tag,
)


class TestSchemaToDictExport:
    def test_nodes_have_required_keys(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        data = Visualize().schema_to_dict(spec)
        for node in data["nodes"]:
            assert "id" in node
            assert "label" in node
            assert "color" in node

    def test_edges_have_required_keys(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        data = Visualize().schema_to_dict(spec)
        for edge in data["edges"]:
            assert "source" in edge
            assert "target" in edge
            assert "label" in edge
            assert "field_class" in edge

    def test_only_forward_edges(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        data = Visualize().schema_to_dict(spec)
        # Should only have forward FK, O2O, M2M, GenericRelation edges
        for edge in data["edges"]:
            assert "REVERSE" not in edge["field_class"]

    def test_no_duplicate_edges(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        data = Visualize().schema_to_dict(spec)
        edge_keys = [(e["source"], e["target"], e["label"]) for e in data["edges"]]
        assert len(edge_keys) == len(set(edge_keys))

    def test_edge_count_matches_dot(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        data = Visualize().schema_to_dict(spec)
        dot = Visualize().schema(spec)
        dot_edge_count = dot.count("->")
        assert len(data["edges"]) == dot_edge_count

    def test_node_fields_populated(self):
        spec = GraphSpec(Author, Article, Category)
        data = Visualize().schema_to_dict(spec)
        # Find the Author node — it has 'name' and 'email' value fields
        author_node = next(n for n in data["nodes"] if n["id"] == "Author")
        assert "field_count" in author_node
        assert "fields" in author_node
        assert author_node["field_count"] > 0

    def test_single_model_no_edges(self):
        spec = GraphSpec(Author)
        data = Visualize().schema_to_dict(spec)
        assert len(data["nodes"]) == 1
        assert len(data["edges"]) == 0

    def test_generic_relation_edge(self):
        spec = GraphSpec(Article, Comment, Author, Category)
        data = Visualize().schema_to_dict(spec)
        generic_edges = [e for e in data["edges"] if "GENERIC" in e["field_class"]]
        assert len(generic_edges) > 0

    def test_m2m_edge(self):
        spec = GraphSpec(Article, Tag, Author, Category)
        data = Visualize().schema_to_dict(spec)
        m2m_edges = [e for e in data["edges"] if "M2M" in e["field_class"]]
        assert len(m2m_edges) > 0

    def test_o2o_edge(self):
        spec = GraphSpec(Article, ArticleStats, Author, Category)
        data = Visualize().schema_to_dict(spec)
        o2o_edges = [e for e in data["edges"] if "O2O" in e["field_class"]]
        assert len(o2o_edges) > 0


class TestInstancesToDictExport:
    def test_nodes_have_required_keys(self, article, author, child_category):
        spec = GraphSpec(
            {Article: {"author": Follow(), "category": Follow()}, Author: {}, Category: {}}
        )
        result = GraphWalker(spec).walk(article)
        data = Visualize().instances_to_dict(result)
        for node in data["nodes"]:
            assert "id" in node
            assert "label" in node
            assert "model" in node
            assert "pk" in node
            assert "group" in node

    def test_edges_connect_visited_instances(self, article, author, child_category):
        spec = GraphSpec(
            {Article: {"author": Follow(), "category": Follow()}, Author: {}, Category: {}}
        )
        result = GraphWalker(spec).walk(article)
        data = Visualize().instances_to_dict(result)
        node_ids = {n["id"] for n in data["nodes"]}
        for edge in data["edges"]:
            assert edge["source"] in node_ids
            assert edge["target"] in node_ids

    def test_m2m_edges_present(self, article, tag_python, tag_django, author, child_category):
        spec = GraphSpec(
            {
                Article: {"author": Follow(), "category": Follow(), "tags": Follow()},
                Author: {},
                Category: {},
                Tag: {},
            }
        )
        result = GraphWalker(spec).walk(article)
        data = Visualize().instances_to_dict(result)
        m2m_edges = [e for e in data["edges"] if e["field_class"] == "M2M_IN_SCOPE"]
        assert len(m2m_edges) > 0


class TestCytoscapeHtml:
    def test_valid_html_structure(self):
        graph_data = {"nodes": [{"id": "A", "label": "A", "color": "#fff"}], "edges": []}
        html = InteractiveRenderer().to_cytoscape_html(graph_data)
        assert html.startswith("<!DOCTYPE html>")
        assert "<html" in html
        assert "</html>" in html

    def test_contains_cytoscape_cdn(self):
        graph_data = {"nodes": [], "edges": []}
        html = InteractiveRenderer().to_cytoscape_html(graph_data)
        assert "unpkg.com/cytoscape@3" in html

    def test_contains_dagre_cdn(self):
        graph_data = {"nodes": [], "edges": []}
        html = InteractiveRenderer().to_cytoscape_html(graph_data)
        assert "unpkg.com/dagre@" in html
        assert "unpkg.com/cytoscape-dagre@" in html

    def test_graph_data_embedded(self):
        graph_data = {
            "nodes": [{"id": "Author", "label": "Author", "color": "#4A90D9"}],
            "edges": [],
        }
        html = InteractiveRenderer().to_cytoscape_html(graph_data)
        assert '"Author"' in html
        assert '"#4A90D9"' in html

    def test_title_set(self):
        graph_data = {"nodes": [], "edges": []}
        html = InteractiveRenderer().to_cytoscape_html(graph_data, title="My Schema")
        assert "<title>My Schema</title>" in html

    def test_json_is_valid(self):
        graph_data = {
            "nodes": [{"id": "A", "label": "A", "color": "#fff", "field_count": 3}],
            "edges": [{"source": "A", "target": "A", "label": "self", "field_class": "FK"}],
        }
        html = InteractiveRenderer().to_cytoscape_html(graph_data)
        # Extract the JSON blob from the template
        marker = "var graphData = "
        start = html.index(marker) + len(marker)
        end = html.index(";\n", start)
        parsed = json.loads(html[start:end])
        assert len(parsed["nodes"]) == 1
        assert len(parsed["edges"]) == 1


class Test3dHtml:
    def test_valid_html_structure(self):
        graph_data = {"nodes": [{"id": "A", "label": "A", "color": "#fff"}], "edges": []}
        html = InteractiveRenderer().to_3d_html(graph_data)
        assert html.startswith("<!DOCTYPE html>")
        assert "<html" in html
        assert "</html>" in html

    def test_contains_3d_force_graph_cdn(self):
        graph_data = {"nodes": [], "edges": []}
        html = InteractiveRenderer().to_3d_html(graph_data)
        assert "unpkg.com/3d-force-graph@1" in html

    def test_graph_data_embedded(self):
        graph_data = {
            "nodes": [{"id": "Book", "label": "Book", "color": "#50C878"}],
            "edges": [],
        }
        html = InteractiveRenderer().to_3d_html(graph_data)
        assert '"Book"' in html
        assert '"#50C878"' in html

    def test_title_set(self):
        graph_data = {"nodes": [], "edges": []}
        html = InteractiveRenderer().to_3d_html(graph_data, title="3D Schema")
        assert "<title>3D Schema</title>" in html

    def test_json_is_valid(self):
        graph_data = {
            "nodes": [{"id": "X", "label": "X", "color": "#000"}],
            "edges": [{"source": "X", "target": "X", "label": "ref", "field_class": "FK"}],
        }
        html = InteractiveRenderer().to_3d_html(graph_data)
        marker = "var graphData = "
        start = html.index(marker) + len(marker)
        end = html.index(";\n", start)
        parsed = json.loads(html[start:end])
        assert len(parsed["nodes"]) == 1
        assert len(parsed["edges"]) == 1


class TestGraphSchemaCommandHtml:
    def test_html_format_produces_html(self, capsys):
        call_command("graph_schema", "testapp", "--format=html")
        output = capsys.readouterr().out
        assert "<!DOCTYPE html>" in output
        assert "cytoscape" in output

    def test_3d_format_produces_html(self, capsys):
        call_command("graph_schema", "testapp", "--format=3d")
        output = capsys.readouterr().out
        assert "<!DOCTYPE html>" in output
        assert "3d-force-graph" in output

    def test_html_output_to_file(self, tmp_path):
        out_file = str(tmp_path / "schema.html")
        call_command("graph_schema", "testapp", "--format=html", "-o", out_file)
        with open(out_file) as f:
            content = f.read()
        assert "<!DOCTYPE html>" in content
        assert "cytoscape" in content

    def test_3d_output_to_file(self, tmp_path):
        out_file = str(tmp_path / "schema3d.html")
        call_command("graph_schema", "testapp", "--format=3d", "-o", out_file)
        with open(out_file) as f:
            content = f.read()
        assert "<!DOCTYPE html>" in content
        assert "3d-force-graph" in content

    def test_html_no_field_names_still_works(self, capsys):
        call_command("graph_schema", "testapp", "--format=html", "--no-field-names")
        output = capsys.readouterr().out
        assert "<!DOCTYPE html>" in output

    def test_html_with_exclude(self, capsys):
        call_command("graph_schema", "testapp", "--format=html", "--exclude=testapp.Comment")
        output = capsys.readouterr().out
        assert "<!DOCTYPE html>" in output
        assert "Comment" not in output
