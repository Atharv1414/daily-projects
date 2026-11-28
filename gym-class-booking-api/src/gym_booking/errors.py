"""Domain errors and the consistent JSON error envelope returned by the API."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """A business-rule failure that maps onto an HTTP status and a stable machine-readable code."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class Unauthorized(DomainError):
    status_code = 401
    code = "unauthorized"


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def make_error(cls: type[DomainError], code: str, message: str) -> DomainError:
    """Create an error of ``cls`` with a more specific ``code``."""
    err = cls(message)
    err.code = code
    return err


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers so every error response has the shape ``{"error": {"code", "message"}}``."""

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(_error(exc.code, exc.message), status_code=exc.status_code, headers=headers)
