from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from streaming_qoe_pipeline.config import Settings
from streaming_qoe_pipeline.events import PlayerEvent
from streaming_qoe_pipeline.generator import generate
from streaming_qoe_pipeline.log import PartitionedLog

T0 = 1_795_287_600_000  # 2026-11-21 19:00:00 UTC


def make_event(event_type: str = "heartbeat", ts: int = T0, **kw: object) -> PlayerEvent:
    base: dict[str, object] = {
        "event_id": kw.pop("event_id", f"evt-{event_type}-{ts}"),
        "event_type": event_type,
        "session_id": kw.pop("session_id", "s-0001"),
        "viewer_id": "v-1",
        "ts": ts,
        "device": kw.pop("device", "smart_tv"),
        "cdn": kw.pop("cdn", "cdn_a"),
        "region": kw.pop("region", "London"),
    }
    defaults = {
        "heartbeat": {"play_ms": 30_000, "bitrate_kbps": 5_000},
        "play_start": {"startup_ms": 1_500},
        "rebuffer_end": {"duration_ms": 2_000},
        "error": {"error_code": "X"},
        "bitrate_switch": {"bitrate_kbps": 3_000},
    }.get(event_type, {})
    return PlayerEvent.model_validate({**base, **defaults, **kw})


def v2_raw(**overrides: object) -> str:
    doc = {
        "schema_version": 2,
        "event_id": "0123456789abcdef",
        "event_type": "heartbeat",
        "session_id": "s-abcdef",
        "viewer_id": "v-000001",
        "event_time": "2026-11-21T20:15:00.000+00:00",
        "device": "web",
        "cdn": "cdn_c",
        "isp": "BT",
        "region": "Scotland",
        "content_id": "title-0001",
        "play_ms": 29_000,
        "bitrate_kbps": 3_000,
    }
    doc.update(overrides)
    return json.dumps({k: v for k, v in doc.items() if v is not None})


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        log_dir=tmp_path / "log",
        warehouse_path=tmp_path / "wh.duckdb",
        segment_size=500,
        poll_records_per_partition=300,
        checkpoint_every_polls=2,
    )


@pytest.fixture(scope="session")
def small_log(tmp_path_factory: pytest.TempPathFactory) -> PartitionedLog:
    """~250 sessions (~7k records): fast enough for crash/resume parametrisation."""
    log = PartitionedLog(tmp_path_factory.mktemp("small") / "log", 4, segment_size=500)
    generate(log, sessions=250, seed=11)
    return log


@pytest.fixture(scope="session")
def medium_log(tmp_path_factory: pytest.TempPathFactory) -> PartitionedLog:
    """Enough traffic for the North West incident to clear the alert volume threshold."""
    log = PartitionedLog(tmp_path_factory.mktemp("medium") / "log", 4, segment_size=5_000)
    generate(log, sessions=6_000, seed=7)
    return log


@pytest.fixture
def event_factory() -> Callable[..., PlayerEvent]:
    return make_event
