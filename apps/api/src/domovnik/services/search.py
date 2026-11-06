"""Vyhledávání a filtrování věcí: fulltext (bez diakritiky, prefixy) + fuzzy (trigramy) + aliasy."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from sqlalchemy import (
    Select,
    and_,
    case,
    desc,
    exists,
    false,
    func,
    literal,
    literal_column,
    or_,
    select,
)
from sqlalchemy.orm import Session

from domovnik.db.models import Item, ItemPlacement, ItemTag, Location, Tag
from domovnik.schemas import CategoryOut, ItemOut, LocationOut
from domovnik.services import categories as category_service
from domovnik.services import items as item_service
from domovnik.services import locations as location_service

SortKey = Literal["relevance", "name", "updated", "created", "label", "warranty", "expires"]


def fold(value: str) -> str:
    """Malá písmena bez diakritiky (stejně jako immutable_unaccent v DB)."""
    norm = unicodedata.normalize("NFKD", value)
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


def tokens(q: str) -> list[str]:
    return [t for t in re.findall(r"\w+", fold(q)) if t]


@dataclass
class ItemFilter:
    q: str | None = None
    category_id: uuid.UUID | None = None  # včetně podkategorií
    location_id: uuid.UUID | None = None  # včetně podstromu
    status: str | None = None
    tags: list[str] = field(default_factory=list)  # musí mít všechny
    unplaced: bool | None = None
    low_stock: bool | None = None
    consumable: bool | None = None
    owner_id: uuid.UUID | None = None
    warranty_before: date | None = None
    expires_before: date | None = None
    trash: bool = False  # jen věci v koši
    sort: SortKey = "relevance"
    descending: bool = False
    limit: int = 50
    offset: int = 0
    fuzzy_threshold: float = 0.3


@dataclass
class ItemPage:
    items: list[ItemOut]
    total: int
    limit: int
    offset: int


def _search_expr(q: str, threshold: float):  # type: ignore[no-untyped-def]
    """Vrátí (podmínka, skóre) pro textový dotaz."""
    toks = tokens(q)
    raw = q.strip()
    ts: Any = literal_column("items.search_tsv")
    folded_name = func.immutable_unaccent(Item.name)
    folded_q = " ".join(toks)

    exact_label = func.lower(Item.label_code) == raw.lower()
    conds = [
        exact_label,
        Item.ean == raw,
        func.lower(func.coalesce(Item.serial_no, "")) == raw.lower(),
    ]
    score: Any = case((exact_label, 10.0), else_=0.0)
    if toks:
        tsquery = func.to_tsquery("simple", " & ".join(f"{t}:*" for t in toks))
        like = f"%{folded_q}%"
        name_like = folded_name.ilike(like)
        sim = func.similarity(folded_name, folded_q)
        alias_sim = func.coalesce(
            select(
                func.max(func.similarity(func.immutable_unaccent(literal_column("a")), folded_q))
            )
            .select_from(func.unnest(Item.aliases).alias("a"))
            .scalar_subquery(),
            0.0,
        )
        conds += [ts.op("@@")(tsquery), name_like, sim > threshold, alias_sim > threshold]
        score = (
            score
            + func.ts_rank_cd(ts, tsquery) * 2.0
            + case((name_like, 1.0), else_=0.0)
            + sim
            + alias_sim
        )
    return or_(*conds), score


def _category_ids(db: Session, category_id: uuid.UUID) -> list[uuid.UUID]:
    return category_service.descendant_ids(db, category_id)


def build_query(db: Session, f: ItemFilter) -> tuple[Select, Select]:  # type: ignore[type-arg]
    where: list[Any] = [Item.deleted_at.is_not(None) if f.trash else Item.deleted_at.is_(None)]
    score = literal(0.0)
    if f.q and f.q.strip():
        cond, score = _search_expr(f.q, f.fuzzy_threshold)
        where.append(cond)
    if f.category_id:
        where.append(Item.category_id.in_(_category_ids(db, f.category_id)))
    if f.location_id:
        loc = db.get(Location, f.location_id)
        if loc is None or loc.path is None:
            where.append(false())
        else:
            where.append(
                exists().where(
                    ItemPlacement.item_id == Item.id,
                    ItemPlacement.location_id == Location.id,
                    literal_column("locations.path").op("<@")(func.text2ltree(loc.path)),
                )
            )
    if f.status:
        where.append(Item.status == f.status)
    for tag in f.tags:
        where.append(
            exists().where(
                ItemTag.item_id == Item.id,
                ItemTag.tag_id == Tag.id,
                func.lower(Tag.name) == tag.strip().lower(),
            )
        )
    if f.unplaced is True:
        where.append(~exists().where(ItemPlacement.item_id == Item.id))
    elif f.unplaced is False:
        where.append(exists().where(ItemPlacement.item_id == Item.id))
    if f.low_stock:
        total = (
            select(func.coalesce(func.sum(ItemPlacement.quantity), 0))
            .where(ItemPlacement.item_id == Item.id)
            .scalar_subquery()
        )
        where.append(and_(Item.min_quantity.is_not(None), total <= Item.min_quantity))
    if f.consumable is not None:
        where.append(Item.is_consumable == f.consumable)
    if f.owner_id:
        where.append(Item.owner_id == f.owner_id)
    if f.warranty_before:
        where.append(
            and_(Item.warranty_until.is_not(None), Item.warranty_until <= f.warranty_before)
        )
    if f.expires_before:
        where.append(and_(Item.expires_at.is_not(None), Item.expires_at <= f.expires_before))

    base = select(Item).where(*where)
    count = select(func.count()).select_from(Item).where(*where)

    order: list = []  # type: ignore[type-arg]
    sort = f.sort
    if sort == "relevance" and not (f.q and f.q.strip()):
        sort = "name"
    if sort == "relevance":
        order = [desc(score), func.lower(Item.name)]
    else:
        col = {
            "name": func.lower(Item.name),
            "updated": Item.updated_at,
            "created": Item.created_at,
            "label": Item.label_code,
            "warranty": Item.warranty_until,
            "expires": Item.expires_at,
        }[sort]
        order = [desc(col).nulls_last() if f.descending else col.asc().nulls_last(), Item.id]
    return base.order_by(*order).limit(f.limit).offset(f.offset), count


def search_items(db: Session, f: ItemFilter) -> ItemPage:
    stmt, count = build_query(db, f)
    items = list(db.execute(stmt).scalars())
    total = db.execute(count).scalar_one()
    return ItemPage(
        items=item_service.to_out(db, items), total=total, limit=f.limit, offset=f.offset
    )


@dataclass
class GlobalResults:
    items: list[ItemOut]
    locations: list[LocationOut]
    categories: list[CategoryOut]


def search_all(db: Session, q: str, *, limit: int = 10, threshold: float = 0.3) -> GlobalResults:
    """Jednotné hledání pro Ctrl+K a AI: věci, umístění a kategorie."""
    page = search_items(db, ItemFilter(q=q, limit=limit, fuzzy_threshold=threshold))
    needle = fold(q).strip()
    locs: list[LocationOut] = []
    cats: list[CategoryOut] = []
    if needle:
        locs = [
            loc
            for loc in location_service.list_locations(db)
            if needle in fold(loc.name)
            or needle in fold(loc.full_name or "")
            or needle == loc.label_code.lower()
        ][:limit]
        cats = [c for c in category_service.list_categories(db) if needle in fold(c.name)][:limit]
    return GlobalResults(items=page.items, locations=locs, categories=cats)


def find_duplicates(
    db: Session, name: str, *, threshold: float = 0.6, limit: int = 5
) -> list[Item]:
    """Věci s velmi podobným názvem (kontrola duplicit při zakládání)."""
    folded = fold(name)
    sim = func.similarity(func.immutable_unaccent(Item.name), folded)
    stmt = (
        select(Item)
        .where(Item.deleted_at.is_(None), sim >= threshold)
        .order_by(desc(sim))
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())
