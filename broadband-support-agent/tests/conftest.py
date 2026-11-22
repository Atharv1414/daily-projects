from __future__ import annotations

import pytest

from broadband_support_agent.approval import ScriptedApproval
from broadband_support_agent.config import Settings
from broadband_support_agent.database import Repository
from broadband_support_agent.datagen import memory_database
from broadband_support_agent.state import SessionState
from broadband_support_agent.tools import ToolContext
from broadband_support_agent.tracing import Tracer


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def conn(settings):
    c = memory_database(settings.now, n_customers=200)
    yield c
    c.close()


@pytest.fixture
def repo(conn) -> Repository:
    return Repository(conn)


@pytest.fixture
def make_ctx(repo, settings):
    def build(verified: str | None = None, approvals: list[bool] | None = None) -> ToolContext:
        state = SessionState("test", verified_account=verified)
        return ToolContext(
            repo,
            settings,
            state,
            ScriptedApproval(list(approvals or [])),
            Tracer(settings.price("scripted")),
        )

    return build
