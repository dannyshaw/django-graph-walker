"""Django app configuration for django-graph-walker."""

from django.apps import AppConfig


class GraphWalkerConfig(AppConfig):
    name = "django_graph_walker"
    verbose_name = "Django Graph Walker"
    default_auto_field = "django.db.models.BigAutoField"
