"""Pydantic request and response models (the public API contract)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import BookingStatus, ClassStatus, Role

CLASS_TYPES = ("yoga", "spin", "hiit", "pilates", "strength", "boxing")


class RegisterRequest(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: Role


class ClassCreate(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    class_type: str
    coach: str = Field(min_length=1, max_length=80)
    room: str = Field(min_length=1, max_length=40)
    starts_at: datetime
    duration_minutes: int = Field(ge=15, le=180)
    capacity: int = Field(ge=1, le=100)

    @field_validator("class_type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        value = value.lower()
        if value not in CLASS_TYPES:
            raise ValueError(f"class_type must be one of {', '.join(CLASS_TYPES)}")
        return value

    @field_validator("starts_at")
    @classmethod
    def _naive_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is not None:
            from datetime import timezone

            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value


class ClassUpdate(BaseModel):
    capacity: int | None = Field(default=None, ge=1, le=100)
    coach: str | None = Field(default=None, min_length=1, max_length=80)
    room: str | None = Field(default=None, min_length=1, max_length=40)


class ClassOut(BaseModel):
    id: int
    title: str
    class_type: str
    coach: str
    room: str
    starts_at: datetime
    duration_minutes: int
    capacity: int
    status: ClassStatus
    booked: int
    spots_left: int
    waitlist_length: int


class ClassPage(BaseModel):
    items: list[ClassOut]
    total: int
    limit: int
    offset: int


class BookingOut(BaseModel):
    id: int
    class_id: int
    class_title: str
    starts_at: datetime
    status: BookingStatus
    waitlist_position: int | None = None
    created_at: datetime
    promoted_at: datetime | None = None
    cancelled_at: datetime | None = None


class CancellationOut(BaseModel):
    booking: BookingOut
    late: bool
    strikes_in_window: int
    promoted_booking_id: int | None = None


class ClassCancellationOut(BaseModel):
    class_id: int
    bookings_cancelled: int


class AttendeeOut(BaseModel):
    booking_id: int
    user_id: int
    full_name: str
    status: BookingStatus
    waitlist_position: int | None = None


class UtilisationRow(BaseModel):
    class_type: str
    sessions: int
    capacity: int
    confirmed: int
    fill_rate: float
    waitlisted: int
    late_cancellations: int
    sessions_full: int


class UtilisationReport(BaseModel):
    period_start: datetime
    period_end: datetime
    rows: list[UtilisationRow]
    overall_fill_rate: float
