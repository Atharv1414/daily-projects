"""Shared fixtures: an app on an in-memory database with a controllable clock."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from gym_booking.clock import FixedClock
from gym_booking.config import Settings
from gym_booking.main import create_app
from gym_booking.models import Role
from gym_booking.services import create_user

NOW = datetime(2026, 12, 1, 8, 0)
PASSWORD = "correct-horse-1"


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite://",
        secret_key="test-secret-key-that-is-long-enough!!",
        password_iterations=1_000,
    )


@pytest.fixture
def app(settings: Settings, clock: FixedClock):
    app = create_app(settings, clock)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def login(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def staff(app, client: TestClient, settings: Settings, clock: FixedClock) -> dict[str, str]:
    with app.state.session_factory() as db:
        create_user(db, "manager@gym.example", "Manager", PASSWORD, Role.STAFF, settings, clock())
        db.commit()
    return login(client, "manager@gym.example")


@pytest.fixture
def member(client: TestClient) -> Callable[[str], dict[str, str]]:
    """Register a member and return auth headers for them."""

    def _make(name: str) -> dict[str, str]:
        email = f"{name.lower()}@members.example"
        resp = client.post("/auth/register", json={"email": email, "full_name": name, "password": PASSWORD})
        assert resp.status_code == 201, resp.text
        return login(client, email)

    return _make


@pytest.fixture
def make_class(client: TestClient, staff: dict[str, str]) -> Callable[..., dict]:
    """Schedule a class as staff (defaults: spin, 18:00 today, capacity 2)."""

    def _make(**overrides) -> dict:
        body = {
            "title": "Spin Express",
            "class_type": "spin",
            "coach": "Marcus Hale",
            "room": "Cycle Studio",
            "starts_at": "2026-12-01T18:00:00",
            "duration_minutes": 45,
            "capacity": 2,
        } | overrides
        resp = client.post("/classes", json=body, headers=staff)
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _make
