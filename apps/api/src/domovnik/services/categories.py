"""Služby pro strom kategorií."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.db.models import Category, Item
from domovnik.errors import Conflict, ValidationFailed
from domovnik.schemas import CategoryCreate, CategoryOut, CategoryUpdate
from domovnik.services.common import check_version, emit, flush, get_or_404, slugify


def _unique_slug(db: Session, name: str) -> str:
    base = slugify(name)
    slug, n = base, 2
    while db.execute(select(Category.id).where(Category.slug == slug)).first():
        slug, n = f"{base}-{n}", n + 1
    return slug


def create_category(db: Session, ctx: ActorContext, data: CategoryCreate) -> Category:
    if data.parent_id:
        get_or_404(db, Category, data.parent_id, what="Nadřazená kategorie")
    cat = Category(
        parent_id=data.parent_id,
        name=data.name.strip(),
        slug=_unique_slug(db, data.name),
        description=data.description,
        color=data.color,
        icon=data.icon,
        sort_order=data.sort_order,
        created_by=ctx.actor_id,
    )
    db.add(cat)
    flush(db)
    db.refresh(cat)
    emit(db, ctx, "category.created", "category", cat.id, {"name": cat.name})
    return cat


def _ancestors(db: Session, category_id: uuid.UUID) -> list[uuid.UUID]:
    """Id kategorie a všech jejích předků (od kategorie ke kořeni)."""
    chain: list[uuid.UUID] = []
    current: uuid.UUID | None = category_id
    while current is not None and current not in chain:
        chain.append(current)
        current = db.execute(select(Category.parent_id).where(Category.id == current)).scalar()
    return chain


def descendant_ids(db: Session, category_id: uuid.UUID) -> list[uuid.UUID]:
    """Kategorie včetně všech potomků."""
    result, frontier = [category_id], [category_id]
    while frontier:
        children = list(
            db.execute(select(Category.id).where(Category.parent_id.in_(frontier))).scalars()
        )
        children = [c for c in children if c not in result]
        result.extend(children)
        frontier = children
    return result


def update_category(
    db: Session, ctx: ActorContext, category_id: uuid.UUID, data: CategoryUpdate
) -> Category:
    cat = get_or_404(db, Category, category_id, lock=True, what="Kategorie")
    check_version(cat.version, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if "name" in changes and not changes["name"]:
        raise ValidationFailed("Název nesmí být prázdný.")
    if "parent_id" in changes:
        new_parent = changes["parent_id"]
        if new_parent is not None:
            get_or_404(db, Category, new_parent, what="Nadřazená kategorie")
            if category_id in _ancestors(db, new_parent):
                raise ValidationFailed("Kategorii nelze přesunout do vlastního podstromu.")
    if "sort_order" in changes and changes["sort_order"] is None:
        del changes["sort_order"]
    for key, value in changes.items():
        setattr(cat, key, value.strip() if key == "name" and isinstance(value, str) else value)
    flush(db)
    db.refresh(cat)
    emit(db, ctx, "category.updated", "category", cat.id, {"fields": sorted(changes)})
    return cat


def merge_categories(
    db: Session, ctx: ActorContext, source_id: uuid.UUID, target_id: uuid.UUID
) -> Category:
    """Přesune věci i podkategorie ze `source` do `target` a `source` smaže."""
    if source_id == target_id:
        raise ValidationFailed("Zdrojová a cílová kategorie jsou stejné.")
    source = get_or_404(db, Category, source_id, lock=True, what="Zdrojová kategorie")
    target = get_or_404(db, Category, target_id, lock=True, what="Cílová kategorie")
    if source_id in _ancestors(db, target_id):
        raise ValidationFailed("Cílová kategorie leží uvnitř zdrojové.")
    db.execute(update(Item).where(Item.category_id == source.id).values(category_id=target.id))
    db.execute(update(Category).where(Category.parent_id == source.id).values(parent_id=target.id))
    db.expire_all()
    db.delete(get_or_404(db, Category, source_id))
    flush(db)
    emit(db, ctx, "category.merged", "category", target.id, {"source": str(source_id)})
    return target


def delete_category(
    db: Session, ctx: ActorContext, category_id: uuid.UUID, *, reassign_to: uuid.UUID | None = None
) -> None:
    cat = get_or_404(db, Category, category_id, lock=True, what="Kategorie")
    has_children = db.execute(
        select(Category.id).where(Category.parent_id == cat.id).limit(1)
    ).first()
    if has_children:
        raise Conflict("Kategorie má podkategorie. Použij sloučení nebo je nejdřív přesuň.")
    used = db.execute(
        select(func.count())
        .select_from(Item)
        .where(Item.category_id == cat.id, Item.deleted_at.is_(None))  # věci v koši nevadí
    ).scalar_one()
    if used and reassign_to is None:
        raise Conflict(f"V kategorii je {used} věcí. Zadej cílovou kategorii nebo použij sloučení.")
    if reassign_to is not None:
        get_or_404(db, Category, reassign_to, what="Cílová kategorie")
        db.execute(update(Item).where(Item.category_id == cat.id).values(category_id=reassign_to))
    db.expire_all()
    db.delete(get_or_404(db, Category, category_id))
    flush(db)
    emit(db, ctx, "category.deleted", "category", category_id, {"name": cat.name})


def list_categories(db: Session) -> list[CategoryOut]:
    """Plochý seznam kategorií s plnou cestou a počty věcí (přímo / včetně podkategorií)."""
    cats = list(db.execute(select(Category).order_by(Category.sort_order, Category.name)).scalars())
    direct = dict(
        db.execute(
            select(Item.category_id, func.count())
            .where(Item.deleted_at.is_(None), Item.category_id.is_not(None))
            .group_by(Item.category_id)
        ).all()
    )
    by_id = {c.id: c for c in cats}
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for c in cats:
        children.setdefault(c.parent_id, []).append(c.id)

    def total(cid: uuid.UUID) -> int:
        return direct.get(cid, 0) + sum(total(ch) for ch in children.get(cid, []))

    def full_name(cid: uuid.UUID) -> str:
        names, seen = [], set()
        cur: uuid.UUID | None = cid
        while cur is not None and cur not in seen:
            seen.add(cur)
            names.append(by_id[cur].name)
            cur = by_id[cur].parent_id
        return " › ".join(reversed(names))

    out: list[CategoryOut] = []
    for c in cats:
        item = CategoryOut.model_validate(c)
        item.direct_item_count = direct.get(c.id, 0)
        item.item_count = total(c.id)
        item.full_name = full_name(c.id)
        out.append(item)
    return out


def get_or_create_path(db: Session, ctx: ActorContext, names: list[str]) -> Category:
    """Najde/vytvoří kategorii podle cesty názvů, např. ['Elektronika', 'Kabely']."""
    if not names:
        raise ValidationFailed("Cesta kategorie je prázdná.")
    parent_id: uuid.UUID | None = None
    current: Category | None = None
    for raw in names:
        name = raw.strip()
        stmt = select(Category).where(
            Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id
        )
        found = next(
            (c for c in db.execute(stmt).scalars() if c.name.lower() == name.lower()), None
        )
        if found is None:
            found = create_category(db, ctx, CategoryCreate(name=name, parent_id=parent_id))
        current, parent_id = found, found.id
    if current is None:  # pragma: no cover
        raise ValidationFailed("Cesta kategorie je prázdná.")
    return current


def path_exists(db: Session, names: list[str]) -> bool:
    """Existuje kategorie s touto cestou (bez ohledu na velikost písmen)?"""
    parent_id: uuid.UUID | None = None
    for raw in names:
        found = next(
            (
                c
                for c in db.execute(
                    select(Category).where(
                        Category.parent_id.is_(None)
                        if parent_id is None
                        else Category.parent_id == parent_id
                    )
                ).scalars()
                if c.name.lower() == raw.strip().lower()
            ),
            None,
        )
        if found is None:
            return False
        parent_id = found.id
    return True
