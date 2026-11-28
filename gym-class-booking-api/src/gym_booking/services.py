"""Business logic for timetables and bookings, kept free of HTTP concerns so it is easy to test."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import schemas
from .config import Settings
from .errors import Conflict, Forbidden, NotFound, Unauthorized, make_error
from .models import ACTIVE_STATUSES, Booking, BookingStatus, ClassStatus, GymClass, Role, User
from .security import hash_password, verify_password

# --------------------------------------------------------------------------- users


def register_member(db: Session, data: schemas.RegisterRequest, settings: Settings, now: datetime) -> User:
    """Create a member account. Email addresses are unique (case-insensitive)."""
    if db.scalar(select(User).where(User.email == data.email)):
        raise make_error(Conflict, "email_taken", "An account with this email already exists")
    user = User(
        email=data.email,
        full_name=data.full_name.strip(),
        password_hash=hash_password(data.password, settings.password_iterations),
        role=Role.MEMBER,
        created_at=now,
    )
    db.add(user)
    db.commit()
    return user


def create_user(
    db: Session, email: str, full_name: str, password: str, role: Role, settings: Settings, now: datetime
) -> User:
    """Create a user with any role (used by the seed script for staff accounts)."""
    user = User(
        email=email.lower(),
        full_name=full_name,
        password_hash=hash_password(password, settings.password_iterations),
        role=role,
        created_at=now,
    )
    db.add(user)
    db.flush()
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    """Return the user for valid credentials. The error never reveals which part was wrong."""
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not verify_password(password, user.password_hash):
        raise Unauthorized("Incorrect email or password")
    return user


# --------------------------------------------------------------------------- classes


@dataclass(frozen=True)
class Occupancy:
    confirmed: int
    waitlisted: int


def occupancy(db: Session, class_id: int) -> Occupancy:
    """Count confirmed and waitlisted bookings for one class."""
    rows = dict(
        db.execute(
            select(Booking.status, func.count())
            .where(Booking.class_id == class_id, Booking.status.in_(ACTIVE_STATUSES))
            .group_by(Booking.status)
        ).all()
    )
    return Occupancy(rows.get(BookingStatus.CONFIRMED, 0), rows.get(BookingStatus.WAITLISTED, 0))


def class_out(db: Session, gym_class: GymClass) -> schemas.ClassOut:
    occ = occupancy(db, gym_class.id)
    return schemas.ClassOut(
        id=gym_class.id,
        title=gym_class.title,
        class_type=gym_class.class_type,
        coach=gym_class.coach,
        room=gym_class.room,
        starts_at=gym_class.starts_at,
        duration_minutes=gym_class.duration_minutes,
        capacity=gym_class.capacity,
        status=gym_class.status,
        booked=occ.confirmed,
        spots_left=max(gym_class.capacity - occ.confirmed, 0),
        waitlist_length=occ.waitlisted,
    )


def get_class(db: Session, class_id: int, *, for_update: bool = False) -> GymClass:
    stmt = select(GymClass).where(GymClass.id == class_id)
    if for_update:
        # Row lock on PostgreSQL/MySQL. SQLite ignores it; database.py uses BEGIN IMMEDIATE there instead.
        stmt = stmt.with_for_update()
    gym_class = db.scalar(stmt)
    if gym_class is None:
        raise NotFound(f"Class {class_id} does not exist")
    return gym_class


def _room_clash(
    db: Session, room: str, starts_at: datetime, ends_at: datetime, exclude_id: int | None
) -> bool:
    candidates = db.scalars(
        select(GymClass).where(
            GymClass.room == room,
            GymClass.status == ClassStatus.SCHEDULED,
            GymClass.starts_at < ends_at,
            GymClass.starts_at > starts_at - timedelta(hours=4),
        )
    )
    return any(c.id != exclude_id and c.ends_at > starts_at for c in candidates)


def create_class(db: Session, data: schemas.ClassCreate, now: datetime) -> GymClass:
    """Schedule a class. It must be in the future and must not overlap another class in the same room."""
    if data.starts_at <= now:
        raise make_error(Conflict, "class_in_past", "Classes must be scheduled in the future")
    ends_at = data.starts_at + timedelta(minutes=data.duration_minutes)
    if _room_clash(db, data.room, data.starts_at, ends_at, exclude_id=None):
        raise make_error(Conflict, "room_double_booked", f"{data.room} is already in use at that time")
    gym_class = GymClass(**data.model_dump(), status=ClassStatus.SCHEDULED)
    db.add(gym_class)
    db.commit()
    return gym_class


def list_classes(
    db: Session,
    now: datetime,
    *,
    class_type: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    available_only: bool,
    limit: int,
    offset: int,
) -> schemas.ClassPage:
    """Upcoming scheduled classes, filtered and paginated, ordered by start time."""
    stmt = select(GymClass).where(
        GymClass.status == ClassStatus.SCHEDULED, GymClass.starts_at >= (date_from or now)
    )
    if class_type:
        stmt = stmt.where(GymClass.class_type == class_type.lower())
    if date_to:
        stmt = stmt.where(GymClass.starts_at < date_to)
    stmt = stmt.order_by(GymClass.starts_at, GymClass.id)
    items = [class_out(db, c) for c in db.scalars(stmt)]
    if available_only:
        items = [c for c in items if c.spots_left > 0]
    return schemas.ClassPage(
        items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset
    )


def update_class(db: Session, class_id: int, data: schemas.ClassUpdate, now: datetime) -> GymClass:
    """Change coach, room or capacity. Raising capacity promotes waitlisted members straight away."""
    gym_class = get_class(db, class_id, for_update=True)
    if gym_class.status == ClassStatus.CANCELLED:
        raise make_error(Conflict, "class_cancelled", "Cancelled classes cannot be edited")
    if data.room and data.room != gym_class.room:
        if _room_clash(db, data.room, gym_class.starts_at, gym_class.ends_at, exclude_id=gym_class.id):
            raise make_error(Conflict, "room_double_booked", f"{data.room} is already in use at that time")
        gym_class.room = data.room
    if data.coach:
        gym_class.coach = data.coach
    if data.capacity is not None:
        confirmed = occupancy(db, class_id).confirmed
        if data.capacity < confirmed:
            raise make_error(
                Conflict,
                "capacity_below_bookings",
                f"{confirmed} members are already confirmed; capacity cannot drop to {data.capacity}",
            )
        gym_class.capacity = data.capacity
        db.flush()
        for _ in range(data.capacity - confirmed):
            if _promote_next(db, class_id, now) is None:
                break
    db.commit()
    return gym_class


def cancel_class(db: Session, class_id: int, now: datetime) -> int:
    """Cancel a class and every active booking on it. Returns the number of bookings cancelled."""
    gym_class = get_class(db, class_id, for_update=True)
    if gym_class.status == ClassStatus.CANCELLED:
        raise make_error(Conflict, "class_cancelled", "Class is already cancelled")
    gym_class.status = ClassStatus.CANCELLED
    bookings = db.scalars(
        select(Booking).where(Booking.class_id == class_id, Booking.status.in_(ACTIVE_STATUSES))
    ).all()
    for booking in bookings:
        booking.status = BookingStatus.CLASS_CANCELLED
        booking.cancelled_at = now
    db.commit()
    return len(bookings)


def roster(db: Session, class_id: int) -> list[schemas.AttendeeOut]:
    """Confirmed attendees followed by the waitlist in queue order."""
    get_class(db, class_id)
    rows = db.execute(
        select(Booking, User)
        .join(User, Booking.user_id == User.id)
        .where(Booking.class_id == class_id, Booking.status.in_(ACTIVE_STATUSES))
        .order_by(Booking.status, Booking.created_at, Booking.id)
    ).all()
    out, position = [], 0
    for booking, user in rows:
        waitlisted = booking.status == BookingStatus.WAITLISTED
        position += waitlisted
        out.append(
            schemas.AttendeeOut(
                booking_id=booking.id,
                user_id=user.id,
                full_name=user.full_name,
                status=booking.status,
                waitlist_position=position if waitlisted else None,
            )
        )
    return out


# --------------------------------------------------------------------------- bookings


def recent_strikes(db: Session, user_id: int, now: datetime, settings: Settings) -> int:
    """Late cancellations by this member within the look-back window."""
    since = now - timedelta(days=settings.strike_lookback_days)
    return db.scalar(
        select(func.count()).where(
            Booking.user_id == user_id,
            Booking.status == BookingStatus.LATE_CANCELLED,
            Booking.cancelled_at >= since,
        )
    )


def waitlist_position(db: Session, booking: Booking) -> int | None:
    if booking.status != BookingStatus.WAITLISTED:
        return None
    ahead = db.scalar(
        select(func.count()).where(
            Booking.class_id == booking.class_id,
            Booking.status == BookingStatus.WAITLISTED,
            (Booking.created_at < booking.created_at)
            | ((Booking.created_at == booking.created_at) & (Booking.id < booking.id)),
        )
    )
    return ahead + 1


def booking_out(db: Session, booking: Booking) -> schemas.BookingOut:
    return schemas.BookingOut(
        id=booking.id,
        class_id=booking.class_id,
        class_title=booking.gym_class.title,
        starts_at=booking.gym_class.starts_at,
        status=booking.status,
        waitlist_position=waitlist_position(db, booking),
        created_at=booking.created_at,
        promoted_at=booking.promoted_at,
        cancelled_at=booking.cancelled_at,
    )


@dataclass(frozen=True)
class BookingResult:
    booking: Booking
    replayed: bool


def book_class(
    db: Session,
    user: User,
    class_id: int,
    settings: Settings,
    now: datetime,
    idempotency_key: str | None = None,
) -> BookingResult:
    """Book a place, or join the waitlist when the class is full.

    Rules, in the order they are checked:
    1. A retried request with the same ``Idempotency-Key`` returns the original booking.
    2. The class must exist, be scheduled, not have started and be within the booking horizon.
    3. Members with ``strike_limit`` late cancellations in the look-back window are suspended.
    4. A member cannot hold two active bookings for the same class.
    5. Confirmed if a place is free, otherwise waitlisted up to ``max_waitlist``.
    """
    if idempotency_key:
        previous = db.scalar(
            select(Booking).where(Booking.user_id == user.id, Booking.idempotency_key == idempotency_key)
        )
        if previous is not None:
            if previous.class_id != class_id:
                raise make_error(
                    Conflict, "idempotency_key_reused", "This Idempotency-Key was used for a different class"
                )
            return BookingResult(previous, replayed=True)

    gym_class = get_class(db, class_id, for_update=True)
    if gym_class.status == ClassStatus.CANCELLED:
        raise make_error(Conflict, "class_cancelled", "This class has been cancelled")
    if gym_class.starts_at <= now:
        raise make_error(Conflict, "class_started", "This class has already started")
    if gym_class.starts_at > now + timedelta(days=settings.booking_horizon_days):
        raise make_error(
            Conflict,
            "outside_booking_window",
            f"Bookings open {settings.booking_horizon_days} days before the class",
        )
    strikes = recent_strikes(db, user.id, now, settings)
    if strikes >= settings.strike_limit:
        raise make_error(
            Forbidden,
            "booking_suspended",
            f"{strikes} late cancellations in the last {settings.strike_lookback_days} days; "
            "booking is suspended until older strikes expire",
        )
    existing = db.scalar(
        select(Booking).where(
            Booking.class_id == class_id, Booking.user_id == user.id, Booking.status.in_(ACTIVE_STATUSES)
        )
    )
    if existing is not None:
        raise make_error(Conflict, "already_booked", f"You already hold booking {existing.id} for this class")

    occ = occupancy(db, class_id)
    if occ.confirmed < gym_class.capacity:
        status = BookingStatus.CONFIRMED
    elif occ.waitlisted < settings.max_waitlist:
        status = BookingStatus.WAITLISTED
    else:
        raise make_error(Conflict, "class_full", "The class and its waitlist are full")

    booking = Booking(
        class_id=class_id, user_id=user.id, status=status, idempotency_key=idempotency_key, created_at=now
    )
    db.add(booking)
    try:
        db.commit()
    except IntegrityError as exc:  # a concurrent duplicate slipped past the checks above
        db.rollback()
        raise make_error(Conflict, "already_booked", "You already hold a booking for this class") from exc
    return BookingResult(booking, replayed=False)


def _promote_next(db: Session, class_id: int, now: datetime) -> Booking | None:
    """Move the longest-waiting member from the waitlist into a confirmed place."""
    nxt = db.scalar(
        select(Booking)
        .where(Booking.class_id == class_id, Booking.status == BookingStatus.WAITLISTED)
        .order_by(Booking.created_at, Booking.id)
        .limit(1)
    )
    if nxt is not None:
        nxt.status = BookingStatus.CONFIRMED
        nxt.promoted_at = now
        db.flush()
    return nxt


@dataclass(frozen=True)
class CancellationResult:
    booking: Booking
    late: bool
    strikes: int
    promoted: Booking | None


def cancel_booking(
    db: Session, user: User, booking_id: int, settings: Settings, now: datetime
) -> CancellationResult:
    """Cancel a booking. Inside the late window a confirmed place counts as a strike.

    Freeing a confirmed place promotes the first member on the waitlist.
    """
    booking = db.get(Booking, booking_id)
    if booking is None or (booking.user_id != user.id and user.role != Role.STAFF):
        raise NotFound(f"Booking {booking_id} does not exist")
    if booking.status not in ACTIVE_STATUSES:
        raise make_error(Conflict, "not_active", f"Booking is already {booking.status.value}")
    gym_class = get_class(db, booking.class_id, for_update=True)
    if gym_class.starts_at <= now:
        raise make_error(Conflict, "class_started", "Bookings cannot be cancelled after the class starts")

    was_confirmed = booking.status == BookingStatus.CONFIRMED
    late = was_confirmed and gym_class.starts_at - now < timedelta(hours=settings.late_cancel_window_hours)
    booking.status = BookingStatus.LATE_CANCELLED if late else BookingStatus.CANCELLED
    booking.cancelled_at = now
    db.flush()
    promoted = _promote_next(db, gym_class.id, now) if was_confirmed else None
    db.commit()
    return CancellationResult(booking, late, recent_strikes(db, booking.user_id, now, settings), promoted)


def my_bookings(db: Session, user: User, now: datetime, include_past: bool) -> list[schemas.BookingOut]:
    stmt = select(Booking).join(GymClass).where(Booking.user_id == user.id)
    if not include_past:
        stmt = stmt.where(GymClass.starts_at >= now)
    stmt = stmt.order_by(GymClass.starts_at, Booking.id)
    return [booking_out(db, b) for b in db.scalars(stmt)]


# --------------------------------------------------------------------------- reporting


def utilisation(db: Session, start: datetime, end: datetime) -> schemas.UtilisationReport:
    """Fill rate, waitlist demand and late cancellations per class type for classes in [start, end)."""
    classes = db.scalars(
        select(GymClass).where(
            GymClass.status == ClassStatus.SCHEDULED, GymClass.starts_at >= start, GymClass.starts_at < end
        )
    ).all()
    counts = {
        (cid, status): n
        for cid, status, n in db.execute(
            select(Booking.class_id, Booking.status, func.count()).group_by(Booking.class_id, Booking.status)
        )
    }
    agg: dict[str, dict[str, int]] = {}
    for c in classes:
        row = agg.setdefault(
            c.class_type,
            dict(sessions=0, capacity=0, confirmed=0, waitlisted=0, late_cancellations=0, sessions_full=0),
        )
        confirmed = counts.get((c.id, BookingStatus.CONFIRMED), 0)
        row["sessions"] += 1
        row["capacity"] += c.capacity
        row["confirmed"] += confirmed
        row["waitlisted"] += counts.get((c.id, BookingStatus.WAITLISTED), 0)
        row["late_cancellations"] += counts.get((c.id, BookingStatus.LATE_CANCELLED), 0)
        row["sessions_full"] += confirmed >= c.capacity
    rows = [
        schemas.UtilisationRow(
            class_type=k, fill_rate=round(v["confirmed"] / v["capacity"], 3) if v["capacity"] else 0.0, **v
        )
        for k, v in agg.items()
    ]
    rows.sort(key=lambda r: r.fill_rate, reverse=True)
    total_cap = sum(r.capacity for r in rows)
    overall = round(sum(r.confirmed for r in rows) / total_cap, 3) if total_cap else 0.0
    return schemas.UtilisationReport(period_start=start, period_end=end, rows=rows, overall_fill_rate=overall)
