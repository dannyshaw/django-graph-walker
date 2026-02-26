"""Tests for Clone action — same-database subgraph cloning."""

from django_graph_walker.actions.clone import Clone
from django_graph_walker.spec import GraphSpec, KeepOriginal, Override
from django_graph_walker.walker import GraphWalker
from tests.testapp.models import Article, ArticleStats, Author, Category, Tag


class TestCloneBasic:
    def test_clone_single_instance(self, db, author):
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)

        cloned = Clone(spec).execute(result)

        assert cloned.clone_count == 1
        clone = cloned.get_clone(author)
        assert clone is not None
        assert clone.pk != author.pk
        assert clone.name == author.name
        assert clone.email == author.email
        assert Author.objects.count() == 2

    def test_clone_with_fk(self, db, article, author, child_category):
        spec = GraphSpec(Article, Author, Category)
        result = GraphWalker(spec).walk(article)

        cloned = Clone(spec).execute(result)

        cloned_article = cloned.get_clone(article)
        cloned_author = cloned.get_clone(author)
        assert cloned_article is not None
        assert cloned_author is not None

        # FK should point to the cloned author, not the original
        assert cloned_article.author_id == cloned_author.pk
        assert cloned_article.author_id != author.pk

    def test_clone_with_m2m(self, db, article, tag_python, tag_django):
        spec = GraphSpec(Article, Author, Category, Tag)
        result = GraphWalker(spec).walk(article)

        cloned = Clone(spec).execute(result)

        cloned_article = cloned.get_clone(article)
        assert cloned_article is not None

        # M2M should point to cloned tags
        cloned_tag_pks = set(cloned_article.tags.values_list("pk", flat=True))
        original_tag_pks = {tag_python.pk, tag_django.pk}
        assert cloned_tag_pks.isdisjoint(original_tag_pks)
        assert len(cloned_tag_pks) == 2

    def test_clone_with_o2o(self, db, article, article_stats):
        spec = GraphSpec(Article, Author, Category, ArticleStats)
        result = GraphWalker(spec).walk(article)

        cloned = Clone(spec).execute(result)

        cloned_article = cloned.get_clone(article)
        cloned_stats = cloned.get_clone(article_stats)
        assert cloned_stats is not None
        assert cloned_stats.article_id == cloned_article.pk
        assert cloned_stats.view_count == 100

    def test_clone_self_referential_fk(self, db, root_category, child_category):
        spec = GraphSpec(Category)
        result = GraphWalker(spec).walk(root_category)

        cloned = Clone(spec).execute(result)

        cloned_root = cloned.get_clone(root_category)
        cloned_child = cloned.get_clone(child_category)
        assert cloned_root is not None
        assert cloned_child is not None
        assert cloned_child.parent_id == cloned_root.pk
        assert cloned_root.parent is None


class TestCloneOverrides:
    def test_override_field_with_static_value(self, db, author):
        spec = GraphSpec({Author: {"name": Override("CLONED")}})
        result = GraphWalker(spec).walk(author)

        cloned = Clone(spec).execute(result)
        clone = cloned.get_clone(author)
        assert clone.name == "CLONED"
        assert clone.email == author.email

    def test_override_field_with_callable(self, db, article):
        spec = GraphSpec(
            {
                Article: {"title": Override(lambda inst, ctx: f"Copy of {inst.title}")},
                Author: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(article)

        cloned = Clone(spec).execute(result)
        clone = cloned.get_clone(article)
        assert clone.title == "Copy of Test Article"

    def test_override_with_ctx(self, db, author):
        spec = GraphSpec(
            {
                Author: {"name": Override(lambda inst, ctx: ctx["new_name"])},
            }
        )
        result = GraphWalker(spec).walk(author)

        cloned = Clone(spec).execute(result, ctx={"new_name": "Charlie"})
        clone = cloned.get_clone(author)
        assert clone.name == "Charlie"

    def test_override_fk_with_ctx_instance(self, db, article, author, reviewer):
        """Override a FK field to point to a specific instance from ctx."""
        spec = GraphSpec(
            {
                Article: {"author": Override(lambda inst, ctx: ctx["new_author"])},
                Author: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(article)

        cloned = Clone(spec).execute(result, ctx={"new_author": reviewer})
        cloned_article = cloned.get_clone(article)

        # Should point to the reviewer, not the original author or a clone
        assert cloned_article.author_id == reviewer.pk

    def test_keep_original_fk(self, db, article, author):
        """KeepOriginal should point to original author, not clone it."""
        spec = GraphSpec(
            {
                Article: {"author": KeepOriginal()},
                Author: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(article)

        cloned = Clone(spec).execute(result)
        cloned_article = cloned.get_clone(article)

        # Should point to the original author, not a clone
        assert cloned_article.author_id == author.pk

    def test_keep_original_conditional(self, db, article, author, reviewer):
        """KeepOriginal(when=...) should conditionally keep original."""
        spec = GraphSpec(
            {
                Article: {
                    "author": KeepOriginal(when=lambda inst, ctx: ctx.get("keep_author")),
                },
                Author: {},
                Category: {},
            }
        )
        result = GraphWalker(spec).walk(article)

        # With keep_author=True: should keep original
        cloned = Clone(spec).execute(result, ctx={"keep_author": True})
        assert cloned.get_clone(article).author_id == author.pk

        # With keep_author=False: should remap to clone
        cloned2 = Clone(spec).execute(result, ctx={"keep_author": False})
        cloned_author = cloned2.get_clone(author)
        assert cloned2.get_clone(article).author_id == cloned_author.pk


class TestCloneResult:
    def test_clone_result_as_walk_result(self, db, article):
        spec = GraphSpec(Article, Author, Category)
        result = GraphWalker(spec).walk(article)

        cloned = Clone(spec).execute(result)
        walk_result = cloned.result

        assert walk_result.instance_count == cloned.clone_count
        assert all(inst.pk != article.pk for inst in walk_result.instances_of(Article))

    def test_get_clone_returns_none_for_unknown(self, db, author, reviewer):
        spec = GraphSpec(Author)
        result = GraphWalker(spec).walk(author)

        cloned = Clone(spec).execute(result)
        assert cloned.get_clone(reviewer) is None


class TestCloneOutOfScope:
    def test_out_of_scope_fk_preserved(self, db, article, author, child_category):
        """When Author is out of scope, the FK should keep the original reference."""
        spec = GraphSpec(Article, Category)  # Author is NOT in scope
        result = GraphWalker(spec).walk(article)

        cloned = Clone(spec).execute(result)
        cloned_article = cloned.get_clone(article)

        # author FK should point to original since Author isn't cloned
        assert cloned_article.author_id == author.pk
