import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HttpConfig(Strict):
    user_agent: str = Field("harvest-portfolio-bot/1.0", min_length=3)
    timeout_s: float = Field(10, gt=0)
    max_attempts: int = Field(5, ge=1, le=10)
    backoff_base_s: float = Field(0.5, ge=0)
    backoff_max_s: float = Field(30, ge=0)
    requests_per_second: float = Field(2, gt=0)
    max_bytes: int = Field(5_000_000, gt=0)
    respect_robots: bool = True


class SourceConfig(Strict):
    url: HttpUrl
    max_pages: int = Field(100, ge=1)


class Config(Strict):
    http: HttpConfig = HttpConfig()
    sources: dict[str, SourceConfig]
    max_reject_rate: float = Field(0.2, ge=0, le=1)


def load_config(path: Path) -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def mysql_options(url: str | None = None) -> dict:
    """Parse mysql://user:password@host:port/database. The URL comes from the environment."""
    parts = urlsplit(url or os.environ.get("HARVEST_MYSQL_URL", ""))
    database = parts.path.lstrip("/")
    if parts.scheme != "mysql" or not parts.hostname or not database:
        raise ValueError("Set HARVEST_MYSQL_URL to mysql://user:password@host:3306/database")
    return {
        "host": parts.hostname,
        "port": parts.port or 3306,
        "user": unquote(parts.username or ""),
        "password": unquote(parts.password or ""),
        "database": database,
    }
