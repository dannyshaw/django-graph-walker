"""Tests for GraphSpec factory methods: from_app, from_apps, all, exclude."""

import pytest

from django_graph_walker.spec import GraphSpec
from tests.testapp.models import (
    Article,
    ArticleStats,
    Author,
    Category,
    Comment,
    PremiumArticle,
    Tag,
)

TESTAPP_MODELS = {Author, Category, Tag, Article, ArticleStats, PremiumArticle, Comment}


class TestFromApp:
    def test_from_app_returns_all_models_in_app(self):
        spec = GraphSpec.from_app("testapp")
        assert spec.models == TESTAPP_MODELS

    def test_from_app_invalid_label_raises(self):
        with pytest.raises(LookupError):
            GraphSpec.from_app("nonexistent")

    def test_from_app_models_have_no_overrides(self):
        spec = GraphSpec.from_app("testapp")
        for model in spec.models:
            assert spec.get_overrides(model) == {}

    def test_from_app_contenttypes(self):
        spec = GraphSpec.from_app("contenttypes")
        from django.contrib.contenttypes.models import ContentType

        assert ContentType in spec


class TestFromApps:
    def test_from_apps_single_app(self):
        spec = GraphSpec.from_apps("testapp")
        assert spec.models == TESTAPP_MODELS

    def test_from_apps_multiple_apps(self):
        spec = GraphSpec.from_apps("testapp", "contenttypes")
        from django.contrib.contenttypes.models import ContentType

        assert Author in spec
        assert ContentType in spec

    def test_from_apps_deduplication(self):
        """Passing same app twice doesn't duplicate models."""
        spec = GraphSpec.from_apps("testapp", "testapp")
        assert spec.models == TESTAPP_MODELS


class TestAll:
    def test_all_excludes_django_contrib_by_default(self):
        spec = GraphSpec.all()
        # testapp models should be included
        assert Author in spec
        assert Article in spec

        # Django contrib auth models should be excluded
        from django.contrib.auth.models import User

        assert User not in spec

    def test_all_with_empty_exclude(self):
        spec = GraphSpec.all(exclude_apps=[])
        # Everything should be included
        from django.contrib.auth.models import User

        assert User in spec
        assert Author in spec

    def test_all_with_custom_exclude(self):
        spec = GraphSpec.all(exclude_apps=["tests.testapp"])
        assert Author not in spec
        assert Article not in spec


class TestExclude:
    def test_exclude_removes_model(self):
        spec = GraphSpec.from_app("testapp").exclude(Comment)
        assert Comment not in spec
        assert Author in spec
        assert Article in spec

    def test_exclude_multiple_models(self):
        spec = GraphSpec.from_app("testapp").exclude(Comment, PremiumArticle)
        assert Comment not in spec
        assert PremiumArticle not in spec
        assert Author in spec

    def test_exclude_preserves_overrides(self):
        from django_graph_walker.spec import Override

        spec = GraphSpec({Author: {"name": Override("Anon")}}, Article)
        spec = spec.exclude(Article)
        assert Article not in spec
        assert Author in spec
        assert "name" in spec.get_overrides(Author)

    def test_exclude_returns_new_spec(self):
        original = GraphSpec.from_app("testapp")
        excluded = original.exclude(Comment)
        # Original is unchanged
        assert Comment in original
        assert Comment not in excluded


class TestComposition:
    def test_from_app_composable_with_or(self):
        spec1 = GraphSpec.from_app("testapp")
        spec2 = GraphSpec.from_app("contenttypes")
        merged = spec1 | spec2
        assert Author in merged
        from django.contrib.contenttypes.models import ContentType

        assert ContentType in merged

    def test_from_app_composable_with_manual_spec(self):
        from django_graph_walker.spec import Override

        auto_spec = GraphSpec.from_app("testapp")
        overrides = GraphSpec({Author: {"name": Override("Anon")}})
        merged = auto_spec | overrides
        assert Author in merged
        assert "name" in merged.get_overrides(Author)
