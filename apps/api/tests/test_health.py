import os

import pytest
from fastapi.testclient import TestClient

from domovnik.main import app

client = TestClient(app)


def test_health_liveness() -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ready_without_database_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@127.0.0.1:1/none")
    from domovnik.config import get_settings

    get_settings.cache_clear()
    try:
        r = client.get("/api/v1/health/ready")
        assert r.status_code == 503
        assert r.json()["database"] == "unavailable"
    finally:
        get_settings.cache_clear()


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL není nastaveno")
def test_ready_with_database() -> None:
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json()["database"] == "ok"
