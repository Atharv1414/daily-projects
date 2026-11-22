"""Runtime settings, read from environment variables with safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from broadband_support_agent.errors import ConfigError

DEFAULT_MODEL = "claude-sonnet-5-5"

# USD per million tokens (input, output). Used only for cost estimates in traces.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "scripted": (2.00, 10.00),  # demo mode priced as Sonnet so cost shapes stay realistic
}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be positive, got {value}")
    return value


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    model: str = DEFAULT_MODEL
    db_path: Path = Path("data/northwire.db")
    max_steps: int = 10
    max_total_tokens: int = 120_000
    max_consecutive_errors: int = 3
    # Bill-credit policy (GBP). <= auto limit: no approval; <= approval limit: human approves;
    # above the approval limit the tool refuses and the agent must hand off.
    credit_auto_limit: float = 15.00
    credit_approval_limit: float = 60.00
    max_credits_per_90_days: int = 2
    # Daily rate modelled on Ofcom's automatic compensation scheme (configurable, not advice).
    compensation_per_day: float = 9.76
    compensation_grace_days: int = 2
    # The agent's notion of "now" is fixed so seeded data and evals are reproducible.
    now: datetime = field(default_factory=lambda: datetime(2026, 11, 20, 10, 0))
    seed: int = 42

    @classmethod
    def from_env(cls) -> Settings:
        now_raw = os.environ.get("SUPPORT_AGENT_NOW")
        try:
            now = datetime.fromisoformat(now_raw) if now_raw else datetime(2026, 11, 20, 10, 0)
        except ValueError as exc:
            raise ConfigError(f"SUPPORT_AGENT_NOW must be ISO format, got {now_raw!r}") from exc
        return cls(
            model=os.environ.get("AGENT_MODEL", DEFAULT_MODEL),
            db_path=Path(os.environ.get("SUPPORT_AGENT_DB", "data/northwire.db")),
            max_steps=_env_int("SUPPORT_AGENT_MAX_STEPS", 10),
            max_total_tokens=_env_int("SUPPORT_AGENT_MAX_TOKENS", 120_000),
            credit_auto_limit=_env_float("SUPPORT_AGENT_CREDIT_AUTO_LIMIT", 15.0),
            credit_approval_limit=_env_float("SUPPORT_AGENT_CREDIT_APPROVAL_LIMIT", 60.0),
            now=now,
        )

    def price(self, model: str) -> tuple[float, float]:
        return PRICES_PER_MTOK.get(model, PRICES_PER_MTOK[DEFAULT_MODEL])
