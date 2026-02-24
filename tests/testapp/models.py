"""
Test models covering all Django relationship types:
- FK tree (Category self-referential, Category → Article)
- M2M (Article ↔ Tag)
- OneToOne (Article → ArticleStats)
- Reverse FK (Author → Articles)
- Nullable FK (Article.reviewer)
- GenericFK (Comment → any model)
- Multi-table inheritance (Article → PremiumArticle)
"""

from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()

    class Meta:
        app_label = "testapp"

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )

    class Meta:
        app_label = "testapp"

    def __str__(self):
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=50)

    class Meta:
        app_label = "testapp"

    def __str__(self):
        return self.name


class Article(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField(default="")
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="articles")
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="articles")
    reviewer = models.ForeignKey(
        Author, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_articles"
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="articles")
    published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    comments = GenericRelation("Comment")

    class Meta:
        app_label = "testapp"

    def __str__(self):
        return self.title


class ArticleStats(models.Model):
    article = models.OneToOneField(Article, on_delete=models.CASCADE, related_name="stats")
    view_count = models.IntegerField(default=0)
    share_count = models.IntegerField(default=0)

    class Meta:
        app_label = "testapp"

    def __str__(self):
        return f"Stats for {self.article}"


class PremiumArticle(Article):
    """Multi-table inheritance from Article."""

    paywall_price = models.DecimalField(max_digits=6, decimal_places=2)
    subscriber_only = models.BooleanField(default=True)

    class Meta:
        app_label = "testapp"


class Comment(models.Model):
    """Generic FK — can comment on any model."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="comments")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "testapp"

    def __str__(self):
        return f"Comment by {self.author} on {self.content_object}"
