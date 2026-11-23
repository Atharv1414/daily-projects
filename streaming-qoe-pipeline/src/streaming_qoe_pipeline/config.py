"""Pipeline settings with environment-variable overrides (prefix ``QOE_``)."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """All tunables in one place. Times are milliseconds."""

    log_dir: Path = Path("data/log")
    warehouse_path: Path = Path("data/qoe.duckdb")
    partitions: int = 4
    segment_size: int = 20_000
    consumer_group: str = "qoe-processor"

    # Event time
    max_out_of_orderness_ms: int = 5_000
    allowed_lateness_ms: int = 90_000
    max_future_skew_ms: int = 300_000
    tumbling_window_ms: int = 60_000
    hopping_size_ms: int = 300_000
    hopping_slide_ms: int = 60_000
    session_gap_ms: int = 120_000

    # Processing
    poll_records_per_partition: int = 2_000
    checkpoint_every_polls: int = 5

    # Alerting
    alert_min_watch_ms: int = 1_800_000
    alert_z_threshold: float = 4.0
    alert_min_ratio: float = 0.02
    alert_warmup_windows: int = 15
    alert_ewma_alpha: float = 0.05

    @classmethod
    def from_env(cls, **overrides: object) -> Settings:
        """Build settings from defaults, then ``QOE_*`` env vars, then explicit overrides."""
        base = cls()
        values: dict[str, object] = {}
        for f in fields(cls):
            raw = os.environ.get(f"QOE_{f.name.upper()}")
            if raw is None:
                continue
            current = getattr(base, f.name)
            if isinstance(current, Path):
                values[f.name] = Path(raw)
            elif isinstance(current, bool):
                values[f.name] = raw.lower() in {"1", "true", "yes"}
            else:
                values[f.name] = type(current)(raw)
        values.update(overrides)
        settings = replace(base, **values)
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.partitions < 1:
            raise ValueError("partitions must be >= 1")
        if self.hopping_size_ms % self.hopping_slide_ms:
            raise ValueError("hopping_size_ms must be a multiple of hopping_slide_ms")
        if min(self.tumbling_window_ms, self.hopping_slide_ms, self.session_gap_ms) <= 0:
            raise ValueError("window sizes must be positive")
        if self.allowed_lateness_ms < 0 or self.max_out_of_orderness_ms < 0:
            raise ValueError("lateness bounds must be non-negative")
