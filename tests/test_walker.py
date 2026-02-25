"""Tests for GraphWalker and WalkResult."""

import pytest

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
        """Article has FK to Author and Category — both in scope, explicit Follow needed."""
        spec = GraphSpec(
            {
                Article: {
                    "author": Follow(),
                    "category": Follow(),
                },
                Author: {},
                Category: {},
            }
        )
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
        """Category.parent is self-referential FK — needs explicit Follow to walk up."""
        spec = GraphSpec({Category: {"parent": Follow()}})
        result = GraphWalker(spec).walk(child_category)
        assert child_category in result
        assert root_category in result

    def test_walk_follows_reverse_self_referential(self, root_category, child_category):
        """Walking from root should find children via reverse FK (default)."""
        spec = GraphSpec(Category)
        result = GraphWalker(spec).walk(root_category)
        assert root_category in result
        assert child_category in result


class TestGraphWalkerM2M:
    def test_walk_follows_m2m_in_scope(self, article, tag_python, tag_django):
        """Article.tags M2M — Tag in scope, explicit Follow needed."""
        spec = GraphSpec(
            {
                Article: {
                    "tags": Follow(),
                    "author": Follow(),
                    "category": Follow(),
                },
                Tag: {},
                Author: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(article)
        assert tag_python in result
        assert tag_django in result

    def test_walk_ignores_m2m_out_of_scope(self, article, tag_python):
        """Tag not in scope — M2M should not follow."""
        spec = GraphSpec(Article, Author, Category)
        result = GraphWalker(spec).walk(article)
        assert tag_python not in result

    def test_walk_follows_reverse_m2m_in_scope(self, tag_python, article):
        """Walking from Tag with Article in scope — reverse M2M needs explicit Follow."""
        spec = GraphSpec(
            {
                Tag: {"articles": Follow()},
                Article: {},
                Author: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(tag_python)
        assert tag_python in result
        assert article in result


class TestGraphWalkerOneToOne:
    def test_walk_follows_o2o_in_scope(self, article, article_stats):
        """Article.stats reverse O2O — ArticleStats in scope should collect (default)."""
        spec = GraphSpec(Article, ArticleStats, Author, Category)
        result = GraphWalker(spec).walk(article)
        assert article_stats in result

    def test_walk_follows_forward_o2o(self, article_stats, article):
        """Walking from ArticleStats should follow FK to Article with explicit Follow."""
        spec = GraphSpec(
            {
                ArticleStats: {"article": Follow()},
                Article: {},
                Author: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(article_stats)
        assert article in result


class TestGraphWalkerGenericFK:
    def test_walk_follows_generic_relation(self, article, comment, author):
        """Article has GenericRelation to Comment — should collect (default)."""
        spec = GraphSpec(Article, Comment, Author, Category)
        result = GraphWalker(spec).walk(article)
        assert comment in result

    def test_walk_ignores_generic_relation_out_of_scope(self, article, comment):
        """Comment not in scope — GenericRelation should not follow."""
        spec = GraphSpec(Article, Author, Category)
        result = GraphWalker(spec).walk(article)
        assert comment not in result


class TestGraphWalkerDefaultFollowBehavior:
    """Verify that all in-scope edges are followed by default."""

    def test_forward_fk_followed_by_default(self, article, author):
        """Article→Author forward FK should be followed when both are in scope."""
        spec = GraphSpec(Article, Author, Category)
        result = GraphWalker(spec).walk(article)
        assert article in result
        assert author in result

    def test_forward_m2m_followed_by_default(self, article, tag_python, tag_django):
        """Article→Tag forward M2M should be followed when both are in scope."""
        spec = GraphSpec(Article, Tag, Author, Category)
        result = GraphWalker(spec).walk(article)
        assert article in result
        assert tag_python in result
        assert tag_django in result

    def test_forward_o2o_followed_by_default(self, article_stats, article):
        """ArticleStats→Article forward O2O should be followed when both are in scope."""
        spec = GraphSpec(ArticleStats, Article, Author, Category)
        result = GraphWalker(spec).walk(article_stats)
        assert article_stats in result
        assert article in result

    def test_reverse_m2m_followed_by_default(self, tag_python, article):
        """Tag→Article reverse M2M should be followed when both are in scope."""
        spec = GraphSpec(Tag, Article, Author, Category)
        result = GraphWalker(spec).walk(tag_python)
        assert tag_python in result
        assert article in result

    def test_forward_fk_not_followed_out_of_scope(self, article, author):
        """Article→Author forward FK should NOT be followed when Author is not in scope."""
        spec = GraphSpec(Article, Category)
        result = GraphWalker(spec).walk(article)
        assert article in result
        assert author not in result

    def test_ignore_overrides_default_follow(self, article, author):
        """Ignore() on a forward FK should prevent traversal."""
        spec = GraphSpec(
            {
                Article: {"author": Ignore()},
                Author: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(article)
        assert article in result
        assert author not in result


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

    def test_forward_m2m_with_filter(self, article, tag_python, tag_django):
        """Follow(filter=...) on forward M2M should filter related instances."""
        spec = GraphSpec(
            {
                Article: {
                    "tags": Follow(filter=lambda ctx, instance: instance.name == "python"),
                },
                Tag: {},
            }
        )
        result = GraphWalker(spec).walk(article)
        assert tag_python in result
        assert tag_django not in result

    def test_forward_fk_with_filter(self, db):
        """Follow(filter=...) on forward FK should filter the related instance."""
        cat = Category.objects.create(name="Root")
        author = Author.objects.create(name="Alice", email="a@a.com")
        article = Article.objects.create(
            title="Test",
            body="body",
            author=author,
            category=cat,
            published=True,
        )

        # Filter that rejects the author
        spec = GraphSpec(
            {
                Article: {
                    "author": Follow(filter=lambda ctx, instance: instance.name == "Bob"),
                },
                Author: {},
            }
        )
        result = GraphWalker(spec).walk(article)
        assert article in result
        assert author not in result

        # Filter that accepts the author
        spec2 = GraphSpec(
            {
                Article: {
                    "author": Follow(filter=lambda ctx, instance: instance.name == "Alice"),
                },
                Author: {},
            }
        )
        result2 = GraphWalker(spec2).walk(article)
        assert article in result2
        assert author in result2


class TestGraphWalkerCycles:
    def test_handles_circular_fk(self, db):
        """Self-referential models should not cause infinite loops."""
        root = Category.objects.create(name="Root")
        child = Category.objects.create(name="Child", parent=root)
        # Walk from root → child (reverse FK, default follow)
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
        spec = GraphSpec(
            {
                Article: {"author": Follow(), "reviewer": Follow()},
                Author: {},
                Category: {},
            }
        )
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
        spec = GraphSpec(
            {
                Article: {"author": Follow(), "category": Follow()},
                Author: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(article)
        by_model = result.by_model()
        assert Article in by_model
        assert Author in by_model
        assert Category in by_model
        assert len(by_model[Article]) == 1

    def test_model_count(self, article, author, child_category):
        spec = GraphSpec(
            {
                Article: {"author": Follow(), "category": Follow()},
                Author: {},
                Category: {},
            }
        )
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
        spec = GraphSpec(
            {
                Article: {"author": Follow(), "category": Follow()},
                Author: {},
                Category: {},
            }
        )
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


class TestWalkResultComposition:
    def test_result_or_merges_instances(self, db):
        """WalkResult + WalkResult should merge instances from both."""
        a1 = Author.objects.create(name="A1", email="a1@test.com")
        a2 = Author.objects.create(name="A2", email="a2@test.com")

        spec = GraphSpec(Author)
        result1 = GraphWalker(spec).walk(a1)
        result2 = GraphWalker(spec).walk(a2)

        merged = result1 | result2
        assert a1 in merged
        assert a2 in merged
        assert merged.instance_count == 2

    def test_result_or_deduplicates(self, db):
        """Overlapping instances should not be duplicated."""
        a1 = Author.objects.create(name="A1", email="a1@test.com")

        spec = GraphSpec(Author)
        result1 = GraphWalker(spec).walk(a1)
        result2 = GraphWalker(spec).walk(a1)

        merged = result1 | result2
        assert merged.instance_count == 1

    def test_result_or_merges_spec_models(self, db):
        """Merged result should have spec_models from both results."""
        a = Author.objects.create(name="A", email="a@test.com")
        cat = Category.objects.create(name="Cat")

        result1 = GraphWalker(GraphSpec(Author)).walk(a)
        result2 = GraphWalker(GraphSpec(Category)).walk(cat)

        merged = result1 | result2
        assert a in merged
        assert cat in merged
        assert merged.instance_count == 2


class TestBatchPrefetch:
    def test_batch_prefetch_reduces_queries(self, db, django_assert_num_queries):
        """Query count should be O(edge types) not O(instances)."""
        cat = Category.objects.create(name="Root")
        author = Author.objects.create(name="Alice", email="a@a.com")

        # Create 10 articles under the same author
        articles = []
        for i in range(10):
            articles.append(
                Article.objects.create(
                    title=f"Article {i}",
                    body="body",
                    author=author,
                    category=cat,
                    published=True,
                )
            )

        spec = GraphSpec(
            {
                Author: {},
                Article: {"author": Follow(), "category": Follow()},
                Category: {},
            }
        )

        # Walking from author should find all 10 articles.
        # With batch prefetch, the BFS level that processes Author will
        # prefetch reverse FKs in bulk, then the Article level prefetches
        # forward FKs in bulk. Without batch prefetch each article would
        # trigger separate FK loads.
        # Expected queries:
        #   1. prefetch articles for Author batch (reverse FK)
        #   2. prefetch reviewed_articles for Author batch (reverse FK)
        #   3. prefetch category for Article batch (forward FK via Follow)
        #   4. prefetch children for Category batch (reverse self-FK)
        #   5. prefetch articles for Category batch (reverse FK)
        # Key: 5 queries for 10 articles, not 10+ individual FK loads
        with django_assert_num_queries(5):
            result = GraphWalker(spec).walk(author)

        assert result.instance_count == 12  # 1 author + 10 articles + 1 category

    def test_follow_prefetch_applied_at_batch_level(self, db):
        """Follow(prefetch=...) should be applied via Prefetch object at batch level."""
        cat = Category.objects.create(name="Root")
        author = Author.objects.create(name="Alice", email="a@a.com")

        # Create articles with specific titles to verify ordering from prefetch
        for title in ["Zebra", "Apple", "Mango"]:
            Article.objects.create(
                title=title, body="body", author=author, category=cat, published=True
            )

        spec = GraphSpec(
            {
                Author: {
                    "articles": Follow(prefetch=lambda qs: qs.order_by("title")),
                },
                Article: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(author)
        # All 3 articles collected
        result_articles = result.instances_of(Article)
        assert len(result_articles) == 3
        titles = {a.title for a in result_articles}
        assert titles == {"Zebra", "Apple", "Mango"}

    def test_filter_still_works_with_batch_prefetch(self, db, django_assert_num_queries):
        """Filters should still exclude instances even after batch prefetch caches data."""
        author = Author.objects.create(name="Alice", email="a@a.com")
        cat = Category.objects.create(name="Root")

        kept = Article.objects.create(
            title="Keep Me", body="body", author=author, category=cat, published=True
        )
        skipped = Article.objects.create(
            title="Skip Me", body="body", author=author, category=cat, published=True
        )

        # Only Author→articles edge, Category not in scope so no alternate path
        spec = GraphSpec(
            {
                Author: {
                    "articles": Follow(filter=lambda ctx, instance: instance.title == "Keep Me"),
                },
                Article: {},
            }
        )
        result = GraphWalker(spec).walk(author)
        assert kept in result
        assert skipped not in result

    def test_batch_prefetch_with_empty_relations(self, db):
        """Instances with no related objects should not cause errors during prefetch."""
        author = Author.objects.create(name="Lonely", email="lonely@test.com")

        spec = GraphSpec(Author, Article, Category)
        result = GraphWalker(spec).walk(author)
        assert result.instance_count == 1
        assert author in result

    @pytest.mark.parametrize("num_roots", [1, 5])
    def test_batch_prefetch_with_multiple_roots(self, db, num_roots):
        """Multiple root instances of the same model should be batched together."""
        cat = Category.objects.create(name="Root")
        authors = []
        for i in range(num_roots):
            a = Author.objects.create(name=f"Author {i}", email=f"a{i}@test.com")
            Article.objects.create(
                title=f"Article by {i}",
                body="body",
                author=a,
                category=cat,
                published=True,
            )
            authors.append(a)

        spec = GraphSpec(Author, Article, Category)
        result = GraphWalker(spec).walk(*authors)
        # Each author has 1 article, plus 1 shared category
        assert result.instance_count == num_roots * 2 + 1


class TestFollowLimit:
    def test_limit_caps_reverse_fk(self, db):
        """Follow(limit=N) should cap the number of related instances per parent."""
        cat = Category.objects.create(name="Root")
        author = Author.objects.create(name="Alice", email="a@a.com")
        for i in range(10):
            Article.objects.create(
                title=f"Article {i}",
                body="body",
                author=author,
                category=cat,
                published=True,
            )

        spec = GraphSpec(
            {
                Author: {"articles": Follow(limit=3)},
                Article: {},
            }
        )
        result = GraphWalker(spec).walk(author)
        articles = result.instances_of(Article)
        assert len(articles) == 3

    def test_limit_caps_forward_m2m(self, db):
        """Follow(limit=N) on forward M2M should cap tags per article."""
        cat = Category.objects.create(name="Root")
        author = Author.objects.create(name="Alice", email="a@a.com")
        article = Article.objects.create(
            title="Test", body="body", author=author, category=cat, published=True
        )
        for i in range(5):
            tag = Tag.objects.create(name=f"tag-{i}")
            article.tags.add(tag)

        spec = GraphSpec(
            {
                Article: {"tags": Follow(limit=2)},
                Tag: {},
            }
        )
        result = GraphWalker(spec).walk(article)
        tags = result.instances_of(Tag)
        assert len(tags) == 2

    def test_limit_applied_after_filter(self, db):
        """Limit should apply after filter, not before."""
        cat = Category.objects.create(name="Root")
        author = Author.objects.create(name="Alice", email="a@a.com")
        for i in range(10):
            Article.objects.create(
                title=f"Article {i}",
                body="body",
                author=author,
                category=cat,
                published=(i % 2 == 0),  # 5 published, 5 not
            )

        spec = GraphSpec(
            {
                Author: {
                    "articles": Follow(
                        filter=lambda ctx, instance: instance.published,
                        limit=3,
                    ),
                },
                Article: {},
            }
        )
        result = GraphWalker(spec).walk(author)
        articles = result.instances_of(Article)
        # 5 pass filter, limit caps to 3
        assert len(articles) == 3
        assert all(a.published for a in articles)

    def test_limit_per_parent_not_global(self, db):
        """Each parent instance gets its own limit independently."""
        cat = Category.objects.create(name="Root")
        a1 = Author.objects.create(name="Alice", email="a@a.com")
        a2 = Author.objects.create(name="Bob", email="b@b.com")
        for i in range(5):
            Article.objects.create(
                title=f"A1-{i}", body="body", author=a1, category=cat, published=True
            )
            Article.objects.create(
                title=f"A2-{i}", body="body", author=a2, category=cat, published=True
            )

        spec = GraphSpec(
            {
                Author: {"articles": Follow(limit=2)},
                Article: {},
            }
        )
        result = GraphWalker(spec).walk(a1, a2)
        articles = result.instances_of(Article)
        # 2 per author = 4 total
        assert len(articles) == 4

    def test_limit_without_follow_override(self, db):
        """Limit only works via Follow() — default edges have no limit."""
        cat = Category.objects.create(name="Root")
        author = Author.objects.create(name="Alice", email="a@a.com")
        for i in range(5):
            Article.objects.create(
                title=f"Article {i}",
                body="body",
                author=author,
                category=cat,
                published=True,
            )

        # No Follow override — default follow, no limit
        spec = GraphSpec(Author, Article, Category)
        result = GraphWalker(spec).walk(author)
        articles = result.instances_of(Article)
        assert len(articles) == 5

    def test_limit_zero_blocks_all(self, db):
        """Follow(limit=0) should effectively block all related instances."""
        author = Author.objects.create(name="Alice", email="a@a.com")
        cat = Category.objects.create(name="Root")
        Article.objects.create(
            title="Test", body="body", author=author, category=cat, published=True
        )

        spec = GraphSpec(
            {
                Author: {"articles": Follow(limit=0)},
                Article: {},
            }
        )
        result = GraphWalker(spec).walk(author)
        assert result.instances_of(Article) == []
