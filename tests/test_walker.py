"""Tests for GraphWalker and WalkResult."""

from django_graph_walker import Follow, GraphSpec, GraphWalker, Ignore
from tests.testapp.models import (
    Article,
    ArticleStats,
    Author,
    Category,
    Comment,
    Tag,
)


class TestGraphWalkerBasic:
    def test_walk_single_model_no_relations(self, author):
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)
        assert result.instance_count == 1
        assert author in result

    def test_walk_follows_fk_to_in_scope(self, article, author, child_category):
        """Article has FK to Author and Category — both in scope, should collect all."""
        spec = GraphSpec(Article, Author, Category)
        result = GraphWalker(spec).walk(article)
        assert article in result
        assert author in result
        assert child_category in result

    def test_walk_does_not_follow_fk_out_of_scope(self, article, author):
        """Author is NOT in spec — should not be collected."""
        spec = GraphSpec(Article, Category)
        result = GraphWalker(spec).walk(article)
        assert article in result
        assert author not in result

    def test_walk_follows_reverse_fk_in_scope(self, author, article):
        """Walking from Author with Article in scope should collect the article."""
        spec = GraphSpec(Author, Article, Category)
        result = GraphWalker(spec).walk(author)
        assert author in result
        assert article in result

    def test_walk_ignores_reverse_fk_out_of_scope(self, author, article):
        """Article not in scope — reverse FK from Author should not follow."""
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)
        assert author in result
        assert article not in result

    def test_walk_follows_self_referential_fk(self, root_category, child_category):
        """Category.parent is self-referential FK — should walk up to root."""
        spec = GraphSpec(Category)
        result = GraphWalker(spec).walk(child_category)
        assert child_category in result
        assert root_category in result

    def test_walk_follows_reverse_self_referential(self, root_category, child_category):
        """Walking from root should find children."""
        spec = GraphSpec(Category)
        result = GraphWalker(spec).walk(root_category)
        assert root_category in result
        assert child_category in result


class TestGraphWalkerM2M:
    def test_walk_follows_m2m_in_scope(self, article, tag_python, tag_django):
        """Article.tags M2M — Tag in scope should collect both tags."""
        spec = GraphSpec(Article, Tag, Author, Category)
        result = GraphWalker(spec).walk(article)
        assert tag_python in result
        assert tag_django in result

    def test_walk_ignores_m2m_out_of_scope(self, article, tag_python):
        """Tag not in scope — M2M should not follow."""
        spec = GraphSpec(Article, Author, Category)
        result = GraphWalker(spec).walk(article)
        assert tag_python not in result

    def test_walk_follows_reverse_m2m_in_scope(self, tag_python, article):
        """Walking from Tag with Article in scope should find articles."""
        spec = GraphSpec(Tag, Article, Author, Category)
        result = GraphWalker(spec).walk(tag_python)
        assert tag_python in result
        assert article in result


class TestGraphWalkerOneToOne:
    def test_walk_follows_o2o_in_scope(self, article, article_stats):
        """Article.stats reverse O2O — ArticleStats in scope should collect."""
        spec = GraphSpec(Article, ArticleStats, Author, Category)
        result = GraphWalker(spec).walk(article)
        assert article_stats in result

    def test_walk_follows_forward_o2o(self, article_stats, article):
        """Walking from ArticleStats should follow FK to Article."""
        spec = GraphSpec(ArticleStats, Article, Author, Category)
        result = GraphWalker(spec).walk(article_stats)
        assert article in result


class TestGraphWalkerGenericFK:
    def test_walk_follows_generic_relation(self, article, comment, author):
        """Article has GenericRelation to Comment — should collect."""
        spec = GraphSpec(Article, Comment, Author, Category)
        result = GraphWalker(spec).walk(article)
        assert comment in result

    def test_walk_ignores_generic_relation_out_of_scope(self, article, comment):
        """Comment not in scope — GenericRelation should not follow."""
        spec = GraphSpec(Article, Author, Category)
        result = GraphWalker(spec).walk(article)
        assert comment not in result


