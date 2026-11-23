"""Stateful stream operators: de-duplication, windowed aggregation and session windows.

Every operator is deterministic and exposes ``snapshot()`` / ``restore()`` so that its state
can be checkpointed in the same transaction as the consumer offsets.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .events import EventType, PlayerEvent
from .metrics import QoEAccumulator, SessionState
from .windows import Window

KeyFn = Callable[[PlayerEvent], tuple[str, ...]]
Assigner = Callable[[int], list[Window]]


@dataclass(frozen=True, slots=True)
class LateEvent:
    event_id: str
    operator: str
    event_type: str
    event_ts: int
    watermark_ms: int
    windows_dropped: int

    def row(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "operator": self.operator,
            "event_type": self.event_type,
            "event_ms": self.event_ts,
            "watermark_ms": self.watermark_ms,
            "lateness_ms": self.watermark_ms - self.event_ts,
            "windows_dropped": self.windows_dropped,
        }


class Deduplicator:
    """Drops client retries (same ``event_id``). State is bounded: ids are forgotten once
    their event time falls behind ``watermark - horizon``, when any copy would be late anyway."""

    def __init__(self, horizon_ms: int) -> None:
        self.horizon_ms = horizon_ms
        self._seen: dict[str, int] = {}

    def is_duplicate(self, e: PlayerEvent) -> bool:
        if e.event_id in self._seen:
            return True
        self._seen[e.event_id] = e.ts
        return False

    def evict(self, watermark: int) -> int:
        cutoff = watermark - self.horizon_ms
        stale = [k for k, ts in self._seen.items() if ts < cutoff]
        for k in stale:
            del self._seen[k]
        return len(stale)

    def __len__(self) -> int:
        return len(self._seen)

    def snapshot(self) -> dict[str, int]:
        return dict(self._seen)

    def restore(self, state: dict[str, int]) -> None:
        self._seen = dict(state)


class WindowAggregator:
    """Keyed event-time window aggregation with allowed lateness.

    A window fires exactly once, when ``watermark >= window.end + allowed_lateness``. An event
    whose window has already fired goes to the late side output and never mutates a published
    result. That trades a little latency for results that are final when written.
    """

    def __init__(
        self,
        name: str,
        assigner: Assigner,
        key_fn: KeyFn,
        key_names: tuple[str, ...],
        allowed_lateness_ms: int,
        track_sessions: bool = False,
    ) -> None:
        self.name = name
        self._assign = assigner
        self._key = key_fn
        self.key_names = key_names
        self._lateness = allowed_lateness_ms
        self._track_sessions = track_sessions
        self._state: dict[tuple[int, int, tuple[str, ...]], QoEAccumulator] = {}
        self._sessions: dict[tuple[int, int, tuple[str, ...]], set[str]] = {}

    def process(self, e: PlayerEvent, watermark: int) -> LateEvent | None:
        key = self._key(e)
        dropped = 0
        for w in self._assign(e.ts):
            if w.end + self._lateness <= watermark:
                dropped += 1
                continue
            slot = (w.start, w.end, key)
            acc = self._state.get(slot)
            if acc is None:
                acc = self._state[slot] = QoEAccumulator()
            acc.add(e)
            if self._track_sessions and e.event_type is EventType.HEARTBEAT:
                self._sessions.setdefault(slot, set()).add(e.session_id)
        if dropped:
            return LateEvent(e.event_id, self.name, e.event_type.value, e.ts, watermark, dropped)
        return None

    def fire(self, watermark: int) -> list[dict[str, object]]:
        ready = sorted(s for s in self._state if s[1] + self._lateness <= watermark)
        rows = []
        for slot in ready:
            start, end, key = slot
            acc = self._state.pop(slot)
            sessions = self._sessions.pop(slot, set())
            row: dict[str, object] = {"window_start": start, "window_end": end}
            row.update(zip(self.key_names, key, strict=True))
            row.update(acc.to_state())
            row["rebuffer_ratio"] = acc.rebuffer_ratio
            row["avg_bitrate_kbps"] = acc.avg_bitrate_kbps
            row["avg_startup_ms"] = acc.avg_startup_ms
            if self._track_sessions:
                row["active_sessions"] = len(sessions)
            rows.append(row)
        return rows

    @property
    def open_windows(self) -> int:
        return len(self._state)

    def snapshot(self) -> list[list[object]]:
        return [
            [s, e, list(k), acc.to_state(), sorted(self._sessions.get((s, e, k), ()))]
            for (s, e, k), acc in sorted(self._state.items())
        ]

    def restore(self, state: list[list[object]]) -> None:
        self._state.clear()
        self._sessions.clear()
        for start, end, key, acc, sessions in state:
            slot = (int(start), int(end), tuple(key))  # type: ignore[arg-type,call-overload]
            self._state[slot] = QoEAccumulator.from_state(acc)  # type: ignore[arg-type]
            if sessions:
                self._sessions[slot] = set(sessions)  # type: ignore[arg-type,call-overload]


class SessionWindowOperator:
    """Per-session summaries keyed by the client's ``session_id``. A session closes once the
    watermark passes ``last event + gap``. An event for an already-closed session is late."""

    name = "sessions"

    def __init__(self, gap_ms: int) -> None:
        self.gap_ms = gap_ms
        self._open: dict[str, SessionState] = {}

    def process(self, e: PlayerEvent, watermark: int) -> LateEvent | None:
        state = self._open.get(e.session_id)
        if state is None:
            if e.ts + self.gap_ms <= watermark:
                return LateEvent(e.event_id, self.name, e.event_type.value, e.ts, watermark, 1)
            state = self._open[e.session_id] = SessionState.open(e)
        state.add(e)
        return None

    def fire(self, watermark: int) -> list[dict[str, object]]:
        ready = sorted(sid for sid, s in self._open.items() if s.last_ts + self.gap_ms <= watermark)
        return [self._open.pop(sid).row() for sid in ready]

    @property
    def open_sessions(self) -> int:
        return len(self._open)

    def snapshot(self) -> list[dict[str, object]]:
        return [self._open[k].to_state() for k in sorted(self._open)]

    def restore(self, state: list[dict[str, object]]) -> None:
        self._open = {s["session_id"]: SessionState.from_state(s) for s in state}  # type: ignore[misc]
