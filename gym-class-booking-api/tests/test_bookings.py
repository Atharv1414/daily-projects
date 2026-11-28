from .conftest import login


def book(client, class_id, headers, key=None):
    if key:
        headers = {**headers, "Idempotency-Key": key}
    return client.post(f"/classes/{class_id}/bookings", headers=headers)


def test_books_until_full_then_waitlists_in_order(client, member, make_class):
    cid = make_class(capacity=2)["id"]
    results = [book(client, cid, member(n)).json() for n in ("Aisha", "Ben", "Chloe", "Dev")]
    assert [r["status"] for r in results] == ["confirmed", "confirmed", "waitlisted", "waitlisted"]
    assert [r["waitlist_position"] for r in results] == [None, None, 1, 2]
    info = client.get(f"/classes/{cid}", headers=member("Ella")).json()
    assert (info["booked"], info["spots_left"], info["waitlist_length"]) == (2, 0, 2)


def test_waitlist_has_a_cap(client, member, make_class, settings):
    cid = make_class(capacity=1)["id"]
    for i in range(1 + settings.max_waitlist):
        assert book(client, cid, member(f"m{i}")).status_code == 201
    resp = book(client, cid, member("late"))
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "class_full"


def test_cannot_double_book(client, member, make_class):
    cid = make_class()["id"]
    headers = member("Aisha")
    assert book(client, cid, headers).status_code == 201
    resp = book(client, cid, headers)
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "already_booked"


def test_idempotency_key_replays_original_booking(client, member, make_class):
    cid = make_class()["id"]
    headers = member("Aisha")
    first = book(client, cid, headers, key="abc-123")
    retry = book(client, cid, headers, key="abc-123")
    assert first.status_code == 201 and retry.status_code == 200
    assert retry.headers["Idempotent-Replay"] == "true"
    assert retry.json()["id"] == first.json()["id"]
    other = make_class(room="Studio 1", class_type="hiit", title="HIIT")["id"]
    reused = book(client, other, headers, key="abc-123")
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "idempotency_key_reused"


def test_cancelling_confirmed_place_promotes_first_waitlisted(client, member, make_class):
    cid = make_class(capacity=1)["id"]
    aisha, ben, chloe = member("Aisha"), member("Ben"), member("Chloe")
    booking_id = book(client, cid, aisha).json()["id"]
    ben_booking = book(client, cid, ben).json()["id"]
    book(client, cid, chloe)
    resp = client.delete(f"/bookings/{booking_id}", headers=aisha).json()
    assert resp["late"] is False and resp["booking"]["status"] == "cancelled"
    assert resp["promoted_booking_id"] == ben_booking
    mine = client.get("/me/bookings", headers=ben).json()
    assert mine[0]["status"] == "confirmed" and mine[0]["promoted_at"] is not None
    assert client.get("/me/bookings", headers=chloe).json()[0]["waitlist_position"] == 1


def test_leaving_waitlist_promotes_nobody_and_is_never_late(client, member, make_class, clock):
    cid = make_class(capacity=1)["id"]
    book(client, cid, member("Aisha"))
    ben = member("Ben")
    ben_id = book(client, cid, ben).json()["id"]
    clock.advance(hours=9, minutes=30)
    ben = login(client, "ben@members.example")
    resp = client.delete(f"/bookings/{ben_id}", headers=ben).json()
    assert resp["late"] is False and resp["promoted_booking_id"] is None and resp["strikes_in_window"] == 0


def test_late_cancellation_records_a_strike(client, member, make_class, clock):
    cid = make_class()["id"]
    booking_id = book(client, cid, member("Aisha")).json()["id"]
    clock.advance(hours=8, minutes=30)  # 16:30, 90 minutes before an 18:00 class
    resp = client.delete(f"/bookings/{booking_id}", headers=login(client, "aisha@members.example"))
    assert resp.json()["late"] is True
    assert resp.json()["booking"]["status"] == "late_cancelled"
    assert resp.json()["strikes_in_window"] == 1


def _schedule(client, starts_at: str) -> int:
    """Create a class with a fresh staff token (fixture tokens expire as the clock moves)."""
    body = {"title": "Flow", "class_type": "yoga", "coach": "Lena Ward", "room": "Studio 2",
            "starts_at": starts_at, "duration_minutes": 60, "capacity": 10}  # fmt: skip
    resp = client.post("/classes", json=body, headers=login(client, "manager@gym.example"))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_three_late_cancellations_suspend_booking_until_they_expire(client, staff, member, clock):
    member("Aisha")
    for day in (2, 3, 4):
        cid = _schedule(client, f"2026-12-0{day}T18:00:00")
        booking_id = book(client, cid, login(client, "aisha@members.example")).json()["id"]
        clock.now = clock.now.replace(day=day, hour=17)  # one hour before start
        client.delete(f"/bookings/{booking_id}", headers=login(client, "aisha@members.example"))
    cid = _schedule(client, "2026-12-06T09:00:00")
    resp = book(client, cid, login(client, "aisha@members.example"))
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "booking_suspended"

    clock.now = clock.now.replace(year=2027, month=1, day=3)  # first strike is now 30+ days old
    cid = _schedule(client, "2027-01-04T09:00:00")
    assert book(client, cid, login(client, "aisha@members.example")).status_code == 201


def test_booking_window_and_started_classes(client, member, make_class, clock):
    far = make_class(starts_at="2026-12-20T18:00:00")["id"]
    soon = make_class(starts_at="2026-12-01T09:00:00", room="Studio 1", class_type="hiit", title="HIIT")["id"]
    headers = member("Aisha")
    assert book(client, far, headers).json()["error"]["code"] == "outside_booking_window"
    booking_id = book(client, soon, headers).json()["id"]
    clock.advance(hours=1, minutes=5)
    headers = login(client, "aisha@members.example")
    assert book(client, soon, member("Ben")).json()["error"]["code"] == "class_started"
    assert (
        client.delete(f"/bookings/{booking_id}", headers=headers).json()["error"]["code"] == "class_started"
    )


def test_members_cannot_touch_each_others_bookings(client, member, make_class):
    cid = make_class()["id"]
    booking_id = book(client, cid, member("Aisha")).json()["id"]
    resp = client.delete(f"/bookings/{booking_id}", headers=member("Ben"))
    assert resp.status_code == 404
    assert client.delete("/bookings/999", headers=member("Chloe")).status_code == 404


def test_cancelling_twice_conflicts(client, member, make_class):
    cid = make_class()["id"]
    headers = member("Aisha")
    booking_id = book(client, cid, headers).json()["id"]
    client.delete(f"/bookings/{booking_id}", headers=headers)
    assert client.delete(f"/bookings/{booking_id}", headers=headers).json()["error"]["code"] == "not_active"
    assert book(client, cid, headers).status_code == 201  # can rebook after cancelling


def test_my_bookings_hides_past_unless_asked(client, member, make_class, clock):
    early = make_class(starts_at="2026-12-01T09:00:00", room="Studio 1", class_type="hiit", title="HIIT")[
        "id"
    ]
    later = make_class()["id"]
    headers = member("Aisha")
    book(client, early, headers)
    book(client, later, headers)
    clock.advance(hours=2)
    headers = login(client, "aisha@members.example")
    assert [b["class_id"] for b in client.get("/me/bookings", headers=headers).json()] == [later]
    all_ = client.get("/me/bookings", params={"include_past": True}, headers=headers).json()
    assert [b["class_id"] for b in all_] == [early, later]
