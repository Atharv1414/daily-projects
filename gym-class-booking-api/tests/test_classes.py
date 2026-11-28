from .test_bookings import book


def test_list_filters_and_paginates(client, member, make_class):
    make_class(capacity=1)
    make_class(starts_at="2026-12-02T07:00:00", class_type="yoga", title="Flow", room="Studio 2")
    make_class(starts_at="2026-12-03T07:00:00")
    headers = member("Aisha")
    page = client.get("/classes", params={"limit": 2}, headers=headers).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert [c["starts_at"] for c in page["items"]] == sorted(c["starts_at"] for c in page["items"])
    yoga = client.get("/classes", params={"class_type": "YOGA"}, headers=headers).json()
    assert [c["title"] for c in yoga["items"]] == ["Flow"]
    window = client.get("/classes", params={"to": "2026-12-02T00:00:00"}, headers=headers).json()
    assert window["total"] == 1
    book(client, page["items"][0]["id"], headers)
    available = client.get("/classes", params={"available_only": True}, headers=headers).json()
    assert available["total"] == 2


def test_validation_rejects_bad_classes(client, staff):
    body = {"title": "X", "class_type": "zumba", "coach": "C", "room": "R",
            "starts_at": "2026-12-02T10:00:00", "duration_minutes": 45, "capacity": 5}  # fmt: skip
    assert client.post("/classes", json=body, headers=staff).status_code == 422
    past = body | {"class_type": "yoga", "starts_at": "2026-11-30T10:00:00"}
    assert client.post("/classes", json=past, headers=staff).json()["error"]["code"] == "class_in_past"
    tz = body | {"class_type": "yoga", "starts_at": "2026-12-02T10:00:00+01:00"}
    assert client.post("/classes", json=tz, headers=staff).json()["starts_at"] == "2026-12-02T09:00:00"


def test_room_double_booking_is_prevented(client, staff, make_class):
    make_class()  # Cycle Studio 18:00-18:45
    body = {"title": "Ride", "class_type": "spin", "coach": "C", "room": "Cycle Studio",
            "starts_at": "2026-12-01T18:30:00", "duration_minutes": 45, "capacity": 5}  # fmt: skip
    assert client.post("/classes", json=body, headers=staff).json()["error"]["code"] == "room_double_booked"
    body["starts_at"] = "2026-12-01T18:45:00"  # back-to-back is fine
    assert client.post("/classes", json=body, headers=staff).status_code == 201


def test_raising_capacity_promotes_waitlist(client, staff, member, make_class):
    cid = make_class(capacity=1)["id"]
    for name in ("Aisha", "Ben", "Chloe"):
        book(client, cid, member(name))
    resp = client.patch(f"/classes/{cid}", json={"capacity": 2, "coach": "Jade Okoro"}, headers=staff).json()
    assert (resp["booked"], resp["waitlist_length"], resp["coach"]) == (2, 1, "Jade Okoro")
    roster = client.get(f"/classes/{cid}/roster", headers=staff).json()
    assert [(r["full_name"], r["status"], r["waitlist_position"]) for r in roster] == [
        ("Aisha", "confirmed", None),
        ("Ben", "confirmed", None),
        ("Chloe", "waitlisted", 1),
    ]
    low = client.patch(f"/classes/{cid}", json={"capacity": 1}, headers=staff)
    assert low.status_code == 409 and low.json()["error"]["code"] == "capacity_below_bookings"


def test_moving_room_checks_for_clashes(client, staff, make_class):
    make_class(room="Studio 1", class_type="hiit", title="HIIT")
    cid = make_class()["id"]
    assert client.patch(f"/classes/{cid}", json={"room": "Studio 1"}, headers=staff).status_code == 409
    assert (
        client.patch(f"/classes/{cid}", json={"room": "Studio 3"}, headers=staff).json()["room"] == "Studio 3"
    )


def test_cancelling_a_class_cancels_its_bookings(client, staff, member, make_class):
    cid = make_class(capacity=1)["id"]
    aisha = member("Aisha")
    book(client, cid, aisha)
    book(client, cid, member("Ben"))
    resp = client.delete(f"/classes/{cid}", headers=staff).json()
    assert resp == {"class_id": cid, "bookings_cancelled": 2}
    assert client.get("/me/bookings", headers=aisha).json()[0]["status"] == "class_cancelled"
    assert book(client, cid, aisha).json()["error"]["code"] == "class_cancelled"
    assert client.delete(f"/classes/{cid}", headers=staff).status_code == 409
    assert client.patch(f"/classes/{cid}", json={"capacity": 5}, headers=staff).status_code == 409
    assert client.get("/classes", headers=aisha).json()["total"] == 0


def test_unknown_class_is_404(client, staff):
    resp = client.get("/classes/42", headers=staff)
    assert resp.status_code == 404
    assert resp.json() == {"error": {"code": "not_found", "message": "Class 42 does not exist"}}
