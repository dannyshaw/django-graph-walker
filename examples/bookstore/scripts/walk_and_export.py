"""Walk from a publisher and export the reachable graph to a JSON fixture."""

import os
import sys

import django

# Add the example project to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bookstore.settings")
django.setup()

from books.models import Author, Book, Genre, Publisher, Review  # noqa: E402

from django_graph_walker.actions.export import Export  # noqa: E402
from django_graph_walker.spec import GraphSpec  # noqa: E402
from django_graph_walker.walker import GraphWalker  # noqa: E402


def main():
    # Pick the first publisher as the root
    publisher = Publisher.objects.first()
    if publisher is None:
        print("No publishers found. Run generate_data.py first.")
        sys.exit(1)

    print(f"Walking from publisher: {publisher}")

    # Define a spec with all five models
    spec = GraphSpec(Publisher, Genre, Author, Book, Review)

    # Walk the graph
    result = GraphWalker(spec).walk(publisher)

    # Print stats
    print("\nWalk result:")
    print(f"  Total instances: {result.instance_count}")
    print(f"  Models touched:  {result.model_count}")
    print("  Breakdown:")
    for model, instances in sorted(result.by_model().items(), key=lambda x: x[0].__name__):
        print(f"    {model.__name__}: {len(instances)}")

    # Export to JSON fixture
    output_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "fixture.json"
    )
    Export(format="json").to_file(result, output_path)
    print(f"\nExported to: {output_path}")


if __name__ == "__main__":
    main()
