"""Deterministic synthetic data for Hollinbeck Harriers (an invented club).

Eight championship fell races, three seasons, about 420 runners. Each runner has a general
ability plus separate climbing and descending skill, so split times differ realistically:
strong climbers lead at the summit and strong descenders catch them on the way down, which
is what the ghost race on the website shows.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

from .models import Checkpoint, Race, age_category

SEASONS = (2024, 2025, 2026)
CLUB = "Hollinbeck Harriers"
GUEST_CLUBS = (
    "Ashgill AC",
    "Crookdale Runners",
    "Langstrath Jogging Club",
    "Mardale Moles",
    "Unattached",
)

# name, slug, FRA category, km, climb, month, blurb, checkpoints (name, km)
RACE_SPECS: tuple[tuple, ...] = (
    (
        "Hollin Pike Dash",
        "hollin-pike-dash",
        "AS",
        5.2,
        410,
        3,
        "Straight up the nose of Hollin Pike and straight back down. The season opener.",
        (("Wall stile", 1.1), ("Hollin Pike summit", 2.6)),
    ),
    (
        "Beckside Round",
        "beckside-round",
        "BM",
        11.0,
        520,
        4,
        "A rolling loop of both becks, with one long drag out of the valley.",
        (("Footbridge", 2.4), ("Crag End", 5.3), ("Sheepfold", 8.1)),
    ),
    (
        "Scar Edge Horseshoe",
        "scar-edge-horseshoe",
        "AM",
        9.6,
        690,
        5,
        "Three tops along the scar, then a knee-jarring descent through the bracken.",
        (("Low Scar", 2.2), ("High Scar", 4.0), ("Cairn Top", 6.1)),
    ),
    (
        "Thrang Moss Trot",
        "thrang-moss-trot",
        "CS",
        6.4,
        180,
        6,
        "Fast and wet. Mostly trods across the moss; bring shoes you do not love.",
        (("Peat hags", 2.7), ("Moss gate", 4.6)),
    ),
    (
        "Raven Crag Race",
        "raven-crag-race",
        "AS",
        3.8,
        360,
        7,
        "A midsummer evening sprint to the crag top. Over in twenty minutes for the fastest.",
        (("Raven Crag", 1.9),),
    ),
    (
        "Three Tarns Traverse",
        "three-tarns-traverse",
        "AL",
        21.5,
        1420,
        8,
        "The long one: every tarn, every top, a full kit check and a lot of climbing.",
        (("Blea Tarn", 4.5), ("Hollin Pike", 8.8), ("Red Tarn", 12.9), ("Grey Knotts", 17.2)),
    ),
    (
        "Gill Head Gallop",
        "gill-head-gallop",
        "BS",
        7.3,
        330,
        9,
        "Up the gill on rocky steps, back along the old quarry track.",
        (("Waterfall", 1.8), ("Gill Head", 3.6)),
    ),
    (
        "Long Stile Fell Race",
        "long-stile-fell-race",
        "AM",
        13.2,
        860,
        10,
        "The championship finale over Long Stile, usually in the season's first proper rain.",
        (("Intake wall", 2.0), ("Long Stile top", 5.4), ("Mere Gap", 9.0)),
    ),
)

FIRST_F = (
    "Amelia",
    "Sophie",
    "Grace",
    "Hannah",
    "Ellie",
    "Ruth",
    "Kirsty",
    "Jess",
    "Megan",
    "Lucy",
    "Isla",
    "Bethan",
    "Anna",
    "Fiona",
    "Claire",
    "Nia",
    "Harriet",
    "Joanne",
    "Rachel",
    "Priya",
    "Aisha",
    "Siobhan",
    "Mairi",
    "Helen",
    "Laura",
    "Zoe",
    "Freya",
)
FIRST_M = (
    "James",
    "Tom",
    "Owen",
    "Rhys",
    "Callum",
    "Ben",
    "Dan",
    "Alistair",
    "Gareth",
    "Sam",
    "Joe",
    "Matt",
    "Ewan",
    "Craig",
    "Ian",
    "Mark",
    "Rob",
    "Hamish",
    "Arjun",
    "Kwame",
    "Liam",
    "Jack",
    "Euan",
    "Neil",
    "Steve",
    "Chris",
    "Pete",
)
SURNAMES = (
    "Atkinson",
    "Birkett",
    "Dobson",
    "Fell",
    "Gaskell",
    "Harrison",
    "Iredale",
    "Jackson",
    "Kirkby",
    "Lowther",
    "Mounsey",
    "Nicholson",
    "Ormerod",
    "Postlethwaite",
    "Raine",
    "Sowerby",
    "Tyson",
    "Walker",
    "Wilson",
    "Youdale",
    "Patel",
    "Okafor",
    "MacLeod",
    "Hughes",
    "Price",
    "Byrne",
    "Shaw",
    "Barker",
    "Cowperthwaite",
    "Hall",
    "Metcalfe",
    "Robinson",
    "Stephenson",
    "Thwaite",
    "Brown",
    "Kaur",
    "Evans",
)


@dataclass(frozen=True)
class RunnerTraits:
    id: str
    name: str
    sex: str
    birth_year: int
    club: str
    ability: float  # time multiple of the course's best possible time
    climb: float  # negative = better climber
    descend: float  # negative = better descender
    keenness: float  # chance of entering a given race
    first_season: int


def race_date(season: int, month: int) -> date:
    """Second Saturday of the month."""
    first = date(season, month, 1)
    to_saturday = (5 - first.weekday()) % 7
    return first + timedelta(days=to_saturday + 7)


def make_profile(rng: random.Random, km: float, climb: int, points: int = 64) -> list[tuple]:
    """A plausible out-and-back-ish profile whose total ascent equals `climb` metres."""
    base = 120 + rng.random() * 200
    shape = [
        math.sin(math.pi * i / (points - 1)) ** 1.4
        + 0.18 * math.sin(i * (0.6 + rng.random() * 0.2))
        + 0.08 * math.sin(i * 1.7 + rng.random())
        for i in range(points)
    ]
    ascent = sum(max(0.0, b - a) for a, b in zip(shape, shape[1:], strict=False))
    scale = climb / ascent if ascent else 1.0
    low = min(shape)
    return [
        (round(km * i / (points - 1), 3), round(base + (h - low) * scale, 1))
        for i, h in enumerate(shape)
    ]


def build_races(rng: random.Random) -> list[Race]:
    races = []
    for name, slug, cat, km, climb, month, blurb, cps in RACE_SPECS:
        races.append(
            Race(
                slug=slug,
                name=name,
                fra_category=cat,
                distance_km=km,
                climb_m=climb,
                month=month,
                blurb=blurb,
                checkpoints=[Checkpoint(name=n, km=k) for n, k in cps]
                + [Checkpoint(name="Finish", km=km)],
                profile=make_profile(rng, km, climb),
            )
        )
    return races


def build_runners(rng: random.Random, count: int = 420) -> list[RunnerTraits]:
    runners = []
    used: set[str] = set()
    for i in range(count):
        sex = "F" if rng.random() < 0.42 else "M"
        while True:
            first = rng.choice(FIRST_F if sex == "F" else FIRST_M)
            name = f"{first} {rng.choice(SURNAMES)}"
            if name not in used:
                used.add(name)
                break
        runners.append(
            RunnerTraits(
                id=f"R{i + 1:04d}",
                name=name,
                sex=sex,
                birth_year=rng.randint(1952, 2006),
                club=CLUB if rng.random() < 0.55 else rng.choice(GUEST_CLUBS),
                ability=1.0 + rng.lognormvariate(-0.75, 0.45),
                climb=rng.gauss(0, 0.12),
                descend=rng.gauss(0, 0.2),
                keenness=0.12 + rng.random() * 0.6,
                first_season=rng.choice((2024, 2024, 2024, 2025, 2026)),
            )
        )
    return runners


def _segment_costs(race: Race) -> list[tuple[float, float, float]]:
    """(flat seconds, climbing seconds, descending seconds) for each checkpoint leg."""
    marks = [0.0] + [cp.km for cp in race.checkpoints]
    legs = []
    for start, end in zip(marks, marks[1:], strict=False):
        pts = [p for p in race.profile if start <= p[0] <= end]
        up = sum(max(0.0, b[1] - a[1]) for a, b in zip(pts, pts[1:], strict=False))
        down = sum(max(0.0, a[1] - b[1]) for a, b in zip(pts, pts[1:], strict=False))
        legs.append(((end - start) * 120.0, up * 1.5, down * 0.4))
    return legs


def simulate_result(rng: random.Random, race: Race, runner: RunnerTraits, season: int) -> dict:
    age = season - runner.birth_year
    age_factor = 1.0 + max(0, age - 34) * 0.009
    sex_factor = 1.11 if runner.sex == "F" else 1.0
    day = rng.gauss(1.0, 0.03)
    splits: list[int] = []
    elapsed = 0.0
    for flat, up, down in _segment_costs(race):
        leg = (flat + up * (1 + runner.climb) + down * (1 + runner.descend)) * runner.ability
        leg *= age_factor * sex_factor * day * rng.gauss(1.0, 0.015)
        elapsed += max(leg, 30.0)
        splits.append(int(round(elapsed)))
    dnf_chance = 0.05 if race.distance_km > 15 else 0.022
    status = "finished"
    if rng.random() < dnf_chance:
        status = "dnf"
        splits = splits[: rng.randint(1, max(1, len(splits) - 1))]
    return {
        "_id": f"{race.slug}:{season}:{runner.id}",
        "race": race.slug,
        "season": season,
        "runner_id": runner.id,
        "name": runner.name,
        "sex": runner.sex,
        "category": age_category(runner.birth_year, season),
        "club": runner.club,
        "status": status,
        "time_s": splits[-1] if status == "finished" else None,
        "splits": splits,
        "version": 1,
    }


def generate(seed: int = 2026) -> dict[str, list[dict]]:
    """Returns documents for the races, runners and results collections."""
    rng = random.Random(seed)
    races = build_races(rng)
    runners = build_runners(rng)
    popularity = {r.slug: 0.75 + rng.random() * 0.5 for r in races}
    results = []
    for season in SEASONS:
        for race in races:
            for runner in runners:
                if runner.first_season > season:
                    continue
                if rng.random() < runner.keenness * popularity[race.slug]:
                    results.append(simulate_result(rng, race, runner, season))
    return {
        "races": [{"_id": r.slug, **r.model_dump()} for r in races],
        "runners": [
            {
                "_id": r.id,
                "name": r.name,
                "name_lower": r.name.lower(),
                "sex": r.sex,
                "birth_year": r.birth_year,
                "club": r.club,
            }
            for r in runners
        ],
        "results": results,
    }
