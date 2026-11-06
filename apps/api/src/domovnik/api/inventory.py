"""Inventura: relace, počítání řádků, uzavření a zrušení."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from domovnik.api import deps
from domovnik.api.deps import RequestCtx
from domovnik.schemas import (
    InventoryCloseIn,
    InventoryCloseOut,
    InventoryCountIn,
    InventorySessionDetail,
    InventorySessionOut,
    InventoryStart,
    InventoryStatus,
)
from domovnik.services import inventory as inventory_service

router = APIRouter(tags=["inventory"])


@router.post("/inventory/sessions", response_model=InventorySessionDetail, status_code=201)
def start_session(
    body: InventoryStart, rc: RequestCtx = Depends(deps.write)
) -> InventorySessionDetail:
    """Založí inventuru; očekávané řádky vzniknou z aktuálních umístění věcí v podstromu."""
    session = inventory_service.start_session(rc.db, rc.ctx, body.location_id, body.name)
    rc.commit()
    return inventory_service.session_detail(rc.db, session.id)


@router.get("/inventory/sessions", response_model=list[InventorySessionOut])
def list_sessions(
    status: InventoryStatus | None = None,
    limit: int = Query(50, ge=1, le=200),
    rc: RequestCtx = Depends(deps.read),
) -> list[InventorySessionOut]:
    return inventory_service.list_sessions(rc.db, status=status, limit=limit)


@router.get("/inventory/sessions/{session_id}", response_model=InventorySessionDetail)
def get_session(
    session_id: uuid.UUID, rc: RequestCtx = Depends(deps.read)
) -> InventorySessionDetail:
    return inventory_service.session_detail(rc.db, session_id)


@router.patch(
    "/inventory/sessions/{session_id}/lines/{item_id}/{location_id}",
    response_model=InventorySessionDetail,
)
def count_line(
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    body: InventoryCountIn,
    rc: RequestCtx = Depends(deps.write),
) -> InventorySessionDetail:
    """Zapíše napočítané množství (0 = chybí, ``null`` = zpět na nezkontrolováno).

    Pro věc, kterou v umístění nečekáme, řádek vznikne (výsledek ``extra`` / ``moved``)."""
    inventory_service.count_line(rc.db, rc.ctx, session_id, item_id, location_id, body.counted_qty)
    rc.commit()
    return inventory_service.session_detail(rc.db, session_id)


@router.post("/inventory/sessions/{session_id}/close", response_model=InventoryCloseOut)
def close_session(
    session_id: uuid.UUID, body: InventoryCloseIn, rc: RequestCtx = Depends(deps.write)
) -> InventoryCloseOut:
    out = inventory_service.close_session(rc.db, rc.ctx, session_id, apply=body.apply)
    rc.commit()
    return out


@router.post("/inventory/sessions/{session_id}/cancel", response_model=InventorySessionOut)
def cancel_session(
    session_id: uuid.UUID, rc: RequestCtx = Depends(deps.write)
) -> InventorySessionOut:
    session = inventory_service.cancel_session(rc.db, rc.ctx, session_id)
    rc.commit()
    return inventory_service.session_out(rc.db, session)
