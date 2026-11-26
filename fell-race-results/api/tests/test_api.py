import pytest


def test_health_lists_seasons(client):
    body = client.get("/api/health").json()
    assert body == {"status": "ok", "seasons": [2024, 2025, 2026]}


def test_races_are_in_calendar_order_with_winners(client):
    races = client.get("/api/races", params={"season": 2025}).json()
    assert [r["date"][:7] for r in races] == sorted(r["date"][:7] for r in races)
    assert len(races) == 8
    for r in races:
        assert r["date"].startswith("2025-")
        assert r["finishers"] > 50
        assert r["winning_time_f"] > r["winning_time_m"] > 0
        assert len(r["profile"]) == 64


def test_unknown_race_is_a_404_with_a_consistent_error_body(client):
    res = client.get("/api/races/no-such-race")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "url",
    [
        "/api/races/BAD_SLUG!",
        "/api/races/scar-edge-horseshoe/results?page=0",
        "/api/races/scar-edge-horseshoe/results?page_size=500",
        "/api/races/scar-edge-horseshoe/results?sex=X",
        "/api/standings?category=V45",
        "/api/runners?q=a",
        "/api/runners/7",
        "/api/ghost?race=scar-edge-horseshoe&runners=R1,R2",
        "/api/ghost?race=scar-edge-horseshoe&runners=R0001,R0002,R0003,R0004,R0005",
    ],
)
def test_bad_input_is_rejected_with_422(client, url):
    res = client.get(url)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid"


def test_results_are_paged_and_positions_continue(client):
    url = "/api/races/beckside-round/results"
    first = client.get(url, params={"season": 2026, "page_size": 40}).json()
    second = client.get(url, params={"season": 2026, "page_size": 40, "page": 2}).json()
    assert first["total"] == second["total"] > 80
    assert [r["position"] for r in first["items"]] == list(range(1, 41))
    assert second["items"][0]["position"] == 41
    times = [r["time_s"] for r in first["items"] + second["items"]]
    assert times == sorted(times)


def test_dnfs_come_last_without_a_position(client):
    body = client.get(
        "/api/races/three-tarns-traverse/results", params={"season": 2026, "page_size": 200}
    ).json()
    items = body["items"]
    dnf = [r for r in items if r["status"] == "dnf"]
    assert dnf, "the long race should have some retirements"
    assert all(r["position"] is None and r["time_s"] is None for r in dnf)
    assert items[-len(dnf) :] == dnf
    assert len(items) == body["total"]


def test_results_filter_by_sex_and_category(client):
    body = client.get(
        "/api/races/gill-head-gallop/results",
        params={"season": 2026, "sex": "F", "category": "V50", "page_size": 200},
    ).json()
    assert body["items"]
    assert {(r["sex"], r["category"]) for r in body["items"]} == {("F", "V50")}


def test_standings_rank_and_filter(client):
    women = client.get("/api/standings", params={"season": 2026, "sex": "F"}).json()
    rows = women["rows"]
    assert rows[0]["rank"] == 1 and women["best_of"] == 5
    assert [r["total"] for r in rows] == sorted((r["total"] for r in rows), reverse=True)
    assert all(sum(x["counted"] for x in r["races"]) == min(5, r["races_run"]) for r in rows)
    v60 = client.get(
        "/api/standings", params={"season": 2026, "sex": "F", "category": "V60"}
    ).json()
    assert [r["category_rank"] for r in v60["rows"]] == list(range(1, len(v60["rows"]) + 1))
    assert {r["category"] for r in v60["rows"]} == {"V60"}


def test_runner_search_matches_first_names_and_surnames(client):
    by_first = client.get("/api/runners", params={"q": "Ruth"}).json()
    assert by_first and all(r["name"].startswith("Ruth") for r in by_first)
    by_surname = client.get("/api/runners", params={"q": "postle"}).json()
    assert by_surname and all("Postlethwaite" in r["name"] for r in by_surname)
    assert client.get("/api/runners", params={"q": "zz"}).json() == []


def test_runner_profile_has_history_and_personal_bests(client):
    body = client.get("/api/runners/R0090").json()
    assert body["runner"]["name"] == "Hamish MacLeod"
    seasons = [r["season"] for r in body["results"]]
    assert seasons == sorted(seasons, reverse=True)
    for race, best in body["personal_bests"].items():
        times = [r["time_s"] for r in body["results"] if r["race"] == race and r["time_s"]]
        assert best == min(times)
    finished = [r for r in body["results"] if r["status"] == "finished"]
    assert all(1 <= r["position"] <= r["finishers"] for r in finished)
    assert client.get("/api/runners/R9999").status_code == 404


def test_ghost_returns_both_runners_splits_against_checkpoints(client):
    body = client.get(
        "/api/ghost",
        params={"race": "scar-edge-horseshoe", "season": 2026, "runners": "R0090,R0084"},
    ).json()
    assert [cp["name"] for cp in body["checkpoints"]][-1] == "Finish"
    hamish, ewan = body["runners"]
    assert len(hamish["splits"]) == len(body["checkpoints"])
    # The story the website tells: Hamish leads at Cairn Top, Ewan wins on the descent.
    assert hamish["splits"][2] < ewan["splits"][2]
    assert ewan["time_s"] < hamish["time_s"]
    missing = client.get(
        "/api/ghost", params={"race": "scar-edge-horseshoe", "runners": "R0090,R0420"}
    )
    assert missing.status_code in {200, 404}


def test_records_are_the_fastest_ever_times(client):
    records = client.get("/api/records").json()
    assert len(records) == 16
    for rec in records[:4]:
        all_seasons = []
        for season in (2024, 2025, 2026):
            page = client.get(
                f"/api/races/{rec['race']}/results",
                params={"season": season, "sex": rec["sex"], "page_size": 1},
            ).json()
            all_seasons.append(page["items"][0]["time_s"])
        assert rec["time_s"] == min(all_seasons)


def test_responses_carry_request_id_and_timing(client):
    res = client.get("/api/health", headers={"x-request-id": "abc123"})
    assert res.headers["x-request-id"] == "abc123"
    assert res.headers["server-timing"].startswith("app;dur=")


def test_openapi_documents_every_route(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/races", "/api/standings", "/api/ghost", "/api/races/{slug}/results"):
        assert p in paths
