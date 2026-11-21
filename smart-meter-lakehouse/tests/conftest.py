from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from smart_meter_lakehouse.config import PipelineConfig
from smart_meter_lakehouse.datagen import generate_landing
from smart_meter_lakehouse.warehouse import connect


@pytest.fixture(scope="session")
def landing(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("landing")
    generate_landing(path, meters=40, days=20, seed=11)  # spans the 1 Oct schema change
    return path


@pytest.fixture
def cfg(landing: Path, tmp_path: Path) -> PipelineConfig:
    return replace(
        PipelineConfig(),
        landing_dir=landing,
        warehouse_path=tmp_path / "wh.duckdb",
        reports_dir=tmp_path / "reports",
        retry_backoff_s=0.0,
    )


@pytest.fixture
def con(cfg: PipelineConfig):
    c = connect(cfg.warehouse_path)
    yield c
    c.close()


def q(con, sql: str, params=None):
    return con.execute(sql, params or []).fetchall()
