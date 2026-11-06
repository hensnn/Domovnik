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


def test_production_refuses_insecure_config() -> None:
    import pytest

    from domovnik.config import Settings

    with pytest.raises(RuntimeError):
        Settings(domovnik_env="production").check_production()  # výchozí (veřejný) klíč
    with pytest.raises(RuntimeError):
        Settings(
            domovnik_env="production",
            secret_key="x" * 40,
            database_url="postgresql://domovnik:domovnik_dev@db/domovnik",
        ).check_production()
    Settings(
        domovnik_env="production",
        secret_key="x" * 40,
        database_url="postgresql://domovnik:silne-heslo@db/domovnik",
    ).check_production()  # v pořádku
    Settings().check_production()  # vývoj: bez omezení
