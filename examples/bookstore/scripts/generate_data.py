"""Generate sample bookstore data using factory_boy."""

import os
import random
import sys

import django

# Add the example project to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bookstore.settings")
django.setup()

from books.factories import (  # noqa: E402
    AuthorFactory,
    GenreFactory,
    PublisherFactory,
    ReviewFactory,
)
from books.models import Author, Book, Genre, Publisher, Review  # noqa: E402
from faker import Faker  # noqa: E402

fake = Faker()


def main():
    # Create publishers
    publishers = [PublisherFactory() for _ in range(5)]
    print(f"Created {len(publishers)} publishers")

    # Create top-level genres
    top_genres = [GenreFactory() for _ in range(5)]

    # Create 2-3 child genres per top-level genre
    child_genres = []
    for parent in top_genres:
        num_children = random.randint(2, 3)
        for _ in range(num_children):
            child_genres.append(GenreFactory(parent=parent))

    all_genres = top_genres + child_genres
    print(
        f"Created {len(all_genres)} genres "
        f"({len(top_genres)} top-level, {len(child_genres)} children)"
    )

    # Create authors
    authors = [AuthorFactory() for _ in range(20)]
    print(f"Created {len(authors)} authors")

    # Create books, each assigned to a random existing publisher
    books = []
    for _ in range(50):
        book = Book.objects.create(
            title=fake.sentence(nb_words=4).rstrip("."),
            publisher=random.choice(publishers),
            published_date=fake.date_between(start_date="-30y", end_date="today"),
            isbn=fake.isbn13(separator=""),
        )
        # Assign 1-3 random authors
        book.authors.set(random.sample(authors, k=random.randint(1, 3)))
        # Assign 1-3 random genres
        book.genres.set(random.sample(all_genres, k=random.randint(1, 3)))
        books.append(book)
    print(f"Created {len(books)} books")

    # Create 0-5 reviews per book
    review_count = 0
    for book in books:
        num_reviews = random.randint(0, 5)
        for _ in range(num_reviews):
            ReviewFactory(book=book)
            review_count += 1
    print(f"Created {review_count} reviews")

    # Summary
    print("\n--- Summary ---")
    print(f"Publishers: {Publisher.objects.count()}")
    print(f"Genres:     {Genre.objects.count()}")
    print(f"Authors:    {Author.objects.count()}")
    print(f"Books:      {Book.objects.count()}")
    print(f"Reviews:    {Review.objects.count()}")


if __name__ == "__main__":
    main()
