"""Testy doménové vrstvy proti skutečnému PostgreSQL."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.db.models import AuditLog, EventOutbox, Item, Movement
from domovnik.errors import Conflict, NotFound, ValidationFailed
from domovnik.schemas import (
    CategoryCreate,
    CategoryUpdate,
    ItemCreate,
    ItemUpdate,
    LocationCreate,
    LocationUpdate,
    PlacementIn,
)
from domovnik.services import categories, items, locations
from domovnik.services import tags as tag_service


def loc(db: Session, ctx: ActorContext, name: str, parent=None, **kw):  # type: ignore[no-untyped-def]
    return locations.create_location(
        db, ctx, LocationCreate(name=name, parent_id=parent.id if parent else None, **kw)
    )


# --- umístění -----------------------------------------------------------------------------


def test_location_tree_paths_and_move_subtree(db: Session, ctx: ActorContext) -> None:
    dum = loc(db, ctx, "Dům", kind="building")
    garaz = loc(db, ctx, "Garáž", dum, kind="room")
    box = loc(db, ctx, "Krabice A", garaz, kind="box", is_movable=True)
    sklep = loc(db, ctx, "Sklep", dum, kind="room")
    assert box.depth == 2 and box.label_code.startswith("L-")

    locations.update_location(db, ctx, box.id, LocationUpdate(parent_id=sklep.id))
    names = {x.id: x.full_name for x in locations.list_locations(db)}
    assert names[box.id] == "Dům › Sklep › Krabice A"


def test_location_cycle_rejected(db: Session, ctx: ActorContext) -> None:
    a = loc(db, ctx, "A")
    b = loc(db, ctx, "B", a)
    with pytest.raises(ValidationFailed):
        locations.update_location(db, ctx, a.id, LocationUpdate(parent_id=b.id))
    with pytest.raises(ValidationFailed):
        locations.update_location(db, ctx, a.id, LocationUpdate(parent_id=a.id))


def test_location_duplicate_sibling_name_conflicts(db: Session, ctx: ActorContext) -> None:
    loc(db, ctx, "Garáž")
    with pytest.raises(Conflict):
        loc(db, ctx, "garáž")


def test_location_optimistic_locking(db: Session, ctx: ActorContext) -> None:
    a = loc(db, ctx, "A")
    v = a.version
    locations.update_location(db, ctx, a.id, LocationUpdate(name="A2", version=v))
    with pytest.raises(Conflict):
        locations.update_location(db, ctx, a.id, LocationUpdate(name="A3", version=v))


def test_archive_blocked_when_not_empty_and_get_or_create_path(
    db: Session, ctx: ActorContext
) -> None:
    garaz = locations.get_or_create_path(db, ctx, ["Dům", "Garáž"])
    again = locations.get_or_create_path(db, ctx, ["dům", "GARÁŽ"])
    assert garaz.id == again.id
    item = items.create_item(
        db, ctx, ItemCreate(name="Kladivo", placements=[PlacementIn(location_id=garaz.id)])
    )
    with pytest.raises(Conflict):
        locations.archive_location(db, ctx, garaz.id)
    items.remove(db, ctx, item.id, garaz.id)
    locations.archive_location(db, ctx, garaz.id)
    with pytest.raises(ValidationFailed):  # do archivovaného umístění se ukládat nesmí
        items.place(db, ctx, item.id, garaz.id)


# --- kategorie ----------------------------------------------------------------------------


def test_category_slug_cycle_merge_delete(db: Session, ctx: ActorContext) -> None:
    root = categories.create_category(db, ctx, CategoryCreate(name="Elektronika"))
    kabely = categories.create_category(db, ctx, CategoryCreate(name="Kabely", parent_id=root.id))
    assert root.slug == "elektronika"
    twin = categories.create_category(
        db, ctx, CategoryCreate(name="Elektronika", parent_id=kabely.id)
    )
    assert twin.slug == "elektronika-2"

    with pytest.raises(ValidationFailed):
        categories.update_category(db, ctx, root.id, CategoryUpdate(parent_id=kabely.id))

    items.create_item(db, ctx, ItemCreate(name="USB kabel", category_id=kabely.id))
    cats = {c.id: c for c in categories.list_categories(db)}
    assert cats[root.id].item_count == 1 and cats[root.id].direct_item_count == 0

    with pytest.raises(Conflict):
        categories.delete_category(db, ctx, kabely.id)  # má podkategorii i věc

    cables2 = categories.create_category(db, ctx, CategoryCreate(name="Napájecí kabely"))
    items.create_item(db, ctx, ItemCreate(name="Napáječ", category_id=cables2.id))
    categories.merge_categories(db, ctx, cables2.id, kabely.id)
    assert {c.id for c in categories.list_categories(db)} >= {kabely.id}
    assert cats[kabely.id].id == kabely.id
    moved = db.execute(select(Item).where(Item.name == "Napáječ")).scalar_one()
    assert moved.category_id == kabely.id


def test_category_get_or_create_path(db: Session, ctx: ActorContext) -> None:
    a = categories.get_or_create_path(db, ctx, ["Nářadí", "Ruční"])
    b = categories.get_or_create_path(db, ctx, ["nářadí", "ruční"])
    assert a.id == b.id
    full = {c.id: c.full_name for c in categories.list_categories(db)}
    assert full[a.id] == "Nářadí › Ruční"


# --- věci ---------------------------------------------------------------------------------


def test_item_lifecycle_placements_and_movements(db: Session, ctx: ActorContext) -> None:
    garaz = loc(db, ctx, "Garáž")
    dilna = loc(db, ctx, "Dílna")
    item = items.create_item(
        db,
        ctx,
        ItemCreate(
            name="Šrouby 4x40",
            is_consumable=True,
            min_quantity=Decimal(20),
            tags=["spojovací", "Kov"],
            placements=[PlacementIn(location_id=garaz.id, quantity=Decimal(50))],
        ),
    )
    assert item.label_code.startswith("I-")
    out = items.get_item_out(db, item.id)
    assert out.total_quantity == 50 and not out.is_low_stock
    assert out.tags == ["Kov", "spojovací"]
    assert out.placements[0].location_path == "Garáž"

    # část množství do dílny
    items.move(db, ctx, item.id, dilna.id, from_location_id=garaz.id, quantity=Decimal(15))
    out = items.get_item_out(db, item.id)
    assert {p.location_id: p.quantity for p in out.placements} == {garaz.id: 35, dilna.id: 15}

    # bez „odkud“ u věci ve více umístěních je to nejednoznačné
    with pytest.raises(ValidationFailed):
        items.move(db, ctx, item.id, garaz.id)
    with pytest.raises(ValidationFailed):
        items.move(db, ctx, item.id, dilna.id, from_location_id=garaz.id, quantity=Decimal(999))

    items.adjust_quantity(db, ctx, item.id, garaz.id, Decimal(5))
    assert items.get_item_out(db, item.id).is_low_stock  # 5 + 15 = 20 <= 20
    items.remove(db, ctx, item.id, dilna.id, dispose=True)
    assert [p.location_id for p in items.get_item_out(db, item.id).placements] == [garaz.id]

    kinds = [m.kind for m in reversed(items.list_movements(db, item.id))]
    assert kinds == ["create", "place", "move", "adjust", "dispose"]


def test_move_single_placement_without_from_and_unplaced_item(
    db: Session, ctx: ActorContext
) -> None:
    a, b = loc(db, ctx, "A"), loc(db, ctx, "B")
    item = items.create_item(db, ctx, ItemCreate(name="Lampa"))  # nezařazeno
    assert items.get_item_out(db, item.id).placements == []
    items.move(db, ctx, item.id, a.id)  # nikde nebyla → place
    items.move(db, ctx, item.id, b.id)  # jediné umístění → přesun
    assert [p.location_id for p in items.get_item_out(db, item.id).placements] == [b.id]
    with pytest.raises(ValidationFailed):
        items.move(db, ctx, item.id, b.id)  # stejné umístění


def test_item_update_version_trash_restore_purge(db: Session, ctx: ActorContext) -> None:
    item = items.create_item(db, ctx, ItemCreate(name="Vrtačka", tags=["nářadí"]))
    v = item.version
    items.update_item(db, ctx, item.id, ItemUpdate(brand="Bosch", version=v))
    with pytest.raises(Conflict):
        items.update_item(db, ctx, item.id, ItemUpdate(brand="Makita", version=v))
    # přidání tagu nezvyšuje verzi (neměnný UPDATE)
    before = items.get_item(db, item.id).version
    items.update_item(db, ctx, item.id, ItemUpdate(tags=["nářadí", "elektro"]))
    assert items.get_item_out(db, item.id).tags == ["elektro", "nářadí"]
    assert items.get_item(db, item.id).version >= before

    items.delete_item(db, ctx, item.id)
    with pytest.raises(NotFound):
        items.get_item(db, item.id)
    items.restore_item(db, ctx, item.id)
    with pytest.raises(Conflict):
        items.purge_item(db, ctx, item.id)  # není v koši
    items.delete_item(db, ctx, item.id)
    items.purge_item(db, ctx, item.id)
    assert db.get(Item, item.id) is None


def test_item_clearing_nullable_field(db: Session, ctx: ActorContext) -> None:
    item = items.create_item(db, ctx, ItemCreate(name="X", brand="Bosch"))
    items.update_item(db, ctx, item.id, ItemUpdate.model_validate({"brand": None}))
    assert items.get_item(db, item.id).brand is None
    with pytest.raises(ValidationFailed):
        items.update_item(db, ctx, item.id, ItemUpdate.model_validate({"name": None}))


def test_fulltext_vector_built_and_tag_changes_refresh_it(db: Session, ctx: ActorContext) -> None:
    item = items.create_item(
        db, ctx, ItemCreate(name="Akušroubovák", aliases=["vrtačka"], tags=["nářadí"])
    )
    q = text(
        "SELECT count(*) FROM items WHERE id = :id AND search_tsv @@ "
        "plainto_tsquery('simple', immutable_unaccent(:q))"
    )
    for word in ("akusroubovak", "vrtacka", "naradi"):
        assert db.execute(q, {"id": item.id, "q": word}).scalar_one() == 1
    tag_service.set_item_tags(db, item.id, ["zahrada"])
    assert db.execute(q, {"id": item.id, "q": "naradi"}).scalar_one() == 0
    assert db.execute(q, {"id": item.id, "q": "zahrada"}).scalar_one() == 1


# --- audit a outbox -----------------------------------------------------------------------


def test_audit_log_records_actor_and_source(db: Session, ctx: ActorContext, user) -> None:  # type: ignore[no-untyped-def]
    item = items.create_item(db, ctx, ItemCreate(name="Konvice"))
    items.update_item(db, ctx, item.id, ItemUpdate(brand="Philips"))
    rows = list(
        db.execute(
            select(AuditLog).where(AuditLog.entity_id == item.id).order_by(AuditLog.id)
        ).scalars()
    )
    assert [r.action for r in rows] == ["insert", "update"]
    assert all(r.actor_id == user.id and r.source == "ui" for r in rows)
    assert rows[1].before is not None and rows[1].after is not None
    assert rows[1].before["brand"] is None and rows[1].after["brand"] == "Philips"


def test_audit_source_differs_per_channel(db: Session, user) -> None:  # type: ignore[no-untyped-def]
    from domovnik.context import bind_context

    ai_ctx = ActorContext(actor_id=user.id, source="ai")
    bind_context(db, ai_ctx)
    item = items.create_item(db, ai_ctx, ItemCreate(name="Z AI"))
    row = db.execute(select(AuditLog).where(AuditLog.entity_id == item.id)).scalars().first()
    assert row is not None and row.source == "ai"
    mv = db.execute(select(Movement).where(Movement.item_id == item.id)).scalars().first()
    assert mv is not None and mv.source == "ai"


def test_outbox_events_written_in_same_transaction(db: Session, ctx: ActorContext) -> None:
    a, b = loc(db, ctx, "A"), loc(db, ctx, "B")
    item = items.create_item(
        db, ctx, ItemCreate(name="Hrnek", placements=[PlacementIn(location_id=a.id)])
    )
    items.move(db, ctx, item.id, b.id)
    types = [
        e.event_type for e in db.execute(select(EventOutbox).order_by(EventOutbox.id)).scalars()
    ]
    assert "item.created" in types and "item.moved" in types and "location.created" in types


def test_unknown_references_give_not_found(db: Session, ctx: ActorContext) -> None:
    import uuid

    with pytest.raises(NotFound):
        items.create_item(db, ctx, ItemCreate(name="X", category_id=uuid.uuid4()))
    with pytest.raises(NotFound):
        locations.create_location(db, ctx, LocationCreate(name="X", parent_id=uuid.uuid4()))


def test_locations_listed_depth_first_sorted_by_name(db: Session, ctx: ActorContext) -> None:
    dum = loc(db, ctx, "Dům")
    loc(db, ctx, "Sklep", dum)
    patro = loc(db, ctx, "Patro", dum)
    loc(db, ctx, "Ložnice", patro)
    loc(db, ctx, "Zahrada")
    assert [x.name for x in locations.list_locations(db)] == [
        "Dům",
        "Patro",
        "Ložnice",
        "Sklep",
        "Zahrada",
    ]


# --- duplikace umístění a kategorií --------------------------------------------------------------


def test_duplicate_location_copies_structure_not_items(db: Session, ctx: ActorContext) -> None:
    from domovnik.services import locations as loc_service

    dum = loc_service.get_or_create_path(db, ctx, ["Dům"])
    regal = loc_service.create_location(
        db,
        ctx,
        LocationCreate(
            name="Regál A", parent_id=dum.id, kind="furniture", notes="vlevo", description="d"
        ),
    )
    p1 = loc_service.create_location(
        db, ctx, LocationCreate(name="Police 1", parent_id=regal.id, kind="shelf")
    )
    loc_service.create_location(
        db, ctx, LocationCreate(name="Police 2", parent_id=regal.id, kind="shelf")
    )
    old = loc_service.create_location(
        db, ctx, LocationCreate(name="Stará", parent_id=regal.id, kind="shelf")
    )
    loc_service.archive_location(db, ctx, old.id)
    items.create_item(
        db, ctx, ItemCreate(name="Kladivo", placements=[PlacementIn(location_id=p1.id)])
    )

    copy, created = loc_service.duplicate_location(db, ctx, regal.id)
    assert created == 3 and copy.name == "Regál A (kopie)" and copy.parent_id == dum.id
    assert (
        copy.kind == "furniture" and copy.notes == "vlevo" and copy.label_code != regal.label_code
    )
    kids = [x.name for x in loc_service.list_locations(db) if x.parent_id == copy.id]
    assert sorted(kids) == ["Police 1", "Police 2"]  # archivovaná se nekopíruje
    by_name = {x.name: x for x in loc_service.list_locations(db) if x.parent_id == copy.id}
    assert by_name["Police 1"].item_count == 0  # věci zůstaly jen v originále
    assert {x.kind for x in by_name.values()} == {"shelf"}

    # druhá kopie dostane další volný název; vlastní název a konflikt
    again, _ = loc_service.duplicate_location(db, ctx, regal.id, include_children=False)
    assert again.name == "Regál A (kopie 2)"
    assert [x for x in loc_service.list_locations(db) if x.parent_id == again.id] == []
    named, n = loc_service.duplicate_location(db, ctx, regal.id, name="Regál B")
    assert named.name == "Regál B" and n == 3
    with pytest.raises(Conflict):
        loc_service.duplicate_location(db, ctx, regal.id, name="regál b")


def test_duplicate_category_copies_subcategories(db: Session, ctx: ActorContext) -> None:
    root = categories.create_category(db, ctx, CategoryCreate(name="Elektro", description="E"))
    kabely = categories.create_category(db, ctx, CategoryCreate(name="Kabely", parent_id=root.id))
    categories.create_category(db, ctx, CategoryCreate(name="USB", parent_id=kabely.id))
    items.create_item(db, ctx, ItemCreate(name="Kabel", category_id=kabely.id))

    copy, created = categories.duplicate_category(db, ctx, root.id)
    assert created == 3 and copy.name == "Elektro (kopie)" and copy.description == "E"
    tree = {c.full_name: c for c in categories.list_categories(db)}
    assert "Elektro (kopie) › Kabely › USB" in tree
    assert tree["Elektro (kopie) › Kabely"].item_count == 0  # věci se nekopírují
    assert tree["Elektro › Kabely"].item_count == 1

    flat, n = categories.duplicate_category(db, ctx, root.id, include_children=False)
    assert n == 1 and flat.name == "Elektro (kopie 2)"
    with pytest.raises(Conflict):
        categories.duplicate_category(db, ctx, root.id, name="Elektro")
