"""Timetable endpoints: browse classes (anyone signed in) and manage them (staff)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from .. import schemas, services
from ..deps import current_user, get_db, get_now, staff_user
from ..models import User

router = APIRouter(prefix="/classes", tags=["classes"])


@router.get("", response_model=schemas.ClassPage)
def list_classes(
    class_type: str | None = Query(default=None, description="yoga, spin, hiit, pilates, strength, boxing"),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    available_only: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
    _: User = Depends(current_user),
) -> schemas.ClassPage:
    """Upcoming classes with live availability."""
    return services.list_classes(
        db,
        now,
        class_type=class_type,
        date_from=date_from,
        date_to=date_to,
        available_only=available_only,
        limit=limit,
        offset=offset,
    )


@router.get("/{class_id}", response_model=schemas.ClassOut)
def get_class(
    class_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)
) -> schemas.ClassOut:
    return services.class_out(db, services.get_class(db, class_id))


@router.post("", response_model=schemas.ClassOut, status_code=status.HTTP_201_CREATED)
def create_class(
    body: schemas.ClassCreate,
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
    _: User = Depends(staff_user),
) -> schemas.ClassOut:
    """Schedule a new class (staff only)."""
    return services.class_out(db, services.create_class(db, body, now))


@router.patch("/{class_id}", response_model=schemas.ClassOut)
def update_class(
    class_id: int,
    body: schemas.ClassUpdate,
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
    _: User = Depends(staff_user),
) -> schemas.ClassOut:
    """Change coach, room or capacity (staff only). Extra capacity is filled from the waitlist."""
    return services.class_out(db, services.update_class(db, class_id, body, now))


@router.delete("/{class_id}", response_model=schemas.ClassCancellationOut)
def cancel_class(
    class_id: int,
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
    _: User = Depends(staff_user),
) -> schemas.ClassCancellationOut:
    """Cancel a class and all its bookings (staff only)."""
    count = services.cancel_class(db, class_id, now)
    return schemas.ClassCancellationOut(class_id=class_id, bookings_cancelled=count)


@router.get("/{class_id}/roster", response_model=list[schemas.AttendeeOut])
def roster(
    class_id: int, db: Session = Depends(get_db), _: User = Depends(staff_user)
) -> list[schemas.AttendeeOut]:
    """Confirmed attendees and the waitlist in order (staff only)."""
    return services.roster(db, class_id)
