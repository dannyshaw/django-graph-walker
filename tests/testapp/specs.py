"""Specs used by lens command tests."""

from django_graph_walker import GraphSpec, Mask
from tests.testapp.models import Author

author_lens = GraphSpec({Author: {"email": Mask("hash")}})

not_a_spec = "I am not a GraphSpec"
