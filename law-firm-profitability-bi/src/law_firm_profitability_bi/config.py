"""Settings. Everything can be overridden through LAWBI_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

CUTOFF = date(2026, 10, 31)
FIRST_MONTH = date(2024, 11, 1)


@dataclass(frozen=True)
class Settings:
    database: Path = field(
        default_factory=lambda: Path(os.environ.get("LAWBI_DATABASE", "build/law_bi.duckdb"))
    )
    # Signs dashboard tokens. The default is for local demos; `serve` refuses to use it unless
    # --demo is passed.
    signing_key: str = field(default_factory=lambda: os.environ.get("LAWBI_SIGNING_KEY", ""))
    token_ttl_seconds: int = field(
        default_factory=lambda: int(os.environ.get("LAWBI_TOKEN_TTL", "28800"))
    )


class BiError(Exception):
    """Base class for expected failures."""


class AccessDenied(BiError):
    """The user may not see the requested organisation unit."""


class BadRequest(BiError):
    """A parameter is invalid."""
