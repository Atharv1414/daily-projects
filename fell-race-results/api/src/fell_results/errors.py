"""Domain errors and their HTTP mapping. Every error body has the same shape."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ClubError(Exception):
    status = 400
    code = "bad_request"


class NotFound(ClubError):
    status = 404
    code = "not_found"


class Unauthorised(ClubError):
    status = 401
    code = "unauthorised"


class UploadConflict(ClubError):
    status = 409
    code = "conflict"


def _body(code: str, message: str, details: list | None = None) -> dict:
    body: dict = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body


def install(app: FastAPI) -> None:
    @app.exception_handler(ClubError)
    async def club_error(_: Request, exc: ClubError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, Unauthorised) else None
        return JSONResponse(_body(exc.code, str(exc)), status_code=exc.status, headers=headers)

    @app.exception_handler(ValueError)
    async def value_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(_body("bad_request", str(exc)), status_code=400)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": [str(p) for p in e.get("loc", ())], "message": e.get("msg", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            _body("invalid", "the request did not pass validation", details), status_code=422
        )
