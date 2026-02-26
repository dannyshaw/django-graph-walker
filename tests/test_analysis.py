"""Tests for FanoutAnalyzer static fan-out risk detection."""

import json

import pytest
from django.core.management import call_command

from django_graph_walker.analysis import (
    FanoutAnalyzer,
    FanoutReport,
)
from django_graph_walker.discovery import FieldClass
from django_graph_walker.spec import Follow, GraphSpec, Ignore
from tests.testapp.models import (
    Article,
    ArticleStats,
    Author,
    Category,
    Comment,
    Tag,
)

# ---------------------------------------------------------------------------
# Traversal graph (Step 1)
# ---------------------------------------------------------------------------


class TestBuildTraversalGraph:
    def test_all_in_scope_edges_included(self):
        spec = GraphSpec(Author, Article, Category, Tag, ArticleStats, Comment)
        report = FanoutAnalyzer(spec).analyze()
        # Should have edges for all in-scope relationships
        assert len(report.edges) > 0
        # Every edge should be in-scope
        for e in report.edges:
            assert "IN_SCOPE" in e.field_class.name

    def test_ignored_edge_excluded(self):
        spec = GraphSpec(
            {Article: {"reviewer": Ignore()}},
            Author,
            Category,
            Tag,
        )
        report = FanoutAnalyzer(spec).analyze()
        reviewer_edges = [e for e in report.edges if e.field_name == "reviewer"]
        assert len(reviewer_edges) == 0

    def test_follow_with_limit_recorded(self):
        spec = GraphSpec(
            {Article: {"author": Follow(limit=5)}},
            Author,
            Category,
            Tag,
        )
        report = FanoutAnalyzer(spec).analyze()
        author_edges = [
            e
            for e in report.edges
            if e.source_label == "testapp.Article" and e.field_name == "author"
        ]
        assert len(author_edges) == 1
        assert author_edges[0].has_limit is True
        assert author_edges[0].limit_value == 5
        assert author_edges[0].is_default is False

    def test_default_flag_set(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        report = FanoutAnalyzer(spec).analyze()
        # All edges should be default since no overrides
        for e in report.edges:
            assert e.is_default is True

    def test_out_of_scope_models_not_traversed(self):
        spec = GraphSpec(Article, Category)
        report = FanoutAnalyzer(spec).analyze()
        # Should not have edges to Author or Tag since they're out of scope
        for e in report.edges:
            assert e.target_model in (Article, Category)


# ---------------------------------------------------------------------------
# Cycle detection (Step 2)
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_self_referential_cycle(self):
        spec = GraphSpec(Category)
        report = FanoutAnalyzer(spec).analyze()
        # Category has parent FK to self + children reverse FK
        assert len(report.cycles) >= 1
        cat_cycle = [c for c in report.cycles if Category in c.models]
        assert len(cat_cycle) >= 1
        assert len(cat_cycle[0].models) == 1

    def test_mutual_cycle(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        report = FanoutAnalyzer(spec).analyze()
        # Article.author -> Author and Author.articles -> Article form a cycle
        found_mutual = False
        for cycle in report.cycles:
            cycle_set = set(cycle.models)
            if Author in cycle_set and Article in cycle_set:
                found_mutual = True
                break
        assert found_mutual

    def test_ignoring_edge_removes_cycle(self):
        # Article -> Author via author FK; break the reverse with Ignore
        spec = GraphSpec(
            {Author: {"articles": Ignore(), "reviewed_articles": Ignore(), "comments": Ignore()}},
            Article,
            Category,
            Tag,
        )
        report = FanoutAnalyzer(spec).analyze()
        # No cycle should include Author -> Article direction
        for cycle in report.cycles:
            cycle_set = set(cycle.models)
            if Author in cycle_set and Article in cycle_set:
                # If there's still a cycle, check that it doesn't use ignored edges
                for e in cycle.edges:
                    assert e.field_name not in ("articles", "reviewed_articles", "comments")

    def test_suggested_breaks_prefer_reverse_default(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        report = FanoutAnalyzer(spec).analyze()
        for cycle in report.cycles:
            if len(cycle.suggested_breaks) > 0:
                brk = cycle.suggested_breaks[0]
                # Should prefer reverse edges followed by default
                if any(
                    e.field_class
                    in (
                        FieldClass.REVERSE_FK_IN_SCOPE,
                        FieldClass.REVERSE_M2M_IN_SCOPE,
                        FieldClass.REVERSE_O2O_IN_SCOPE,
                    )
                    and e.is_default
                    for e in cycle.edges
                ):
                    assert brk.is_default


# ---------------------------------------------------------------------------
# Bidirectional detection (Step 3)
# ---------------------------------------------------------------------------


class TestBidirectionalDetection:
    def test_article_author_bidirectional(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        report = FanoutAnalyzer(spec).analyze()
        pairs = {(fwd.source_model, fwd.target_model) for fwd, _ in report.bidirectional} | {
            (bwd.source_model, bwd.target_model) for _, bwd in report.bidirectional
        }
        # Article <-> Author should be bidirectional
        assert (Article, Author) in pairs or (Author, Article) in pairs

    def test_article_tag_bidirectional(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        report = FanoutAnalyzer(spec).analyze()
        pairs = set()
        for fwd, bwd in report.bidirectional:
            pairs.add(frozenset({fwd.source_model, fwd.target_model}))
        assert frozenset({Article, Tag}) in pairs

    def test_not_bidirectional_when_one_ignored(self):
        spec = GraphSpec(
            {Author: {"articles": Ignore(), "reviewed_articles": Ignore()}},
            {Article: {"reviewer": Ignore()}},
            Category,
            Tag,
        )
        report = FanoutAnalyzer(spec).analyze()
        for fwd, bwd in report.bidirectional:
            pair = frozenset({fwd.source_model, fwd.target_model})
            # Article <-> Author should not be bidirectional when reverse is ignored
            assert pair != frozenset({Article, Author})


# ---------------------------------------------------------------------------
# Limit bypass detection (Step 4)
# ---------------------------------------------------------------------------


class TestLimitBypassDetection:
    def test_direct_bypass_same_source_target(self):
        # Article.author with limit, Article.reviewer without limit, both -> Author
        spec = GraphSpec(
            {Article: {"author": Follow(limit=1)}},
            Author,
            Category,
            Tag,
        )
        report = FanoutAnalyzer(spec).analyze()
        # reviewer is another FK from Article -> Author without a limit
        bypasses_for_author = [
            b
            for b in report.limit_bypasses
            if b.limited_edge.field_name == "author" and b.limited_edge.source_model == Article
        ]
        assert len(bypasses_for_author) >= 1
        # At least one bypass path should be the direct reviewer edge
        has_direct = any(
            len(b.bypass_path) == 1 and b.bypass_path[0].field_name == "reviewer"
            for b in bypasses_for_author
        )
        assert has_direct

    def test_no_bypasses_when_no_limits(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        report = FanoutAnalyzer(spec).analyze()
        assert len(report.limit_bypasses) == 0


# ---------------------------------------------------------------------------
# Shared reference detection (Step 5)
# ---------------------------------------------------------------------------


class TestSharedReferenceDetection:
    def test_author_shared_at_threshold_2(self):
        # Author reached from Article (author, reviewer) and Comment (author) = 2 models
        spec = GraphSpec(Author, Article, Category, Tag, Comment, ArticleStats)
        report = FanoutAnalyzer(spec).analyze(threshold=2)
        shared_models = {ref.model for ref in report.shared_references}
        assert Author in shared_models

    def test_author_not_shared_at_high_threshold(self):
        spec = GraphSpec(Author, Article, Category, Tag, Comment, ArticleStats)
        report = FanoutAnalyzer(spec).analyze(threshold=10)
        shared_models = {ref.model for ref in report.shared_references}
        assert Author not in shared_models

    def test_shared_ref_has_incoming_and_outgoing(self):
        spec = GraphSpec(Author, Article, Category, Tag, Comment, ArticleStats)
        report = FanoutAnalyzer(spec).analyze(threshold=2)
        found = False
        for ref in report.shared_references:
            if ref.model == Author:
                found = True
                assert ref.in_degree >= 2
                # Article.author, Article.reviewer, Comment.author = 3 incoming edges
                assert len(ref.incoming_edges) >= 2
                # Author has outgoing reverse edges (articles, reviewed_articles, comments)
                assert len(ref.outgoing_edges) >= 1
                break
        assert found

    def test_threshold_adjustable(self):
        spec = GraphSpec(Author, Article, Category, Tag, Comment, ArticleStats)
        report_low = FanoutAnalyzer(spec).analyze(threshold=2)
        report_high = FanoutAnalyzer(spec).analyze(threshold=5)
        assert len(report_low.shared_references) >= len(report_high.shared_references)


# ---------------------------------------------------------------------------
# Cardinality estimation (Step 6)
# ---------------------------------------------------------------------------


class TestCardinalityEstimation:
    @pytest.fixture(autouse=True)
    def setup_data(self, article, article_stats, comment):
        """Use existing conftest fixtures to populate data."""

    def test_estimate_produces_results(self):
        spec = GraphSpec(Author, Article, Category, Tag, ArticleStats, Comment)
        report = FanoutAnalyzer(spec).estimate_fanout()
        assert report.cardinality is not None
        assert len(report.cardinality) > 0

    def test_reverse_fk_cardinality(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        report = FanoutAnalyzer(spec).estimate_fanout()
        assert report.cardinality is not None
        # Find cardinality for Author.articles (reverse FK)
        author_articles = [
            est
            for est in report.cardinality
            if est.edge.source_label == "testapp.Author" and est.edge.field_name == "articles"
        ]
        if author_articles:
            est = author_articles[0]
            assert est.total_count >= 1
            assert est.max_cardinality >= 1

    def test_cardinality_none_without_estimate(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        report = FanoutAnalyzer(spec).analyze()
        assert report.cardinality is None


# ---------------------------------------------------------------------------
# FanoutReport structure
# ---------------------------------------------------------------------------


class TestFanoutReport:
    def test_report_fields(self):
        spec = GraphSpec(Author, Article, Category, Tag)
        report = FanoutAnalyzer(spec).analyze()
        assert isinstance(report, FanoutReport)
        assert isinstance(report.edges, list)
        assert isinstance(report.cycles, list)
        assert isinstance(report.bidirectional, list)
        assert isinstance(report.limit_bypasses, list)
        assert isinstance(report.shared_references, list)

    def test_edge_info_str(self):
        spec = GraphSpec(Author, Article)
        report = FanoutAnalyzer(spec).analyze()
        for e in report.edges:
            s = str(e)
            assert e.source_label in s
            assert e.field_name in s


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------


class TestGraphFanoutCommand:
    def test_text_output(self, capsys):
        out = _call_command("testapp")
        assert "Fan-out Analysis" in out
        assert "CYCLES" in out
        assert "BIDIRECTIONAL" in out
        assert "LIMIT BYPASSES" in out
        assert "SHARED REFERENCES" in out

    def test_json_output(self):
        out = _call_command("testapp", format="json")
        data = json.loads(out)
        assert "edges" in data
        assert "cycles" in data
        assert "bidirectional" in data
        assert "limit_bypasses" in data
        assert "shared_references" in data

    def test_estimate_flag(self, db):
        out = _call_command("testapp", estimate=True)
        assert "CARDINALITY" in out

    def test_json_with_estimate(self, db):
        out = _call_command("testapp", format="json", estimate=True)
        data = json.loads(out)
        assert "cardinality" in data

    def test_threshold_flag(self):
        out = _call_command("testapp", threshold=1)
        assert "SHARED REFERENCES" in out
        assert "threshold=1" in out

    def test_exclude_flag(self):
        out_with = _call_command("testapp", format="json")
        out_without = _call_command("testapp", format="json", exclude=["testapp.Comment"])
        data_with = json.loads(out_with)
        data_without = json.loads(out_without)
        # Should have fewer edges when Comment is excluded
        assert len(data_without["edges"]) <= len(data_with["edges"])

    def test_all_flag(self):
        out = _call_command(all_apps=True, format="json")
        data = json.loads(out)
        assert len(data["edges"]) > 0

    def test_no_args_raises(self):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match="Provide app labels"):
            _call_command()

    def test_bad_app_raises(self):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match="No installed app"):
            _call_command("nonexistent_app")

    def test_bad_exclude_raises(self):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match="Unknown model"):
            _call_command("testapp", exclude=["testapp.Nonexistent"])

    def test_spec_flag_bad_path_raises(self):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            _call_command(spec="nonexistent.module.spec")


def _call_command(*apps, **kwargs):
    """Helper to call graph_fanout and capture stdout."""
    from io import StringIO

    out = StringIO()
    call_command("graph_fanout", *apps, stdout=out, **kwargs)
    return out.getvalue()
