import re

from gym_booking.__main__ import main
from gym_booking.seed import STAFF_EMAIL, STAFF_PASSWORD, seed

from .conftest import login
from .test_bookings import book


def test_utilisation_report_aggregates_by_class_type(client, staff, member, make_class):
    spin = make_class(capacity=2)["id"]
    make_class(class_type="yoga", title="Flow", room="Studio 2", capacity=4)
    for name in ("Aisha", "Ben", "Chloe"):
        book(client, spin, member(name))
    report = client.get("/reports/utilisation", headers=staff).json()
    rows = {r["class_type"]: r for r in report["rows"]}
    assert (rows["spin"]["fill_rate"], rows["spin"]["sessions_full"], rows["spin"]["waitlisted"]) == (
        1.0,
        1,
        1,
    )
    assert rows["yoga"]["fill_rate"] == 0.0
    assert report["rows"][0]["class_type"] == "spin"  # sorted by fill rate
    assert report["overall_fill_rate"] == round(2 / 6, 3)


def test_report_rejects_inverted_range(client, staff):
    params = {"from": "2026-12-05T00:00:00", "to": "2026-12-04T00:00:00"}
    assert client.get("/reports/utilisation", params=params, headers=staff).status_code == 400


def test_seed_is_reproducible_and_respects_rules(app, settings, clock):
    with app.state.session_factory() as db:
        summary = seed(db, settings, clock(), members=40, seed_value=7)
    assert summary.classes == 97 and summary.bookings > 0
    from fastapi.testclient import TestClient

    client = TestClient(app)
    staff = login(client, STAFF_EMAIL, STAFF_PASSWORD)
    report = client.get(
        "/reports/utilisation",
        params={"from": "2026-12-01T00:00:00", "to": "2026-12-20T00:00:00"},
        headers=staff,
    ).json()
    assert sum(r["sessions"] for r in report["rows"]) == 97
    assert all(0 <= r["fill_rate"] <= 1 for r in report["rows"])
    assert all(r["waitlisted"] == 0 or r["sessions_full"] > 0 for r in report["rows"])


def test_cli_demo_and_report(capsys):
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "Idempotent-Replay" in out and '"late": true' in out and "promoted_booking_id" in out
    assert main(["report", "--members", "60"]) == 0
    assert "Overall fill rate" in capsys.readouterr().out


def test_cli_seed_writes_to_configured_database(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GYM_BOOKING_DATABASE_URL", f"sqlite:///{tmp_path / 'gym.db'}")
    assert main(["seed", "--members", "20"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"Seeded \d+ classes and 20 members", out), out
    assert (tmp_path / "gym.db").exists()
