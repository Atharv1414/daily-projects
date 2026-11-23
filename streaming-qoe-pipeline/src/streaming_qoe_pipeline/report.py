"""Analytical queries over the sink and the charts used in the README."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .generator import INCIDENT_END, INCIDENT_START  # noqa: E402
from .sink import DuckDBSink  # noqa: E402

PALETTE = {"cdn_a": "#2a6fdb", "cdn_b": "#e0533d", "cdn_c": "#2f9e6e", "unknown": "#9aa0a6"}

INCIDENTS_SQL = """
-- Gaps-and-islands: consecutive alerting 5-minute windows (1-minute slide) form one incident.
WITH a AS (
    SELECT *, window_start - 60000 * row_number() OVER (
        PARTITION BY cdn, region ORDER BY window_start) AS island
    FROM alerts
)
SELECT cdn, region,
       epoch_ms(min(window_start)) AS first_window,
       epoch_ms(max(window_end))   AS last_window_end,
       count(*)                    AS alert_windows,
       round(max(rebuffer_ratio) * 100, 2) AS peak_rebuffer_pct,
       round(avg(baseline_ratio) * 100, 2) AS baseline_pct,
       round(max(z_score), 1)      AS peak_z
FROM a GROUP BY cdn, region, island ORDER BY first_window
"""

CDN_SQL = """
SELECT cdn,
       count(*)                                              AS sessions,
       round(100 * avg(exit_before_start::INT), 2)           AS ebvs_pct,
       round(median(startup_ms) FILTER (WHERE started), 0)   AS median_vst_ms,
       round(100 * sum(rebuffer_ms) / nullif(sum(watch_ms + rebuffer_ms), 0), 3) AS rebuffer_pct,
       round(sum(watch_ms) / 3.6e6, 0)                       AS watch_hours,
       round(sum(avg_bitrate_kbps * watch_ms) / nullif(sum(watch_ms), 0), 0) AS avg_kbps
FROM sessions GROUP BY cdn ORDER BY sessions DESC
"""

DEVICE_SQL = """
SELECT device,
       count(*) AS sessions,
       round(quantile_cont(startup_ms, 0.5) FILTER (WHERE started), 0)  AS p50_vst_ms,
       round(quantile_cont(startup_ms, 0.95) FILTER (WHERE started), 0) AS p95_vst_ms,
       round(100 * avg(exit_before_start::INT), 2) AS ebvs_pct,
       round(100 * avg((end_reason = 'fatal_error')::INT), 3) AS fatal_pct
