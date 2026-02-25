"""django-graph-walker: Walk Django model relationship graphs."""


def __getattr__(name):
    """Lazy imports to avoid triggering Django model loading during app registry setup."""
    _spec_exports = {"Anonymize", "Follow", "GraphSpec", "Ignore", "KeepOriginal", "Override"}
    _walker_exports = {"GraphWalker"}

    if name in _spec_exports:
        from django_graph_walker import spec

        return getattr(spec, name)

    if name in _walker_exports:
        from django_graph_walker import walker

        return getattr(walker, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "GraphSpec",
    "GraphWalker",
    "Follow",
    "Ignore",
    "Override",
    "KeepOriginal",
    "Anonymize",
]

__version__ = "0.1.0"

default_app_config = "django_graph_walker.apps.GraphWalkerConfig"
