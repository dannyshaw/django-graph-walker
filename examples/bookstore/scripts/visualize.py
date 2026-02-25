"""Generate interactive HTML visualizations of the bookstore graph."""

import os
import sys

import django

# Add the example project to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bookstore.settings")
django.setup()

from books.models import Author, Book, Genre, Publisher, Review  # noqa: E402

from django_graph_walker.actions.visualize import Visualize  # noqa: E402
from django_graph_walker.spec import GraphSpec  # noqa: E402
from django_graph_walker.walker import GraphWalker  # noqa: E402


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Define a spec with all five models
    spec = GraphSpec(Publisher, Genre, Author, Book, Review)
    viz = Visualize()

    # Generate schema-level DOT string (no DB needed)
    schema_dot = viz.schema(spec)

    # Walk from first publisher for instance-level graph
    publisher = Publisher.objects.first()
    if publisher is None:
        print("No publishers found. Run generate_data.py first.")
        sys.exit(1)

    print(f"Walking from publisher: {publisher}")
    result = GraphWalker(spec).walk(publisher)

    # Generate instance-level DOT string
    instances_dot = viz.instances(result)

    # Read the HTML template
    template_path = os.path.join(base_dir, "templates", "graph.html")
    with open(template_path) as f:
        template = f.read()

    # Write schema HTML
    schema_html = template.replace("{{TITLE}}", "Bookstore Schema Graph")
    schema_html = schema_html.replace("{{DOT_STRING}}", schema_dot)
    schema_path = os.path.join(output_dir, "schema.html")
    with open(schema_path, "w") as f:
        f.write(schema_html)
    print(f"Schema graph: {schema_path}")

    # Write instances HTML
    instances_html = template.replace("{{TITLE}}", "Bookstore Instance Graph")
    instances_html = instances_html.replace("{{DOT_STRING}}", instances_dot)
    instances_path = os.path.join(output_dir, "instances.html")
    with open(instances_path, "w") as f:
        f.write(instances_html)
    print(f"Instance graph: {instances_path}")


if __name__ == "__main__":
    main()
