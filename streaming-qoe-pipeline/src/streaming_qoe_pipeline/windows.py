"""Event-time primitives: window assigners and a multi-partition watermark tracker."""

from __future__ import annotations

from dataclasses import dataclass

NEG_INF = -(2**62)
POS_INF = 2**62


@dataclass(frozen=True, slots=True, order=True)
class Window:
    """Half-open interval ``[start, end)`` in epoch milliseconds."""

    start: int
    end: int

    def contains(self, ts: int) -> bool:
        return self.start <= ts < self.end


def tumbling(ts: int, size: int) -> list[Window]:
    """The single fixed-size window containing ``ts``. Floor division handles negative times."""
    start = ts - ts % size
    return [Window(start, start + size)]


def hopping(ts: int, size: int, slide: int) -> list[Window]:
    """Every window of length ``size`` (one every ``slide`` ms) that contains ``ts``.

    Each event belongs to exactly ``size // slide`` windows when ``size`` is a multiple of
    ``slide``. Windows are returned oldest first.
    """
    last_start = ts - ts % slide
    first_start = last_start - size + slide
    return [Window(s, s + size) for s in range(first_start, last_start + 1, slide)]


class WatermarkTracker:
    """Bounded-out-of-orderness watermarks, tracked per partition.

    Each partition's watermark is ``max event time seen - max_out_of_orderness``. The global
    watermark is the **minimum** across partitions, so a slow partition holds windows open
    rather than having its on-time data declared late. The watermark never moves backwards.
    """

    def __init__(self, partitions: int, max_out_of_orderness_ms: int) -> None:
        self._bound = max_out_of_orderness_ms
        self._max_ts: dict[int, int] = dict.fromkeys(range(partitions), NEG_INF)
        self._current = NEG_INF

    def observe(self, partition: int, ts: int) -> None:
        if ts > self._max_ts[partition]:
            self._max_ts[partition] = ts

    def advance(self) -> int:
        """Recompute the global watermark (called once per poll) and return it."""
        candidate = min(
            (m - self._bound if m != NEG_INF else NEG_INF) for m in self._max_ts.values()
        )
        self._current = max(self._current, candidate)
        return self._current

    def finish(self) -> int:
        """End of a bounded input: everything is complete, so close every window."""
        self._current = POS_INF
        return self._current

    @property
    def current(self) -> int:
        return self._current

    def mark_idle(self, partition: int) -> None:
        """An exhausted partition must not hold the global watermark back for ever."""
        self._max_ts[partition] = POS_INF

    def snapshot(self) -> dict[str, object]:
        return {"max_ts": {str(k): v for k, v in self._max_ts.items()}, "current": self._current}

    def restore(self, state: dict[str, object]) -> None:
        max_ts = state["max_ts"]
        assert isinstance(max_ts, dict)
        self._max_ts = {int(k): int(v) for k, v in max_ts.items()}
        current = state["current"]
        assert isinstance(current, int)
        self._current = current
