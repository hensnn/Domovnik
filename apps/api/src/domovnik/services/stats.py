"""Souhrny pro dashboard a audit."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domovnik.db.models import AuditLog, Category, Item, ItemPlacement, Location, Movement
from domovnik.schemas import ItemOut, MovementOut
from domovnik.services import items as item_service
from domovnik.services import search
from domovnik.services.search import ItemFilter


def dashboard(db: Session, *, warranty_days: int = 30, expiry_days: int = 14) -> dict[str, Any]:
    today = date.today()
    active = Item.deleted_at.is_(None)
    total_items = db.execute(select(func.count()).select_from(Item).where(active)).scalar_one()
    trash = db.execute(
        select(func.count()).select_from(Item).where(Item.deleted_at.is_not(None))
    ).scalar_one()
    locations = db.execute(
        select(func.count()).select_from(Location).where(Location.archived_at.is_(None))
    ).scalar_one()
    categories = db.execute(select(func.count()).select_from(Category)).scalar_one()
    placed = select(ItemPlacement.item_id).distinct()
    unplaced = db.execute(
        select(func.count()).select_from(Item).where(active, Item.id.not_in(placed))
    ).scalar_one()
    uncategorized = db.execute(
        select(func.count()).select_from(Item).where(active, Item.category_id.is_(None))
    ).scalar_one()

    def page(f: ItemFilter) -> tuple[list[ItemOut], int]:
        res = search.search_items(db, f)
        return res.items, res.total

    low, low_n = page(ItemFilter(low_stock=True, limit=10))
    warranty, warranty_n = page(
        ItemFilter(warranty_before=today + timedelta(days=warranty_days), sort="warranty", limit=10)
    )
    expiring, expiring_n = page(
        ItemFilter(expires_before=today + timedelta(days=expiry_days), sort="expires", limit=10)
    )
    recent = item_service.list_movements(db, limit=10)
    return {
        "counts": {
            "items": total_items,
            "locations": locations,
            "categories": categories,
            "unplaced": unplaced,
            "uncategorized": uncategorized,
            "low_stock": low_n,
            "warranty_soon": warranty_n,
            "expiring_soon": expiring_n,
            "trash": trash,
        },
        "low_stock": low,
        "warranty_soon": warranty,
        "expiring_soon": expiring,
        "recent_movements": [MovementOut.model_validate(m) for m in recent],
    }


def audit_for_entity(
    db: Session,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    *,
    limit: int = 100,
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    return list(db.execute(stmt).scalars())


def recent_movements(db: Session, limit: int = 50) -> list[Movement]:
    return item_service.list_movements(db, limit=limit)
