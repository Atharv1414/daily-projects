"""ORM models: members and staff, scheduled classes, and bookings."""

from __future__ import annotations

import enum
from datetime import datetime, timedelta

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Role(str, enum.Enum):
    MEMBER = "member"
    STAFF = "staff"


class ClassStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"


class BookingStatus(str, enum.Enum):
    CONFIRMED = "confirmed"
    WAITLISTED = "waitlisted"
    CANCELLED = "cancelled"
    LATE_CANCELLED = "late_cancelled"
    CLASS_CANCELLED = "class_cancelled"


ACTIVE_STATUSES = (BookingStatus.CONFIRMED, BookingStatus.WAITLISTED)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), default=Role.MEMBER)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class GymClass(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(80))
    class_type: Mapped[str] = mapped_column(String(30), index=True)
    coach: Mapped[str] = mapped_column(String(80))
    room: Mapped[str] = mapped_column(String(40))
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    capacity: Mapped[int] = mapped_column(Integer)
    status: Mapped[ClassStatus] = mapped_column(
        Enum(ClassStatus, native_enum=False), default=ClassStatus.SCHEDULED
    )

    bookings: Mapped[list[Booking]] = relationship(back_populates="gym_class")

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_minutes)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        # A member may hold at most one active (confirmed or waitlisted) booking per class.
        Index(
            "uq_active_booking",
            "class_id",
            "user_id",
            unique=True,
            sqlite_where=text("status IN ('CONFIRMED', 'WAITLISTED')"),
            postgresql_where=text("status IN ('CONFIRMED', 'WAITLISTED')"),
        ),
        UniqueConstraint("user_id", "idempotency_key", name="uq_user_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus, native_enum=False))
    idempotency_key: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    gym_class: Mapped[GymClass] = relationship(back_populates="bookings")
    user: Mapped[User] = relationship()
