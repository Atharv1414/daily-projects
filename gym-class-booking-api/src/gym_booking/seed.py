"""Seeded synthetic data: a two-week timetable for a three-studio gym with realistic demand.

Demand is modelled per class type and time slot (evening spin and HIIT sell out; mid-day
pilates does not), so the utilisation report has a believable shape. The same seed always
produces the same data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from . import services
from .config import Settings
from .models import BookingStatus, GymClass, Role, User
from .security import hash_password

STAFF_EMAIL = "manager@ironworks.example"
STAFF_PASSWORD = "manager-password"
MEMBER_PASSWORD = "member-password"

FIRST = ["Aisha", "Ben", "Chloe", "Dev", "Ella", "Femi", "Grace", "Harry", "Isla", "Jay", "Kara", "Leo",
         "Maya", "Nate", "Olu", "Priya", "Quinn", "Rosa", "Sam", "Tom"]  # fmt: skip
LAST = ["Patel", "Smith", "Okafor", "Jones", "Khan", "Taylor", "Brown", "Nguyen", "Evans", "Ahmed"]

# (class_type, title, coach, room, capacity, base demand as a share of capacity)
CLASS_CATALOGUE = {
    "spin": ("Spin Express", "Marcus Hale", "Cycle Studio", 20, 1.05),
    "hiit": ("HIIT Blast", "Jade Okoro", "Studio 1", 16, 0.95),
    "yoga": ("Vinyasa Flow", "Lena Ward", "Studio 2", 18, 0.75),
    "pilates": ("Mat Pilates", "Lena Ward", "Studio 2", 14, 0.62),
    "strength": ("Barbell Strength", "Owen Price", "Studio 1", 12, 0.80),
    "boxing": ("Boxfit", "Jade Okoro", "Studio 1", 16, 0.70),
}
# (slot start, demand multiplier)
SLOTS = [(time(7, 0), 0.85), (time(12, 30), 0.55), (time(18, 0), 1.25), (time(19, 15), 1.05)]
# Which class types run in each slot on weekdays, by slot index; weekends use the morning pair only.
WEEKDAY_PLAN = [("spin", "yoga"), ("pilates", "strength"), ("hiit", "spin", "yoga"), ("boxing", "pilates")]
WEEKEND_PLAN = [("spin", "yoga"), ("hiit", "pilates")]
WEEKEND_SLOTS = [(time(9, 0), 1.1), (time(10, 30), 0.95)]


@dataclass(frozen=True)
class SeedSummary:
    members: int
    classes: int
    bookings: int
    late_cancellations: int


def seed(
    db: Session, settings: Settings, start: datetime, members: int = 120, seed_value: int = 42
) -> SeedSummary:
    """Populate an empty database. ``start`` is the moment the timetable is generated from."""
    rng = random.Random(seed_value)
    services.create_user(db, STAFF_EMAIL, "Gym Manager", STAFF_PASSWORD, Role.STAFF, settings, start)
    shared_hash = hash_password(MEMBER_PASSWORD, settings.password_iterations)  # one hash keeps seeding fast
    users = []
    for i in range(members):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        user = User(
            email=f"{first}.{last}.{i}@members.example".lower(),
            full_name=f"{first} {last}",
            password_hash=shared_hash,
            role=Role.MEMBER,
            created_at=start,
        )
        db.add(user)
        users.append(user)
    db.flush()

    classes: list[tuple[GymClass, float]] = []
    first_day = start.date() + timedelta(days=1)
    for offset in range(settings.booking_horizon_days - 1):  # last bookable full day
        day = first_day + timedelta(days=offset)
        weekend = day.weekday() >= 5
        plan, slots = (WEEKEND_PLAN, WEEKEND_SLOTS) if weekend else (WEEKDAY_PLAN, SLOTS)
        for (slot, slot_mult), types in zip(slots, plan, strict=True):
            for class_type in types:
                title, coach, room, capacity, demand = CLASS_CATALOGUE[class_type]
                gym_class = GymClass(
                    title=title,
                    class_type=class_type,
                    coach=coach,
                    room=room,
                    starts_at=datetime.combine(day, slot),
                    duration_minutes=45,
                    capacity=capacity,
                )
                db.add(gym_class)
                classes.append((gym_class, demand * slot_mult))
    db.commit()

    bookings = late = 0
    for gym_class, demand in classes:
        wanted = max(0, round(gym_class.capacity * demand * rng.uniform(0.8, 1.2)))
        wanted = min(wanted, gym_class.capacity + settings.max_waitlist, len(users))
        for user in rng.sample(users, wanted):
            services.book_class(db, user, gym_class.id, settings, start)
            bookings += 1

    # Some members cancel: most in good time, a few within the late window.
    active = db.query(services.Booking).filter(services.Booking.status == BookingStatus.CONFIRMED).all()
    for booking in rng.sample(active, k=len(active) // 12):
        starts_at = booking.gym_class.starts_at
        is_late = rng.random() < 0.35
        when = starts_at - (timedelta(minutes=rng.randint(20, 110)) if is_late else timedelta(days=1))
        user = db.get(User, booking.user_id)
        result = services.cancel_booking(db, user, booking.id, settings, max(when, start))
        late += result.late
    return SeedSummary(members, len(classes), bookings, late)
