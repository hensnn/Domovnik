"""Nastavení, přehled (dashboard), globální hledání, audit a živé události (SSE)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from domovnik.api import deps
from domovnik.api.deps import RequestCtx
from domovnik.db import get_sessionmaker
from domovnik.db.models import EventOutbox
from domovnik.errors import Forbidden
from domovnik.schemas import AuditOut, LocationKind, SearchOut, SettingUpdate
from domovnik.services import search as search_service
from domovnik.services import settings as settings_service
from domovnik.services import stats as stats_service
from domovnik.services.search import SearchScope
from domovnik.services.settings import SettingOut

router = APIRouter(tags=["system"])


# --- Nastavení ----------------------------------------------------------------------------


@router.get("/settings", response_model=list[SettingOut])
def list_settings(rc: RequestCtx = Depends(deps.read)) -> list[SettingOut]:
    """Všechna nastavení s efektivní hodnotou pro přihlášeného uživatele (tajné maskované)."""
    return settings_service.list_effective(rc.db, rc.user_id)


@router.put("/settings/{key}", status_code=204)
def put_setting(key: str, body: SettingUpdate, rc: RequestCtx = Depends(deps.read)) -> None:
    """Nastaví hodnotu. `scope=user` = jen pro mě, `scope=global` = pro všechny (admin)."""
    if body.scope == "global":
        if not rc.is_admin:
            raise Forbidden("Globální nastavení smí měnit jen administrátor.")
        settings_service.set_value(rc.db, rc.ctx, key, body.value, actor_is_admin=True)
    else:
        settings_service.set_value(rc.db, rc.ctx, key, body.value, user_id=rc.user_id)
    rc.commit()


@router.delete("/settings/{key}", status_code=204)
def reset_setting(
    key: str,
    scope: str = Query("user", pattern="^(user|global)$"),
    rc: RequestCtx = Depends(deps.read),
) -> None:
    """Vrátí nastavení na výchozí hodnotu."""
    if scope == "global":
        settings_service.reset_value(rc.db, rc.ctx, key, actor_is_admin=rc.is_admin)
    else:
        settings_service.reset_value(rc.db, rc.ctx, key, user_id=rc.user_id)
    rc.commit()


# --- Přehled, hledání, audit --------------------------------------------------------------


@router.get("/stats")
def dashboard(rc: RequestCtx = Depends(deps.read)) -> dict[str, Any]:
    warranty = int(settings_service.get_value(rc.db, "notifications.warranty_days"))
    expiry = int(settings_service.get_value(rc.db, "notifications.expiry_days"))
    result = stats_service.dashboard(rc.db, warranty_days=warranty, expiry_days=expiry)
    # Pydantic modely → JSON-serializovatelné dicty
    return cast(dict[str, Any], json.loads(json.dumps(result, default=_encode)))


def _encode(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return str(obj)


@router.get("/search", response_model=SearchOut)
def global_search(
    q: str = "",
    limit: int = Query(10, ge=1, le=50),
    scope: SearchScope = "all",
    kind: list[LocationKind] = Query(default_factory=list),
    rc: RequestCtx = Depends(deps.read),
) -> SearchOut:
    """Rychlé hledání napříč věcmi, umístěními a kategoriemi (Ctrl+K).

    Umístění se najdou i podle druhu („nábytek“, „místnost“…); `kind` zúží umístění na druhy
    (stačí i bez textu), `scope` omezí hledání na jeden typ.
    """
    if not q.strip() and not kind:
        return SearchOut(items=[], locations=[], categories=[], totals={})
    threshold = float(settings_service.get_value(rc.db, "search.fuzzy_threshold"))
    res = search_service.search_all(
        rc.db, q, limit=limit, threshold=threshold, scope=scope, kinds=list(kind)
    )
    return SearchOut(
        items=res.items,
        locations=res.locations,
        categories=res.categories,
        totals=res.totals,
    )


@router.get("/audit", response_model=list[AuditOut])
def audit(
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    limit: int = Query(100, ge=1, le=1000),
    rc: RequestCtx = Depends(deps.admin),
) -> list[Any]:
    return stats_service.audit_for_entity(rc.db, entity_type, entity_id, limit=limit)


# --- Živé události (SSE) ------------------------------------------------------------------


@router.get("/events")
async def events(
    request: Request,
    last_id: int | None = Query(None, description="Poslat události novější než toto id"),
    rc: RequestCtx = Depends(deps.read),
) -> StreamingResponse:
    """Proud změn (Server-Sent Events) pro živou aktualizaci UI."""
    header = request.headers.get("last-event-id", "")
    cursor = last_id if last_id is not None else (int(header) if header.isdigit() else None)
    rc.db.close()  # session z dependency nepotřebujeme, stream si otevírá vlastní

    async def stream() -> AsyncIterator[str]:
        nonlocal cursor
        yield "retry: 3000\n\n"
        while True:
            if await request.is_disconnected():
                return
            rows = await asyncio.to_thread(_fetch_events, cursor)
            for row in rows:
                cursor = row["id"]
                yield f"id: {row['id']}\nevent: {row['type']}\ndata: {json.dumps(row)}\n\n"
            if not rows:
                yield ": keepalive\n\n"
            await asyncio.sleep(1.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _fetch_events(after: int | None) -> list[dict[str, Any]]:
    with get_sessionmaker()() as db:
        if after is None:  # nový odběratel začíná od „teď“
            latest = db.execute(
                select(EventOutbox.id).order_by(EventOutbox.id.desc()).limit(1)
            ).scalar()
            return [{"id": latest, "type": "hello", "payload": {}}] if latest else []
        rows = db.execute(
            select(EventOutbox).where(EventOutbox.id > after).order_by(EventOutbox.id).limit(100)
        ).scalars()
        return [
            {
                "id": r.id,
                "type": r.event_type,
                "entity_type": r.entity_type,
                "entity_id": str(r.entity_id) if r.entity_id else None,
                "payload": r.payload,
            }
            for r in rows
        ]
