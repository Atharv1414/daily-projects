from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from hotel_revenue_agent.config import Settings
from hotel_revenue_agent.database import Warehouse
from hotel_revenue_agent.datagen import generate
from hotel_revenue_agent.tools import ToolRegistry, build_tools


@pytest.fixture(scope="session")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("db") / "hotel.db"
    generate(path, bookings=4_000, guests=800, seed=7)
    return path


@pytest.fixture
def settings(db_path: Path, tmp_path: Path) -> Settings:
    return replace(
        Settings(),
        db_path=db_path,
        reports_dir=tmp_path / "reports",
        traces_dir=tmp_path / "traces",
    )


@pytest.fixture
def warehouse(settings: Settings):
    wh = Warehouse(settings.db_path, settings.max_rows, settings.query_timeout_ms)
    yield wh
    wh.close()


@pytest.fixture
def registry(warehouse: Warehouse, settings: Settings) -> ToolRegistry:
    return ToolRegistry(build_tools(warehouse, settings.reports_dir))
