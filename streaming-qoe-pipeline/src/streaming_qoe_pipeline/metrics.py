"""QoE accumulators and the industry-standard metrics derived from them.

* **Rebuffering ratio**: stall time / (stall time + play time). This is the strongest predictor of
  abandonment.
* **Video start time (VST)**: mean time from pressing play to the first frame.
* **Exits before video start (EBVS)**: the share of attempts that never reached a first frame.
* **Average bitrate**: time-weighted by play time, so a 2 s blip at 800 kbps counts less than an
  hour at 8 Mbps.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .events import EventType, PlayerEvent


@dataclass(slots=True)
class QoEAccumulator:
    attempts: int = 0
    plays: int = 0
    startup_ms_sum: int = 0
    watch_ms: int = 0
    rebuffer_ms: int = 0
    rebuffer_events: int = 0
    bitrate_ms_sum: int = 0
    errors: int = 0
    fatal_errors: int = 0
    events: int = 0

    def add(self, e: PlayerEvent) -> None:
        self.events += 1
        match e.event_type:
            case EventType.PLAY_ATTEMPT:
                self.attempts += 1
            case EventType.PLAY_START:
                self.plays += 1
                self.startup_ms_sum += e.startup_ms or 0
            case EventType.HEARTBEAT:
                play = e.play_ms or 0
                self.watch_ms += play
                self.bitrate_ms_sum += play * (e.bitrate_kbps or 0)
            case EventType.REBUFFER_END:
                self.rebuffer_ms += e.duration_ms or 0
                self.rebuffer_events += 1
            case EventType.ERROR:
                self.errors += 1
                self.fatal_errors += int(e.fatal)
            case _:
                pass

    def merge(self, other: QoEAccumulator) -> None:
        for name in self.__slots__:  # type: ignore[attr-defined]
            setattr(self, name, getattr(self, name) + getattr(other, name))

    @property
    def rebuffer_ratio(self) -> float:
        total = self.watch_ms + self.rebuffer_ms
        return self.rebuffer_ms / total if total else 0.0

    @property
    def avg_bitrate_kbps(self) -> float:
        return self.bitrate_ms_sum / self.watch_ms if self.watch_ms else 0.0

    @property
    def avg_startup_ms(self) -> float:
        return self.startup_ms_sum / self.plays if self.plays else 0.0

    def to_state(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_state(cls, state: dict[str, int]) -> QoEAccumulator:
        return cls(**state)


@dataclass(slots=True)
class SessionState:
    """Running summary of one viewing session (a session window keyed by ``session_id``)."""

    session_id: str
    viewer_id: str
    device: str
    cdn: str
    isp: str
    region: str
    content_id: str
    first_ts: int
    last_ts: int
    attempted: bool = False
    started: bool = False
    startup_ms: int | None = None
    watch_ms: int = 0
    rebuffer_ms: int = 0
    rebuffer_count: int = 0
    bitrate_ms_sum: int = 0
    bitrate_switches: int = 0
    end_reason: str = "timeout"
    ended_at: int | None = None
    events: int = 0

    @classmethod
    def open(cls, e: PlayerEvent) -> SessionState:
        return cls(
            e.session_id, e.viewer_id, e.device, e.cdn, e.isp, e.region, e.content_id, e.ts, e.ts
        )

    def add(self, e: PlayerEvent) -> None:
        self.events += 1
        self.first_ts = min(self.first_ts, e.ts)
        self.last_ts = max(self.last_ts, e.ts)
        if self.cdn == "unknown" and e.cdn != "unknown":
            self.cdn = e.cdn
        match e.event_type:
            case EventType.PLAY_ATTEMPT:
                self.attempted = True
            case EventType.PLAY_START:
                self.started = True
                self.startup_ms = e.startup_ms
            case EventType.HEARTBEAT:
                self.watch_ms += e.play_ms or 0
                self.bitrate_ms_sum += (e.play_ms or 0) * (e.bitrate_kbps or 0)
            case EventType.REBUFFER_END:
                self.rebuffer_ms += e.duration_ms or 0
                self.rebuffer_count += 1
            case EventType.BITRATE_SWITCH:
                self.bitrate_switches += 1
            case EventType.ERROR if e.fatal:
                self.end_reason = "fatal_error"
                self.ended_at = e.ts
            case EventType.PLAY_END:
                if self.end_reason != "fatal_error":
                    self.end_reason = "completed" if self.started else "abandoned"
                self.ended_at = e.ts
            case _:
                pass

    @property
    def exit_before_start(self) -> bool:
        return self.attempted and not self.started

    def row(self) -> dict[str, object]:
        ratio_den = self.watch_ms + self.rebuffer_ms
        return {
            "session_id": self.session_id,
            "viewer_id": self.viewer_id,
            "device": self.device,
            "cdn": self.cdn,
            "isp": self.isp,
            "region": self.region,
            "content_id": self.content_id,
            "start_ms": self.first_ts,
            "end_ms": self.last_ts,
            "attempted": self.attempted,
            "started": self.started,
            "exit_before_start": self.exit_before_start,
            "startup_ms": self.startup_ms,
            "watch_ms": self.watch_ms,
            "rebuffer_ms": self.rebuffer_ms,
            "rebuffer_count": self.rebuffer_count,
            "rebuffer_ratio": self.rebuffer_ms / ratio_den if ratio_den else 0.0,
            "avg_bitrate_kbps": self.bitrate_ms_sum / self.watch_ms if self.watch_ms else 0.0,
            "bitrate_switches": self.bitrate_switches,
            "end_reason": self.end_reason,
            "events": self.events,
        }

    def to_state(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__slots__}  # type: ignore[attr-defined]

    @classmethod
    def from_state(cls, state: dict[str, object]) -> SessionState:
        return cls(**state)  # type: ignore[arg-type]
