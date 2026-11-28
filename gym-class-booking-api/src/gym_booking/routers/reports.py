"""Operational reporting for gym managers."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import schemas, services
from ..deps import get_db, get_now, staff_user
from ..errors import DomainError
from ..models import User

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/utilisation", response_model=schemas.UtilisationReport)
def utilisation(
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
    _: User = Depends(staff_user),
) -> schemas.UtilisationReport:
    """Fill rate and waitlist demand by class type (defaults to the next 7 days)."""
    start = date_from or now
    end = date_to or start + timedelta(days=7)
    if end <= start:
        raise DomainError("'to' must be after 'from'")
    return services.utilisation(db, start, end)
