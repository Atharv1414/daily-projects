from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest

from planning_casework_mcp.agent.mcp_bridge import MCPGateway, memory_gateway
from planning_casework_mcp.datagen import TODAY, build_store
from planning_casework_mcp.store import CaseStore


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def store(tmp_path) -> Iterator[CaseStore]:
    s = build_store(str(tmp_path / "test.db"), n=300, seed=11)
    yield s
    s.close()


@pytest.fixture
async def gateway(store: CaseStore) -> AsyncIterator[MCPGateway]:
    async with memory_gateway(store, TODAY) as gw:
        yield gw
