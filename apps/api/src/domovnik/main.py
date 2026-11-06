"""Vstupní bod FastAPI aplikace."""

from fastapi import FastAPI, Response, status

from domovnik import __version__
from domovnik.config import get_settings
from domovnik.db import check_database

app = FastAPI(title="Domovník API", version=__version__)


@app.get("/api/v1/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness: aplikace běží (bez kontroly databáze)."""
    return {"status": "ok", "version": __version__}


@app.get("/api/v1/health/ready", tags=["system"])
def ready(response: Response) -> dict[str, str]:
    """Readiness: aplikace + databáze (pgvector) dostupné."""
    ok = check_database(get_settings().database_url)
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ok else "unavailable", "database": "ok" if ok else "unavailable"}
