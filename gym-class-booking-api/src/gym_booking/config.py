"""Runtime settings, read from environment variables with safe development defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEV_SECRET_KEY = "dev-only-secret-change-me-in-production-0000"


@dataclass(frozen=True)
class Settings:
    """Business rules and infrastructure settings for one app instance."""

    database_url: str = "sqlite:///./gym_booking.db"
    secret_key: str = DEV_SECRET_KEY
    token_ttl_minutes: int = 60
    password_iterations: int = 600_000
    booking_horizon_days: int = 14
    late_cancel_window_hours: int = 2
    strike_limit: int = 3
    strike_lookback_days: int = 30
    max_waitlist: int = 10

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from ``GYM_BOOKING_*`` environment variables."""
        env = os.environ
        return cls(
            database_url=env.get("GYM_BOOKING_DATABASE_URL", cls.database_url),
            secret_key=env.get("GYM_BOOKING_SECRET_KEY", cls.secret_key),
            token_ttl_minutes=int(env.get("GYM_BOOKING_TOKEN_TTL_MINUTES", cls.token_ttl_minutes)),
        )
