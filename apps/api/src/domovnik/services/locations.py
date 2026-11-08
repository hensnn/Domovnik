"""Služby pro strom umístění."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.db.models import ItemPlacement, Location
from domovnik.errors import Conflict, ValidationFailed
from domovnik.schemas import LocationCreate, LocationOut, LocationUpdate
from domovnik.services.common import check_version, emit, flush, get_or_404


def _next_label(db: Session) -> str:
    n = db.execute(text("SELECT nextval('location_label_seq')")).scalar_one()
    return f"L-{n:06d}"


def _require_active_parent(db: Session, parent_id: uuid.UUID | None) -> Location | None:
    if parent_id is None:
        return None
    parent = get_or_404(db, Location, parent_id, what="Nadřazené umístění")
    if parent.archived_at is not None:
        raise ValidationFailed("Nadřazené umístění je archivované.")
    return parent


def create_location(db: Session, ctx: ActorContext, data: LocationCreate) -> Location:
    """Vytvoří umístění. S klientským ``id`` je volání idempotentní (existující se vrátí)."""
    if data.id is not None:
        existing = db.get(Location, data.id)
        if existing is not None:
            return existing
    _require_active_parent(db, data.parent_id)
    loc = Location(
        **({"id": data.id} if data.id is not None else {}),
        parent_id=data.parent_id,
        kind=data.kind,
        name=data.name.strip(),
        label_code=data.label_code or _next_label(db),
        description=data.description,
        notes=data.notes,
        is_movable=data.is_movable,
        color=data.color,
        icon=data.icon,
        sort_order=data.sort_order,
        attributes=data.attributes,
        created_by=ctx.actor_id,
    )
    db.add(loc)
    flush(db)
    db.refresh(loc)
    emit(db, ctx, "location.created", "location", loc.id, {"name": loc.name})
    return loc


def find_path(db: Session, path: list[str]) -> Location | None:
    """Aktivní umístění podle cesty názvů od kořene (bez ohledu na velikost písmen); nic nevytváří."""
    rows = db.execute(select(Location).where(Location.archived_at.is_(None))).scalars().all()
    parent_id: uuid.UUID | None = None
    found: Location | None = None
    for name in path:
        wanted = name.strip().lower()
        found = next(
            (r for r in rows if r.parent_id == parent_id and r.name.strip().lower() == wanted),
            None,
        )
        if found is None:
            return None
        parent_id = found.id
    return found


MAX_DUPLICATE_NODES = 500


def _free_copy_name(taken: set[str], name: str) -> str:
    """„Název (kopie)“, případně „Název (kopie 2)“ … – první, který mezi sourozenci není."""
    candidate, n = f"{name} (kopie)", 2
    while candidate.lower() in taken:
        candidate, n = f"{name} (kopie {n})", n + 1
    return candidate


def duplicate_location(
    db: Session,
    ctx: ActorContext,
    location_id: uuid.UUID,
    *,
    name: str | None = None,
    include_children: bool = True,
) -> tuple[Location, int]:
    """Zkopíruje umístění (vedle původního) a volitelně celý podstrom aktivních podřízených.

    Kopíruje se jen struktura (název, druh, popis, poznámky, barva, ikona, atributy); věci,
    fotky a štítky ne – kopie dostane nové kódy štítků. Vrací (kořen kopie, počet vytvořených).
    """
    src = get_or_404(db, Location, location_id, what="Umístění")
    siblings = {
        n.lower()
        for n in db.execute(select(Location.name).where(Location.parent_id == src.parent_id))
        .scalars()
        .all()
    }
    if name is not None and name.strip().lower() in siblings:
        raise Conflict(f"Umístění „{name.strip()}“ už na stejné úrovni existuje.")
    new_name = name.strip() if name else _free_copy_name(siblings, src.name)

    created = 0

    def copy(node: Location, parent_id: uuid.UUID | None, node_name: str) -> Location:
        nonlocal created
        if created >= MAX_DUPLICATE_NODES:
            raise Conflict(f"Příliš velký strom ke zkopírování (max. {MAX_DUPLICATE_NODES}).")
        clone = create_location(
            db,
            ctx,
            LocationCreate(
                name=node_name,
                parent_id=parent_id,
                kind=node.kind,  # type: ignore[arg-type]
                description=node.description,
                notes=node.notes,
                is_movable=node.is_movable,
                color=node.color,
                icon=node.icon,
                sort_order=node.sort_order,
                attributes=node.attributes or {},
            ),
        )
        created += 1
        if include_children:
            kids = (
                db.execute(
                    select(Location)
                    .where(Location.parent_id == node.id, Location.archived_at.is_(None))
                    .order_by(Location.sort_order, Location.name)
                )
                .scalars()
                .all()
            )
            for kid in kids:
                copy(kid, clone.id, kid.name)
        return clone

    root = copy(src, src.parent_id, new_name)
    emit(
        db,
        ctx,
        "location.duplicated",
        "location",
        root.id,
        {"source": str(src.id), "created": created},
    )
    return root, created


def update_location(
    db: Session, ctx: ActorContext, location_id: uuid.UUID, data: LocationUpdate
) -> Location:
    loc = get_or_404(db, Location, location_id, lock=True, what="Umístění")
    check_version(loc.version, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if "name" in changes and changes["name"] is None:
        raise ValidationFailed("Název nesmí být prázdný.")
    for field in ("kind", "is_movable", "sort_order", "attributes"):
        if field in changes and changes[field] is None:
            del changes[field]

    if "parent_id" in changes and changes["parent_id"] != loc.parent_id:
        move_location(db, ctx, loc, changes.pop("parent_id"))
    else:
        changes.pop("parent_id", None)

    for key, value in changes.items():
        setattr(loc, key, value.strip() if key == "name" and isinstance(value, str) else value)
    flush(db)
    db.refresh(loc)
    emit(db, ctx, "location.updated", "location", loc.id, {"fields": sorted(changes)})
    return loc


def move_location(
    db: Session, ctx: ActorContext, loc: Location, new_parent_id: uuid.UUID | None
) -> None:
    """Přesune umístění (i s celým podstromem). Trigger v DB přepočítá cesty."""
    parent = _require_active_parent(db, new_parent_id)
    if parent is not None:
        if parent.id == loc.id:
            raise ValidationFailed("Umístění nelze přesunout samo do sebe.")
        is_descendant = db.execute(
            text("SELECT CAST(:p AS ltree) <@ CAST(:c AS ltree)"),
            {"p": parent.path, "c": loc.path},
        ).scalar_one()
        if is_descendant:
            raise ValidationFailed("Umístění nelze přesunout do vlastního podstromu.")
    old_parent = loc.parent_id
    loc.parent_id = new_parent_id
    flush(db)
    db.refresh(loc)
    emit(
        db,
        ctx,
        "location.moved",
        "location",
        loc.id,
        {
            "from_parent": str(old_parent) if old_parent else None,
            "to_parent": str(new_parent_id) if new_parent_id else None,
        },
    )


def _subtree_ids(db: Session, loc: Location) -> list[uuid.UUID]:
    rows = db.execute(
        text("SELECT id FROM locations WHERE path <@ CAST(:p AS ltree)"), {"p": loc.path}
    ).all()
    return [r[0] for r in rows]


def archive_location(db: Session, ctx: ActorContext, location_id: uuid.UUID) -> Location:
    """Archivuje umístění i podstrom; odmítne, pokud je v něm nějaká věc."""
    loc = get_or_404(db, Location, location_id, lock=True, what="Umístění")
    ids = _subtree_ids(db, loc)
    count = db.execute(
        text("SELECT count(*) FROM item_placements WHERE location_id = ANY(:ids)"), {"ids": ids}
    ).scalar_one()
    if count:
        raise Conflict(
            f"V umístění (a jeho podstromu) je {count} položek. Nejdřív je přesuň jinam.",
            placements=count,
        )
    db.execute(
        text(
            "UPDATE locations SET archived_at = now() WHERE id = ANY(:ids) AND archived_at IS NULL"
        ),
        {"ids": ids},
    )
    db.refresh(loc)
    emit(db, ctx, "location.archived", "location", loc.id)
    return loc


def unarchive_location(db: Session, ctx: ActorContext, location_id: uuid.UUID) -> Location:
    loc = get_or_404(db, Location, location_id, lock=True, what="Umístění")
    if loc.parent_id:
        parent = get_or_404(db, Location, loc.parent_id)
        if parent.archived_at is not None:
            raise Conflict("Nejdřív obnov nadřazené umístění.")
    loc.archived_at = None
    flush(db)
    db.refresh(loc)
    emit(db, ctx, "location.unarchived", "location", loc.id)
    return loc


def delete_location(db: Session, ctx: ActorContext, location_id: uuid.UUID) -> None:
    """Trvale smaže prázdné umístění bez potomků."""
    loc = get_or_404(db, Location, location_id, lock=True, what="Umístění")
    children = db.execute(select(Location.id).where(Location.parent_id == loc.id).limit(1)).first()
    if children:
        raise Conflict("Umístění má podřízená umístění.")
    placed = db.execute(
        select(ItemPlacement.id).where(ItemPlacement.location_id == loc.id).limit(1)
    ).first()
    if placed:
        raise Conflict("V umístění jsou položky.")
    db.delete(loc)
    flush(db)
    emit(db, ctx, "location.deleted", "location", loc.id, {"name": loc.name})


def get_or_create_path(
    db: Session, ctx: ActorContext, names: list[str], kind_by_depth: list[str] | None = None
) -> Location:
    """Najde/vytvoří umístění podle cesty názvů, např. ['Dům', 'Garáž', 'Regál A']."""
    if not names:
        raise ValidationFailed("Cesta umístění je prázdná.")
    parent_id: uuid.UUID | None = None
    current: Location | None = None
    for depth, raw in enumerate(names):
        name = raw.strip()
        stmt = select(Location).where(
            Location.parent_id.is_(None) if parent_id is None else Location.parent_id == parent_id,
            Location.archived_at.is_(None),
        )
        found = next(
            (x for x in db.execute(stmt).scalars() if x.name.lower() == name.lower()), None
        )
        if found is None:
            kind = kind_by_depth[depth] if kind_by_depth and depth < len(kind_by_depth) else "other"
            found = create_location(
                db,
                ctx,
                LocationCreate(name=name, parent_id=parent_id, kind=kind),  # type: ignore[arg-type]
            )
        current, parent_id = found, found.id
    if current is None:  # pragma: no cover
        raise ValidationFailed("Cesta umístění je prázdná.")
    return current


_LIST_SQL = text(
    """
    SELECT l.id, l.parent_id, l.kind, l.name, l.label_code, l.description, l.notes, l.is_movable,
           l.color, l.icon, l.sort_order, l.attributes, l.depth, l.archived_at, l.version,
           (SELECT string_agg(a.name, ' › ' ORDER BY a.depth) FROM locations a
             WHERE a.path @> l.path) AS full_name,
           (SELECT count(DISTINCT p.item_id) FROM locations d
              JOIN item_placements p ON p.location_id = d.id
              JOIN items i ON i.id = p.item_id AND i.deleted_at IS NULL
             WHERE d.path <@ l.path) AS item_count,
           (SELECT count(DISTINCT p.item_id) FROM item_placements p
              JOIN items i ON i.id = p.item_id AND i.deleted_at IS NULL
             WHERE p.location_id = l.id) AS direct_item_count
      FROM locations l
     WHERE (:include_archived OR l.archived_at IS NULL)
     ORDER BY l.path
    """
)


def list_locations(db: Session, *, include_archived: bool = False) -> list[LocationOut]:
    """Plochý seznam v pořadí průchodu stromem (sourozenci dle sort_order, pak názvu).

    Strom si klient složí přes ``parent_id``; ``full_name`` a počty položek jsou předpočítané.
    """
    rows = db.execute(_LIST_SQL, {"include_archived": include_archived}).mappings().all()
    items = [LocationOut.model_validate(dict(r)) for r in rows]
    children: dict[uuid.UUID | None, list[LocationOut]] = {}
    ids = {i.id for i in items}
    for item in items:
        # potomek archivovaného rodiče (při skrytých archivovaných) se chová jako kořen
        key = item.parent_id if item.parent_id in ids else None
        children.setdefault(key, []).append(item)
    ordered: list[LocationOut] = []

    def walk(parent: uuid.UUID | None) -> None:
        for child in sorted(children.get(parent, []), key=lambda x: (x.sort_order, x.name.lower())):
            ordered.append(child)
            walk(child.id)

    walk(None)
    return ordered


def get_location_out(db: Session, location_id: uuid.UUID) -> LocationOut:
    get_or_404(db, Location, location_id, what="Umístění")
    for loc in list_locations(db, include_archived=True):
        if loc.id == location_id:
            return loc
    raise AssertionError("unreachable")  # pragma: no cover


def location_full_names(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = db.execute(
        text(
            """
            SELECT l.id, (SELECT string_agg(a.name, ' › ' ORDER BY a.depth)
                            FROM locations a WHERE a.path @> l.path) AS full_name
              FROM locations l WHERE l.id = ANY(:ids)
            """
        ),
        {"ids": ids},
    ).all()
    return {r[0]: r[1] for r in rows}


def contents(
    db: Session, location_id: uuid.UUID, *, recursive: bool = True
) -> list[dict[str, Any]]:
    """Co je v umístění (a případně v jeho podstromu)."""
    loc = get_or_404(db, Location, location_id, what="Umístění")
    rows = db.execute(
        text(
            """
            SELECT i.id AS item_id, i.label_code, i.name, i.unit, p.quantity,
                   d.id AS location_id, d.label_code AS location_label
              FROM locations d
              JOIN item_placements p ON p.location_id = d.id
              JOIN items i ON i.id = p.item_id AND i.deleted_at IS NULL
             WHERE (CASE WHEN :rec THEN d.path <@ CAST(:p AS ltree) ELSE d.id = :id END)
             ORDER BY i.name
            """
        ),
        {"rec": recursive, "p": loc.path, "id": location_id},
    ).mappings()
    return [dict(r) for r in rows]


def path_exists(db: Session, names: list[str]) -> bool:
    """Existuje (neanchivované) umístění s touto cestou?"""
    parent_id: uuid.UUID | None = None
    for raw in names:
        stmt = select(Location).where(
            Location.parent_id.is_(None) if parent_id is None else Location.parent_id == parent_id,
            Location.archived_at.is_(None),
        )
        found = next(
            (x for x in db.execute(stmt).scalars() if x.name.lower() == raw.strip().lower()), None
        )
        if found is None:
            return False
        parent_id = found.id
    return True
