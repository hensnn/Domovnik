"""Služby pro věci a jejich umístění (placements, pohyby, množství)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.db.models import (
    Category,
    Item,
    ItemPlacement,
    ItemTag,
    Location,
    Movement,
    Tag,
)
from domovnik.errors import Conflict, NotFound, ValidationFailed
from domovnik.schemas import ItemCreate, ItemOut, ItemUpdate, PlacementOut
from domovnik.services import tags as tag_service
from domovnik.services.common import check_version, emit, flush, get_or_404
from domovnik.services.locations import location_full_names

_PLAIN_FIELDS = (
    "name aliases description notes category_id status is_consumable unit min_quantity "
    "home_location_id brand model serial_no ean purchase_date purchase_price currency "
    "purchase_place warranty_until expires_at est_value condition owner_id attributes"
).split()


# --- čtení --------------------------------------------------------------------------------


def get_item(
    db: Session, item_id: uuid.UUID, *, lock: bool = False, include_deleted: bool = False
) -> Item:
    item = get_or_404(db, Item, item_id, lock=lock, what="Věc")
    if item.deleted_at is not None and not include_deleted:
        raise NotFound(f"Věc {item_id} je v koši.")
    return item


def _category_paths(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    cats = {c.id: c for c in db.execute(select(Category)).scalars()}
    out: dict[uuid.UUID, str] = {}
    for cid in ids:
        names, cur, seen = [], cid, set()
        while cur is not None and cur in cats and cur not in seen:
            seen.add(cur)
            names.append(cats[cur].name)
            cur = cats[cur].parent_id  # type: ignore[assignment]
        out[cid] = " › ".join(reversed(names))
    return out


def to_out(db: Session, items: list[Item]) -> list[ItemOut]:
    """Sestaví ItemOut (tagy, umístění, součty) pro více věcí najednou."""
    if not items:
        return []
    ids = [i.id for i in items]
    tag_rows = db.execute(
        select(ItemTag.item_id, Tag.name)
        .join(Tag, Tag.id == ItemTag.tag_id)
        .where(ItemTag.item_id.in_(ids))
        .order_by(Tag.name)
    ).all()
    tags: dict[uuid.UUID, list[str]] = {}
    for item_id, name in tag_rows:
        tags.setdefault(item_id, []).append(name)

    placements = list(
        db.execute(
            select(ItemPlacement, Location.label_code)
            .join(Location, Location.id == ItemPlacement.location_id)
            .where(ItemPlacement.item_id.in_(ids))
            .order_by(ItemPlacement.placed_at)
        ).all()
    )
    names = location_full_names(db, list({p.location_id for p, _ in placements}))
    by_item: dict[uuid.UUID, list[PlacementOut]] = {}
    for p, label in placements:
        by_item.setdefault(p.item_id, []).append(
            PlacementOut(
                location_id=p.location_id,
                quantity=p.quantity,
                note=p.note,
                location_label=label,
                location_path=names.get(p.location_id),
            )
        )
    cat_paths = _category_paths(db, {i.category_id for i in items if i.category_id})

    out: list[ItemOut] = []
    for item in items:
        o = ItemOut.model_validate(item)
        o.tags = tags.get(item.id, [])
        o.placements = by_item.get(item.id, [])
        o.total_quantity = sum((p.quantity for p in o.placements), Decimal(0))
        o.is_low_stock = item.min_quantity is not None and o.total_quantity <= item.min_quantity
        o.category_path = cat_paths.get(item.category_id) if item.category_id else None
        out.append(o)
    return out


def get_item_out(db: Session, item_id: uuid.UUID, *, include_deleted: bool = False) -> ItemOut:
    return to_out(db, [get_item(db, item_id, include_deleted=include_deleted)])[0]


# --- vytvoření a úprava -------------------------------------------------------------------


def _validate_refs(db: Session, data: dict[str, Any]) -> None:
    if data.get("category_id"):
        get_or_404(db, Category, data["category_id"], what="Kategorie")
    if data.get("home_location_id"):
        get_or_404(db, Location, data["home_location_id"], what="Domovské umístění")


def _movement(
    db: Session,
    ctx: ActorContext,
    item_id: uuid.UUID,
    kind: str,
    *,
    from_loc: uuid.UUID | None = None,
    to_loc: uuid.UUID | None = None,
    quantity: Decimal | None = None,
    note: str | None = None,
) -> None:
    db.add(
        Movement(
            item_id=item_id,
            kind=kind,
            from_location_id=from_loc,
            to_location_id=to_loc,
            quantity=quantity,
            actor_id=ctx.actor_id,
            source=ctx.source,
            change_set_id=ctx.change_set_id,
            note=note,
        )
    )


def create_item(db: Session, ctx: ActorContext, data: ItemCreate) -> Item:
    values = {f: getattr(data, f) for f in _PLAIN_FIELDS}
    _validate_refs(db, values)
    values["name"] = values["name"].strip()
    item = Item(**values, created_by=ctx.actor_id, updated_by=ctx.actor_id)
    db.add(item)
    flush(db)
    db.refresh(item)
    _movement(db, ctx, item.id, "create")
    if data.tags:
        tag_service.set_item_tags(db, item.id, data.tags)
    for p in data.placements:
        place(db, ctx, item.id, p.location_id, p.quantity, note=p.note)
    db.refresh(item)
    emit(db, ctx, "item.created", "item", item.id, {"name": item.name, "label": item.label_code})
    return item


def update_item(db: Session, ctx: ActorContext, item_id: uuid.UUID, data: ItemUpdate) -> Item:
    item = get_item(db, item_id, lock=True)
    check_version(item.version, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version", "tags"})
    # sloupce NOT NULL nelze nastavit na None
    for field in ("name", "aliases", "status", "is_consumable", "unit", "currency", "attributes"):
        if field in changes and changes[field] is None:
            raise ValidationFailed(f"Pole „{field}“ nesmí být prázdné.")
    _validate_refs(db, changes)
    for key, value in changes.items():
        setattr(item, key, value.strip() if key == "name" and isinstance(value, str) else value)
    item.updated_by = ctx.actor_id
    if data.tags is not None:
        tag_service.set_item_tags(db, item.id, data.tags)
    flush(db)
    db.refresh(item)
    emit(db, ctx, "item.updated", "item", item.id, {"fields": sorted(changes)})
    return item


def delete_item(db: Session, ctx: ActorContext, item_id: uuid.UUID) -> Item:
    """Přesune věc do koše (měkké smazání). Umístění zůstávají pro případ obnovy."""
    item = get_item(db, item_id, lock=True)
    item.deleted_at = datetime.now(UTC)
    flush(db)
    db.refresh(item)
    emit(db, ctx, "item.deleted", "item", item.id, {"name": item.name})
    return item


def restore_item(db: Session, ctx: ActorContext, item_id: uuid.UUID) -> Item:
    item = get_item(db, item_id, lock=True, include_deleted=True)
    if item.deleted_at is None:
        return item
    item.deleted_at = None
    flush(db)
    db.refresh(item)
    emit(db, ctx, "item.restored", "item", item.id, {"name": item.name})
    return item


def purge_item(db: Session, ctx: ActorContext, item_id: uuid.UUID) -> None:
    """Trvalé smazání – jen věci, které už jsou v koši."""
    item = get_item(db, item_id, lock=True, include_deleted=True)
    if item.deleted_at is None:
        raise Conflict("Trvale lze smazat jen věc z koše.")
    db.delete(item)
    flush(db)
    emit(db, ctx, "item.purged", "item", item_id, {"name": item.name})


# --- umístění věcí a množství -------------------------------------------------------------


def _active_location(db: Session, location_id: uuid.UUID) -> Location:
    loc = get_or_404(db, Location, location_id, what="Umístění")
    if loc.archived_at is not None:
        raise ValidationFailed(f"Umístění „{loc.name}“ je archivované.")
    return loc


def _placement(
    db: Session, item_id: uuid.UUID, location_id: uuid.UUID, *, lock: bool = True
) -> ItemPlacement | None:
    stmt = select(ItemPlacement).where(
        ItemPlacement.item_id == item_id, ItemPlacement.location_id == location_id
    )
    if lock:
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def place(
    db: Session,
    ctx: ActorContext,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    quantity: Decimal = Decimal(1),
    *,
    note: str | None = None,
    _kind: str = "place",
) -> ItemPlacement:
    """Přidá `quantity` kusů věci do umístění (vznik nebo navýšení)."""
    if quantity <= 0:
        raise ValidationFailed("Množství musí být kladné.")
    item = get_item(db, item_id, lock=True)
    _active_location(db, location_id)
    p = _placement(db, item.id, location_id)
    if p is None:
        p = ItemPlacement(item_id=item.id, location_id=location_id, quantity=quantity, note=note)
        db.add(p)
    else:
        p.quantity = p.quantity + quantity
        if note:
            p.note = note
    flush(db)
    _movement(db, ctx, item.id, _kind, to_loc=location_id, quantity=quantity, note=note)
    emit(
        db,
        ctx,
        "item.placed",
        "item",
        item.id,
        {"location_id": str(location_id), "quantity": str(quantity)},
    )
    return p


def move(
    db: Session,
    ctx: ActorContext,
    item_id: uuid.UUID,
    to_location_id: uuid.UUID,
    *,
    from_location_id: uuid.UUID | None = None,
    quantity: Decimal | None = None,
    note: str | None = None,
) -> ItemPlacement:
    """Přesune věc (celou nebo část množství) z jednoho umístění do druhého."""
    item = get_item(db, item_id, lock=True)
    _active_location(db, to_location_id)

    current = list(
        db.execute(
            select(ItemPlacement).where(ItemPlacement.item_id == item.id).with_for_update()
        ).scalars()
    )
    if from_location_id is None:
        if len(current) == 1:
            from_location_id = current[0].location_id
        elif len(current) > 1:
            raise ValidationFailed(
                "Věc je ve více umístěních – uveď, odkud ji přesunout.",
                locations=[str(p.location_id) for p in current],
            )
    if from_location_id == to_location_id:
        raise ValidationFailed("Zdrojové a cílové umístění jsou stejné.")

    if from_location_id is None:  # věc zatím nikde není (nezařazeno)
        return place(db, ctx, item.id, to_location_id, quantity or Decimal(1), note=note)

    src = next((p for p in current if p.location_id == from_location_id), None)
    if src is None:
        raise NotFound("Věc v zadaném zdrojovém umístění není.")
    qty = quantity if quantity is not None else src.quantity
    if qty > src.quantity:
        raise ValidationFailed(f"V umístění je jen {src.quantity}, nelze přesunout {qty}.")

    if qty == src.quantity:
        db.delete(src)
    else:
        src.quantity = src.quantity - qty
    flush(db)
    dst = _placement(db, item.id, to_location_id)
    if dst is None:
        dst = ItemPlacement(item_id=item.id, location_id=to_location_id, quantity=qty)
        db.add(dst)
    else:
        dst.quantity = dst.quantity + qty
    flush(db)
    _movement(
        db,
        ctx,
        item.id,
        "move",
        from_loc=from_location_id,
        to_loc=to_location_id,
        quantity=qty,
        note=note,
    )
    emit(
        db,
        ctx,
        "item.moved",
        "item",
        item.id,
        {"from": str(from_location_id), "to": str(to_location_id), "quantity": str(qty)},
    )
    return dst


def adjust_quantity(
    db: Session,
    ctx: ActorContext,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    new_quantity: Decimal,
    *,
    note: str | None = None,
) -> ItemPlacement | None:
    """Nastaví přesné množství v umístění (inventura). 0 = placement zanikne."""
    if new_quantity < 0:
        raise ValidationFailed("Množství nesmí být záporné.")
    item = get_item(db, item_id, lock=True)
    p = _placement(db, item.id, location_id)
    old = p.quantity if p else Decimal(0)
    if new_quantity == old:
        return p
    if p is None:
        _active_location(db, location_id)
        p = ItemPlacement(item_id=item.id, location_id=location_id, quantity=new_quantity)
        db.add(p)
        result: ItemPlacement | None = p
    elif new_quantity == 0:
        db.delete(p)
        result = None
    else:
        p.quantity = new_quantity
        result = p
    flush(db)
    _movement(
        db,
        ctx,
        item.id,
        "adjust",
        to_loc=location_id,
        quantity=new_quantity - old,
        note=note or f"{old} → {new_quantity}",
    )
    emit(
        db,
        ctx,
        "item.adjusted",
        "item",
        item.id,
        {"location_id": str(location_id), "from": str(old), "to": str(new_quantity)},
    )
    return result


def remove(
    db: Session,
    ctx: ActorContext,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    quantity: Decimal | None = None,
    *,
    dispose: bool = False,
    note: str | None = None,
) -> None:
    """Ubere množství z umístění (spotřeba / vyřazení). Bez množství odebere vše."""
    item = get_item(db, item_id, lock=True)
    p = _placement(db, item.id, location_id)
    if p is None:
        raise NotFound("Věc v zadaném umístění není.")
    qty = quantity if quantity is not None else p.quantity
    if qty > p.quantity:
        raise ValidationFailed(f"V umístění je jen {p.quantity}, nelze odebrat {qty}.")
    if qty == p.quantity:
        db.delete(p)
    else:
        p.quantity = p.quantity - qty
    flush(db)
    _movement(
        db,
        ctx,
        item.id,
        "dispose" if dispose else "remove",
        from_loc=location_id,
        quantity=qty,
        note=note,
    )
    emit(
        db,
        ctx,
        "item.removed",
        "item",
        item.id,
        {"location_id": str(location_id), "quantity": str(qty)},
    )


def list_movements(
    db: Session, item_id: uuid.UUID | None = None, *, limit: int = 100
) -> list[Movement]:
    stmt = select(Movement).order_by(Movement.moved_at.desc(), Movement.id.desc()).limit(limit)
    if item_id is not None:
        stmt = stmt.where(Movement.item_id == item_id)
    return list(db.execute(stmt).scalars())


def count_items(db: Session) -> int:
    return db.execute(
        select(func.count()).select_from(Item).where(Item.deleted_at.is_(None))
    ).scalar_one()
