"""Synthetic player telemetry for a UK video-on-demand service on a Saturday evening.

The generator produces realistic volume and realistic mess:

* sessions ramp towards a 21:00 peak, with device, CDN, ISP and region mixes skewed like UK traffic
* about a third of Android and console clients still send **schema v1** (terse keys, no CDN)
* network delivery is out of order: most events arrive within a second, some 5-60 s late
  (mobile reconnects) and ~0.5% minutes late (offline buffers flushed on reconnect)
* client retries create duplicates, a small share of records is malformed, and a few
  devices have clocks set days in the future
* an **incident**: ``cdn_b`` in the North West degrades between 20:40 and 21:00 UTC, causing
  more stalls, longer start-up and more abandonment. The pipeline has to find it.
"""

from __future__ import annotations

import json
import math
import random
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .events import REGIONS
from .log import PartitionedLog, partition_for

START = datetime(2026, 11, 21, 19, 0, tzinfo=UTC)
INCIDENT_CDN = "cdn_b"
INCIDENT_REGION = "North West"
INCIDENT_START = START + timedelta(minutes=100)
INCIDENT_END = START + timedelta(minutes=120)

DEVICES = {"smart_tv": 0.38, "ios": 0.20, "android": 0.18, "web": 0.14, "console": 0.10}
STARTUP_MEDIAN_MS = {"smart_tv": 1800, "ios": 1200, "android": 1500, "web": 1400, "console": 2200}
CDN_WEIGHTS = {"cdn_a": 0.45, "cdn_b": 0.35, "cdn_c": 0.20}
ISPS = {
    "BT": 0.30,
    "Sky": 0.22,
    "Virgin Media": 0.20,
    "TalkTalk": 0.10,
    "EE": 0.10,
    "Vodafone": 0.08,
}
REGION_WEIGHTS = dict(
    zip(REGIONS, (0.20, 0.14, 0.08, 0.16, 0.11, 0.04, 0.08, 0.05, 0.08, 0.03), strict=True)
)
LADDER = (800, 1500, 3000, 5000, 8000)
HEARTBEAT_MS = 30_000


@dataclass
class GenerationSummary:
    sessions: int = 0
    events: int = 0
    records: int = 0
    counts: Counter[str] = field(default_factory=Counter)


