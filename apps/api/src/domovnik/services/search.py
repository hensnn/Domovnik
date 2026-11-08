"""Vyhledávání a filtrování věcí: fulltext (bez diakritiky, prefixy) + fuzzy (trigramy) + aliasy."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
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

SortKey = Literal[
    "relevance", "name", "updated", "created", "label", "warranty", "expires", "price", "quantity"
]
SearchScope = Literal["all", "items", "locations", "categories"]

# Druhy umístění: české názvy a synonyma, podle kterých jdou umístění najít ("nábytek", "místnost"…).
KIND_LABELS: dict[str, str] = {
    "building": "budova",
    "floor": "patro",
    "room": "místnost",
    "zone": "zóna",
    "furniture": "nábytek",
    "shelf": "police",
    "drawer": "zásuvka",
    "box": "krabice",
    "other": "jiné",
}
KIND_SYNONYMS: dict[str, tuple[str, ...]] = {
    "building": ("dům", "domek", "stavba"),
    "floor": ("podlaží", "etáž"),
    "room": ("pokoj", "místnosti", "room"),
    "zone": ("oblast", "prostor"),
    "furniture": ("nábytku", "furniture"),
    "shelf": ("regál", "polička", "shelf"),
    "drawer": ("šuplík", "šuflík", "drawer"),
    "box": ("krabička", "přepravka", "kontejner", "box"),
}


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
    location_kinds: list[str] = field(default_factory=list)  # druh umístění (kterékoli z nich)
    brand: str | None = None  # část značky, bez diakritiky
    condition: str | None = None
    has_photo: bool | None = None
    no_category: bool | None = None  # True = jen bez kategorie
    min_price: Decimal | None = None  # pořizovací cena
    max_price: Decimal | None = None
    purchased_after: date | None = None
    purchased_before: date | None = None
    min_qty: Decimal | None = None  # celkové množství
    max_qty: Decimal | None = None
    created_after: date | None = None
    updated_after: date | None = None
    expired: bool | None = None  # True = prošlá trvanlivost
    warranty_active: bool | None = None  # True = záruka ještě běží
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
    if f.location_kinds:
        where.append(
            exists().where(
                ItemPlacement.item_id == Item.id,
                ItemPlacement.location_id == Location.id,
                Location.kind.in_(f.location_kinds),
            )
        )
    if f.brand and f.brand.strip():
        where.append(
            func.immutable_unaccent(func.coalesce(Item.brand, "")).ilike(
                f"%{fold(f.brand).strip()}%"
            )
        )
    if f.condition:
        where.append(Item.condition == f.condition)
    if f.has_photo is not None:
        where.append(
            Item.primary_file_id.is_not(None) if f.has_photo else Item.primary_file_id.is_(None)
        )
    if f.no_category:
        where.append(Item.category_id.is_(None))
    if f.min_price is not None:
        where.append(Item.purchase_price >= f.min_price)
    if f.max_price is not None:
        where.append(Item.purchase_price <= f.max_price)
    if f.purchased_after:
        where.append(Item.purchase_date >= f.purchased_after)
    if f.purchased_before:
        where.append(Item.purchase_date <= f.purchased_before)
    total_qty = (
        select(func.coalesce(func.sum(ItemPlacement.quantity), 0))
        .where(ItemPlacement.item_id == Item.id)
        .scalar_subquery()
    )
    if f.low_stock:
        where.append(and_(Item.min_quantity.is_not(None), total_qty <= Item.min_quantity))
    if f.min_qty is not None:
        where.append(total_qty >= f.min_qty)
    if f.max_qty is not None:
        where.append(total_qty <= f.max_qty)
    if f.created_after:
        where.append(Item.created_at >= datetime.combine(f.created_after, time.min, tzinfo=UTC))
    if f.updated_after:
        where.append(Item.updated_at >= datetime.combine(f.updated_after, time.min, tzinfo=UTC))
    today = date.today()
    if f.expired is True:
        where.append(and_(Item.expires_at.is_not(None), Item.expires_at < today))
    if f.warranty_active is True:
        where.append(and_(Item.warranty_until.is_not(None), Item.warranty_until >= today))
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
            "price": Item.purchase_price,
            "quantity": total_qty,
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
    totals: dict[str, int] = field(default_factory=dict)  # počty všech nálezů (před ořezem limitem)


def _kind_text(kind: str) -> str:
    """Slova, podle kterých se umístění hledá jako druh (kód, český název, synonyma)."""
    return " ".join([kind, KIND_LABELS.get(kind, ""), *KIND_SYNONYMS.get(kind, ())])


def _match_locations(
    all_locations: list[LocationOut], toks: list[str], kinds: list[str]
) -> list[LocationOut]:
    """Umístění, kde se každé slovo dotazu najde v názvu, cestě, štítku nebo druhu.

    Nálezy podle názvu / cesty jsou před nálezy jen podle druhu.
    """
    by_name: list[LocationOut] = []
    by_kind: list[LocationOut] = []
    for loc in all_locations:
        if kinds and loc.kind not in kinds:
            continue
        name_hay = fold(f"{loc.name} {loc.full_name or ''} {loc.label_code}")
        kind_hay = fold(_kind_text(loc.kind))
        if all(t in name_hay for t in toks):
            by_name.append(loc)
        elif all(t in name_hay or t in kind_hay for t in toks):
            by_kind.append(loc)
    return by_name + by_kind


def search_all(
    db: Session,
    q: str,
    *,
    limit: int = 10,
    threshold: float = 0.3,
    scope: SearchScope = "all",
    kinds: list[str] | None = None,
) -> GlobalResults:
    """Jednotné hledání pro Ctrl+K a AI: věci, umístění a kategorie.

    Umístění se najdou i podle druhu (např. „nábytek“, „místnost“); `kinds` výsledek zúží,
    `scope` omezí hledání jen na jeden typ.
    """
    toks = tokens(q)
    items: list[ItemOut] = []
    locs: list[LocationOut] = []
    cats: list[CategoryOut] = []
    totals = {"items": 0, "locations": 0, "categories": 0}
    if scope in ("all", "items") and not kinds:
        page = search_items(db, ItemFilter(q=q, limit=limit, fuzzy_threshold=threshold))
        items, totals["items"] = page.items, page.total
    if (toks or kinds) and scope in ("all", "locations"):
        found = _match_locations(location_service.list_locations(db), toks, kinds or [])
        totals["locations"] = len(found)
        locs = found[:limit]
    if toks and scope in ("all", "categories") and not kinds:
        found_cats = [
            c for c in category_service.list_categories(db) if all(t in fold(c.name) for t in toks)
        ]
        totals["categories"] = len(found_cats)
        cats = found_cats[:limit]
    return GlobalResults(items=items, locations=locs, categories=cats, totals=totals)


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
