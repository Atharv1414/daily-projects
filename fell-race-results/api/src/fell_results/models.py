"""Pydantic models: the API contract, and validation for uploaded results."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Sex = Literal["F", "M"]
Category = Literal["Open", "V40", "V50", "V60", "V70"]
Status = Literal["finished", "dnf"]
FraCategory = Literal["AS", "AM", "AL", "BS", "BM", "BL", "CS", "CM", "CL"]

CATEGORIES: tuple[Category, ...] = ("Open", "V40", "V50", "V60", "V70")


def age_category(birth_year: int, season: int) -> Category:
    """Fell running veteran classes, using age at the end of the season."""
    age = season - birth_year
    if age >= 70:
        return "V70"
    if age >= 60:
        return "V60"
    if age >= 50:
        return "V50"
    if age >= 40:
        return "V40"
    return "Open"


class Checkpoint(BaseModel):
    name: str
    km: float = Field(ge=0)


class Race(BaseModel):
    slug: str
    name: str
    fra_category: FraCategory
    distance_km: float = Field(gt=0)
    climb_m: int = Field(gt=0)
    month: int = Field(ge=1, le=12)
    blurb: str
    checkpoints: list[Checkpoint]
    profile: list[tuple[float, float]] = Field(description="(km, metres above sea level)")


class RaceSummary(BaseModel):
    slug: str
    name: str
    fra_category: FraCategory
    distance_km: float
    climb_m: int
    date: date
    blurb: str
    finishers: int
    winner_f: str | None
    winner_m: str | None
    winning_time_f: int | None
    winning_time_m: int | None
    profile: list[tuple[float, float]]


class Runner(BaseModel):
    id: str
    name: str
    sex: Sex
    birth_year: int
    club: str


class ResultRow(BaseModel):
    position: int | None
    runner_id: str
    name: str
    sex: Sex
    category: Category
    club: str
    status: Status
    time_s: int | None
    splits: list[int]


class RaceResults(BaseModel):
    race: str
    season: int
    total: int
    page: int
    page_size: int
    items: list[ResultRow]


class RaceCount(BaseModel):
    race: str
    points: float
    position: int
    counted: bool


class StandingRow(BaseModel):
    rank: int
    category_rank: int
    runner_id: str
    name: str
    sex: Sex
    category: Category
    club: str
    total: float
    races_run: int
    races: list[RaceCount]


class Standings(BaseModel):
    season: int
    sex: Sex
    category: Category | None
    best_of: int
    rows: list[StandingRow]


class RunnerResult(BaseModel):
    race: str
    race_name: str
    season: int
    status: Status
    time_s: int | None
    position: int | None
    finishers: int
    category: Category


class RunnerProfile(BaseModel):
    runner: Runner
    results: list[RunnerResult]
    personal_bests: dict[str, int]


class GhostRunner(BaseModel):
    runner_id: str
    name: str
    status: Status
    time_s: int | None
    splits: list[int]


class Ghost(BaseModel):
    race: str
    season: int
    checkpoints: list[Checkpoint]
    profile: list[tuple[float, float]]
    runners: list[GhostRunner]


class Record(BaseModel):
    race: str
    race_name: str
    sex: Sex
    runner_id: str
    name: str
    season: int
    time_s: int


class ResultIn(BaseModel):
    """One row of an organiser's upload. Splits are cumulative seconds at each checkpoint."""

    model_config = ConfigDict(extra="forbid")

    runner_id: str = Field(pattern=r"^R\d{4}$")
    status: Status = "finished"
    splits: list[int] = Field(min_length=1)
    version: int = Field(default=1, ge=1, description="Higher versions replace lower ones")

    @field_validator("splits")
    @classmethod
    def strictly_increasing(cls, splits: list[int]) -> list[int]:
        if any(s <= 0 for s in splits):
            raise ValueError("split times must be positive")
        if any(b <= a for a, b in zip(splits, splits[1:], strict=False)):
            raise ValueError("split times must increase from checkpoint to checkpoint")
        return splits


class UploadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    season: int = Field(ge=2000, le=2100)
    results: list[ResultIn] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_runners(self) -> UploadIn:
        seen: set[str] = set()
        for row in self.results:
            if row.runner_id in seen:
                raise ValueError(f"runner {row.runner_id} appears twice in one upload")
            seen.add(row.runner_id)
        return self


class RowError(BaseModel):
    row: int
    runner_id: str
    reason: str


class UploadSummary(BaseModel):
    upload_id: str
    race: str
    season: int
    inserted: int
    updated: int
    unchanged: int
    rejected: list[RowError]
    replayed: bool = False
