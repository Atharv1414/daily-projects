"""FastAPI dependencies: database session, clock, settings and the authenticated user."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import Settings
from .errors import Forbidden, Unauthorized
from .models import Role, User
from .security import decode_access_token

bearer = HTTPBearer(auto_error=False, description="JWT from POST /auth/login")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_now(request: Request) -> datetime:
    return request.app.state.clock()


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_now),
) -> User:
    """Resolve the bearer token to a user, or fail with 401."""
    if credentials is None:
        raise Unauthorized("Missing bearer token")
    claims = decode_access_token(credentials.credentials, settings.secret_key, now)
    user = db.get(User, int(claims["sub"]))
    if user is None:
        raise Unauthorized("User no longer exists")
    return user


def staff_user(user: User = Depends(current_user)) -> User:
    """Allow only staff accounts through, otherwise 403."""
    if user.role != Role.STAFF:
        raise Forbidden("Staff access required")
    return user
