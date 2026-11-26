"""Championship scoring.

Each finisher scores 100 x (winner's time / their time) in their sex, to one decimal place
(half up),
so the winner gets 100 and someone twice as slow gets 50. A runner's total is their best
`best_of` scores across the season. Categories only filter and re-rank the overall table.

There are two implementations with identical output:

* `pipeline()` - a MongoDB aggregation using $setWindowFields and $sortArray, so the
  database does the work next to the data (used against a real server);
* `compute()` - plain Python over the same documents, used with mongomock (which lacks
  window functions) and as an executable specification in tests.

A test marked `mongo` runs both against real MongoDB and asserts they agree.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

BEST_OF = 5


def _tenths(winner: int, time_s: int) -> int:
    """Points in tenths, rounded half up, in exact integer arithmetic.

    Integers keep Python and MongoDB in exact agreement: float rounding ($round is
    half-to-even, $sum uses compensated summation) would otherwise differ in the last digit.
    """
    return (1000 * winner + time_s // 2) // time_s


def compute(results: Iterable[dict], best_of: int = BEST_OF) -> list[dict]:
    """Standings for every runner in the given season's results (both sexes)."""
    finished = [r for r in results if r["status"] == "finished" and r.get("time_s")]
    by_race_sex: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in finished:
        by_race_sex[(r["race"], r["sex"])].append(r)

    per_runner: dict[str, dict] = {}
    for group in by_race_sex.values():
        group.sort(key=lambda r: (r["time_s"], r["runner_id"]))
        winner = group[0]["time_s"]
        rank = 0
        prev_time = None
        for i, r in enumerate(group):
            if r["time_s"] != prev_time:  # standard competition ranking (1, 2, 2, 4)
                rank = i + 1
                prev_time = r["time_s"]
            entry = per_runner.setdefault(
                r["runner_id"],
                {
                    "runner_id": r["runner_id"],
                    "name": r["name"],
                    "sex": r["sex"],
                    "category": r["category"],
                    "club": r["club"],
                    "races": [],
                },
            )
            entry["races"].append(
                {"race": r["race"], "tenths": _tenths(winner, r["time_s"]), "position": rank}
            )

    rows = []
    for entry in per_runner.values():
        ordered = sorted(entry["races"], key=lambda x: (-x["tenths"], x["race"]))
        best = ordered[:best_of]
        races = [
            {
                "race": x["race"],
                "points": x["tenths"] / 10,
                "position": x["position"],
                "counted": i < best_of,
            }
            for i, x in enumerate(ordered)
        ]
        total = sum(x["tenths"] for x in best) / 10
        rows.append({**entry, "races": races, "total": total, "races_run": len(races)})
    return _rank(rows)


def _rank(rows: list[dict]) -> list[dict]:
    rows.sort(key=lambda r: (r["sex"], -r["total"], -r["races_run"], r["runner_id"]))
    out: list[dict] = []
    counters: dict[tuple, int] = defaultdict(int)
    for r in rows:
        counters[(r["sex"],)] += 1
        counters[(r["sex"], r["category"])] += 1
        out.append(
            {
                **r,
                "rank": counters[(r["sex"],)],
                "category_rank": counters[(r["sex"], r["category"])],
            }
        )
    return out


def pipeline(season: int, best_of: int = BEST_OF) -> list[dict]:
    """The same scoring as `compute`, as a MongoDB 7+ aggregation pipeline."""
    return [
        {"$match": {"season": season, "status": "finished", "time_s": {"$ne": None}}},
        {
            "$setWindowFields": {
                "partitionBy": {"race": "$race", "sex": "$sex"},
                "sortBy": {"time_s": 1},
                "output": {
                    "winner": {
                        "$min": "$time_s",
                        "window": {"documents": ["unbounded", "unbounded"]},
                    },
                    "position": {"$rank": {}},
                },
            }
        },
        {
            "$group": {
                "_id": "$runner_id",
                "name": {"$first": "$name"},
                "sex": {"$first": "$sex"},
                "category": {"$first": "$category"},
                "club": {"$first": "$club"},
                "races": {
                    "$push": {
                        "race": "$race",
                        "position": "$position",
                        "tenths": {
                            "$floor": {
                                "$divide": [
                                    {
                                        "$add": [
                                            {"$multiply": [1000, "$winner"]},
                                            {"$floor": {"$divide": ["$time_s", 2]}},
                                        ]
                                    },
                                    "$time_s",
                                ]
                            }
                        },
                    }
                },
            }
        },
        {
            "$set": {
                "races": {"$sortArray": {"input": "$races", "sortBy": {"tenths": -1, "race": 1}}},
                "races_run": {"$size": "$races"},
            }
        },
        {"$set": {"best": {"$slice": ["$races", best_of]}}},
        {
            "$set": {
                "total": {"$divide": [{"$sum": "$best.tenths"}, 10]},
                "races": {
                    "$map": {
                        "input": "$races",
                        "as": "r",
                        "in": {
                            "race": "$$r.race",
                            "position": "$$r.position",
                            "points": {"$divide": ["$$r.tenths", 10]},
                            "counted": {"$in": ["$$r", "$best"]},
                        },
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "runner_id": "$_id",
                "name": 1,
                "sex": 1,
                "category": 1,
                "club": 1,
                "races": 1,
                "races_run": 1,
                "total": 1,
            }
        },
    ]


def from_pipeline(docs: Iterable[dict]) -> list[dict]:
    """Ranks pipeline output exactly as `compute` does (ties broken by runner id)."""
    rows = []
    for d in docs:
        races = [
            {
                "race": r["race"],
                "points": float(r["points"]),
                "position": int(r["position"]),
                "counted": bool(r["counted"]),
            }
            for r in d["races"]
        ]
        rows.append({**d, "races": races, "total": float(d["total"])})
    return _rank(rows)
