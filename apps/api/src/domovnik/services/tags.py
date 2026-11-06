"""Služby pro štítky (tagy)."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.db.models import ItemTag, Tag
from domovnik.errors import ValidationFailed
from domovnik.schemas import TagOut
from domovnik.services.common import emit, flush, get_or_404


def normalize(name: str) -> str:
    return " ".join(name.split()).strip()


def get_or_create(db: Session, names: list[str]) -> list[Tag]:
    """Vrátí tagy podle názvů (bez ohledu na velikost písmen), chybějící vytvoří."""
    result: list[Tag] = []
    seen: set[str] = set()
    for raw in names:
        name = normalize(raw)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        tag = db.execute(
            select(Tag).where(func.lower(Tag.name) == name.lower())
        ).scalar_one_or_none()
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            flush(db)
        result.append(tag)
    return result


def set_item_tags(db: Session, item_id: uuid.UUID, names: list[str]) -> list[str]:
    tags = get_or_create(db, names)
    wanted = {t.id for t in tags}
    current = set(db.execute(select(ItemTag.tag_id).where(ItemTag.item_id == item_id)).scalars())
    for tag_id in current - wanted:
        db.execute(delete(ItemTag).where(ItemTag.item_id == item_id, ItemTag.tag_id == tag_id))
    for tag_id in wanted - current:
        db.execute(insert(ItemTag).values(item_id=item_id, tag_id=tag_id))
    return [t.name for t in tags]


def item_tag_names(db: Session, item_id: uuid.UUID) -> list[str]:
    return list(
        db.execute(
            select(Tag.name)
            .join(ItemTag, ItemTag.tag_id == Tag.id)
            .where(ItemTag.item_id == item_id)
            .order_by(Tag.name)
        ).scalars()
    )


def list_tags(db: Session) -> list[TagOut]:
    rows = db.execute(
        select(Tag, func.count(ItemTag.item_id))
        .outerjoin(ItemTag, ItemTag.tag_id == Tag.id)
        .group_by(Tag.id)
        .order_by(Tag.name)
    ).all()
    return [TagOut(id=t.id, name=t.name, color=t.color, item_count=n) for t, n in rows]


def rename_tag(db: Session, ctx: ActorContext, tag_id: uuid.UUID, name: str) -> Tag:
    tag = get_or_404(db, Tag, tag_id, lock=True, what="Tag")
    new = normalize(name)
    if not new:
        raise ValidationFailed("Název tagu nesmí být prázdný.")
    tag.name = new
    flush(db)
    emit(db, ctx, "tag.updated", "tag", tag.id, {"name": new})
    return tag


def delete_tag(db: Session, ctx: ActorContext, tag_id: uuid.UUID) -> None:
    tag = get_or_404(db, Tag, tag_id, lock=True, what="Tag")
    db.delete(tag)
    flush(db)
    emit(db, ctx, "tag.deleted", "tag", tag_id)
