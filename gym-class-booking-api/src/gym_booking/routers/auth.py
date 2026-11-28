"""Registration, login and the current user's profile."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from .. import schemas, services
from ..config import Settings
from ..deps import current_user, get_db, get_now, get_settings
from ..models import User
from ..security import create_access_token

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def register(
    body: schemas.RegisterRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_now),
) -> User:
    """Create a member account."""
    return services.register_member(db, body, settings, now)


@router.post("/auth/login", response_model=schemas.TokenResponse)
def login(
    body: schemas.LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_now),
) -> schemas.TokenResponse:
    """Exchange email and password for a JWT access token."""
    user = services.authenticate(db, body.email, body.password)
    token = create_access_token(
        user.id, user.role.value, settings.secret_key, settings.token_ttl_minutes, now
    )
    return schemas.TokenResponse(access_token=token, expires_in=settings.token_ttl_minutes * 60)


@router.get("/me", response_model=schemas.UserOut)
def me(user: User = Depends(current_user)) -> User:
    """The authenticated user's profile."""
    return user
