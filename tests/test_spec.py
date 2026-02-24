"""Tests for GraphSpec construction and validation."""

import pytest

from django_graph_walker.spec import (
    Anonymize,
    Follow,
    GraphSpec,
    Ignore,
    KeepOriginal,
    Override,
)
from tests.testapp.models import (
    Article,
    Author,
    Category,
    Tag,
)


class TestGraphSpecConstruction:
    def test_simple_model_list(self):
        spec = GraphSpec(Author, Article, Category)
        assert spec.models == {Author, Article, Category}

    def test_dict_with_overrides(self):
        spec = GraphSpec(
            {
                Author: {},
                Article: {"title": Override("New Title")},
            }
        )
        assert spec.models == {Author, Article}
        assert isinstance(spec.get_overrides(Article)["title"], Override)

    def test_mixed_models_and_dicts(self):
        spec = GraphSpec(
            {Author: {"name": Override("Anon")}},
            Article,
            Tag,
        )
        assert spec.models == {Author, Article, Tag}
        assert spec.get_overrides(Article) == {}
        assert "name" in spec.get_overrides(Author)

    def test_contains(self):
        spec = GraphSpec(Author, Article)
        assert Author in spec
        assert Article in spec
        assert Tag not in spec

    def test_empty_spec(self):
        spec = GraphSpec()
        assert spec.models == set()

    def test_duplicate_model_raises(self):
        with pytest.raises(ValueError, match="more than once"):
            GraphSpec(Author, {Author: {}})

    def test_non_model_raises(self):
        with pytest.raises(TypeError, match="Django Model classes"):
            GraphSpec("not a model")

    def test_get_overrides_for_unknown_model(self):
        spec = GraphSpec(Author)
        assert spec.get_overrides(Article) == {}


class TestGraphSpecValidation:
    def test_valid_spec_passes(self):
        spec = GraphSpec(
            {
                Author: {"name": Override("Anon")},
                Article: {"title": Override("New")},
            }
        )
        spec.validate()  # Should not raise

    def test_invalid_field_name_raises(self):
        spec = GraphSpec(
            {
                Author: {"nonexistent_field": Override("value")},
            }
        )
        with pytest.raises(ValueError, match="nonexistent_field"):
            spec.validate()

    def test_empty_overrides_valid(self):
        spec = GraphSpec(Author, Article)
        spec.validate()  # Should not raise


class TestOverrideTypes:
    def test_override_static_value(self):
        o = Override("hello")
        assert o.resolve(None, {}) == "hello"

    def test_override_callable(self):
        o = Override(lambda m, ctx: f"title-{ctx['year']}")

        class FakeModel:
            pass

        assert o.resolve(FakeModel(), {"year": 2026}) == "title-2026"

    def test_follow_with_filter(self):
        f = Follow(filter=lambda ctx, instance: instance.pk > 5)
        assert f.filter is not None
        assert f.prefetch is None

    def test_follow_with_prefetch(self):
        f = Follow(prefetch=lambda qs: qs.select_related("author"))
        assert f.prefetch is not None

    def test_ignore(self):
        i = Ignore()
        assert isinstance(i, Ignore)

    def test_keep_original_unconditional(self):
        ko = KeepOriginal()
        assert ko.when is None

    def test_keep_original_conditional(self):
        ko = KeepOriginal(when=lambda m, ctx: m.pk == 1)
        assert ko.when is not None

    def test_anonymize_with_provider_string(self):
        a = Anonymize("email")
        assert a.provider == "email"

    def test_anonymize_with_callable(self):
        def anon_fn(m, ctx):
            return "anon@test.com"

        a = Anonymize(anon_fn)
        assert a.provider is anon_fn
