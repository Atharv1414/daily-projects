"""FastAPI application factory and routes."""

import hashlib
import hmac
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from pymongo.database import Database

from . import errors, observability
from .config import Settings
from .db import connect, prepare
from .errors import Unauthorised
from .models import (
    Category,
    Ghost,
    RaceResults,
    RaceSummary,
    Record,
    Runner,
    RunnerProfile,
    Sex,
    Standings,
    UploadIn,
    UploadSummary,
)
from .service import ClubService

Slug = Annotated[str, Path(pattern=r"^[a-z0-9-]{3,60}$")]
RunnerId = Annotated[str, Path(pattern=r"^R\d{4}$")]


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    observability.configure_logging(settings.log_level)
    database = db if db is not None else connect(settings)
    prepare(database, settings)
    service = ClubService(database, settings.max_upload_rows)
    token_hashes = [hashlib.sha256(t.encode()).digest() for t in settings.tokens()]

    app = FastAPI(
        title="Hollinbeck Harriers results API",
        version="1.0.0",
        description="Race results, championship standings and ghost-race splits for an "
        "invented fell running club. All data is synthetic.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["authorization", "content-type"],
    )
    errors.install(app)
    observability.install(app)
    app.state.service = service

    def club() -> ClubService:
        return service

    Svc = Annotated[ClubService, Depends(club)]

    def season_or_latest(season: int | None) -> int:
        return season if season is not None else service.latest_season()

    def organiser(authorization: Annotated[str | None, Header()] = None) -> str:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise Unauthorised("send an organiser token as 'Authorization: Bearer <token>'")
        digest = hashlib.sha256(authorization[7:].strip().encode()).digest()
        # compare_digest over every stored hash: no early exit that leaks which token matched
        matches = [hmac.compare_digest(digest, h) for h in token_hashes]
        if not any(matches):
            raise Unauthorised("organiser token not recognised")
        return f"organiser-{matches.index(True) + 1}"

    @app.get("/api/health")
    def health(svc: Svc) -> dict:
        return {"status": "ok", "seasons": svc.seasons()}

    @app.get("/api/races", response_model=list[RaceSummary])
    def list_races(svc: Svc, season: Annotated[int | None, Query(ge=2000, le=2100)] = None):
        return svc.races(season_or_latest(season))

    @app.get("/api/races/{slug}")
    def get_race(svc: Svc, slug: Slug) -> dict:
        return svc.race(slug)

    @app.get("/api/races/{slug}/results", response_model=RaceResults)
    def race_results(
        svc: Svc,
        slug: Slug,
        season: Annotated[int | None, Query(ge=2000, le=2100)] = None,
        sex: Sex | None = None,
        category: Category | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        return svc.results(slug, season_or_latest(season), sex, category, page, page_size)

    @app.post("/api/races/{slug}/results", response_model=UploadSummary)
    def upload_results(
        svc: Svc, slug: Slug, body: UploadIn, who: Annotated[str, Depends(organiser)]
    ):
        return svc.upload(slug, body, who)

    @app.get("/api/records", response_model=list[Record])
    def records(svc: Svc):
        return svc.records()

    @app.get("/api/standings", response_model=Standings)
    def standings(
        svc: Svc,
        season: Annotated[int | None, Query(ge=2000, le=2100)] = None,
        sex: Sex = "F",
        category: Category | None = None,
    ):
        return svc.standings(season_or_latest(season), sex, category)

    @app.get("/api/runners", response_model=list[Runner])
    def search_runners(svc: Svc, q: Annotated[str, Query(min_length=2, max_length=40)]):
        return svc.search_runners(q)

    @app.get("/api/runners/{runner_id}", response_model=RunnerProfile)
    def runner(svc: Svc, runner_id: RunnerId):
        return svc.runner(runner_id)

    @app.get("/api/ghost", response_model=Ghost)
    def ghost(
        svc: Svc,
        race: Annotated[str, Query(pattern=r"^[a-z0-9-]{3,60}$")],
        runners: Annotated[str, Query(pattern=r"^R\d{4}(,R\d{4}){0,3}$")],
        season: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    ):
        return svc.ghost(race, season_or_latest(season), runners.split(","))

    return app
