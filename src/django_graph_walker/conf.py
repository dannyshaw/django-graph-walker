"""Settings for django-graph-walker with sensible defaults."""

from __future__ import annotations

_DEFAULTS = {
    "EXCLUDE_APPS": [
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
        "django.contrib.sites",
        "django.contrib.flatpages",
        "django.contrib.redirects",
        "django.contrib.sitemaps",
        "django.contrib.syndication",
        "django.contrib.humanize",
    ],
}


def get_setting(name: str):
    """Get a django-graph-walker setting, falling back to defaults.

    Reads from django.conf.settings.GRAPH_WALKER dict if available.
    """
    from django.conf import settings

    user_settings = getattr(settings, "GRAPH_WALKER", {})
    if name in user_settings:
        return user_settings[name]
    return _DEFAULTS[name]
