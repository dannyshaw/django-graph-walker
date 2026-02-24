import pytest

from tests.testapp.models import (
    Article,
    ArticleStats,
    Author,
    Category,
    Comment,
    Tag,
)


@pytest.fixture
def author(db):
    return Author.objects.create(name="Alice", email="alice@example.com")


@pytest.fixture
def reviewer(db):
    return Author.objects.create(name="Bob", email="bob@example.com")


@pytest.fixture
def root_category(db):
    return Category.objects.create(name="Science")


@pytest.fixture
def child_category(db, root_category):
    return Category.objects.create(name="Physics", parent=root_category)


@pytest.fixture
def tag_python(db):
    return Tag.objects.create(name="python")


@pytest.fixture
def tag_django(db):
    return Tag.objects.create(name="django")


@pytest.fixture
def article(db, author, child_category, reviewer, tag_python, tag_django):
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
    return ArticleStats.objects.create(article=article, view_count=100, share_count=10)


@pytest.fixture
def comment(db, article, author):
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(Article)
    return Comment.objects.create(
        content_type=ct,
        object_id=article.pk,
        author=author,
        text="Great article!",
    )
