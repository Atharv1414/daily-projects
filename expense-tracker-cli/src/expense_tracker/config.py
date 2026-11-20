"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import ValidationError

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """All tunables in one immutable object, so they are easy to pass around and test."""

    db_path: Path = Path.home() / ".expense_tracker.db"
    currency_symbol: str = "£"
    log_level: str = "WARNING"
    log_json: bool = False
    anomaly_threshold: float = 3.5

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        defaults = cls()
        level = env.get("EXPENSE_LOG_LEVEL", defaults.log_level).upper()
        if level not in _LOG_LEVELS:
            raise ValidationError(f"EXPENSE_LOG_LEVEL must be one of {sorted(_LOG_LEVELS)}")
        try:
            threshold = float(env.get("EXPENSE_ANOMALY_THRESHOLD", defaults.anomaly_threshold))
        except ValueError as exc:
            raise ValidationError("EXPENSE_ANOMALY_THRESHOLD must be a number") from exc
        if threshold <= 0:
            raise ValidationError("EXPENSE_ANOMALY_THRESHOLD must be positive")
        return cls(
            db_path=Path(env.get("EXPENSE_DB", str(defaults.db_path))).expanduser(),
            currency_symbol=env.get("EXPENSE_CURRENCY", defaults.currency_symbol),
            log_level=level,
            log_json=env.get("EXPENSE_LOG_JSON", "").strip().lower() in _TRUE,
            anomaly_threshold=threshold,
        )
