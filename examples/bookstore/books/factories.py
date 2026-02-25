import factory
from faker import Faker

from books.models import Author, Book, Genre, Publisher, Review

fake = Faker()


class PublisherFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Publisher

    name = factory.LazyFunction(lambda: fake.company())
    founded_year = factory.LazyFunction(lambda: fake.random_int(min=1900, max=2024))


class GenreFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Genre

    name = factory.LazyFunction(lambda: fake.word().title())
    parent = None


class AuthorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Author

    name = factory.LazyFunction(lambda: fake.name())
    email = factory.LazyFunction(lambda: fake.email())


class BookFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Book

    title = factory.LazyFunction(lambda: fake.sentence(nb_words=4).rstrip("."))
    publisher = factory.SubFactory(PublisherFactory)
    published_date = factory.LazyFunction(
        lambda: fake.date_between(start_date="-30y", end_date="today")
    )
    isbn = factory.LazyFunction(lambda: fake.isbn13(separator=""))


class ReviewFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Review

    book = factory.SubFactory(BookFactory)
    reviewer_name = factory.LazyFunction(lambda: fake.name())
    rating = factory.LazyFunction(lambda: fake.random_int(min=1, max=5))
    text = factory.LazyFunction(lambda: fake.paragraph())
