"""An end-to-end walkthrough against an in-memory database, printed as HTTP calls and responses."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi.testclient import TestClient

from .clock import FixedClock
from .config import Settings
from .main import create_app
from .seed import STAFF_EMAIL, STAFF_PASSWORD, seed

DEMO_START = datetime(2026, 12, 1, 8, 0)
DEMO_SECRET = "demo-secret-key-for-local-walkthroughs-only"


def _show(method: str, path: str, resp, keys: tuple[str, ...] | None = None) -> dict:
    body = resp.json()
    shown = {k: body[k] for k in keys if k in body} if keys and isinstance(body, dict) else body
    replay = "  (Idempotent-Replay)" if resp.headers.get("Idempotent-Replay") else ""
    print(f"{method:<6} {path:<32} -> {resp.status_code}{replay}")
    print("       " + json.dumps(shown, default=str))
    return body


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    token = client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def run_demo() -> None:
    """Walk through booking, idempotent retry, waitlist, late cancellation and promotion."""
    clock = FixedClock(DEMO_START)
    settings = Settings(database_url="sqlite://", secret_key=DEMO_SECRET, password_iterations=10_000)
    client = TestClient(create_app(settings, clock))
    with client.app.state.session_factory() as db:
        from .models import Role
        from .services import create_user

        create_user(db, STAFF_EMAIL, "Gym Manager", STAFF_PASSWORD, Role.STAFF, settings, clock())
        db.commit()
    staff = _login(client, STAFF_EMAIL, STAFF_PASSWORD)

    print(f"Clock: {clock():%a %d %b %Y %H:%M}\n")
    new_class = {
        "title": "Spin Express", "class_type": "spin", "coach": "Marcus Hale", "room": "Cycle Studio",
        "starts_at": "2026-12-01T18:00:00", "duration_minutes": 45, "capacity": 2,
    }  # fmt: skip
    cls = _show("POST", "/classes", client.post("/classes", json=new_class, headers=staff),
                ("id", "title", "starts_at", "capacity", "spots_left"))  # fmt: skip
    cid = cls["id"]

    members = {}
    for name in ("Aisha Khan", "Ben Smith", "Chloe Okafor"):
        email = name.split()[0].lower() + "@members.example"
        client.post("/auth/register", json={"email": email, "full_name": name, "password": "correct-horse-1"})
        members[name.split()[0]] = _login(client, email, "correct-horse-1")
    print(f"{'POST':<6} {'/auth/register + /auth/login x3':<32} -> 201, 200\n")

    keys = ("id", "status", "waitlist_position")
    path = f"/classes/{cid}/bookings"
    retry = {**members["Aisha"], "Idempotency-Key": "aisha-7f3c"}
    _show("POST", path + " (Aisha)", client.post(path, headers=retry), keys)
    _show("POST", path + " (Aisha retry)", client.post(path, headers=retry), keys)
    ben = _show("POST", path + " (Ben)", client.post(path, headers=members["Ben"]), keys)
    _show("POST", path + " (Chloe)", client.post(path, headers=members["Chloe"]), keys)
    _show("POST", path + " (Ben again)", client.post(path, headers=members["Ben"]))
    _show("GET", f"/classes/{cid}", client.get(f"/classes/{cid}", headers=staff),
          ("capacity", "booked", "spots_left", "waitlist_length"))  # fmt: skip

    clock.advance(hours=8, minutes=30)
    print(f"\nClock: {clock():%H:%M} (90 minutes before the class)\n")
    _show("GET", "/me (token from 08:00)", client.get("/me", headers=members["Ben"]))
    members = {n: _login(client, n.lower() + "@members.example", "correct-horse-1") for n in members}
    staff = _login(client, STAFF_EMAIL, STAFF_PASSWORD)
    print(f"{'POST':<6} {'/auth/login x4 (fresh tokens)':<32} -> 200")
    resp = client.delete(f"/bookings/{ben['id']}", headers=members["Ben"])
    _show(
        "DELETE", f"/bookings/{ben['id']} (Ben)", resp, ("late", "strikes_in_window", "promoted_booking_id")
    )
    _show("GET", "/me/bookings (Chloe)", client.get("/me/bookings", headers=members["Chloe"]))
    roster = client.get(f"/classes/{cid}/roster", headers=staff).json()
    print(f"{'GET':<6} {f'/classes/{cid}/roster':<32} -> 200")
    for row in roster:
        print(f"       {row['full_name']:<14} {row['status']}")
    _show("GET", "/classes (no token)", client.get("/classes"))
    client.app.state.engine.dispose()


def run_report(members: int = 120) -> None:
    """Seed a 13-day synthetic timetable and print the utilisation report."""
    clock = FixedClock(DEMO_START)
    settings = Settings(database_url="sqlite://", secret_key=DEMO_SECRET, password_iterations=10_000)
    app = create_app(settings, clock)
    with app.state.session_factory() as db:
        summary = seed(db, settings, clock(), members=members)
    print(
        f"Seeded {summary.members} members, {summary.classes} classes, {summary.bookings} booking requests, "
        f"{summary.late_cancellations} late cancellations\n"
    )
    client = TestClient(app)
    staff = _login(client, STAFF_EMAIL, STAFF_PASSWORD)
    report = client.get(
        "/reports/utilisation",
        params={"from": "2026-12-02T00:00:00", "to": "2026-12-15T00:00:00"},
        headers=staff,
    ).json()
    header = f"{'class_type':<10} {'sessions':>8} {'capacity':>8} {'confirmed':>9} {'fill':>6} {'full':>5} "
    print(header + f"{'waitlist':>8} {'late_cxl':>8}")
    for r in report["rows"]:
        print(
            f"{r['class_type']:<10} {r['sessions']:>8} {r['capacity']:>8} {r['confirmed']:>9} "
            f"{r['fill_rate']:>6.1%} {r['sessions_full']:>5} "
            f"{r['waitlisted']:>8} {r['late_cancellations']:>8}"
        )
    print(f"\nOverall fill rate: {report['overall_fill_rate']:.1%}")
    app.state.engine.dispose()
