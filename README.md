# django-graph-walker

Walk Django model relationship graphs for cloning, subsetting, export, and visualization.

## Overview

django-graph-walker traverses Django model relationships using breadth-first search, collecting all reachable instances into a result set you can export, visualize, or inspect. It is designed for tasks like creating dev/test data subsets from production, cloning content trees with all their dependencies, and understanding complex schema relationships.

The walker uses batch prefetching so queries scale with the number of edge types per BFS level, not with the number of instances. A walk across thousands of instances typically requires only a handful of queries per relationship type.

## Installation

```bash
pip install django-graph-walker
```

Optional extras:

```bash
pip install django-graph-walker[viz]        # graphviz for DOT rendering
pip install django-graph-walker[anonymize]  # faker for field anonymization
```

Requires Python 3.10+ and Django 3.2+.

## Quick Start

```python
from django_graph_walker import GraphSpec, GraphWalker

# Define which models are in scope
spec = GraphSpec(Author, Article, Tag)

# Walk from a root instance
article = Article.objects.get(pk=1)
result = GraphWalker(spec).walk(article)

# Inspect the result
print(result.instance_count)        # total instances collected
print(result.instances_of(Author))  # all Author instances reached
print(result.by_model())            # {Author: [...], Article: [...], Tag: [...]}

# Export to a JSON fixture
from django_graph_walker.actions.export import Export
Export().to_file(result, "dev_data.json")
```

## Core Concepts

### GraphSpec

A `GraphSpec` declares which Django models are in scope for a walk and optionally provides per-field overrides. Models not in the spec are never traversed to.

**Positional models** -- all defaults, no overrides:

```python
spec = GraphSpec(Author, Article, Category, Tag)
```

**Dict with overrides** -- control specific fields:

```python
spec = GraphSpec({
    Author: {
        "email": Anonymize("email"),
    },
    Article: {
        "reviewer": Ignore(),
    },
    Tag: {},
})
```

**Mixed** -- combine both styles:

```python
spec = GraphSpec(
    {Author: {"email": Anonymize("email")}},
    Article,
    Tag,
)
```

**Composition with `|`** -- merge two specs, with the right-hand side winning on conflicts:

```python
base = GraphSpec(Author, Article, Tag)
overrides = GraphSpec({Article: {"reviewer": Ignore()}})
combined = base | overrides
```

### Field Overrides

| Override | Description | Example |
|---|---|---|
| `Follow(filter=..., prefetch=..., limit=...)` | Force-follow an edge. Optional filter, prefetch customization, and per-parent limit. | `Follow(filter=lambda ctx, a: a.published, limit=10)` |
| `Ignore()` | Suppress traversal of an edge that would otherwise be followed. | `Ignore()` |
| `Override(value)` | Set a field to a static value or a callable `(instance, ctx) -> value`. | `Override(lambda inst, ctx: ctx["new_title"])` |
| `KeepOriginal(when=...)` | For FK fields to in-scope models: keep the original target instead of using a clone. Optional conditional. | `KeepOriginal(when=lambda inst, ctx: inst.is_shared)` |
| `Anonymize(provider)` | Anonymize a field using a faker provider string or callable `(instance, ctx) -> value`. | `Anonymize("first_name")` |

### GraphWalker

`GraphWalker` performs level-order BFS from one or more root instances. Every relationship where both endpoints are in the spec is followed by default. Use `Ignore()` to opt out of specific edges.

```python
walker = GraphWalker(spec)

# Single root
result = walker.walk(article)

# Multiple roots
result = walker.walk(article_1, article_2, article_3)

# With context passed to filter/override callables
result = walker.walk(article, ctx={"tenant_id": 42})
```

**Batch prefetching**: Each BFS level groups queued instances by model, then calls `prefetch_related_objects()` once per model group. This means traversing 1,000 articles with FK to Author issues one prefetch query for the Author relationship, not 1,000 individual lookups.

### WalkResult

`WalkResult` is the container returned by `GraphWalker.walk()`. It holds all visited instances keyed by `(model_class, pk)`.

```python
result = GraphWalker(spec).walk(article)

# Group by model
for model, instances in result.by_model().items():
    print(f"{model.__name__}: {len(instances)}")

# Get instances of a specific model
authors = result.instances_of(Author)

# Dependency-ordered model list (FK targets before FK sources)
for model in result.topological_order():
    print(model.__name__)

# Iteration and membership
for instance in result:
    print(instance)

if article in result:
    print("Article was visited")

# Merge two results
combined = result_a | result_b
```

Properties:
- `instance_count` -- total number of collected instances
- `model_count` -- number of distinct model types collected

## Actions

### Export

The `Export` class serializes walk results to JSON fixtures or copies them to another database.

```python
from django_graph_walker.actions.export import Export

result = GraphWalker(spec).walk(article)
```

**JSON fixture string**:

```python
json_str = Export(format="json").to_fixture(result)
```

**Write to file**:

```python
Export(format="json").to_file(result, "dev_data.json")
```

**Copy to another database** with automatic PK and FK remapping:

```python
instance_map = Export().to_database(result, target_db="staging")
# instance_map: {(OriginalModel, old_pk): new_instance, ...}
```

**With anonymization** -- reference fields as `"ModelName.field_name"`:

```python
export = Export(
    anonymizers={
        "Author.email": "email",               # faker provider
        "Author.name": lambda inst, ctx: "Anon",  # callable
    },
)
export.to_file(result, "anonymized.json")
```

Additional options:
- `use_natural_keys=True` -- use Django's natural key serialization

### Visualize

The `Visualize` class generates Graphviz DOT output for schema-level and instance-level graphs.

```python
from django_graph_walker.actions.visualize import Visualize

spec = GraphSpec(Author, Article, Category, Tag)
viz = Visualize(show_field_names=True)
```

**Schema-level** -- shows models and their relationships (no database queries):

```python
dot_string = viz.schema(spec)
print(dot_string)  # valid DOT/Graphviz source
```

**Instance-level** -- shows actual instances and connections from a walk result:

```python
result = GraphWalker(spec).walk(article)
dot_string = viz.instances(result)
```

**Graphviz objects** -- requires the `graphviz` package (`pip install django-graph-walker[viz]`):

```python
graph = viz.schema_to_graphviz(spec)
graph.render("schema", format="png")

graph = viz.instances_to_graphviz(result)
graph.render("instances", format="svg")
```

## Examples

See [`examples/bookstore/`](examples/bookstore/) for a working example project that demonstrates walking a bookstore data model, exporting to JSON fixtures, and generating interactive graph visualizations.

## Acknowledgements

This project was inspired by an internal clone tool built by [@MattFisher](https://github.com/MattFisher) at [Edrolo](https://edrolo.com.au), which pioneered the idea of spec-driven Django model graph traversal.

## License

MIT
