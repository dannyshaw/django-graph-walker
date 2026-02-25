# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

django-graph-walker walks Django model relationship graphs for cloning, subsetting, export, and visualization. Given a set of root model instances and a `GraphSpec` defining which models are in scope, `GraphWalker` performs BFS traversal across relationships, collecting all reachable instances into a `WalkResult`.

## Commands

```bash
# Run all tests (uses pytest with pytest-django, in-memory SQLite)
uv run pytest

# Run a single test file
uv run pytest tests/test_walker.py

# Run a single test by name
uv run pytest tests/test_walker.py -k "test_walk_follows_fk_to_in_scope"

# Lint
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Install dev dependencies
uv sync --extra dev
```

## Architecture

### Core pipeline: GraphSpec → GraphWalker → WalkResult → Action

1. **`spec.py` — GraphSpec and field overrides**: `GraphSpec` declares which Django models are "in scope" for a walk and per-field overrides (`Follow`, `Ignore`, `Override`, `KeepOriginal`, `Anonymize`). Specs compose with `|` (union, later overrides win).

2. **`discovery.py` — Field classification**: Introspects `model._meta.get_fields()` and classifies each field into a `FieldClass` enum (e.g. `FK_IN_SCOPE`, `REVERSE_M2M_OUT_OF_SCOPE`). The in-scope/out-of-scope distinction is central — it determines which edges are traversable. Handles FK, M2M, O2O, reverse relations, and GenericRelation.

3. **`walker.py` — GraphWalker (BFS engine)**: Level-order BFS with batch prefetching. Each BFS level drains the queue into model-grouped batches, calls `prefetch_related_objects()` per batch, then resolves edges. All in-scope edge types are followed by default; use `Ignore()` to opt out. `Follow(filter=..., prefetch=..., limit=...)` provides per-edge control.

4. **`result.py` — WalkResult**: Container for visited instances keyed by `(model_class, pk)`. Provides `by_model()`, `instances_of()`, `topological_order()` (Kahn's algorithm for dependency-ordered insertion). Results compose with `|`.

5. **Actions** (`actions/`):
   - `visualize.py` — Generates Graphviz DOT strings for schema-level or instance-level graphs
   - `export.py` — Serializes to JSON fixtures (`to_fixture`, `to_file`) or copies to another database (`to_database`) with FK remapping and optional anonymization

### Key design decisions

- **All in-scope edges followed by default**: Unlike graph traversal libraries that require explicit edge selection, the walker follows every edge where both endpoints are in the spec. Use `Ignore()` to suppress specific edges.
- **Batch prefetching**: Queries are O(edge types per BFS level), not O(instances). The walker groups instances by model and calls `prefetch_related_objects()` once per batch.
- **In-scope vs out-of-scope**: `discovery.py` classifies every field relative to the spec's model set. Out-of-scope edges are never traversed regardless of overrides.

### Test setup

Tests use `tests/testapp/models.py` which covers: FK tree (self-referential Category), M2M (Article↔Tag), O2O (Article→ArticleStats), reverse FK, nullable FK, GenericFK (Comment), and multi-table inheritance (PremiumArticle). Django settings are in `tests/settings.py` (in-memory SQLite with a `secondary` database for cross-DB export tests). Fixtures are in `tests/conftest.py`.

## Style

- Ruff with `line-length = 99`, `target-version = "py310"`, rules: E, F, I, W
- Python 3.10+ (uses `type[Model]` syntax, `|` union in type hints)
