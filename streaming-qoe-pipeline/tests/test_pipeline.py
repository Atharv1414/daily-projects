from dataclasses import replace

import pytest

from streaming_qoe_pipeline.config import Settings
from streaming_qoe_pipeline.errors import SimulatedCrash
from streaming_qoe_pipeline.log import PartitionedLog
from streaming_qoe_pipeline.pipeline import StreamProcessor
from streaming_qoe_pipeline.sink import DuckDBSink

TABLES = ["qoe_minute", "qoe_cdn_region_5m", "sessions", "late_events", "dead_letters", "alerts"]


def run_to_end(settings: Settings, log: PartitionedLog, path: str) -> DuckDBSink:
    sink = DuckDBSink(path)
    StreamProcessor(settings, log, sink).run()
    return sink


def snapshot(sink: DuckDBSink) -> dict[str, list[tuple]]:
    return {t: sink.table_snapshot(t) for t in TABLES}


def test_end_to_end_counts_reconcile(
    settings: Settings, small_log: PartitionedLog, tmp_path
) -> None:
    sink = DuckDBSink(tmp_path / "e2e.duckdb")
    result = StreamProcessor(settings, small_log, sink).run()
    st = result.stats
    assert result.finished
    assert st["records_read"] == sum(small_log.end_offsets().values())
    assert (
        st["records_read"] == st["events_processed"] + st["duplicates_dropped"] + st["dead_letters"]
    )
    assert st["open_windows"] == st["open_sessions"] == st["dedup_ids"] == 0
    dl = sink.query("SELECT count(*) AS n FROM dead_letters")["n"][0]
    assert dl == st["dead_letters"] > 0
    sessions = sink.query("SELECT count(*) AS n FROM sessions")["n"][0]
    assert 240 <= sessions <= 260  # late stragglers may re-open a handful


def test_watch_time_in_windows_matches_sessions(
    settings: Settings, small_log: PartitionedLog, tmp_path
) -> None:
    sink = run_to_end(settings, small_log, str(tmp_path / "rec.duckdb"))
    window_watch = sink.query("SELECT sum(watch_ms) AS w FROM qoe_minute")["w"][0]
    session_watch = sink.query("SELECT sum(watch_ms) AS w FROM sessions")["w"][0]
    late = sink.query("SELECT count(*) AS n FROM late_events WHERE event_type = 'heartbeat'")["n"][
        0
    ]
    # Every on-time heartbeat lands in exactly one minute window and one session; the only
    # difference is late data, which each operator judges against its own deadline.
    assert abs(window_watch - session_watch) <= late * 30_000


@pytest.mark.parametrize("crash_after", [1, 3, 6])
def test_crash_and_resume_is_exactly_once(
    settings: Settings, small_log: PartitionedLog, tmp_path, crash_after: int
) -> None:
    reference = snapshot(run_to_end(settings, small_log, str(tmp_path / "ref.duckdb")))

    path = str(tmp_path / f"crash{crash_after}.duckdb")
    sink = DuckDBSink(path)
    with pytest.raises(SimulatedCrash):
        StreamProcessor(settings, small_log, sink, crash_after_polls=crash_after).run()
    sink.close()  # the process "dies": in-memory state and uncommitted outputs are gone

    resumed = DuckDBSink(path)
    result = StreamProcessor(settings, small_log, resumed).run()
    assert result.finished
    assert snapshot(resumed) == reference


def test_rerun_after_completion_is_a_no_op(
    settings: Settings, small_log: PartitionedLog, tmp_path
) -> None:
    path = str(tmp_path / "noop.duckdb")
    sink = run_to_end(settings, small_log, path)
    before = snapshot(sink)
    result = StreamProcessor(settings, small_log, sink).run()
    assert result.stats["records_read"] == 0
    assert snapshot(sink) == before


def test_paused_run_resumes_from_committed_offsets(
    settings: Settings, small_log: PartitionedLog, tmp_path
) -> None:
    sink = DuckDBSink(tmp_path / "pause.duckdb")
    first = StreamProcessor(settings, small_log, sink).run(drain=False, max_polls=3)
    assert not first.finished
    offsets = sink.query("SELECT sum(next_offset) AS n FROM consumer_offsets")["n"][0]
    assert offsets == first.stats["records_read"]
    second = StreamProcessor(settings, small_log, sink).run()
    assert first.stats["records_read"] + second.stats["records_read"] == sum(
        small_log.end_offsets().values()
    )


def test_future_clocks_are_quarantined_not_watermarked(
    settings: Settings, small_log, tmp_path
) -> None:
    sink = run_to_end(settings, small_log, str(tmp_path / "fut.duckdb"))
    future = sink.query("SELECT count(*) AS n FROM dead_letters WHERE reason='future_timestamp'")
    assert future["n"][0] >= 1
    # If a +2 day clock had moved the watermark, nearly everything after it would be late.
    late_share = sink.query("SELECT count(*) AS n FROM late_events")["n"][0] / 7_000
    assert late_share < 0.05


def test_injected_cdn_incident_is_detected(medium_log: PartitionedLog, tmp_path) -> None:
    settings = replace(Settings(), poll_records_per_partition=5_000, checkpoint_every_polls=10)
    sink = run_to_end(settings, medium_log, str(tmp_path / "inc.duckdb"))
    alerts = sink.query("SELECT DISTINCT cdn, region FROM alerts")
    assert alerts.to_dict("records") == [{"cdn": "cdn_b", "region": "North West"}]
    window = sink.query("SELECT min(window_start) AS s, max(window_end) AS e FROM alerts").iloc[0]
    # Incident ran 20:40-21:00 UTC; alerts must fall around it.
    assert 1_795_293_000_000 <= window["s"] <= 1_795_294_200_000
    assert window["e"] <= 1_795_294_800_000 + 300_000
