"""Gym Class Booking API.

A FastAPI service that lets gym members book fitness classes. It enforces class capacity,
keeps a first-in-first-out waitlist that promotes members automatically when a place frees up,
records late cancellations as strikes, and makes booking requests safe to retry with
idempotency keys.
"""

__version__ = "1.0.0"
