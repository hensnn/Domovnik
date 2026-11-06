"""Inventura: založení z umístění, počítání, uzavření (s/bez aplikace změn), API."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.db.models import AuditLog, EventOutbox, Item, ItemPlacement, Movement
from domovnik.errors import Conflict, NotFound, ValidationFailed
from domovnik.main import app
from domovnik.ratelimit import login_limiter
from domovnik.schemas import ItemCreate, LocationCreate, PlacementIn
from domovnik.services import inventory, items, locations

PASSWORD = "correct horse battery"
D = Decimal


def world(db: Session, ctx: ActorContext):  # type: ignore[no-untyped-def]
    dum = locations.create_location(db, ctx, LocationCreate(name="Dům"))
    garaz = locations.create_location(db, ctx, LocationCreate(name="Garáž", parent_id=dum.id))
    regal = locations.create_location(db, ctx, LocationCreate(name="Regál", parent_id=garaz.id))
    sklep = locations.create_location(db, ctx, LocationCreate(name="Sklep", parent_id=dum.id))

    def mk(name: str, loc, qty: str):  # type: ignore[no-untyped-def]
        return items.create_item(
            db,
            ctx,
            ItemCreate(name=name, placements=[PlacementIn(location_id=loc.id, quantity=D(qty))]),
        )

    vrtacka = mk("Vrtačka", garaz, "1")
    sroubky = mk("Šroubky", regal, "50")
    kladivo = mk("Kladivo", sklep, "1")
    return dum, garaz, regal, sklep, vrtacka, sroubky, kladivo


def line(detail, item, loc):  # type: ignore[no-untyped-def]
    return next(x for x in detail.lines if x.item_id == item.id and x.location_id == loc.id)


def test_start_session_builds_expected_lines_from_subtree(db: Session, ctx: ActorContext) -> None:
    dum, garaz, regal, sklep, vrtacka, sroubky, kladivo = world(db, ctx)
    s = inventory.start_session(db, ctx, garaz.id)
    d = inventory.session_detail(db, s.id)
    assert d.name == "Inventura – Garáž" and d.status == "open"
    assert {(x.item_name, x.expected_qty) for x in d.lines} == {
        ("Vrtačka", D("1")),
        ("Šroubky", D("50")),
    }
    assert d.counts.total == 2 and d.counts.unchecked == 2

    whole = inventory.session_detail(db, inventory.start_session(db, ctx, None, " Roční ").id)
    assert whole.name == "Roční" and whole.counts.total == 3
    assert whole.location_id is None


def test_trashed_items_not_in_session(db: Session, ctx: ActorContext) -> None:
    _, garaz, _, _, vrtacka, *_ = world(db, ctx)
    items.delete_item(db, ctx, vrtacka.id)
    d = inventory.session_detail(db, inventory.start_session(db, ctx, garaz.id).id)
    assert [x.item_name for x in d.lines] == ["Šroubky"]


def test_count_results(db: Session, ctx: ActorContext) -> None:
    dum, garaz, regal, sklep, vrtacka, sroubky, kladivo = world(db, ctx)
    s = inventory.start_session(db, ctx, dum.id)

    inventory.count_line(db, ctx, s.id, vrtacka.id, garaz.id, D(1))
    inventory.count_line(db, ctx, s.id, sroubky.id, regal.id, D(40))
    inventory.mark_missing(db, ctx, s.id, kladivo.id, sklep.id)
    d = inventory.session_detail(db, s.id)
    assert line(d, vrtacka, garaz).result == "ok"
    sr = line(d, sroubky, regal)
    assert sr.result == "missing" and sr.diff == D("-10") and sr.counted_at is not None
    assert line(d, kladivo, sklep).result == "missing" and line(d, kladivo, sklep).counted_qty == 0

    inventory.count_line(db, ctx, s.id, sroubky.id, regal.id, D(55))
    assert line(inventory.session_detail(db, s.id), sroubky, regal).result == "extra"

    # reset řádku
    inventory.count_line(db, ctx, s.id, sroubky.id, regal.id, None)
    r = line(inventory.session_detail(db, s.id), sroubky, regal)
    assert r.result == "unchecked" and r.counted_qty is None and r.counted_at is None


def test_unexpected_item_extra_and_moved(db: Session, ctx: ActorContext) -> None:
    dum, garaz, regal, sklep, vrtacka, sroubky, kladivo = world(db, ctx)
    nove = items.create_item(db, ctx, ItemCreate(name="Nalezená pila"))  # nikde nezařazená
    s = inventory.start_session(db, ctx, dum.id)

    # věc, kterou nikde nečekáme -> extra
    inventory.count_line(db, ctx, s.id, nove.id, garaz.id, D(1))
    # kladivo je čekáno ve sklepě, ale našli jsme ho v garáži -> moved
    inventory.count_line(db, ctx, s.id, kladivo.id, garaz.id, D(1))
    d = inventory.session_detail(db, s.id)
    assert line(d, nove, garaz).result == "extra" and line(d, nove, garaz).expected_qty is None
    assert line(d, kladivo, garaz).result == "moved"
    assert line(d, kladivo, sklep).result == "unchecked"
    assert d.counts.extra == 1 and d.counts.moved == 1

    # neočekávaný řádek lze odebrat vrácením na „nezkontrolováno“
    inventory.count_line(db, ctx, s.id, nove.id, garaz.id, None)
    assert not [x for x in inventory.session_detail(db, s.id).lines if x.item_id == nove.id]


def test_count_validation(db: Session, ctx: ActorContext) -> None:
    dum, garaz, regal, sklep, vrtacka, *_ = world(db, ctx)
    s = inventory.start_session(db, ctx, regal.id)  # jen regál
    with pytest.raises(ValidationFailed):  # mimo rozsah
        inventory.count_line(db, ctx, s.id, vrtacka.id, sklep.id, D(1))
    with pytest.raises(ValidationFailed):  # neočekávaná věc s nulou
        inventory.count_line(db, ctx, s.id, vrtacka.id, regal.id, D(0))
    with pytest.raises(ValidationFailed):
        inventory.count_line(db, ctx, s.id, vrtacka.id, regal.id, D(-1))
    with pytest.raises(NotFound):
        inventory.count_line(db, ctx, s.id, vrtacka.id, regal.id, None)


def test_close_without_apply_changes_nothing(db: Session, ctx: ActorContext) -> None:
    dum, garaz, regal, sklep, vrtacka, sroubky, kladivo = world(db, ctx)
    s = inventory.start_session(db, ctx, dum.id)
    inventory.count_line(db, ctx, s.id, sroubky.id, regal.id, D(40))
    out = inventory.close_session(db, ctx, s.id, apply=False)
    assert out.session.status == "closed" and out.applied is False and out.changes == []
    assert out.session.applied_at is None and out.session.closed_at is not None
    p = db.execute(select(ItemPlacement).where(ItemPlacement.item_id == sroubky.id)).scalar_one()
    assert p.quantity == D("50")
    db.refresh(sroubky)
    assert sroubky.last_seen_at is None
    with pytest.raises(Conflict):
        inventory.close_session(db, ctx, s.id)
    with pytest.raises(Conflict):
        inventory.count_line(db, ctx, s.id, sroubky.id, regal.id, D(1))


def test_close_with_apply_adjusts_quantities(db: Session, ctx: ActorContext) -> None:
    dum, garaz, regal, sklep, vrtacka, sroubky, kladivo = world(db, ctx)
    nove = items.create_item(db, ctx, ItemCreate(name="Nalezená pila"))
    s = inventory.start_session(db, ctx, dum.id)
    inventory.count_line(db, ctx, s.id, vrtacka.id, garaz.id, D(1))  # ok
    inventory.count_line(db, ctx, s.id, sroubky.id, regal.id, D(40))  # méně
    inventory.mark_missing(db, ctx, s.id, kladivo.id, sklep.id)  # chybí
    inventory.count_line(db, ctx, s.id, nove.id, garaz.id, D(2))  # extra

    assert inventory.session_detail(db, s.id).counts.changes == 3
    out = inventory.close_session(db, ctx, s.id, apply=True)
    assert out.applied and out.session.applied_at is not None
    assert {(c.item_name, c.from_qty, c.to_qty) for c in out.changes} == {
        ("Šroubky", D("50"), D("40")),
        ("Kladivo", D("1"), D("0")),
        ("Nalezená pila", D("0"), D("2")),
    }

    def qty(item, loc):  # type: ignore[no-untyped-def]
        p = db.execute(
            select(ItemPlacement).where(
                ItemPlacement.item_id == item.id, ItemPlacement.location_id == loc.id
            )
        ).scalar_one_or_none()
        return p.quantity if p else None

    assert qty(sroubky, regal) == D("40")
    assert qty(kladivo, sklep) is None
    assert qty(nove, garaz) == D("2")
    assert qty(vrtacka, garaz) == D("1")

    # last_seen_at jen u nalezených věcí; kladivo (nenalezeno) ne
    for it in (vrtacka, sroubky, nove, kladivo):
        db.refresh(it)
    assert vrtacka.last_seen_at and sroubky.last_seen_at and nove.last_seen_at
    assert kladivo.last_seen_at is None

    # pohyby a audit mají zdroj „inventory“, ne „ui“
    moves = db.execute(
        select(Movement).where(Movement.kind == "adjust", Movement.item_id == sroubky.id)
    ).scalars()
    assert {m.source for m in moves} == {"inventory"}
    audit = db.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "item_placements", AuditLog.source == "inventory"
        )
    ).scalars()
    assert list(audit)
    # po uzavření se kontext vrátil na původní zdroj
    items.create_item(db, ctx, ItemCreate(name="Po inventuře"))
    created = db.execute(
        select(AuditLog).where(AuditLog.entity_type == "items", AuditLog.action == "insert")
    ).scalars()
    assert {a.source for a in created if a.after and a.after["name"] == "Po inventuře"} == {"ui"}


def test_moved_item_applied_places_it_at_new_location(db: Session, ctx: ActorContext) -> None:
    dum, garaz, regal, sklep, vrtacka, sroubky, kladivo = world(db, ctx)
    s = inventory.start_session(db, ctx, dum.id)
    inventory.count_line(db, ctx, s.id, kladivo.id, garaz.id, D(1))  # moved
    inventory.mark_missing(db, ctx, s.id, kladivo.id, sklep.id)  # tam už není
    inventory.close_session(db, ctx, s.id, apply=True)
    places = db.execute(
        select(ItemPlacement.location_id).where(ItemPlacement.item_id == kladivo.id)
    ).scalars()
    assert list(places) == [garaz.id]


def test_cancel_and_events(db: Session, ctx: ActorContext) -> None:
    dum, *_ = world(db, ctx)
    s = inventory.start_session(db, ctx, dum.id)
    c = inventory.cancel_session(db, ctx, s.id)
    assert c.status == "cancelled" and c.closed_at is not None
    with pytest.raises(Conflict):
        inventory.cancel_session(db, ctx, s.id)
    types = {e.event_type for e in db.execute(select(EventOutbox)).scalars()}
    assert {"inventory.started", "inventory.cancelled"} <= types
    assert inventory.list_sessions(db, status="open") == []
    assert [x.id for x in inventory.list_sessions(db)] == [s.id]
    assert db.execute(select(Item)).scalars().first() is not None


# --- API ----------------------------------------------------------------------------------


@pytest.fixture
def client(clean_db: None) -> Iterator[TestClient]:
    login_limiter._events.clear()
    with TestClient(app) as c:
        r = c.post("/api/v1/auth/setup", json={"username": "admin", "password": PASSWORD})
        assert r.status_code == 201, r.text
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        yield c


def ok(r: Any, code: int = 200) -> Any:
    assert r.status_code == code, f"{r.status_code}: {r.text}"
    return r.json() if r.content else None


def test_api_inventory_flow(client: TestClient) -> None:
    loc = ok(client.post("/api/v1/locations", json={"name": "Spíž"}), 201)
    mouka = ok(
        client.post(
            "/api/v1/items",
            json={
                "name": "Mouka",
                "unit": "kg",
                "placements": [{"location_id": loc["id"], "quantity": 3}],
            },
        ),
        201,
    )
    s = ok(client.post("/api/v1/inventory/sessions", json={"location_id": loc["id"]}), 201)
    assert s["status"] == "open" and len(s["lines"]) == 1 and s["lines"][0]["unit"] == "kg"
    url = f"/api/v1/inventory/sessions/{s['id']}/lines/{mouka['id']}/{loc['id']}"

    d = ok(client.patch(url, json={"counted_qty": 2}))
    assert d["lines"][0]["result"] == "missing" and d["counts"]["missing"] == 1
    assert d["counts"]["changes"] == 1
    assert client.patch(url, json={"counted_qty": -1}).status_code == 422

    listing = ok(client.get("/api/v1/inventory/sessions", params={"status": "open"}))
    assert [x["id"] for x in listing] == [s["id"]]

    out = ok(client.post(f"/api/v1/inventory/sessions/{s['id']}/close", json={"apply": True}))
    assert out["applied"] and out["changes"][0]["to_qty"] in ("2.000", 2, "2")
    after = ok(client.get(f"/api/v1/items/{mouka['id']}"))
    assert float(after["total_quantity"]) == 2.0
    assert after["placements"][0]["quantity"] is not None
    assert client.post(f"/api/v1/inventory/sessions/{s['id']}/cancel").status_code == 409
    assert (
        client.get(
            "/api/v1/inventory/sessions/" + "0" * 8 + "-0000-0000-0000-" + "0" * 12
        ).status_code
        == 404
    )


def test_api_inventory_requires_write_scope(client: TestClient) -> None:
    tok = ok(client.post("/api/v1/tokens", json={"name": "ro", "scopes": ["items:read"]}), 201)
    secret = tok["token"]
    assert secret
    anon = TestClient(app)
    h = {"Authorization": f"Bearer {secret}"}
    assert anon.get("/api/v1/inventory/sessions", headers=h).status_code == 200
    assert anon.post("/api/v1/inventory/sessions", json={}, headers=h).status_code == 403
