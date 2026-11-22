from __future__ import annotations

from datetime import datetime

import pytest

from grocery_retail_bi.datagen import GenConfig, generate
from grocery_retail_bi.warehouse import build


@pytest.fixture(scope="session")
def raw_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("raw")
    generate(GenConfig(out_dir=out, n_baskets=6_000))
    return out


@pytest.fixture(scope="session")
def built(raw_dir):
    conn, stats = build(raw_dir, ":memory:", [datetime(2026, 3, 31), datetime(2026, 8, 31)])
    yield conn, stats
    conn.close()


@pytest.fixture(scope="session")
def conn(built):
    return built[0]