class TestGraphWalkerFiltering:
    def test_follow_with_filter(self, db):
        """Follow override with filter should only collect matching instances."""
        cat = Category.objects.create(name="Root")
        child1 = Category.objects.create(name="Keep", parent=cat)
        child2 = Category.objects.create(name="Skip", parent=cat)

        spec = GraphSpec(
            {
                Category: {
                    "children": Follow(filter=lambda ctx, instance: instance.name == "Keep"),
                },
            }
        )
        result = GraphWalker(spec).walk(cat)
        assert child1 in result
        assert child2 not in result

    def test_ignore_override_prevents_following(self, author, article):
        """Ignore override should prevent following even in-scope reverse FK."""
        spec = GraphSpec(
            {
                Author: {"articles": Ignore()},
                Article: {},
            }
        )
        result = GraphWalker(spec).walk(author)
        assert author in result
        assert article not in result

    def test_follow_override_on_out_of_scope_reverse(self, db):
        """Follow override can't make out-of-scope models appear — the target must be in spec."""
        a = Author.objects.create(name="X", email="x@x.com")
        spec = GraphSpec(
            {
                Author: {"articles": Follow()},
                # Article is NOT in spec
            }
        )
        result = GraphWalker(spec).walk(a)
        # Even with Follow(), Article isn't in spec so shouldn't be collected
        assert result.instance_count == 1


class TestGraphWalkerCycles:
    def test_handles_circular_fk(self, db):
        """Self-referential models should not cause infinite loops."""
        root = Category.objects.create(name="Root")
        child = Category.objects.create(name="Child", parent=root)
        # Walk from root → child → root (cycle via parent FK)
        spec = GraphSpec(Category)
        result = GraphWalker(spec).walk(root)
        assert result.instance_count == 2
        assert root in result
        assert child in result

    def test_multiple_paths_to_same_instance(self, article, author, reviewer):
        """Article.author and Article.reviewer may point to same Author — should visit once."""
        # Make reviewer same as author
        article.reviewer = author
        article.save()
        spec = GraphSpec(Article, Author, Category)
        result = GraphWalker(spec).walk(article)
        models_by_type = result.by_model()
        # Only 1 author instance, not 2
        assert len(models_by_type[Author]) == 1


class TestGraphWalkerMultipleRoots:
    def test_walk_multiple_roots(self, db):
        a1 = Author.objects.create(name="A1", email="a1@test.com")
        a2 = Author.objects.create(name="A2", email="a2@test.com")
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(a1, a2)
        assert result.instance_count == 2
        assert a1 in result
        assert a2 in result


class TestGraphWalkerContext:
    def test_ctx_passed_to_filter(self, db):
        """Context dict should be available in Follow filter."""
        cat = Category.objects.create(name="Root")
        child1 = Category.objects.create(name="A", parent=cat)
        child2 = Category.objects.create(name="B", parent=cat)

        spec = GraphSpec(
            {
                Category: {
                    "children": Follow(filter=lambda ctx, instance: instance.name == ctx["keep"]),
                },
            }
        )
        result = GraphWalker(spec).walk(cat, ctx={"keep": "A"})
        assert child1 in result
        assert child2 not in result


class TestWalkResult:
    def test_by_model(self, article, author, child_category):
        spec = GraphSpec(Article, Author, Category)
        result = GraphWalker(spec).walk(article)
        by_model = result.by_model()
        assert Article in by_model
        assert Author in by_model
        assert Category in by_model
        assert len(by_model[Article]) == 1

    def test_model_count(self, article, author, child_category):
        spec = GraphSpec(Article, Author, Category)
        result = GraphWalker(spec).walk(article)
        assert result.model_count >= 3  # Article, Author, Category (may include reviewer's Author)

    def test_instances_of(self, article, author, child_category):
        spec = GraphSpec(Article, Author, Category)
        result = GraphWalker(spec).walk(article)
        articles = result.instances_of(Article)
        assert article in articles

    def test_iter(self, author):
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)
        all_instances = list(result)
        assert author in all_instances
        assert len(all_instances) == 1

    def test_topological_order(self, article, author, child_category, root_category):
        """Models should be ordered so dependencies come before dependents."""
        spec = GraphSpec(Article, Author, Category)
        result = GraphWalker(spec).walk(article)
        order = result.topological_order()
        # Author and Category should come before Article (Article depends on both)
        author_idx = order.index(Author)
        category_idx = order.index(Category)
        article_idx = order.index(Article)
        assert author_idx < article_idx
        assert category_idx < article_idx

    def test_contains(self, author):
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)
        assert author in result
        # Non-walked instance should not be in result
        other = Author(pk=99999, name="Other", email="o@o.com")
        assert other not in result
