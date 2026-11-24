"""Users, signed tokens and organisation scope."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import duckdb

from .config import AccessDenied


@dataclass(frozen=True)
class User:
    user_id: str
    name: str
    unit_id: str  # sees this unit and everything below it


USERS = {
    u.user_id: u
    for u in (
        User("mp", "Managing Partner", "FIRM"),
        User("finance", "Finance Director", "FIRM"),
        User("head_disputes", "Head of Disputes", "DIS"),
        User("head_realestate", "Head of Real Estate", "REAL"),
        User("head_construction", "Construction team lead", "LIT-CON"),
    )
}


def _sign(payload: bytes, key: str) -> str:
    return hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()


def issue_token(user_id: str, key: str, ttl: int, now: float | None = None) -> str:
    if user_id not in USERS:
        raise AccessDenied(f"unknown user {user_id!r}")
    expiry = int((time.time() if now is None else now) + ttl)
    payload = json.dumps({"sub": user_id, "exp": expiry}).encode()
    return f"{base64.urlsafe_b64encode(payload).decode()}.{_sign(payload, key)}"


def verify_token(token: str, key: str, now: float | None = None) -> User:
    try:
        encoded, signature = token.split(".")
        payload = base64.urlsafe_b64decode(encoded)
        if not hmac.compare_digest(_sign(payload, key), signature):
            raise AccessDenied("invalid token")
        claims = json.loads(payload)
        user, expiry = USERS[claims["sub"]], claims["exp"]
    except (ValueError, KeyError, TypeError) as error:
        raise AccessDenied("invalid token") from error
    if expiry < (time.time() if now is None else now):
        raise AccessDenied("token expired")
    return user


def resolve_unit(con: duckdb.DuckDBPyConnection, user: User, unit_id: str | None) -> str:
    """Returns the unit to report on. Unknown and forbidden units give the same answer, so the
    error cannot be used to probe the organisation structure."""
    wanted = unit_id or user.unit_id
    allowed = con.execute(
        "SELECT 1 FROM bridge_org WHERE ancestor_id = ? AND descendant_id = ?",
        [user.unit_id, wanted],
    ).fetchone()
    if not allowed:
        raise AccessDenied(f"{user.user_id} may not view {wanted!r}")
    return wanted


def visible_units(con: duckdb.DuckDBPyConnection, user: User) -> list[tuple[str, str, int]]:
    """(unit id, name, depth below the user's unit), parents before children."""
    return con.execute(
        """
        WITH RECURSIVE tree AS (
            SELECT unit_id, unit_name, 0 AS depth, [unit_name] AS path
            FROM dim_org WHERE unit_id = ?
            UNION ALL
            SELECT o.unit_id, o.unit_name, t.depth + 1, list_append(t.path, o.unit_name)
            FROM tree t JOIN dim_org o ON o.parent_id = t.unit_id
        )
        SELECT unit_id, unit_name, depth FROM tree ORDER BY path
        """,
        [user.unit_id],
    ).fetchall()
