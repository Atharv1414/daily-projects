"""Booking endpoints for members."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.orm import Session

from .. import schemas, services
from ..config import Settings
from ..deps import current_user, get_db, get_now, get_settings
from ..models import User

router = APIRouter(tags=["bookings"])


@router.post(
    "/classes/{class_id}/bookings",
    response_model=schemas.BookingOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Replay of an earlier request with the same Idempotency-Key"}},
)
def book(
    class_id: int,
    response: Response,
    idempotency_key: str | None = Header(default=None, max_length=64),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_now),
    user: User = Depends(current_user),
) -> schemas.BookingOut:
    """Book a place; joins the waitlist when the class is full. Send an Idempotency-Key to retry safely."""
    result = services.book_class(db, user, class_id, settings, now, idempotency_key)
    if result.replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replay"] = "true"
    return services.booking_out(db, result.booking)


@router.delete("/bookings/{booking_id}", response_model=schemas.CancellationOut)
def cancel(
    booking_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_now),
    user: User = Depends(current_user),
) -> schemas.CancellationOut:
    """Cancel a booking. Cancelling a confirmed place inside the late window records a strike."""
    result = services.cancel_booking(db, user, booking_id, settings, now)
    return schemas.CancellationOut(
        booking=services.booking_out(db, result.booking),
        late=result.late,
        strikes_in_window=result.strikes,
        promoted_booking_id=result.promoted.id if result.promoted else None,
    )


@router.get("/me/bookings", response_model=list[schemas.BookingOut])
def my_bookings(
    include_past: bool = False,
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
    user: User = Depends(current_user),
) -> list[schemas.BookingOut]:
    """The signed-in member's bookings, soonest first."""
    return services.my_bookings(db, user, now, include_past)