def _pick(rng: random.Random, weights: dict[str, float]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _in_incident(cdn: str, region: str, t_ms: int) -> bool:
    return (
        cdn == INCIDENT_CDN
        and region == INCIDENT_REGION
        and INCIDENT_START.timestamp() * 1000 <= t_ms < INCIDENT_END.timestamp() * 1000
    )


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat(timespec="milliseconds")


def _delay(rng: random.Random) -> int:
    roll = rng.random()
    if roll < 0.005:
        return rng.randint(180_000, 1_500_000)
    if roll < 0.04:
        return rng.randint(5_000, 60_000)
    return int(rng.lognormvariate(math.log(400), 0.8))


def _session_events(rng: random.Random, t0: int, ctx: dict[str, str]) -> list[tuple[int, dict]]:
    """Return (true_time_ms, payload) pairs for one viewing session."""
    cdn, region, device = ctx["cdn"], ctx["region"], ctx["device"]
    out: list[tuple[int, dict]] = [(t0, {"event_type": "play_attempt"})]
    incident = _in_incident(cdn, region, t0)
    startup = int(rng.lognormvariate(math.log(STARTUP_MEDIAN_MS[device]), 0.45))
    if incident:
        startup = int(startup * rng.uniform(2.5, 4.0))
    startup = min(startup, 60_000)
    ebvs_p = 0.025 + (0.10 if incident else 0.0) + (0.25 if startup > 6_000 else 0.0)
    if rng.random() < ebvs_p:
        out.append(
            (t0 + rng.randint(2_000, min(9_000, startup + 2_000)), {"event_type": "play_end"})
        )
        return out

    t = t0 + startup
    out.append((t, {"event_type": "play_start", "startup_ms": startup}))
    watch_target = min(int(rng.expovariate(1 / 720_000)), 5_400_000) + 30_000
    rung = {"smart_tv": 4, "console": 4, "web": 3, "ios": 3, "android": 2}[device]
    rung = max(0, min(len(LADDER) - 1, rung - (1 if rng.random() < 0.3 else 0)))
    watched = 0
    while watched < watch_target:
        stall = 0
        p_stall = 0.15 if _in_incident(cdn, region, t) else 0.012
        if rng.random() < p_stall:
            median = 4_500 if _in_incident(cdn, region, t) else 1_500
            stall = min(int(rng.lognormvariate(math.log(median), 0.6)), 25_000)
            out.append(
                (
                    t + rng.randint(1_000, 20_000),
                    {"event_type": "rebuffer_end", "duration_ms": stall},
                )
            )
            if rung > 0:
                rung -= 1
                out.append(
                    (
                        t + rng.randint(20_000, 25_000),
                        {"event_type": "bitrate_switch", "bitrate_kbps": LADDER[rung]},
                    )
                )
        elif rung < len(LADDER) - 1 and rng.random() < 0.05:
            rung += 1
            out.append(
                (
                    t + rng.randint(1_000, 25_000),
                    {"event_type": "bitrate_switch", "bitrate_kbps": LADDER[rung]},
                )
            )
        play = max(0, HEARTBEAT_MS - stall)
        t += HEARTBEAT_MS
        watched += play
        out.append(
            (
                t,
                {
                    "event_type": "heartbeat",
                    "play_ms": play,
                    "bitrate_kbps": LADDER[rung],
                    "buffer_ms": rng.randint(2_000, 30_000),
                },
            )
        )
        if rng.random() < 0.0008:
            out.append(
                (
                    t + 500,
                    {
                        "event_type": "error",
                        "error_code": rng.choice(
                            ["DRM_LICENSE_SLOW", "SEGMENT_404", "MANIFEST_TIMEOUT"]
                        ),
                        "fatal": False,
                    },
                )
            )
        if rng.random() < 0.0003 * (8 if _in_incident(cdn, region, t) else 1):
            out.append(
                (t + 800, {"event_type": "error", "error_code": "PLAYBACK_FAILED", "fatal": True})
            )
            return out
    out.append((t + rng.randint(500, 5_000), {"event_type": "play_end"}))
    return out


def _encode(rng: random.Random, ts: int, payload: dict, ctx: dict[str, str], v1: bool) -> str:
    event_id = uuid.UUID(int=rng.getrandbits(128), version=4).hex
    if v1:
        doc = {
            "v": 1,
            "id": event_id,
            "type": payload["event_type"],
            "sid": ctx["session_id"],
            "uid": ctx["viewer_id"],
            "t": _iso(ts),
            "dev": ctx["device"],
            "region": ctx["region"],
            "isp": ctx["isp"],
            "cid": ctx["content_id"],
        }
        mapping = {
            "startup_ms": "st_ms",
            "play_ms": "pl_ms",
            "bitrate_kbps": "br",
            "buffer_ms": "buf_ms",
            "duration_ms": "rb_ms",
            "error_code": "err",
            "fatal": "fatal",
        }
        doc.update({mapping[k]: v for k, v in payload.items() if k in mapping})
    else:
        doc = {
            "schema_version": 2,
            "event_id": event_id,
            "session_id": ctx["session_id"],
            "viewer_id": ctx["viewer_id"],
            "event_time": _iso(ts),
            "device": ctx["device"],
            "cdn": ctx["cdn"],
            "isp": ctx["isp"],
            "region": ctx["region"],
            "content_id": ctx["content_id"],
            **payload,
        }
    return json.dumps(doc, separators=(",", ":"))


def _corrupt(rng: random.Random, raw: str) -> tuple[str, str]:
    kind = rng.choice(
        ["truncated", "missing_session", "bad_time", "unknown_type", "negative", "v3"]
    )
    doc = json.loads(raw)
    if kind == "truncated":
        return raw[: len(raw) // 2], kind
    if kind == "missing_session":
        doc.pop("session_id", None)
        doc.pop("sid", None)
    elif kind == "bad_time":
        doc["event_time" if "event_time" in doc else "t"] = "21/11/2026 20:15"
    elif kind == "unknown_type":
        doc["event_type" if "event_type" in doc else "type"] = "ad_impression"
    elif kind == "negative":
        doc["event_type" if "event_type" in doc else "type"] = "rebuffer_end"
        doc["duration_ms" if "event_time" in doc else "rb_ms"] = -250
    else:
        doc["schema_version"] = 3
        doc.pop("v", None)
    return json.dumps(doc), kind


def generate(
    log: PartitionedLog,
    sessions: int = 12_000,
    seed: int = 7,
    hours: float = 4.0,
) -> GenerationSummary:
    """Write a full evening of telemetry to ``log`` (arrival-ordered within each partition)."""
    rng = random.Random(seed)
    summary = GenerationSummary(sessions=sessions)
    span_ms = int(hours * 3_600_000)
    base_ms = int(START.timestamp() * 1000)
    viewers = [f"v-{i:06d}" for i in range(int(sessions * 0.6))]
    titles = [f"title-{i:04d}" for i in range(400)]
    by_partition: dict[int, list[tuple[int, str, str]]] = {p: [] for p in range(log.partitions)}

    for _ in range(sessions):
        device = _pick(rng, DEVICES)
        ctx = {
            "session_id": f"s-{rng.getrandbits(64):016x}",
            "viewer_id": rng.choice(viewers),
            "device": device,
            "cdn": _pick(rng, CDN_WEIGHTS),
            "isp": _pick(rng, ISPS),
            "region": _pick(rng, REGION_WEIGHTS),
            "content_id": titles[min(int(rng.paretovariate(1.1)) - 1, len(titles) - 1)],
        }
        v1 = device in {"android", "console"} and rng.random() < 0.35
        skew = int(rng.gauss(0, 400))
        t0 = base_ms + int(rng.triangular(0, span_ms, span_ms * 0.5))
        partition = partition_for(ctx["session_id"], log.partitions)
        for true_ms, payload in _session_events(rng, t0, ctx):
            summary.events += 1
            reported = true_ms + skew
            if rng.random() < 0.0005:
                reported += 2 * 86_400_000
                summary.counts["future_clock"] += 1
            raw = _encode(rng, reported, payload, ctx, v1)
            if rng.random() < 0.003:
                raw, kind = _corrupt(rng, raw)
                summary.counts[f"malformed_{kind}"] += 1
            arrival = true_ms + _delay(rng)
            by_partition[partition].append((arrival, ctx["session_id"], raw))
            if rng.random() < 0.015:
                summary.counts["duplicates"] += 1
                by_partition[partition].append(
                    (arrival + rng.randint(1_000, 30_000), ctx["session_id"], raw)
                )
        summary.counts["sessions_v1" if v1 else "sessions_v2"] += 1

    for partition, records in by_partition.items():
        records.sort(key=lambda r: r[0])
        log.write_partition(partition, records)
        summary.records += len(records)
    return summary
