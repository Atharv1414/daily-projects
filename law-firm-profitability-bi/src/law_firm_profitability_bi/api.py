"""FastAPI service: JSON metrics plus the interactive dashboard."""

import logging
import time
from collections.abc import Iterator
from datetime import date
from typing import Annotated, Any

import duckdb
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .config import AccessDenied, BadRequest, Settings
from .dashboard import View, render
from .metrics import CATALOGUE, FY25, FY26, Metrics, Period
from .security import User, verify_token

log = logging.getLogger(__name__)


def create_app(con: duckdb.DuckDBPyConnection, settings: Settings) -> FastAPI:
    if not settings.signing_key:
        raise ValueError("a signing key is required")
    app = FastAPI(title="Law firm profitability", version="1.0.0")

    @app.middleware("http")
    async def access_log(request: Request, call_next: Any) -> Any:
        started = time.perf_counter()
        response = await call_next(request)
        # The path only: query strings can carry login tokens.
        log.info(
            "%s %s %s %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    @app.exception_handler(AccessDenied)
    async def denied(_: Request, __: AccessDenied) -> JSONResponse:
        return JSONResponse({"detail": "not permitted"}, status_code=403)

    @app.exception_handler(BadRequest)
    async def bad(_: Request, error: BadRequest) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=422)

    def current_user(
        authorization: Annotated[str | None, Header()] = None,
        lawbi: Annotated[str | None, Cookie()] = None,
    ) -> User:
        token = lawbi
        if authorization and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ")
        if not token:
            raise HTTPException(401, "sign in first")
        try:
            return verify_token(token, settings.signing_key)
        except AccessDenied as error:
            raise HTTPException(401, str(error)) from error

    def connection() -> Iterator[duckdb.DuckDBPyConnection]:
        cursor = con.cursor()  # cursors are cheap and safe to use from separate threads
        try:
            yield cursor
        finally:
            cursor.close()

    def period(start: date = FY26.start, end: date = FY26.end) -> Period:
        return Period(start, end)

    UserDep = Annotated[User, Depends(current_user)]
    ConDep = Annotated[duckdb.DuckDBPyConnection, Depends(connection)]
    PeriodDep = Annotated[Period, Depends(period)]

    def metrics(con: ConDep, user: UserDep) -> Metrics:
        return Metrics(con, user)

    MetricsDep = Annotated[Metrics, Depends(metrics)]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/login")
    def login(token: str) -> RedirectResponse:
        """Swaps a signed link for a cookie, so the token does not stay in the address bar."""
        try:
            verify_token(token, settings.signing_key)
        except AccessDenied as error:
            raise HTTPException(401, str(error)) from error
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("lawbi", token, httponly=True, samesite="strict")
        return response

    @app.get("/", response_class=HTMLResponse)
    def page(
        con: ConDep,
        user: UserDep,
        period: PeriodDep,
        unit: str | None = None,
        month: date = date(2026, 4, 1),
    ) -> str:
        Period(month, month)  # reject months outside the data
        return render(con, View(user, unit or user.unit_id, period, month))

    @app.get("/api/catalogue")
    def catalogue(_: UserDep) -> dict[str, str]:
        return CATALOGUE

    @app.get("/api/kpis")
    def kpis(m: MetricsDep, period: PeriodDep, unit: str | None = None) -> dict[str, Any]:
        return m.kpis(period, unit)

    @app.get("/api/units")
    def units(m: MetricsDep, period: PeriodDep, unit: str | None = None) -> list[dict[str, Any]]:
        return m.children(period, unit)

    @app.get("/api/lockup")
    def lockup(m: MetricsDep, period: PeriodDep, unit: str | None = None) -> list[dict[str, Any]]:
        return m.lockup_trend(period, unit)

    @app.get("/api/waterfall")
    def waterfall(
        m: MetricsDep, period: PeriodDep, unit: str | None = None
    ) -> list[dict[str, Any]]:
        return m.waterfall(period, unit)

    @app.get("/api/variance")
    def variance(m: MetricsDep, unit: str | None = None) -> dict[str, float]:
        return m.variance(FY25, FY26, unit)

    @app.get("/api/restatement")
    def restatement(
        m: MetricsDep,
        month: date,
        reported_on: date,
        restated_on: date,
        unit: str | None = None,
    ) -> list[dict[str, Any]]:
        return m.restatement(month, reported_on, restated_on, unit)

    @app.get("/api/lifecycle")
    def lifecycle(m: MetricsDep, unit: str | None = None) -> list[dict[str, Any]]:
        return m.lifecycle(unit)

    @app.get("/api/matters")
    def matters(
        m: MetricsDep,
        unit: str | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
        size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: str = "recorded",
    ) -> dict[str, Any]:
        return m.matters(unit, page, size, sort)

    return app
