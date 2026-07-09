"""Tests for the Mask override and the Lens action (view/role DDL + schema context)."""

import pytest

from django_graph_walker import Mask


class TestMaskOverride:
    def test_default_strategy_is_hash(self):
        assert Mask().strategy == "hash"

    def test_accepts_known_strategies(self):
        assert Mask("redact").strategy == "redact"
        assert Mask("null").strategy == "null"

    def test_rejects_unknown_strategy(self):
        with pytest.raises(ValueError, match="Unknown mask strategy"):
            Mask("shred")

    def test_importable_from_top_level(self):
        from django_graph_walker import Mask as TopMask

        assert TopMask is Mask
