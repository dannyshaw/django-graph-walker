import os
import sys

import pytest

# Set Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
sys.path.insert(0, "src")
sys.path.insert(0, ".")


@pytest.fixture
def author(db):
    from tests.testapp.models import Author

    return Author.objects.create(name="Alice", email="alice@example.com")


@pytest.fixture
def reviewer(db):
    from tests.testapp.models import Author

    return Author.objects.create(name="Bob", email="bob@example.com")


@pytest.fixture
def root_category(db):
    from tests.testapp.models import Category

    return Category.objects.create(name="Science")


@pytest.fixture
def child_category(db, root_category):
    from tests.testapp.models import Category

    return Category.objects.create(name="Physics", parent=root_category)


@pytest.fixture
def tag_python(db):
    from tests.testapp.models import Tag

    return Tag.objects.create(name="python")


@pytest.fixture
def tag_django(db):
    from tests.testapp.models import Tag

    return Tag.objects.create(name="django")


@pytest.fixture
def article(db, author, child_category, reviewer, tag_python, tag_django):
    from tests.testapp.models import Article

    article = Article.objects.create(
        title="Test Article",
        body="Some content",
        author=author,
        category=child_category,
        reviewer=reviewer,
        published=True,
    )
    article.tags.add(tag_python, tag_django)
    return article


@pytest.fixture
def article_stats(db, article):
    from tests.testapp.models import ArticleStats

    return ArticleStats.objects.create(article=article, view_count=100, share_count=10)


@pytest.fixture
def comment(db, article, author):
    from django.contrib.contenttypes.models import ContentType

    from tests.testapp.models import Article, Comment

    ct = ContentType.objects.get_for_model(Article)
    return Comment.objects.create(
        content_type=ct,
        object_id=article.pk,
        author=author,
        text="Great article!",
    )
