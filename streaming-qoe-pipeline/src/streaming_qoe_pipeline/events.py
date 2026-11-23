"""Player event schema, versioned parsing and upcasting.

Two schema versions are in the wild:

* **v2** (current apps): ``{"schema_version": 2, "event_id", "event_type", "session_id",
  "viewer_id", "event_time" (ISO-8601), "device", "cdn", "isp", "region", "content_id", ...}``
* **v1** (older console/Android builds): terse keys, no CDN field, bitrate called ``br``.

Everything is upcast to :class:`PlayerEvent` (v2). Anything that cannot be parsed becomes a
:class:`DeadLetter` with a machine-readable reason, and is never silently dropped.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class EventType(StrEnum):
    PLAY_ATTEMPT = "play_attempt"
    PLAY_START = "play_start"
    HEARTBEAT = "heartbeat"
    REBUFFER_END = "rebuffer_end"
    BITRATE_SWITCH = "bitrate_switch"
    ERROR = "error"
    PLAY_END = "play_end"


Device = Literal["smart_tv", "ios", "android", "web", "console"]
CDNS = ("cdn_a", "cdn_b", "cdn_c")
REGIONS = (
    "London",
    "South East",
    "South West",
    "Midlands",
    "North West",
    "North East",
    "Yorkshire",
    "Wales",
    "Scotland",
    "Northern Ireland",
)


class PlayerEvent(BaseModel):
    """A validated, upcast player event. ``ts`` is event time in epoch milliseconds (UTC)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: str = Field(min_length=8, max_length=64)
    event_type: EventType
    session_id: str = Field(min_length=4, max_length=64)
    viewer_id: str = Field(min_length=1, max_length=64)
    ts: int
    device: Device
    cdn: str = "unknown"
    isp: str = "unknown"
    region: str = "unknown"
    content_id: str = "unknown"
    schema_version: int = 2

    startup_ms: int | None = Field(default=None, ge=0, le=120_000)
    play_ms: int | None = Field(default=None, ge=0, le=120_000)
    bitrate_kbps: int | None = Field(default=None, ge=100, le=50_000)
    buffer_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0, le=600_000)
    error_code: str | None = None
    fatal: bool = False

    @field_validator("region")
    @classmethod
    def _known_region(cls, v: str) -> str:
        return v if v in REGIONS else "unknown"

    @model_validator(mode="after")
    def _payload_matches_type(self) -> PlayerEvent:
        required = {
            EventType.PLAY_START: ("startup_ms",),
            EventType.HEARTBEAT: ("play_ms", "bitrate_kbps"),
            EventType.REBUFFER_END: ("duration_ms",),
            EventType.BITRATE_SWITCH: ("bitrate_kbps",),
            EventType.ERROR: ("error_code",),
        }.get(self.event_type, ())
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.event_type.value} requires {', '.join(missing)}")
        return self


class DeadLetter(BaseModel):
    """A record that failed parsing or validation, kept with its raw bytes for replay."""

    model_config = ConfigDict(frozen=True)

    partition: int
    offset: int
    reason: str
    detail: str
    raw: str


def _iso_to_ms(value: Any) -> int:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return int(value)
    if not isinstance(value, str):
        raise ValueError("event_time must be an ISO-8601 string or epoch milliseconds")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


_V1_KEYS = {
    "id": "event_id",
    "type": "event_type",
    "sid": "session_id",
    "uid": "viewer_id",
    "t": "event_time",
    "dev": "device",
    "region": "region",
    "isp": "isp",
    "cid": "content_id",
    "st_ms": "startup_ms",
    "pl_ms": "play_ms",
    "br": "bitrate_kbps",
    "buf_ms": "buffer_ms",
    "rb_ms": "duration_ms",
    "err": "error_code",
    "fatal": "fatal",
}


def upcast_v1(doc: dict[str, Any]) -> dict[str, Any]:
    """Rename v1 keys to v2. v1 clients do not report a CDN, so it becomes ``unknown``."""
    out = {_V1_KEYS[k]: v for k, v in doc.items() if k in _V1_KEYS}
    out["schema_version"] = 1
    out.setdefault("cdn", "unknown")
    return out


def parse_record(raw: str, partition: int, offset: int) -> PlayerEvent | DeadLetter:
    """Decode one raw log value into an event, or a dead letter explaining why not."""

    def dead(reason: str, detail: str) -> DeadLetter:
        return DeadLetter(
            partition=partition, offset=offset, reason=reason, detail=detail[:300], raw=raw[:2000]
        )

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        return dead("invalid_json", str(exc))
    if not isinstance(doc, dict):
        return dead("not_an_object", type(doc).__name__)

    version = doc.get("schema_version", doc.get("v"))
    if version == 1:
        doc = upcast_v1(doc)
    elif version != 2:
        return dead("unknown_schema_version", repr(version))

    try:
        doc["ts"] = _iso_to_ms(doc.pop("event_time", None))
    except (ValueError, TypeError) as exc:
        return dead("bad_timestamp", str(exc))

    try:
        return PlayerEvent.model_validate(doc)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(p) for p in first["loc"]) or "event"
        return dead("schema_violation", f"{location}: {first['msg']}")
