from __future__ import annotations

import duckdb
import pytest

from law_firm_profitability_bi import datagen, warehouse
from law_firm_profitability_bi.metrics import Metrics
from law_firm_profitability_bi.security import USERS

SMALL = datagen.GenConfig(entries=20_000, matters=300, clients=60, timekeepers=80)


@pytest.fixture(scope="session")
def sources():
    return datagen.generate(SMALL)


@pytest.fixture(scope="session")
def con(sources):
    connection = duckdb.connect()
    warehouse.build(connection, sources)
    return connection


@pytest.fixture
def firm(con):
    return Metrics(con, USERS["mp"])
