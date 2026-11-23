import json

import pytest

from streaming_qoe_pipeline.events import DeadLetter, EventType, PlayerEvent, parse_record

from .conftest import v2_raw


def test_v2_record_parses_with_epoch_ms_timestamp() -> None:
    event = parse_record(v2_raw(), 0, 0)
    assert isinstance(event, PlayerEvent)
    assert event.ts == 1_795_292_100_000
    assert event.cdn == "cdn_c" and event.schema_version == 2


def test_v1_record_is_upcast_with_unknown_cdn() -> None:
    raw = json.dumps(
        {
            "v": 1,
            "id": "abcdef0123456789",
            "type": "heartbeat",
            "sid": "s-legacy",
            "uid": "v-9",
            "t": "2026-11-21T20:15:00Z",
            "dev": "console",
            "region": "Wales",
            "pl_ms": 30_000,
            "br": 1_500,
        }
    )
    event = parse_record(raw, 1, 7)
    assert isinstance(event, PlayerEvent)
    assert (event.schema_version, event.cdn, event.bitrate_kbps) == (1, "unknown", 1_500)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ('{"schema_version": 2, "event_id": ', "invalid_json"),
        ("[1, 2, 3]", "not_an_object"),
        (v2_raw(schema_version=3), "unknown_schema_version"),
        (v2_raw(event_time="21/11/2026 20:15"), "bad_timestamp"),
        (v2_raw(event_type="ad_impression"), "schema_violation"),
        (v2_raw(session_id=None), "schema_violation"),
        (v2_raw(event_type="rebuffer_end", duration_ms=-250), "schema_violation"),
        (v2_raw(play_ms=None), "schema_violation"),
    ],
)
def test_bad_records_become_dead_letters(raw: str, reason: str) -> None:
    result = parse_record(raw, 2, 42)
    assert isinstance(result, DeadLetter)
    assert (result.reason, result.partition, result.offset) == (reason, 2, 42)
    assert result.raw == raw[:2000]


def test_unknown_region_is_normalised_not_rejected() -> None:
    event = parse_record(v2_raw(region="Atlantis"), 0, 0)
    assert isinstance(event, PlayerEvent) and event.region == "unknown"


def test_event_type_payload_contract() -> None:
    with pytest.raises(ValueError, match="play_start requires startup_ms"):
        PlayerEvent(
            event_id="e" * 8,
            event_type=EventType.PLAY_START,
            session_id="s-01",
            viewer_id="v",
            ts=0,
            device="ios",
        )
