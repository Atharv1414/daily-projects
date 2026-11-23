from hypothesis import given
from hypothesis import strategies as st

from streaming_qoe_pipeline.windows import POS_INF, WatermarkTracker, Window, hopping, tumbling


def test_tumbling_boundaries_are_half_open() -> None:
    assert tumbling(60_000, 60_000) == [Window(60_000, 120_000)]
    assert tumbling(119_999, 60_000) == [Window(60_000, 120_000)]
    assert tumbling(-1, 60_000) == [Window(-60_000, 0)]


@given(ts=st.integers(-(10**12), 10**13), slide_min=st.integers(1, 10), factor=st.integers(1, 6))
def test_hopping_assigns_every_containing_window_exactly_once(
    ts: int, slide_min: int, factor: int
) -> None:
    slide = slide_min * 60_000
    size = slide * factor
    windows = hopping(ts, size, slide)
    assert len(windows) == factor
    assert len(set(windows)) == factor
    assert all(w.contains(ts) and w.end - w.start == size for w in windows)
    assert all(w.start % slide == 0 for w in windows)


@given(ts=st.integers(-(10**12), 10**13), size=st.integers(1, 10**7))
def test_tumbling_window_always_contains_ts(ts: int, size: int) -> None:
    (w,) = tumbling(ts, size)
    assert w.contains(ts)


def test_global_watermark_is_min_across_partitions_and_never_regresses() -> None:
    wm = WatermarkTracker(partitions=2, max_out_of_orderness_ms=5_000)
    wm.observe(0, 100_000)
    assert wm.advance() < 0  # partition 1 has seen nothing yet
    wm.observe(1, 50_000)
    assert wm.advance() == 45_000
    wm.observe(1, 10_000)  # an out-of-order event must not move it back
    assert wm.advance() == 45_000


def test_idle_partition_stops_holding_watermark_back() -> None:
    wm = WatermarkTracker(partitions=2, max_out_of_orderness_ms=0)
    wm.observe(0, 1_000)
    wm.mark_idle(1)
    assert wm.advance() == 1_000
    assert wm.finish() == POS_INF


def test_watermark_snapshot_round_trip() -> None:
    a = WatermarkTracker(3, 1_000)
    for p, ts in [(0, 5_000), (1, 7_000), (2, 9_000)]:
        a.observe(p, ts)
    a.advance()
    b = WatermarkTracker(3, 1_000)
    b.restore(a.snapshot())
    assert b.current == a.current == 4_000
