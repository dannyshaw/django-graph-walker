from django.db import models


class Publisher(models.Model):
    name = models.CharField(max_length=200)
    founded_year = models.IntegerField(null=True, blank=True)

    class Meta:
        app_label = "books"

    def __str__(self):
        return self.name


class Genre(models.Model):
    """Self-referential FK tree for genre hierarchy."""

    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )

    class Meta:
        app_label = "books"

    def __str__(self):
        return self.name


class Author(models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)

    class Meta:
        app_label = "books"

    def __str__(self):
        return self.name


class Book(models.Model):
    title = models.CharField(max_length=300)
    publisher = models.ForeignKey(Publisher, on_delete=models.CASCADE, related_name="books")
    authors = models.ManyToManyField(Author, related_name="books")
    genres = models.ManyToManyField(Genre, related_name="books")
    published_date = models.DateField(null=True, blank=True)
    isbn = models.CharField(max_length=13, blank=True)

    class Meta:
        app_label = "books"

    def __str__(self):
        return self.title


class Review(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="reviews")
    reviewer_name = models.CharField(max_length=200)
    rating = models.IntegerField()
    text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "books"

    def __str__(self):
        return f"Review of {self.book} by {self.reviewer_name}"
