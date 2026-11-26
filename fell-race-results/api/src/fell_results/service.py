"""Read and write operations over the club database. The API layer stays thin."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from pymongo import ASCENDING
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from . import standings as scoring
from .db import is_real_mongo
from .errors import NotFound, UploadConflict
from .models import CATEGORIES, RowError, UploadIn, UploadSummary, age_category
from .seed import SEASONS, race_date

log = logging.getLogger(__name__)

MAX_PAGE_SIZE = 200


class ClubService:
    def __init__(self, db: Database, max_upload_rows: int = 500) -> None:
        self.db = db
        self.max_upload_rows = max_upload_rows

    # ---- races -------------------------------------------------------------------------

    def seasons(self) -> list[int]:
        found = sorted(self.db.results.distinct("season"))
        return found or list(SEASONS)

    def latest_season(self) -> int:
        return self.seasons()[-1]

    def race(self, slug: str) -> dict:
        doc = self.db.races.find_one({"_id": slug})
        if doc is None:
            raise NotFound(f"no race called {slug!r}")
        doc.pop("_id", None)
        return doc

    def races(self, season: int) -> list[dict]:
        out = []
        for race in self.db.races.find({}, sort=[("month", ASCENDING)]):
            winners = {}
            for sex in ("F", "M"):
                w = self.db.results.find_one(
                    {"race": race["slug"], "season": season, "sex": sex, "status": "finished"},
                    sort=[("time_s", ASCENDING), ("runner_id", ASCENDING)],
                    projection={"name": 1, "time_s": 1},
                )
                winners[sex] = w
            out.append(
                {
                    "slug": race["slug"],
                    "name": race["name"],
                    "fra_category": race["fra_category"],
                    "distance_km": race["distance_km"],
                    "climb_m": race["climb_m"],
                    "date": race_date(season, race["month"]).isoformat(),
                    "blurb": race["blurb"],
                    "finishers": self.db.results.count_documents(
                        {"race": race["slug"], "season": season, "status": "finished"}
                    ),
                    "winner_f": winners["F"]["name"] if winners["F"] else None,
                    "winner_m": winners["M"]["name"] if winners["M"] else None,
                    "winning_time_f": winners["F"]["time_s"] if winners["F"] else None,
                    "winning_time_m": winners["M"]["time_s"] if winners["M"] else None,
                    "profile": [list(p) for p in race["profile"]],
                }
            )
        return out

    def results(
        self,
        slug: str,
        season: int,
        sex: str | None = None,
        category: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        self.race(slug)  # 404 for unknown races
        if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page must be >= 1 and page_size between 1 and {MAX_PAGE_SIZE}")
        query: dict = {"race": slug, "season": season}
        if sex:
            query["sex"] = sex
        if category:
            query["category"] = category
        projection = {"_id": 0, "version": 0}
        finished_q = {**query, "status": "finished"}
        finished_total = self.db.results.count_documents(finished_q)
        dnf_docs = list(self.db.results.find({**query, "status": "dnf"}, projection=projection))
        start = (page - 1) * page_size
        rows: list[dict] = []
        # Finishers come from the database already sorted and paged (the race_season_sex_time
        # index serves this); positions count finishers only, as on a printed results sheet.
        if start < finished_total:
            cursor = (
                self.db.results.find(finished_q, projection=projection)
                .sort([("time_s", ASCENDING), ("runner_id", ASCENDING)])
                .skip(start)
                .limit(page_size)
            )
            rows = [{**_result_row(d), "position": start + i + 1} for i, d in enumerate(cursor)]
        # DNFs (a handful per race) follow, ordered by how far they got.
        dnf_docs.sort(key=lambda d: (-len(d["splits"]), d["splits"][-1], d["runner_id"]))
        dnf_start = max(0, start - finished_total)
        room = page_size - len(rows)
        rows.extend(
            {**_result_row(d), "position": None} for d in dnf_docs[dnf_start : dnf_start + room]
        )
        return {
            "race": slug,
            "season": season,
            "total": finished_total + len(dnf_docs),
            "page": page,
            "page_size": page_size,
            "items": rows,
        }

    def records(self) -> list[dict]:
        names = {r["_id"]: r["name"] for r in self.db.races.find({}, projection={"name": 1})}
        out = []
        for slug in sorted(names, key=lambda s: self.db.races.find_one({"_id": s})["month"]):
            for sex in ("F", "M"):
                best = self.db.results.find_one(
                    {"race": slug, "sex": sex, "status": "finished"},
                    sort=[("time_s", ASCENDING), ("season", ASCENDING)],
                )
                if best:
                    out.append(
                        {
                            "race": slug,
                            "race_name": names[slug],
                            "sex": sex,
                            "runner_id": best["runner_id"],
                            "name": best["name"],
                            "season": best["season"],
                            "time_s": best["time_s"],
                        }
                    )
        return out

    # ---- championship ------------------------------------------------------------------

    def standings(
        self, season: int, sex: str, category: str | None = None, best_of: int = scoring.BEST_OF
    ) -> dict:
        if category is not None and category not in CATEGORIES:
            raise ValueError(f"category must be one of {', '.join(CATEGORIES)}")
        if is_real_mongo(self.db):
            rows = scoring.from_pipeline(
                self.db.results.aggregate(scoring.pipeline(season, best_of), allowDiskUse=False)
            )
        else:
            docs = self.db.results.find(
                {"season": season, "status": "finished"}, projection={"_id": 0}
            )
            rows = scoring.compute(docs, best_of)
        rows = [
            r for r in rows if r["sex"] == sex and (category is None or r["category"] == category)
        ]
        return {
            "season": season,
            "sex": sex,
            "category": category,
            "best_of": best_of,
            "rows": rows,
        }

    # ---- runners -----------------------------------------------------------------------

    def search_runners(self, q: str, limit: int = 20) -> list[dict]:
        q = q.strip().lower()
        if len(q) < 2:
            raise ValueError("search needs at least two letters")
        # First-name prefix uses the name_lower index; surname matches are a second query.
        prefix = {"name_lower": {"$regex": "^" + re.escape(q)}}
        word = {"name_lower": {"$regex": r" " + re.escape(q)}}
        seen: dict[str, dict] = {}
        for query in (prefix, word):
            for doc in self.db.runners.find(query, sort=[("name_lower", ASCENDING)], limit=limit):
                seen.setdefault(doc["_id"], _runner(doc))
        return list(seen.values())[:limit]

    def runner(self, runner_id: str) -> dict:
        doc = self.db.runners.find_one({"_id": runner_id})
        if doc is None:
            raise NotFound(f"no runner {runner_id!r}")
        race_names = {r["_id"]: r["name"] for r in self.db.races.find({}, projection={"name": 1})}
        history = []
        bests: dict[str, int] = {}
        for res in self.db.results.find({"runner_id": runner_id}, sort=[("season", -1)]):
            field = {"race": res["race"], "season": res["season"], "status": "finished"}
            position = None
            if res["status"] == "finished":
                position = 1 + self.db.results.count_documents(
                    {**field, "sex": res["sex"], "time_s": {"$lt": res["time_s"]}}
                )
                best = bests.get(res["race"])
                bests[res["race"]] = res["time_s"] if best is None else min(best, res["time_s"])
            history.append(
                {
                    "race": res["race"],
                    "race_name": race_names.get(res["race"], res["race"]),
                    "season": res["season"],
                    "status": res["status"],
                    "time_s": res["time_s"],
                    "position": position,
                    "finishers": self.db.results.count_documents({**field, "sex": res["sex"]}),
                    "category": res["category"],
                }
            )
        month = {r["_id"]: r["month"] for r in self.db.races.find({}, projection={"month": 1})}
        history.sort(key=lambda h: (-h["season"], month.get(h["race"], 0)))
        return {"runner": _runner(doc), "results": history, "personal_bests": bests}

    def ghost(self, slug: str, season: int, runner_ids: list[str]) -> dict:
        race = self.race(slug)
        if not 1 <= len(runner_ids) <= 4:
            raise ValueError("compare between one and four runners")
        found = {
            d["runner_id"]: d
            for d in self.db.results.find(
                {"race": slug, "season": season, "runner_id": {"$in": runner_ids}}
            )
        }
        missing = [r for r in runner_ids if r not in found]
        if missing:
            raise NotFound(f"no {season} result for {', '.join(missing)} in {race['name']}")
        return {
            "race": slug,
            "season": season,
            "checkpoints": race["checkpoints"],
            "profile": [list(p) for p in race["profile"]],
            "runners": [
                {
                    "runner_id": rid,
                    "name": found[rid]["name"],
                    "status": found[rid]["status"],
                    "time_s": found[rid]["time_s"],
                    "splits": found[rid]["splits"],
                }
                for rid in runner_ids
            ],
        }

    # ---- uploads -----------------------------------------------------------------------

    def upload(self, slug: str, payload: UploadIn, organiser: str) -> UploadSummary:
        """Idempotent batch upsert of an organiser's results.

        * The same `upload_id` replayed returns the stored summary and writes nothing.
        * A row replaces an existing result only if its `version` is higher (a conditional
          update, so two organisers correcting the same row cannot lose each other's fix).
        * Rows are validated individually; bad rows are rejected, good rows still load.
        """
        race = self.race(slug)
        if len(payload.results) > self.max_upload_rows:
            raise ValueError(f"at most {self.max_upload_rows} rows per upload")
        previous = self.db.uploads.find_one({"upload_id": payload.upload_id})
        if previous is not None:
            if previous["race"] != slug or previous["season"] != payload.season:
                raise UploadConflict("upload_id was already used for a different race or season")
            summary = UploadSummary(**previous["summary"])
            return summary.model_copy(update={"replayed": True})

        expected = len(race["checkpoints"])
        runner_ids = [r.runner_id for r in payload.results]
        runners = {d["_id"]: d for d in self.db.runners.find({"_id": {"$in": runner_ids}})}
        rejected: list[RowError] = []
        writes: list[tuple[int, str, dict, dict]] = []
        for i, row in enumerate(payload.results, start=1):
            reason = _row_problem(row, expected, race["distance_km"], runners.get(row.runner_id))
            if reason:
                rejected.append(RowError(row=i, runner_id=row.runner_id, reason=reason))
                continue
            runner = runners[row.runner_id]
            doc = {
                "race": slug,
                "season": payload.season,
                "runner_id": row.runner_id,
                "name": runner["name"],
                "sex": runner["sex"],
                "category": age_category(runner["birth_year"], payload.season),
                "club": runner["club"],
                "status": row.status,
                "time_s": row.splits[-1] if row.status == "finished" else None,
                "splits": row.splits,
                "version": row.version,
            }
            key = {"race": slug, "season": payload.season, "runner_id": row.runner_id}
            update = {
                "$set": doc,
                "$setOnInsert": {"_id": f"{slug}:{payload.season}:{row.runner_id}"},
            }
            writes.append((i, row.runner_id, {**key, "version": {"$lt": row.version}}, update))

        inserted = updated = unchanged = 0
        for i, rid, filter_, update in writes:
            # One write per row keeps the outcome per row exact. A stale version makes the
            # filter miss, the upsert then collides with the unique index: that is "unchanged".
            try:
                res = self.db.results.update_one(filter_, update, upsert=True)
            except DuplicateKeyError:
                unchanged += 1
                continue
            if res.upserted_id is not None:
                inserted += 1
            elif res.modified_count:
                updated += 1
            else:
                unchanged += 1
            log.debug("result row", extra={"row": i, "runner": rid})

        summary = UploadSummary(
            upload_id=payload.upload_id,
            race=slug,
            season=payload.season,
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            rejected=rejected,
        )
        try:
            self.db.uploads.insert_one(
                {
                    "upload_id": payload.upload_id,
                    "race": slug,
                    "season": payload.season,
                    "organiser": organiser,
                    "at": datetime.now(UTC),
                    "summary": summary.model_dump(),
                }
            )
        except DuplicateKeyError:
            # A concurrent request with the same id won the race; both wrote the same rows
            # (the writes are idempotent), so report the stored summary.
            stored = self.db.uploads.find_one({"upload_id": payload.upload_id})
            return UploadSummary(**stored["summary"]).model_copy(update={"replayed": True})
        log.info(
            "results uploaded",
            extra={
                "race": slug,
                "season": payload.season,
                "inserted": inserted,
                "updated": updated,
                "rejected": len(rejected),
            },
        )
        return summary


def _row_problem(row, expected: int, distance_km: float, runner: dict | None) -> str | None:
    if runner is None:
        return "unknown runner id"
    if row.status == "finished" and len(row.splits) != expected:
        return f"a finisher needs {expected} split times, got {len(row.splits)}"
    if row.status == "dnf" and len(row.splits) >= expected:
        return "a DNF cannot have a finish split"
    # Faster than 2:00 per km on a fell course is not credible (world-class road pace is
    # about 2:50 per km). Catches minutes typed where seconds were meant.
    covered = distance_km if row.status == "finished" else distance_km * len(row.splits) / expected
    if row.splits[-1] < covered * 120:
        return "implausibly fast: check the times are in seconds"
    if row.splits[-1] > 12 * 3600:
        return "over 12 hours: check the times are in seconds"
    return None


def _result_row(d: dict) -> dict:
    return {
        "runner_id": d["runner_id"],
        "name": d["name"],
        "sex": d["sex"],
        "category": d["category"],
        "club": d["club"],
        "status": d["status"],
        "time_s": d["time_s"],
        "splits": d["splits"],
    }


def _runner(doc: dict) -> dict:
    return {
        "id": doc["_id"],
        "name": doc["name"],
        "sex": doc["sex"],
        "birth_year": doc["birth_year"],
        "club": doc["club"],
    }
