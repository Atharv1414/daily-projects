"""Tests that need a real MongoDB 7+ server. CI runs them with MONGO_URL set."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError, WriteError

from fell_results import standings
from fell_results.app import create_app
from fell_results.config import Settings
from fell_results.db import prepare
from fell_results.models import UploadIn
from fell_results.service import ClubService
from tests.conftest import AUTH

pytestmark = pytest.mark.mongo

SETTINGS = Settings(
    mongo_url="mongodb://unused", log_level="WARNING", organiser_tokens=(AUTH["Authorization"][7:],)
)


@pytest.fixture
def seeded(mongo_db):
    prepare(mongo_db, SETTINGS)
    return mongo_db


@pytest.mark.parametrize("season", [2024, 2025, 2026])
def test_aggregation_pipeline_matches_python_reference(seeded, season):
    docs = list(seeded.results.find({"season": season, "status": "finished"}, {"_id": 0}))
    expected = standings.compute(docs)
    actual = standings.from_pipeline(seeded.results.aggregate(standings.pipeline(season)))
    assert actual == expected


def test_results_page_query_uses_the_compound_index(seeded):
    plan = (
        seeded.results.find(
            {"race": "scar-edge-horseshoe", "season": 2026, "sex": "F", "status": "finished"}
        )
        .sort([("time_s", 1)])
        .limit(20)
        .explain()
    )
    text = str(plan["queryPlanner"]["winningPlan"])
    assert "race_season_sex_time" in text
    assert "SORT" not in text.replace("SORT_KEY", "")  # served in index order, no in-memory sort


def test_runner_prefix_search_uses_the_name_index(seeded):
    plan = seeded.runners.find({"name_lower": {"$regex": "^ruth"}}).explain()
    assert "name_lower" in str(plan["queryPlanner"]["winningPlan"])


def test_validator_rejects_documents_that_bypass_the_api(seeded):
    with pytest.raises(WriteError):
        seeded.results.insert_one(
            {
                "race": "x",
                "season": 2026,
                "runner_id": "nobody",
                "sex": "F",
                "category": "Open",
                "status": "finished",
                "splits": [1],
            }
        )


def test_unique_index_blocks_a_second_result_for_the_same_runner(seeded):
    doc = seeded.results.find_one({}, {"_id": 0})
    with pytest.raises(DuplicateKeyError):
        seeded.results.insert_one(doc)


def test_migrations_are_idempotent(seeded):
    prepare(seeded, SETTINGS)
    assert seeded.meta.find_one({"_id": "schema"})["version"] == 2


def test_concurrent_replays_of_one_upload_write_once(seeded):
    service = ClubService(seeded)
    taken = set(seeded.results.distinct("runner_id", {"race": "raven-crag-race", "season": 2026}))
    rid = next(f"R{i:04d}" for i in range(1, 421) if f"R{i:04d}" not in taken)
    body = UploadIn(
        upload_id="race-condition-1",
        season=2026,
        results=[{"runner_id": rid, "splits": [700, 1450]}],
    )

    with ThreadPoolExecutor(max_workers=6) as pool:
        replies = list(pool.map(lambda _: service.upload("raven-crag-race", body, "t"), range(6)))
    assert seeded.uploads.count_documents({"upload_id": "race-condition-1"}) == 1
    assert seeded.results.count_documents({"race": "raven-crag-race", "runner_id": rid}) == 1
    assert sum(not r.replayed for r in replies) == 1


def test_api_on_real_mongo_serves_pipeline_standings(seeded):
    client = TestClient(create_app(SETTINGS, db=seeded))
    body = client.get("/api/standings", params={"season": 2026, "sex": "F"}).json()
    docs = list(seeded.results.find({"season": 2026, "status": "finished"}, {"_id": 0}))
    expected = [r for r in standings.compute(docs) if r["sex"] == "F"]
    assert body["rows"] == expected
