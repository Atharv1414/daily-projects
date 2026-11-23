from streaming_qoe_pipeline.metrics import QoEAccumulator
from streaming_qoe_pipeline.operators import Deduplicator, SessionWindowOperator, WindowAggregator
from streaming_qoe_pipeline.windows import hopping, tumbling

from .conftest import T0, make_event

MIN = 60_000


def minute_agg(lateness: int = 30_000) -> WindowAggregator:
    return WindowAggregator(
        "m",
        lambda ts: tumbling(ts, MIN),
        lambda e: (e.cdn,),
        ("cdn",),
        lateness,
        track_sessions=True,
    )


def test_dedup_drops_retries_and_evicts_old_ids() -> None:
    d = Deduplicator(horizon_ms=10_000)
    e = make_event(ts=T0)
    assert not d.is_duplicate(e)
    assert d.is_duplicate(e)
    assert d.evict(T0 + 5_000) == 0
    assert d.evict(T0 + 10_001) == 1 and len(d) == 0


def test_window_fires_only_after_end_plus_allowed_lateness() -> None:
    agg = minute_agg(lateness=30_000)
    agg.process(make_event(ts=T0 + 1_000), watermark=T0)
    assert agg.fire(T0 + MIN + 29_999) == []
    (row,) = agg.fire(T0 + MIN + 30_000)
    assert (row["window_start"], row["cdn"], row["watch_ms"], row["active_sessions"]) == (
        T0,
        "cdn_a",
        30_000,
        1,
    )


def test_event_within_lateness_updates_window_but_after_firing_goes_to_side_output() -> None:
    agg = minute_agg(lateness=30_000)
    agg.process(make_event(ts=T0 + 1_000, event_id="on-time-1"), watermark=T0)
    assert agg.process(make_event(ts=T0 + 2_000, event_id="late-ok-1"), T0 + MIN + 10_000) is None
    (row,) = agg.fire(T0 + MIN + 30_000)
    assert row["events"] == 2
    late = agg.process(make_event(ts=T0 + 3_000, event_id="too-late-1"), T0 + MIN + 30_000)
    assert late is not None and late.windows_dropped == 1 and late.operator == "m"
    assert agg.open_windows == 0


def test_hopping_late_event_still_counts_in_newer_windows() -> None:
    agg = WindowAggregator(
        "h", lambda ts: hopping(ts, 5 * MIN, MIN), lambda e: (e.cdn,), ("cdn",), 0
    )
    # Watermark has passed the end of the oldest window containing T0 + 4 min only.
    late = agg.process(make_event(ts=T0 + 4 * MIN), watermark=T0 + 5 * MIN)
    assert late is not None and late.windows_dropped == 1
    assert agg.open_windows == 4


def test_rebuffer_ratio_and_time_weighted_bitrate() -> None:
    acc = QoEAccumulator()
    acc.add(make_event("heartbeat", play_ms=30_000, bitrate_kbps=8_000, event_id="hb-0000001"))
    acc.add(make_event("heartbeat", play_ms=10_000, bitrate_kbps=800, event_id="hb-0000002"))
    acc.add(make_event("rebuffer_end", duration_ms=10_000, event_id="rb-0000001"))
    acc.add(make_event("play_start", startup_ms=2_000, event_id="ps-0000001"))
    assert acc.rebuffer_ratio == 10_000 / 50_000
    assert acc.avg_bitrate_kbps == (30_000 * 8_000 + 10_000 * 800) / 40_000
    assert acc.avg_startup_ms == 2_000


def test_session_closes_after_gap_and_flags_exit_before_start() -> None:
    op = SessionWindowOperator(gap_ms=120_000)
    op.process(make_event("play_attempt", ts=T0, event_id="att-000001"), watermark=T0)
    op.process(make_event("play_end", ts=T0 + 4_000, event_id="end-000001"), watermark=T0)
    assert op.fire(T0 + 100_000) == []
    (row,) = op.fire(T0 + 124_000)
    assert row["exit_before_start"] is True and row["end_reason"] == "abandoned"
    late = op.process(make_event("heartbeat", ts=T0 + 5_000, event_id="hb-late-01"), T0 + 200_000)
    assert late is not None and late.operator == "sessions"


def test_operator_snapshots_round_trip_to_identical_output() -> None:
    a = minute_agg()
    for i in range(20):
        a.process(
            make_event(
                ts=T0 + i * 7_000,
                event_id=f"evt-{i:05d}",
                session_id=f"s-{i % 3:04d}",
                cdn="cdn_b" if i % 2 else "cdn_a",
            ),
            watermark=T0,
        )
    b = minute_agg()
    b.restore(a.snapshot())
    assert a.fire(T0 + 10 * MIN) == b.fire(T0 + 10 * MIN)
