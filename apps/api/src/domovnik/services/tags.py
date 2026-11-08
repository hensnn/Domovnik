"""Služby pro štítky (tagy)."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.db.models import Item, ItemTag, Tag
from domovnik.errors import Conflict, ValidationFailed
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
        tag = _find_by_name(db, name)
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


def _find_by_name(db: Session, name: str) -> Tag | None:
    return db.execute(select(Tag).where(func.lower(Tag.name) == name.lower())).scalar_one_or_none()


def _refresh_search(db: Session, tag_id: uuid.UUID) -> None:
    """Přegeneruje fulltext věcí s tímto tagem (tag je součástí `search_tsv`)."""
    db.execute(
        update(Item)
        .where(Item.id.in_(select(ItemTag.item_id).where(ItemTag.tag_id == tag_id)))
        .values(updated_at=Item.updated_at)
    )


def create_tag(db: Session, ctx: ActorContext, name: str, color: str | None = None) -> Tag:
    clean = normalize(name)
    if not clean:
        raise ValidationFailed("Název tagu nesmí být prázdný.")
    if _find_by_name(db, clean) is not None:
        raise Conflict(f"Tag „{clean}“ už existuje.")
    tag = Tag(name=clean, color=color)
    db.add(tag)
    flush(db)
    emit(db, ctx, "tag.created", "tag", tag.id, {"name": clean})
    return tag


def update_tag(
    db: Session,
    ctx: ActorContext,
    tag_id: uuid.UUID,
    *,
    name: str | None = None,
    color: str | None = None,
    set_color: bool = False,
) -> Tag:
    """Přejmenuje tag a / nebo změní barvu (`set_color` povolí i vynulování barvy)."""
    tag = get_or_404(db, Tag, tag_id, lock=True, what="Tag")
    fields: dict[str, str | None] = {}
    if name is not None:
        new = normalize(name)
        if not new:
            raise ValidationFailed("Název tagu nesmí být prázdný.")
        other = _find_by_name(db, new)
        if other is not None and other.id != tag.id:
            raise Conflict(f"Tag „{other.name}“ už existuje. Použij sloučení tagů.")
        if new != tag.name:
            tag.name = new
            fields["name"] = new
    if set_color and color != tag.color:
        tag.color = color
        fields["color"] = color
    flush(db)
    if "name" in fields:
        _refresh_search(db, tag.id)
    if fields:
        emit(db, ctx, "tag.updated", "tag", tag.id, fields)
    return tag


def merge_tags(db: Session, ctx: ActorContext, source_id: uuid.UUID, target_id: uuid.UUID) -> Tag:
    """Přesune všechny věci z tagu `source` na `target` a `source` smaže."""
    if source_id == target_id:
        raise ValidationFailed("Tag nelze sloučit sám se sebou.")
    source = get_or_404(db, Tag, source_id, lock=True, what="Tag")
    target = get_or_404(db, Tag, target_id, lock=True, what="Tag")
    moved = db.execute(
        select(func.count()).select_from(ItemTag).where(ItemTag.tag_id == source.id)
    ).scalar_one()
    db.execute(
        insert(ItemTag)
        .from_select(
            ["item_id", "tag_id"],
            select(ItemTag.item_id, literal(target.id)).where(ItemTag.tag_id == source.id),
        )
        .on_conflict_do_nothing()
    )
    db.delete(source)  # ON DELETE CASCADE odstraní i původní vazby
    flush(db)
    emit(
        db,
        ctx,
        "tag.merged",
        "tag",
        target.id,
        {"source": source.name, "target": target.name, "items": moved},
    )
    return target


def delete_tag(db: Session, ctx: ActorContext, tag_id: uuid.UUID) -> None:
    tag = get_or_404(db, Tag, tag_id, lock=True, what="Tag")
    db.delete(tag)
    flush(db)
    emit(db, ctx, "tag.deleted", "tag", tag_id)
