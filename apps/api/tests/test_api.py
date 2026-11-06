"""API testy (HTTP) – commitují do testovací DB, každý test začíná s prázdnými daty."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from domovnik.main import app
from domovnik.ratelimit import login_limiter

PASSWORD = "correct horse battery"


@pytest.fixture
def anon(clean_db: None) -> Iterator[TestClient]:
    login_limiter._events.clear()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(anon: TestClient) -> TestClient:
    """Přihlášený administrátor (cookie + CSRF hlavička)."""
    r = anon.post("/api/v1/auth/setup", json={"username": "admin", "password": PASSWORD})
    assert r.status_code == 201, r.text
    anon.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return anon


def ok(r: Any, code: int = 200) -> Any:
    assert r.status_code == code, f"{r.status_code}: {r.text}"
    return r.json() if r.content else None


# --- autentizace --------------------------------------------------------------------------


def test_setup_login_logout_and_csrf(anon: TestClient) -> None:
    assert ok(anon.get("/api/v1/auth/status")) == {"setup_required": True, "authenticated": False}
    assert anon.get("/api/v1/items").status_code == 401

    me = ok(anon.post("/api/v1/auth/setup", json={"username": "admin", "password": PASSWORD}), 201)
    assert me["user"]["role"] == "admin" and "admin" in me["scopes"]
    assert (
        anon.post("/api/v1/auth/setup", json={"username": "x", "password": PASSWORD}).status_code
        == 409
    )
    assert ok(anon.get("/api/v1/auth/status"))["authenticated"] is True

    # změna stavu bez CSRF hlavičky je zakázána
    r = anon.post("/api/v1/locations", json={"name": "A"})
    assert r.status_code == 403
    r = anon.post(
        "/api/v1/locations", json={"name": "A"}, headers={"X-CSRF-Token": me["csrf_token"]}
    )
    assert r.status_code == 201

    ok(anon.post("/api/v1/auth/logout", headers={"X-CSRF-Token": me["csrf_token"]}), 204)
    assert anon.get("/api/v1/auth/me").status_code == 401

    assert (
        anon.post("/api/v1/auth/login", json={"username": "admin", "password": "nope"}).status_code
        == 401
    )
    ok(anon.post("/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}))
    assert anon.get("/api/v1/auth/me").status_code == 200


def test_login_rate_limit(anon: TestClient) -> None:
    ok(anon.post("/api/v1/auth/setup", json={"username": "admin", "password": PASSWORD}), 201)
    anon.cookies.clear()
    codes = [
        anon.post("/api/v1/auth/login", json={"username": "admin", "password": "bad"}).status_code
        for _ in range(10)
    ]
    assert codes[:8] == [401] * 8 and codes[8] == 429


def test_tokens_roles_and_scopes(client: TestClient) -> None:
    csrf = client.headers["X-CSRF-Token"]
    ok(
        client.post(
            "/api/v1/users", json={"username": "viewer", "password": PASSWORD, "role": "viewer"}
        ),
        201,
    )
    tok = ok(client.post("/api/v1/tokens", json={"name": "ha", "scopes": ["items:read"]}), 201)
    assert tok["token"].startswith("dmv_")

    with TestClient(app) as api:  # bez cookie, jen Bearer
        h = {"Authorization": f"Bearer {tok['token']}"}
        assert api.get("/api/v1/locations", headers=h).status_code == 200
        r = api.post("/api/v1/locations", json={"name": "X"}, headers=h)
        assert r.status_code == 403  # token má jen čtení
        assert (
            api.get("/api/v1/locations", headers={"Authorization": "Bearer dmv_bad"}).status_code
            == 401
        )

    # viewer se přihlásí, vidí, ale nezapisuje
    with TestClient(app) as v:
        me = ok(v.post("/api/v1/auth/login", json={"username": "viewer", "password": PASSWORD}))
        vh = {"X-CSRF-Token": me["csrf_token"]}
        assert v.get("/api/v1/items").status_code == 200
        assert v.post("/api/v1/locations", json={"name": "X"}, headers=vh).status_code == 403
        assert v.get("/api/v1/users").status_code == 403
        assert v.get("/api/v1/audit").status_code == 403

    ok(client.delete(f"/api/v1/tokens/{tok['id']}", headers={"X-CSRF-Token": csrf}), 204)
    with TestClient(app) as api:
        assert (
            api.get(
                "/api/v1/items", headers={"Authorization": f"Bearer {tok['token']}"}
            ).status_code
            == 401
        )


# --- katalog a věci -----------------------------------------------------------------------


def test_full_item_flow_over_http(client: TestClient) -> None:
    dum = ok(client.post("/api/v1/locations", json={"name": "Dům", "kind": "building"}), 201)
    garaz = ok(
        client.post("/api/v1/locations", json={"name": "Garáž", "parent_id": dum["id"]}), 201
    )
    sklep = ok(
        client.post("/api/v1/locations", json={"name": "Sklep", "parent_id": dum["id"]}), 201
    )
    cat = ok(client.post("/api/v1/categories", json={"name": "Nářadí"}), 201)

    item = ok(
        client.post(
            "/api/v1/items",
            json={
                "name": "Akušroubovák",
                "category_id": cat["id"],
                "tags": ["Bosch", "elektro"],
                "placements": [{"location_id": garaz["id"], "quantity": 1}],
            },
        ),
        201,
    )
    assert item["placements"][0]["location_path"] == "Dům › Garáž"
    assert item["category_path"] == "Nářadí"

    found = ok(client.get("/api/v1/items", params={"q": "akusroubovak"}))
    assert found["total"] == 1 and found["items"][0]["id"] == item["id"]
    assert ok(client.get("/api/v1/items", params={"location_id": dum["id"]}))["total"] == 1
    assert ok(client.get("/api/v1/items", params={"tag": "BOSCH"}))["total"] == 1

    moved = ok(
        client.post(f"/api/v1/items/{item['id']}/move", json={"to_location_id": sklep["id"]})
    )
    assert moved["placements"][0]["location_path"] == "Dům › Sklep"

    # optimistické zamykání přes If-Match
    etag = client.get(f"/api/v1/items/{item['id']}").headers["ETag"]
    ok(
        client.patch(
            f"/api/v1/items/{item['id']}", json={"brand": "Bosch"}, headers={"If-Match": etag}
        )
    )
    r = client.patch(
        f"/api/v1/items/{item['id']}", json={"brand": "Makita"}, headers={"If-Match": etag}
    )
    assert r.status_code == 409 and r.headers["content-type"].startswith("application/problem+json")

    hist = ok(client.get(f"/api/v1/items/{item['id']}/movements"))
    assert [m["kind"] for m in reversed(hist)] == ["create", "place", "move"]

    # koš
    ok(client.delete(f"/api/v1/items/{item['id']}"), 204)
    assert ok(client.get("/api/v1/items"))["total"] == 0
    assert ok(client.get("/api/v1/items", params={"trash": True}))["total"] == 1
    ok(client.post(f"/api/v1/items/{item['id']}/restore"))
    assert ok(client.get("/api/v1/items"))["total"] == 1

    # audit (jen admin) zachytil kanál „ui“
    audit = ok(
        client.get("/api/v1/audit", params={"entity_type": "items", "entity_id": item["id"]})
    )
    assert audit and all(a["source"] == "ui" for a in audit)


def test_bulk_stats_search_and_settings(client: TestClient) -> None:
    box = ok(client.post("/api/v1/locations", json={"name": "Krabice"}), 201)
    ids = [ok(client.post("/api/v1/items", json={"name": f"Věc {i}"}), 201)["id"] for i in range(3)]
    res = ok(
        client.post(
            "/api/v1/items/bulk", json={"ids": ids, "action": "move", "location_id": box["id"]}
        )
    )
    assert res["ok"] == 3 and not res["failed"]
    res = ok(
        client.post(
            "/api/v1/items/bulk",
            json={
                "ids": [*ids[:1], "00000000-0000-0000-0000-000000000000"],
                "action": "add_tags",
                "tags": ["x"],
            },
        )
    )
    assert res["ok"] == 1 and len(res["failed"]) == 1
    assert ok(client.get("/api/v1/tags"))[0]["item_count"] == 1

    stats = ok(client.get("/api/v1/stats"))
    assert stats["counts"]["items"] == 3 and stats["counts"]["unplaced"] == 0

    s = ok(client.get("/api/v1/search", params={"q": "krabice"}))
    assert [x["name"] for x in s["locations"]] == ["Krabice"]

    settings = {x["key"]: x for x in ok(client.get("/api/v1/settings"))}
    assert settings["ui.theme"]["value"] == "auto" and settings["ui.theme"]["is_default"]
    ok(client.put("/api/v1/settings/ui.theme", json={"value": "dark"}), 204)
    ok(
        client.put(
            "/api/v1/settings/items.trash_retention_days", json={"value": 30, "scope": "global"}
        ),
        204,
    )
    settings = {x["key"]: x for x in ok(client.get("/api/v1/settings"))}
    assert (
        settings["ui.theme"]["value"] == "dark"
        and settings["items.trash_retention_days"]["value"] == 30
    )
    assert client.put("/api/v1/settings/ui.theme", json={"value": "neon"}).status_code == 422

    ok(
        client.put(
            "/api/v1/settings/ai.gemini_api_key", json={"value": "AIzaSECRET", "scope": "global"}
        ),
        204,
    )
    body = client.get("/api/v1/settings").text
    assert "AIzaSECRET" not in body


def test_category_and_location_conflicts_map_to_409(client: TestClient) -> None:
    a = ok(client.post("/api/v1/locations", json={"name": "A"}), 201)
    assert client.post("/api/v1/locations", json={"name": "a"}).status_code == 409
    b = ok(client.post("/api/v1/locations", json={"name": "B", "parent_id": a["id"]}), 201)
    r = client.patch(f"/api/v1/locations/{a['id']}", json={"parent_id": b["id"]})
    assert r.status_code == 422
    assert client.get("/api/v1/locations/00000000-0000-0000-0000-000000000000").status_code == 404

    root = ok(client.post("/api/v1/categories", json={"name": "Elektro"}), 201)
    sub = ok(
        client.post("/api/v1/categories", json={"name": "Kabely", "parent_id": root["id"]}), 201
    )
    ok(client.post("/api/v1/items", json={"name": "USB", "category_id": sub["id"]}), 201)
    assert client.delete(f"/api/v1/categories/{sub['id']}").status_code == 409
    merged = ok(
        client.post(f"/api/v1/categories/{sub['id']}/merge", json={"target_id": root["id"]})
    )
    assert merged["item_count"] == 1


def test_openapi_documents_core_routes(anon: TestClient) -> None:
    spec = ok(anon.get("/openapi.json"))
    for path in (
        "/api/v1/items",
        "/api/v1/items/{item_id}/move",
        "/api/v1/locations",
        "/api/v1/settings",
    ):
        assert path in spec["paths"], path
