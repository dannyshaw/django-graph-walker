# Bookstore Example

Demonstrates django-graph-walker with a bookstore data model.

## Setup

```bash
pip install -r requirements.txt
pip install -e ../../  # install django-graph-walker from source
python manage.py migrate
```

## Usage

### Management commands (no Python needed)

```bash
# Visualize the books app schema
python manage.py graph_schema books

# Walk from a Book and see stats
python manage.py graph_walk books.Book 1 --dry-run

# Walk and export to fixture
python manage.py graph_walk books.Book 1 -o output/fixture.json

# Dependency analysis
python manage.py graph_deps books.Book
python manage.py graph_deps books --tree
```

### Python scripts

```bash
# Generate sample data
python scripts/generate_data.py

# Walk from a publisher and export to JSON
python scripts/walk_and_export.py

# Generate interactive graph visualizations
python scripts/visualize.py
```

## Output

After running the scripts, check the `output/` directory:
- `fixture.json` — JSON fixture of all walked instances
- `schema.html` — Interactive schema-level graph
- `instances.html` — Interactive instance-level graph

Open the HTML files in a browser to explore the graphs with zoom and pan.
