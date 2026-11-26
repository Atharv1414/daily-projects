"""MongoDB connection, schema validators, indexes and versioned migrations."""

from __future__ import annotations

import logging
from collections.abc import Callable

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.database import Database
from pymongo.errors import CollectionInvalid, OperationFailure

from .config import Settings
from .seed import generate

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2

RESULT_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["race", "season", "runner_id", "sex", "category", "status", "splits"],
        "properties": {
            "race": {"bsonType": "string"},
            "season": {"bsonType": "int", "minimum": 2000, "maximum": 2100},
            "runner_id": {"bsonType": "string", "pattern": "^R[0-9]{4}$"},
            "sex": {"enum": ["F", "M"]},
            "category": {"enum": ["Open", "V40", "V50", "V60", "V70"]},
            "status": {"enum": ["finished", "dnf"]},
            "time_s": {"bsonType": ["int", "null"], "minimum": 1},
            "splits": {"bsonType": "array", "minItems": 1, "items": {"bsonType": "int"}},
            "version": {"bsonType": "int", "minimum": 1},
        },
    }
}

RUNNER_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["name", "name_lower", "sex", "birth_year", "club"],
        "properties": {
            "sex": {"enum": ["F", "M"]},
            "birth_year": {"bsonType": "int", "minimum": 1900, "maximum": 2020},
        },
    }
}


def connect(settings: Settings) -> Database:
    """A real MongoDB database, or an in-memory mongomock one when MONGO_URL is unset."""
    if settings.in_memory:
        import mongomock  # dev dependency: only needed for the in-memory demo and tests

        return mongomock.MongoClient(tz_aware=True)[settings.database]
    from pymongo import MongoClient

    client: MongoClient = MongoClient(
        settings.mongo_url, serverSelectionTimeoutMS=5000, tz_aware=True
    )
    return client[settings.database]


def is_real_mongo(db: Database) -> bool:
    return type(db).__module__.startswith("pymongo")


def _create(db: Database, name: str, validator: dict | None) -> None:
    if not is_real_mongo(db):
        validator = None  # mongomock has no $jsonSchema; Pydantic still validates every write
    try:
        if validator is None:
            db.create_collection(name)
        else:
            db.create_collection(name, validator=validator, validationLevel="strict")
    except CollectionInvalid:
        if validator is not None and is_real_mongo(db):
            db.command("collMod", name, validator=validator, validationLevel="strict")


def _v1(db: Database) -> None:
    _create(db, "races", None)
    _create(db, "runners", RUNNER_VALIDATOR)
    _create(db, "results", RESULT_VALIDATOR)
    db.results.create_indexes(
        [
            # One result per runner per race per season: makes uploads idempotent upserts.
            IndexModel(
                [("race", ASCENDING), ("season", ASCENDING), ("runner_id", ASCENDING)],
                unique=True,
                name="race_season_runner",
            ),
            # Race result pages: filter by race+season(+sex), sorted by time.
            IndexModel(
                [
                    ("race", ASCENDING),
                    ("season", ASCENDING),
                    ("sex", ASCENDING),
                    ("time_s", ASCENDING),
                ],
                name="race_season_sex_time",
            ),
            # Championship and runner history.
            IndexModel([("season", ASCENDING), ("status", ASCENDING)], name="season_status"),
            IndexModel([("runner_id", ASCENDING), ("season", DESCENDING)], name="runner_history"),
        ]
    )
    # Anchored, case-folded prefix search ("^ruth") can use this index; $regex /i cannot.
    db.runners.create_index([("name_lower", ASCENDING)], name="name_lower")


def _v2(db: Database) -> None:
    _create(db, "uploads", None)
    db.uploads.create_index([("upload_id", ASCENDING)], unique=True, name="upload_id")


MIGRATIONS: dict[int, Callable[[Database], None]] = {1: _v1, 2: _v2}


def migrate(db: Database) -> int:
    """Applies migrations newer than the stored schema version. Safe to run repeatedly."""
    meta = db.meta.find_one({"_id": "schema"}) or {"version": 0}
    current = int(meta["version"])
    for version in sorted(v for v in MIGRATIONS if v > current):
        log.info("applying migration", extra={"version": version})
        MIGRATIONS[version](db)
        db.meta.update_one({"_id": "schema"}, {"$set": {"version": version}}, upsert=True)
        current = version
    return current


def seed(db: Database, seed_value: int) -> dict[str, int]:
    """Loads the synthetic club data if the database is empty. Returns document counts."""
    if db.races.estimated_document_count() == 0:
        data = generate(seed_value)
        for name, docs in data.items():
            if docs:
                db[name].insert_many(docs, ordered=False)
        log.info("seeded database", extra={k: len(v) for k, v in data.items()})
    return {name: db[name].count_documents({}) for name in ("races", "runners", "results")}


def prepare(db: Database, settings: Settings) -> None:
    """Seeds an empty database (if asked), then brings its schema up to date.

    Bulk-loading before building indexes is the usual order for a fresh database: one index
    build is cheaper than maintaining the index on every insert (and much cheaper on
    mongomock, whose unique-index check is quadratic). The seed data is unique by
    construction, and the migrations then enforce it.
    """
    if settings.seed_on_start:
        seed(db, settings.seed)
    try:
        migrate(db)
    except OperationFailure as exc:  # pragma: no cover - depends on server permissions
        raise RuntimeError(f"could not migrate database: {exc}") from exc
