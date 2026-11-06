"""Inventura: kontrola, že věci opravdu jsou tam, kde mají být.

Průběh: ``start_session`` zmrazí očekávaný stav (řádky z ``item_placements`` v podstromu),
uživatel řádky odškrtává (``count_line``), nakonec ``close_session`` volitelně zapíše rozdíly
do dat přes ``items.adjust_quantity`` se zdrojem ``inventory``.

Výsledek řádku (``result``):

- ``ok``      – napočítáno přesně očekávané množství,
- ``missing`` – napočítáno méně než se čekalo (0 = věc chybí úplně),
- ``extra``   – napočítáno víc než se čekalo, nebo věc, kterou tu nečekáme (a nikde jinde
  v rozsahu inventury se nečeká),
- ``moved``   – věc, kterou tu nečekáme, ale v rámci inventury se čeká v jiném umístění.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from domovnik.context import ActorContext, bind_context
from domovnik.db.models import (
    InventoryLine,
    InventorySession,
    Item,
    ItemPlacement,
    Location,
)
from domovnik.errors import Conflict, NotFound, ValidationFailed
from domovnik.schemas import (
    InventoryChange,
    InventoryCloseOut,
    InventoryCounts,
    InventoryLineOut,
    InventorySessionDetail,
    InventorySessionOut,
)
from domovnik.services import items as item_service
from domovnik.services.common import emit, flush, get_or_404
from domovnik.services.locations import location_full_names

ZERO = Decimal(0)


# --- pomocné ------------------------------------------------------------------------------


def _get_session(db: Session, session_id: uuid.UUID, *, lock: bool = False) -> InventorySession:
    return get_or_404(db, InventorySession, session_id, lock=lock, what="Inventura")


def _require_open(session: InventorySession) -> None:
    if session.status != "open":
        raise Conflict("Inventura už je uzavřená nebo zrušená.", status=session.status)


def _subtree_ids(db: Session, location: Location) -> list[uuid.UUID]:
    rows = db.execute(
        text("SELECT id FROM locations WHERE path <@ CAST(:p AS ltree)"), {"p": location.path}
    ).all()
    return [r[0] for r in rows]


def _in_scope(db: Session, session: InventorySession, location_id: uuid.UUID) -> bool:
    if session.location_id is None:
        return True
    root = db.get(Location, session.location_id)
    if root is None:  # kořen mezitím zmizel – rozsah už nelze ověřit
        return True
    return location_id in _subtree_ids(db, root)


def classify(expected: Decimal | None, counted: Decimal, *, elsewhere: bool = False) -> str:
    """Výsledek řádku podle očekávaného a napočítaného množství."""
    if expected is None:
        return "moved" if elsewhere else "extra"
    if counted == expected:
        return "ok"
    return "missing" if counted < expected else "extra"


# --- založení -----------------------------------------------------------------------------


def start_session(
    db: Session, ctx: ActorContext, location_id: uuid.UUID | None, name: str | None = None
) -> InventorySession:
    """Založí inventuru; očekávané řádky vzniknou z aktuálních umístění věcí v podstromu."""
    location: Location | None = None
    if location_id is not None:
        location = get_or_404(db, Location, location_id, what="Umístění")
    title = (name or "").strip() or (
        f"Inventura – {location.name}" if location else "Inventura – celý dům"
    )
    session = InventorySession(location_id=location_id, name=title, started_by=ctx.actor_id)
    db.add(session)
    flush(db)
    db.refresh(session)

    stmt = (
        select(ItemPlacement.item_id, ItemPlacement.location_id, ItemPlacement.quantity)
        .join(Item, Item.id == ItemPlacement.item_id)
        .join(Location, Location.id == ItemPlacement.location_id)
        .where(Item.deleted_at.is_(None))
    )
    if location is not None:
        stmt = stmt.where(ItemPlacement.location_id.in_(_subtree_ids(db, location)))
    for item_id, loc_id, qty in db.execute(stmt).all():
        db.add(
            InventoryLine(
                session_id=session.id,
                item_id=item_id,
                location_id=loc_id,
                expected_qty=qty,
            )
        )
    flush(db)
    emit(db, ctx, "inventory.started", "inventory_session", session.id, {"name": session.name})
    return session


# --- počítání -----------------------------------------------------------------------------


def count_line(
    db: Session,
    ctx: ActorContext,
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    counted_qty: Decimal | None,
) -> InventoryLine:
    """Zapíše napočítané množství řádku (i neočekávané věci). ``None`` řádek vrátí do výchozího
    stavu; neočekávaný řádek se tím smaže."""
    session = _get_session(db, session_id, lock=True)
    _require_open(session)
    if counted_qty is not None and counted_qty < 0:
        raise ValidationFailed("Množství nesmí být záporné.")
    line = db.get(InventoryLine, (session_id, item_id, location_id))

    if counted_qty is None:
        if line is None:
            raise NotFound("Řádek inventury neexistuje.")
        if line.expected_qty is None:  # neočekávaný řádek přidaný při počítání
            db.delete(line)
            flush(db)
            return line
        line.counted_qty, line.counted_at, line.result = None, None, "unchecked"
        flush(db)
        return line

    now = datetime.now(UTC)
    if line is None:
        item = get_or_404(db, Item, item_id, what="Věc")
        if item.deleted_at is not None:
            raise ValidationFailed("Věc je v koši.")
        get_or_404(db, Location, location_id, what="Umístění")
        if not _in_scope(db, session, location_id):
            raise ValidationFailed("Umístění je mimo rozsah této inventury.")
        if counted_qty == 0:
            raise ValidationFailed("Neočekávaná věc musí mít kladné množství.")
        elsewhere = (
            db.execute(
                select(InventoryLine.item_id).where(
                    InventoryLine.session_id == session_id,
                    InventoryLine.item_id == item_id,
                    InventoryLine.expected_qty.is_not(None),
                )
            ).first()
            is not None
        )
        line = InventoryLine(
            session_id=session_id,
            item_id=item_id,
            location_id=location_id,
            expected_qty=None,
            counted_qty=counted_qty,
            result=classify(None, counted_qty, elsewhere=elsewhere),
            counted_at=now,
        )
        db.add(line)
    else:
        line.counted_qty = counted_qty
        line.counted_at = now
        line.result = classify(line.expected_qty, counted_qty)
    flush(db)
    return line


def mark_missing(
    db: Session,
    ctx: ActorContext,
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
) -> InventoryLine:
    """Věc tu není (napočítáno 0)."""
    return count_line(db, ctx, session_id, item_id, location_id, ZERO)


# --- uzavření a zrušení -------------------------------------------------------------------


def _pending_changes(db: Session, session_id: uuid.UUID) -> list[tuple[InventoryLine, Decimal]]:
    """Řádky, jejichž napočítané množství se liší od stavu v databázi (kandidáti na zápis)."""
    out: list[tuple[InventoryLine, Decimal]] = []
    lines = db.execute(
        select(InventoryLine).where(
            InventoryLine.session_id == session_id, InventoryLine.counted_qty.is_not(None)
        )
    ).scalars()
    for line in lines:
        current = db.execute(
            select(ItemPlacement.quantity).where(
                ItemPlacement.item_id == line.item_id,
                ItemPlacement.location_id == line.location_id,
            )
        ).scalar_one_or_none()
        current_qty = current if current is not None else ZERO
        if line.counted_qty is not None and line.counted_qty != current_qty:
            out.append((line, current_qty))
    return out


def close_session(
    db: Session, ctx: ActorContext, session_id: uuid.UUID, *, apply: bool = False
) -> InventoryCloseOut:
    """Uzavře inventuru. S ``apply`` zapíše rozdíly (zdroj ``inventory``) a ``last_seen_at``."""
    session = _get_session(db, session_id, lock=True)
    _require_open(session)
    changes: list[InventoryChange] = []
    now = datetime.now(UTC)

    if apply:
        inv_ctx = dataclasses.replace(ctx, source="inventory")
        bind_context(db, inv_ctx)
        try:
            for line, current in _pending_changes(db, session_id):
                counted = line.counted_qty if line.counted_qty is not None else ZERO
                item = item_service.get_item(db, line.item_id, include_deleted=True)
                if item.deleted_at is not None:
                    continue  # věc mezitím putovala do koše – nesahat
                item_service.adjust_quantity(
                    db,
                    inv_ctx,
                    line.item_id,
                    line.location_id,
                    counted,
                    note=f"Inventura „{session.name}“",
                )
                changes.append(
                    InventoryChange(
                        item_id=line.item_id,
                        item_name=item.name,
                        location_id=line.location_id,
                        from_qty=current,
                        to_qty=counted,
                    )
                )
            seen = db.execute(
                select(InventoryLine.item_id)
                .where(
                    InventoryLine.session_id == session_id,
                    InventoryLine.counted_qty > 0,
                )
                .distinct()
            ).scalars()
            for item_id in list(seen):
                found = db.get(Item, item_id)
                if found is not None and found.deleted_at is None:
                    found.last_seen_at = now
            flush(db)
        finally:
            bind_context(db, ctx)

    session.status = "closed"
    session.closed_at = now
    session.applied_at = now if apply else None
    flush(db)
    db.refresh(session)
    emit(
        db,
        ctx,
        "inventory.closed",
        "inventory_session",
        session.id,
        {"name": session.name, "applied": apply, "changes": len(changes)},
    )
    return InventoryCloseOut(session=session_out(db, session), applied=apply, changes=changes)


def cancel_session(db: Session, ctx: ActorContext, session_id: uuid.UUID) -> InventorySession:
    session = _get_session(db, session_id, lock=True)
    _require_open(session)
    session.status = "cancelled"
    session.closed_at = datetime.now(UTC)
    flush(db)
    db.refresh(session)
    emit(db, ctx, "inventory.cancelled", "inventory_session", session.id, {"name": session.name})
    return session


# --- čtení --------------------------------------------------------------------------------


def _counts(db: Session, session_id: uuid.UUID) -> InventoryCounts:
    counts = InventoryCounts()
    rows = db.execute(
        select(InventoryLine.result).where(InventoryLine.session_id == session_id)
    ).scalars()
    for result in rows:
        counts.total += 1
        setattr(counts, result, getattr(counts, result) + 1)
    counts.changes = len(_pending_changes(db, session_id))
    return counts


def session_out(db: Session, session: InventorySession) -> InventorySessionOut:
    location_name = None
    if session.location_id is not None:
        location_name = location_full_names(db, [session.location_id]).get(session.location_id)
    return InventorySessionOut(
        id=session.id,
        location_id=session.location_id,
        location_name=location_name,
        name=session.name,
        status=session.status,  # type: ignore[arg-type]
        started_by=session.started_by,
        started_at=session.started_at,
        closed_at=session.closed_at,
        applied_at=session.applied_at,
        counts=_counts(db, session.id),
    )


def list_sessions(
    db: Session, *, status: str | None = None, limit: int = 50
) -> list[InventorySessionOut]:
    stmt = select(InventorySession).order_by(InventorySession.started_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(InventorySession.status == status)
    return [session_out(db, s) for s in db.execute(stmt).scalars()]


def session_detail(db: Session, session_id: uuid.UUID) -> InventorySessionDetail:
    session = _get_session(db, session_id)
    rows = db.execute(
        select(InventoryLine, Item.name, Item.label_code, Item.unit, Location.name)
        .join(Item, Item.id == InventoryLine.item_id)
        .join(Location, Location.id == InventoryLine.location_id)
        .where(InventoryLine.session_id == session_id)
        .order_by(Location.path, Item.name)
    ).all()
    paths = location_full_names(db, list({line.location_id for line, *_ in rows}))
    lines = [
        InventoryLineOut(
            item_id=line.item_id,
            item_name=name,
            item_label_code=label,
            unit=unit,
            location_id=line.location_id,
            location_name=loc_name,
            location_path=paths.get(line.location_id),
            expected_qty=line.expected_qty,
            counted_qty=line.counted_qty,
            result=line.result,  # type: ignore[arg-type]
            counted_at=line.counted_at,
            diff=(
                line.counted_qty - (line.expected_qty or ZERO)
                if line.counted_qty is not None
                else None
            ),
        )
        for line, name, label, unit, loc_name in rows
    ]
    base = session_out(db, session)
    return InventorySessionDetail(**base.model_dump(), lines=lines)
