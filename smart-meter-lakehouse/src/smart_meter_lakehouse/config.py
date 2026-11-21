"""Pipeline configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from smart_meter_lakehouse.errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class PipelineConfig:
    landing_dir: Path = PROJECT_ROOT / "data" / "landing"
    warehouse_path: Path = PROJECT_ROOT / "data" / "lakehouse.duckdb"
    reports_dir: Path = PROJECT_ROOT / "reports"
    max_retries: int = 3
    retry_backoff_s: float = 0.2
    # Reject a readings batch outright if more than this share of rows fails error rules.
    max_error_rate: float = 0.05
    # Simulated flaky tariff API: number of transient failures before it succeeds.
    flaky_tariff_failures: int = 0

    @classmethod
    def from_env(cls) -> PipelineConfig:
        base = cls()
        return cls(
            landing_dir=Path(os.environ.get("METERLAKE_LANDING", base.landing_dir)),
            warehouse_path=Path(os.environ.get("METERLAKE_DB", base.warehouse_path)),
            reports_dir=Path(os.environ.get("METERLAKE_REPORTS", base.reports_dir)),
            max_retries=int(_float_env("METERLAKE_MAX_RETRIES", base.max_retries)),
            retry_backoff_s=_float_env("METERLAKE_RETRY_BACKOFF", base.retry_backoff_s),
            max_error_rate=_float_env("METERLAKE_MAX_ERROR_RATE", base.max_error_rate),
            flaky_tariff_failures=int(_float_env("METERLAKE_FLAKY_TARIFF", 0)),
        )
