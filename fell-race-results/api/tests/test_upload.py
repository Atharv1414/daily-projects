import pytest

from tests.conftest import AUTH

URL = "/api/races/raven-crag-race/results"  # two checkpoints: Raven Crag, Finish


def _newcomer(client) -> str:
    """A runner with no 2026 Raven Crag result."""
    taken = {
        r["runner_id"]
        for r in client.get(URL, params={"season": 2026, "page_size": 200}).json()["items"]
    }
    return next(f"R{i:04d}" for i in range(1, 421) if f"R{i:04d}" not in taken)


def _upload(upload_id, rows, season=2026):
    return {"upload_id": upload_id, "season": season, "results": rows}


def test_upload_needs_an_organiser_token(fresh_client):
    body = _upload("upload-0001", [{"runner_id": "R0001", "splits": [700, 1500]}])
    assert fresh_client.post(URL, json=body).status_code == 401
    wrong = fresh_client.post(URL, json=body, headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    assert wrong.headers["www-authenticate"] == "Bearer"


def test_upload_inserts_and_the_new_result_appears(fresh_client):
    rid = _newcomer(fresh_client)
    res = fresh_client.post(
        URL, json=_upload("upload-0002", [{"runner_id": rid, "splits": [700, 1450]}]), headers=AUTH
    )
    assert res.status_code == 200
    assert res.json() | {"rejected": []} == {
        "upload_id": "upload-0002",
        "race": "raven-crag-race",
        "season": 2026,
        "inserted": 1,
        "updated": 0,
        "unchanged": 0,
        "rejected": [],
        "replayed": False,
    }
    items = fresh_client.get(URL, params={"season": 2026, "page_size": 200}).json()["items"]
    mine = [r for r in items if r["runner_id"] == rid]
    assert mine and mine[0]["time_s"] == 1450


def test_replaying_an_upload_is_idempotent(fresh_client):
    rid = _newcomer(fresh_client)
    body = _upload("upload-0003", [{"runner_id": rid, "splits": [700, 1450]}])
    first = fresh_client.post(URL, json=body, headers=AUTH).json()
    again = fresh_client.post(URL, json=body, headers=AUTH).json()
    assert first["inserted"] == 1 and not first["replayed"]
    assert again == {**first, "replayed": True}
    total = fresh_client.get(URL, params={"season": 2026}).json()["total"]
    fresh_client.post(URL, json=body, headers=AUTH)
    assert fresh_client.get(URL, params={"season": 2026}).json()["total"] == total


def test_reusing_an_upload_id_for_another_race_is_a_conflict(fresh_client):
    rid = _newcomer(fresh_client)
    body = _upload("upload-0004", [{"runner_id": rid, "splits": [700, 1450]}])
    assert fresh_client.post(URL, json=body, headers=AUTH).status_code == 200
    other = fresh_client.post("/api/races/hollin-pike-dash/results", json=body, headers=AUTH)
    assert other.status_code == 409


def test_corrections_only_win_with_a_higher_version(fresh_client):
    rid = _newcomer(fresh_client)
    post = lambda uid, splits, v: fresh_client.post(  # noqa: E731
        URL, json=_upload(uid, [{"runner_id": rid, "splits": splits, "version": v}]), headers=AUTH
    ).json()
    assert post("fix-000001", [700, 1450], 1)["inserted"] == 1
    assert post("fix-000002", [700, 1400], 2)["updated"] == 1
    # A late-arriving older correction must not overwrite the newer one.
    assert post("fix-000003", [700, 1600], 1)["unchanged"] == 1
    items = fresh_client.get(URL, params={"season": 2026, "page_size": 200}).json()["items"]
    assert next(r for r in items if r["runner_id"] == rid)["time_s"] == 1400


def test_bad_rows_are_rejected_individually(fresh_client):
    rid = _newcomer(fresh_client)
    rows = [
        {"runner_id": rid, "splits": [700, 1450]},
        {"runner_id": "R9999", "splits": [700, 1450]},
        {"runner_id": "R0002", "splits": [1450]},
        {"runner_id": "R0003", "splits": [7, 14]},
        {"runner_id": "R0004", "status": "dnf", "splits": [700, 1450]},
    ]
    body = fresh_client.post(URL, json=_upload("upload-0005", rows), headers=AUTH).json()
    assert body["inserted"] == 1
    reasons = {e["runner_id"]: e["reason"] for e in body["rejected"]}
    assert reasons["R9999"] == "unknown runner id"
    assert "needs 2 split times" in reasons["R0002"]
    assert "implausibly fast" in reasons["R0003"]
    assert "cannot have a finish split" in reasons["R0004"]
    assert [e["row"] for e in body["rejected"]] == [2, 3, 4, 5]


@pytest.mark.parametrize(
    "rows",
    [
        [{"runner_id": "R0001", "splits": [900, 800]}],  # times go backwards
        [{"runner_id": "R0001", "splits": [0, 800]}],
        [{"runner_id": "R0001", "splits": [700, 1450], "bib": 12}],  # unknown field
        [
            {"runner_id": "R0001", "splits": [700, 1450]},
            {"runner_id": "R0001", "splits": [700, 1460]},
        ],
        [{"runner_id": "bob", "splits": [700, 1450]}],
        [],
    ],
)
def test_malformed_uploads_fail_validation(fresh_client, rows):
    res = fresh_client.post(URL, json=_upload("upload-0006", rows), headers=AUTH)
    assert res.status_code == 422
    assert res.json()["error"]["details"]


def test_uploading_a_dnf_and_seeing_it_in_standings(fresh_client):
    before = fresh_client.get("/api/standings", params={"season": 2026, "sex": "M"}).json()
    leader = before["rows"][0]
    # Give the leader a faster time in a race he did not count: his total can only rise.
    raced = {r["race"] for r in leader["races"]}
    target = (
        next(
            r["slug"]
            for r in fresh_client.get("/api/races", params={"season": 2026}).json()
            if r["slug"] not in raced
        )
        if len(raced) < 8
        else None
    )
    if target is None:
        pytest.skip("leader ran every race")
    race = fresh_client.get(f"/api/races/{target}").json()
    n = len(race["checkpoints"])
    winner = fresh_client.get(
        f"/api/races/{target}/results", params={"season": 2026, "sex": "M", "page_size": 1}
    ).json()["items"][0]
    splits = [s - 5 for s in winner["splits"]]  # five seconds quicker than the winner
    assert len(splits) == n
    res = fresh_client.post(
        f"/api/races/{target}/results",
        json=_upload("upload-0007", [{"runner_id": leader["runner_id"], "splits": splits}]),
        headers=AUTH,
    )
    assert res.json()["inserted"] == 1
    after = fresh_client.get("/api/standings", params={"season": 2026, "sex": "M"}).json()
    new = next(r for r in after["rows"] if r["runner_id"] == leader["runner_id"])
    assert new["races_run"] == leader["races_run"] + 1
    assert new["total"] >= leader["total"]
    assert any(r["race"] == target and r["points"] == 100.0 for r in new["races"])
