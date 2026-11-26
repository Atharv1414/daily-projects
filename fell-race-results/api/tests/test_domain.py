from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fell_results import standings
from fell_results.config import DEMO_TOKEN, Settings
from fell_results.models import age_category
from fell_results.seed import generate, race_date


@pytest.mark.parametrize(
    ("birth_year", "season", "expected"),
    [
        (1990, 2026, "Open"),
        (1987, 2026, "Open"),
        (1986, 2026, "V40"),
        (1976, 2026, "V50"),
        (1966, 2026, "V60"),
        (1956, 2026, "V70"),
        (1940, 2026, "V70"),
    ],
)
def test_age_category_uses_age_at_end_of_season(birth_year, season, expected):
    assert age_category(birth_year, season) == expected


def test_race_date_is_second_saturday():
    assert race_date(2026, 5) == date(2026, 5, 9)
    assert race_date(2026, 8).weekday() == 5
    assert 8 <= race_date(2025, 3).day <= 14


def test_seed_is_deterministic_and_realistic():
    a, b = generate(2026), generate(2026)
    assert a == b
    assert generate(1) != a
    assert len(a["races"]) == 8 and len(a["runners"]) == 420
    assert 3000 < len(a["results"]) < 4500
    dnf = [r for r in a["results"] if r["status"] == "dnf"]
    assert 0.01 < len(dnf) / len(a["results"]) < 0.06
    races = {r["slug"]: r for r in a["races"]}
    for r in a["results"]:
        expected = len(races[r["race"]]["checkpoints"])
        if r["status"] == "finished":
            assert len(r["splits"]) == expected and r["time_s"] == r["splits"][-1]
        else:
            assert len(r["splits"]) < expected and r["time_s"] is None
        assert r["splits"] == sorted(r["splits"])


def test_profiles_climb_what_the_race_says():
    for race in generate(2026)["races"]:
        heights = [h for _, h in race["profile"]]
        ascent = sum(max(0.0, b - a) for a, b in zip(heights, heights[1:], strict=False))
        assert ascent == pytest.approx(race["climb_m"], rel=0.02)
        assert race["profile"][-1][0] == pytest.approx(race["distance_km"])


def _res(race, runner, time_s, sex="F", category="Open", status="finished"):
    return {
        "race": race,
        "runner_id": runner,
        "name": runner,
        "sex": sex,
        "category": category,
        "club": "C",
        "status": status,
        "time_s": time_s,
    }


def test_scoring_gives_winner_100_and_counts_best_five():
    rows = []
    for i, race in enumerate("abcdefg"):  # seven races: worst two are dropped
        rows.append(_res(race, "R0001", 1000))
        rows.append(_res(race, "R0002", 1000 + 100 * i))
    table = {r["runner_id"]: r for r in standings.compute(rows)}
    assert table["R0001"]["total"] == 500.0
    two = table["R0002"]
    assert two["races_run"] == 7
    assert [r["counted"] for r in two["races"]] == [True] * 5 + [False] * 2
    assert two["total"] == round(sum(r["points"] for r in two["races"][:5]), 1)
    assert two["races"][0]["points"] == 100.0  # tied with the winner in race a
    assert table["R0001"]["rank"] == 1 and two["rank"] == 2


def test_scoring_is_per_sex_and_ties_share_a_position():
    rows = [
        _res("a", "R0001", 1200, "F"),
        _res("a", "R0002", 1000, "M"),
        _res("a", "R0003", 1200, "F"),
        _res("a", "R0004", 1500, "F", "V50"),
        _res("a", "R0005", 900, "F", status="dnf"),
    ]
    table = {r["runner_id"]: r for r in standings.compute(rows)}
    assert table["R0001"]["races"][0]["points"] == 100.0  # men do not set women's points
    assert table["R0003"]["races"][0]["position"] == 1  # tie
    assert table["R0004"]["races"][0]["position"] == 3
    assert table["R0004"]["category_rank"] == 1
    assert "R0005" not in table  # DNFs score nothing


@given(st.lists(st.integers(min_value=600, max_value=9000), min_size=1, max_size=10))
def test_total_is_bounded_and_never_drops_when_a_race_is_added(times):
    rows = [_res(f"race{i}", "R0001", t) for i, t in enumerate(times)]
    rows += [_res(f"race{i}", "R0002", 600) for i in range(len(times) + 1)]
    before = {r["runner_id"]: r for r in standings.compute(rows)}["R0001"]["total"]
    assert 0 < before <= 100 * standings.BEST_OF
    rows.append(_res(f"race{len(times)}", "R0001", 3000))
    after = {r["runner_id"]: r for r in standings.compute(rows)}["R0001"]["total"]
    assert after >= before


def test_settings_from_env_and_demo_token_only_in_memory():
    s = Settings.from_env({"FELL_ORGANISER_TOKENS": "a, b ,", "FELL_SEED": "7"})
    assert s.organiser_tokens == ("a", "b") and s.seed == 7 and s.in_memory
    assert Settings.from_env({}).tokens() == (DEMO_TOKEN,)
    assert Settings.from_env({"MONGO_URL": "mongodb://db"}).tokens() == ()
