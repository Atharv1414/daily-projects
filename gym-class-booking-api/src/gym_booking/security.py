"""Password hashing (PBKDF2-HMAC-SHA256) and JWT access tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from .errors import Unauthorized

ALGORITHM = "HS256"
_SCHEME = "pbkdf2_sha256"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str, iterations: int = 600_000) -> str:
    """Hash a password with a random 16-byte salt. Output: ``pbkdf2_sha256$<iter>$<salt>$<hash>``."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{_SCHEME}${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored hash in constant time."""
    try:
        scheme, iterations, salt_b64, hash_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != _SCHEME:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iterations))
    return hmac.compare_digest(digest, base64.b64decode(hash_b64))


def create_access_token(user_id: int, role: str, secret: str, ttl_minutes: int, now: datetime) -> str:
    """Issue a signed JWT carrying the user id (``sub``) and role."""
    issued = now.replace(tzinfo=timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, secret: str, now: datetime) -> dict:
    """Validate a JWT's signature and expiry against the app clock, returning its claims."""
    # Time claims are checked here against the injected app clock rather than the wall clock.
    options = {"verify_exp": False, "verify_iat": False, "verify_nbf": False, "require": ["sub", "exp"]}
    try:
        claims = jwt.decode(token, secret, algorithms=[ALGORITHM], options=options)
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid access token") from exc
    if claims.get("exp", 0) <= now.replace(tzinfo=timezone.utc).timestamp():
        raise Unauthorized("Access token has expired")
    return claims
