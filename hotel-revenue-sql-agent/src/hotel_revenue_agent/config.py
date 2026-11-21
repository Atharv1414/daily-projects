"""Settings loaded from environment variables, with safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from hotel_revenue_agent.errors import ConfigError

DEFAULT_MODEL = "claude-sonnet-5-5"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# USD per million tokens (input, output). Used for cost estimates in traces.
PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "scripted": (2.00, 10.00),
}


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    model: str = DEFAULT_MODEL
    db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "hotel.db")
    reports_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "reports")
    traces_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "traces")
    max_steps: int = 8
    max_total_tokens: int = 60_000
    max_rows: int = 200
    query_timeout_ms: int = 3_000
    max_tokens_per_call: int = 4_000
    max_consecutive_errors: int = 3

    @classmethod
    def from_env(cls) -> Settings:
        base = cls()
        return cls(
            model=os.environ.get("AGENT_MODEL", DEFAULT_MODEL),
            db_path=Path(os.environ.get("HOTEL_DB", base.db_path)),
            reports_dir=Path(os.environ.get("AGENT_REPORTS_DIR", base.reports_dir)),
            traces_dir=Path(os.environ.get("AGENT_TRACES_DIR", base.traces_dir)),
            max_steps=_int_env("AGENT_MAX_STEPS", base.max_steps),
            max_total_tokens=_int_env("AGENT_MAX_TOKENS", base.max_total_tokens, 1_000),
            max_rows=_int_env("AGENT_MAX_ROWS", base.max_rows),
            query_timeout_ms=_int_env("AGENT_QUERY_TIMEOUT_MS", base.query_timeout_ms, 50),
        )

    def price(self, model: str | None = None) -> tuple[float, float]:
        return PRICING_PER_MTOK.get(model or self.model, PRICING_PER_MTOK[DEFAULT_MODEL])
