"""Settings read from environment variables, with safe local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEMO_TOKEN = "hollinbeck-demo-organiser"
"""Organiser token used when FELL_ORGANISER_TOKENS is not set. It only works against the
in-memory demo database; any deployment with MONGO_URL must set its own tokens."""


def _split(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    mongo_url: str | None = None
    database: str = "fell_results"
    organiser_tokens: tuple[str, ...] = field(default_factory=tuple)
    seed_on_start: bool = True
    seed: int = 2026
    log_level: str = "INFO"
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    max_upload_rows: int = 500

    @property
    def in_memory(self) -> bool:
        return not self.mongo_url

    def tokens(self) -> tuple[str, ...]:
        """Tokens that may upload results. The demo token is only accepted in memory."""
        if self.organiser_tokens:
            return self.organiser_tokens
        return (DEMO_TOKEN,) if self.in_memory else ()

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        return cls(
            mongo_url=env.get("MONGO_URL") or None,
            database=env.get("FELL_DATABASE", "fell_results"),
            organiser_tokens=_split(env.get("FELL_ORGANISER_TOKENS", "")),
            seed_on_start=env.get("FELL_SEED_ON_START", "1") not in {"0", "false", "no"},
            seed=int(env.get("FELL_SEED", "2026")),
            log_level=env.get("FELL_LOG_LEVEL", "INFO").upper(),
            cors_origins=_split(env.get("FELL_CORS_ORIGINS", ""))
            or ("http://localhost:5173", "http://127.0.0.1:5173"),
            max_upload_rows=int(env.get("FELL_MAX_UPLOAD_ROWS", "500")),
        )
