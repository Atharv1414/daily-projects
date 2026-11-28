"""Application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from . import __version__
from .clock import Clock, utc_now
from .config import DEV_SECRET_KEY, Settings
from .database import Base, make_engine, make_session_factory
from .errors import install_error_handlers
from .routers import auth, bookings, classes, reports

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, clock: Clock = utc_now) -> FastAPI:
    """Build a configured FastAPI app. Tests pass in-memory settings and a fixed clock."""
    settings = settings or Settings.from_env()
    if settings.secret_key == DEV_SECRET_KEY:
        logger.warning("Using the development JWT secret; set GYM_BOOKING_SECRET_KEY in production")

    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)

    app = FastAPI(
        title="Gym Class Booking API",
        version=__version__,
        description="Book fitness classes with capacity control, waitlists and fair cancellation rules.",
    )
    app.state.settings = settings
    app.state.clock = clock
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    install_error_handlers(app)
    for module in (auth, classes, bookings, reports):
        app.include_router(module.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app
