from streaming_qoe_pipeline.alerts import RebufferAlertDetector


def window(i: int, ratio: float, watch: int = 3_600_000, cdn: str = "cdn_b") -> dict[str, object]:
    rebuffer = int(watch * ratio)
    return {
        "window_start": i * 60_000,
        "window_end": i * 60_000 + 300_000,
        "cdn": cdn,
        "region": "North West",
        "watch_ms": watch - rebuffer,
        "rebuffer_ms": rebuffer,
        "rebuffer_ratio": rebuffer / watch,
    }


def detector() -> RebufferAlertDetector:
    return RebufferAlertDetector(
        z_threshold=4, min_ratio=0.02, min_watch_ms=1_800_000, warmup=10, alpha=0.05
    )


def test_spike_after_warmup_alerts() -> None:
    d = detector()
    assert all(d.observe(window(i, 0.001 + (i % 3) * 0.0005)) is None for i in range(20))
    alert = d.observe(window(20, 0.04))
    assert alert is not None and alert["severity"] == "critical" and alert["z_score"] > 8


def test_no_alert_during_warmup_even_for_high_ratio() -> None:
    d = detector()
    assert d.observe(window(0, 0.001)) is None
    assert d.observe(window(1, 0.05)) is None


def test_slow_ramp_does_not_poison_baseline() -> None:
    d = detector()
    for i in range(20):
        d.observe(window(i, 0.001))
    ramp = [0.004, 0.008, 0.012, 0.018, 0.025, 0.03]
    alerts = [d.observe(window(20 + j, r)) for j, r in enumerate(ramp)]
    assert alerts[-1] is not None and alerts[-2] is not None
    assert d.snapshot()["cdn_b|North West"][0] < 0.002  # baseline mean stayed near 0.1%


def test_low_volume_and_unknown_cdn_are_ignored() -> None:
    d = detector()
    for i in range(20):
        d.observe(window(i, 0.001))
    assert d.observe(window(20, 0.2, watch=600_000)) is None
    assert d.observe(window(21, 0.2, cdn="unknown")) is None
