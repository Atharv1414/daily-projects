"""Structured JSON logging and simple run counters."""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter
from dataclasses import dataclass, field


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("streaming_qoe_pipeline")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


def log_event(logger: logging.Logger, msg: str, **fields: object) -> None:
    logger.info(msg, extra={"fields": fields})


@dataclass
class RunStats:
    """Counters for one processor run, persisted to ``pipeline_runs``."""

    started_at: float = field(default_factory=time.time)
    counters: Counter[str] = field(default_factory=Counter)
    checkpoint_seconds: list[float] = field(default_factory=list)
    checkpoint_bytes: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in ("records_read", "events_processed", "duplicates_dropped", "dead_letters"):
            self.counters[name] += 0

    def incr(self, name: str, by: int = 1) -> None:
        self.counters[name] += by

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at

    def summary(self) -> dict[str, object]:
        records = self.counters["records_read"]
        return {
            **dict(sorted(self.counters.items())),
            "elapsed_s": round(self.elapsed, 2),
            "records_per_s": round(records / self.elapsed) if self.elapsed else 0,
            "checkpoints": len(self.checkpoint_seconds),
            "avg_checkpoint_ms": round(
                1000 * sum(self.checkpoint_seconds) / max(1, len(self.checkpoint_seconds)), 1
            ),
            "max_checkpoint_kb": round(max(self.checkpoint_bytes, default=0) / 1024, 1),
        }
