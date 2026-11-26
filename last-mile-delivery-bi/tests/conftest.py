"""Shared fixtures: a small, seeded warehouse built once per test session."""

from __future__ import annotations

import pytest

from last_mile_delivery_bi.data_generator import GeneratorConfig, generate
from last_mile_delivery_bi.warehouse import build_warehouse

SMALL = GeneratorConfig(start="2026-09-01", end="2026-11-14", routes_per_depot=3, seed=7)


@pytest.fixture(scope="session")
def tables():
    return generate(SMALL)


@pytest.fixture(scope="session")
def con():
    connection = build_warehouse(config=SMALL)
    yield connection
    connection.close()