FROM sessions GROUP BY device ORDER BY sessions DESC
"""

QUALITY_SQL = """
SELECT 'dead letter: ' || reason AS item, count(*) AS records FROM dead_letters GROUP BY reason
UNION ALL
SELECT 'late (' || operator || ')', count(*) FROM late_events GROUP BY operator
ORDER BY records DESC
"""


def incidents(sink: DuckDBSink) -> pd.DataFrame:
    return sink.query(INCIDENTS_SQL)


def tables(sink: DuckDBSink) -> dict[str, pd.DataFrame]:
    return {
        "incidents": incidents(sink),
        "cdn": sink.query(CDN_SQL),
        "device": sink.query(DEVICE_SQL),
        "quality": sink.query(QUALITY_SQL),
    }


def _ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, unit="ms", utc=True)


def _shade_incident(ax: plt.Axes) -> None:
    ax.axvspan(INCIDENT_START, INCIDENT_END, color="#e0533d", alpha=0.08, lw=0)


def chart_rebuffer_by_cdn(sink: DuckDBSink, out: Path) -> Path:
    df = sink.query(
        """SELECT window_start, cdn, sum(rebuffer_ms) / nullif(sum(watch_ms + rebuffer_ms), 0) AS r
           FROM qoe_minute WHERE cdn <> 'unknown' AND region = 'North West'
           GROUP BY ALL ORDER BY window_start"""
    )
    fig, ax = plt.subplots(figsize=(10, 4.2))
    for cdn, g in df.groupby("cdn"):
        smooth = g["r"].rolling(3, min_periods=1).mean() * 100
        ax.plot(_ts(g["window_start"]), smooth, label=cdn, color=PALETTE[cdn], lw=1.6)
    alerts = sink.query("SELECT window_end, rebuffer_ratio FROM alerts WHERE region='North West'")
    if not alerts.empty:
        ax.scatter(
            _ts(alerts["window_end"]),
            alerts["rebuffer_ratio"] * 100,
            marker="v",
            color="#7a1f12",
            s=22,
            zorder=5,
            label="alert (5-min window end)",
        )
    _shade_incident(ax)
    ax.set_title("North West rebuffering ratio by CDN (1-min windows, 3-min smoothing)")
    ax.set_ylabel("rebuffering ratio (%)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.legend(frameon=False, ncol=2, loc="upper left")
    ax.grid(alpha=0.25)
    return _save(fig, out / "rebuffer_north_west.png")


def chart_concurrency(sink: DuckDBSink, out: Path) -> Path:
    df = sink.query(
        """SELECT window_start, sum(active_sessions) AS viewers, sum(watch_ms) / 60000 AS minutes
           FROM qoe_minute GROUP BY ALL ORDER BY window_start"""
    )
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.fill_between(_ts(df["window_start"]), df["viewers"], color="#2a6fdb", alpha=0.25)
    ax.plot(_ts(df["window_start"]), df["viewers"], color="#2a6fdb", lw=1.4)
    ax.set_title("Concurrent viewers per minute (distinct sessions sending heartbeats)")
    ax.set_ylabel("sessions")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(alpha=0.25)
    return _save(fig, out / "concurrency.png")


def chart_vst_by_device(sink: DuckDBSink, out: Path) -> Path:
    df = sink.query("SELECT device, startup_ms FROM sessions WHERE started")
    order = df.groupby("device")["startup_ms"].median().sort_values().index.tolist()
    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.boxplot(
        [df.loc[df.device == d, "startup_ms"] / 1000 for d in order],
        tick_labels=order,
        showfliers=False,
        patch_artist=True,
        boxprops={"facecolor": "#dce8fb", "edgecolor": "#2a6fdb"},
        medianprops={"color": "#e0533d"},
    )
    ax.set_title("Video start time by device (whiskers 1.5×IQR, outliers hidden)")
    ax.set_ylabel("seconds to first frame")
    ax.grid(axis="y", alpha=0.25)
    return _save(fig, out / "vst_by_device.png")


def chart_delay_profile(delays: dict[str, int], lateness_s: float, out: Path) -> Path:
    order = ["<= 1s", "<= 5s", "<= 30s", "<= 90s", "<= 300s", "<= 1800s", "> 1800s"]
    values = [delays.get(k, 0) for k in order]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    bars = ax.bar(order, values, color="#2a6fdb")
    for b, v in zip(bars, values, strict=True):
        ax.annotate(
            f"{v:,}", (b.get_x() + b.get_width() / 2, v), ha="center", va="bottom", fontsize=8
        )
    ax.set_yscale("log")
    ax.set_title(f"Arrival delay (arrival − event time); allowed lateness = {lateness_s:.0f}s")
    ax.set_ylabel("events (log scale)")
    ax.grid(axis="y", alpha=0.25)
    return _save(fig, out / "delay_profile.png")


def chart_benchmark(rows: list[dict[str, float]], out: Path) -> Path:
    df = pd.DataFrame(rows)
    fig, ax1 = plt.subplots(figsize=(7, 3.6))
    ax1.bar(df["checkpoint_every"].astype(str), df["records_per_s"], color="#2a6fdb")
    ax1.set_xlabel("checkpoint every N polls")
    ax1.set_ylabel("records / s", color="#2a6fdb")
    ax2 = ax1.twinx()
    ax2.plot(
        df["checkpoint_every"].astype(str), df["avg_checkpoint_ms"], color="#e0533d", marker="o"
    )
    ax2.set_ylabel("avg checkpoint (ms)", color="#e0533d")
    ax1.set_title("Throughput vs checkpoint interval")
    return _save(fig, out / "checkpoint_benchmark.png")


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path
