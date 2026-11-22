from __future__ import annotations

import pytest

from grocery_retail_bi.models import MODELS, CycleError, Model, ordered


def test_order_respects_dependencies():
    names = [m.name for m in ordered()]
    for m in MODELS:
        for dep in m.depends_on:
            if dep in names:
                assert names.index(dep) < names.index(m.name)


def test_cycle_detected():
    a = Model("a", "view", "", "SELECT 1", ["b"])
    b = Model("b", "view", "", "SELECT 1", ["a"])
    with pytest.raises(CycleError):
        ordered([a, b])


def test_every_model_is_documented():
    for m in MODELS:
        assert len(m.description) > 20 and m.grain
