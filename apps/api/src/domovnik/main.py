"""Vstupní bod FastAPI aplikace."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from domovnik import __version__
from domovnik.api import auth, catalog, files, items, system
from domovnik.config import get_settings
from domovnik.db import check_database
from domovnik.errors import DomainError

app = FastAPI(
    title="Domovník API",
    version=__version__,
    description="Domácí inventář s AI asistentem. Autentizace: cookie relace (web) nebo "
    "`Authorization: Bearer dmv_…` (API tokeny).",
)


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    """RFC 9457 problem+json."""
    return JSONResponse(
        status_code=exc.status,
        media_type="application/problem+json",
        content={
            "type": f"urn:domovnik:error:{exc.code}",
            "title": exc.code,
            "status": exc.status,
            "detail": exc.message,
            **exc.extra,
        },
    )


@app.get("/api/v1/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness: aplikace běží (bez kontroly databáze)."""
    return {"status": "ok", "version": __version__}


@app.get("/api/v1/health/ready", tags=["system"])
def ready(response: Response) -> dict[str, str]:
    """Readiness: aplikace + databáze dostupné."""
    ok = check_database(get_settings().database_url)
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ok else "unavailable", "database": "ok" if ok else "unavailable"}


for module in (auth, catalog, items, files, system):
    app.include_router(module.router, prefix="/api/v1")
