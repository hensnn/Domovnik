"""AI asistent: chat (SSE), stručné dotazy (/ask pro Home Assistant), balíčky změn, konverzace."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from domovnik.ai import agent, changesets
from domovnik.ai.providers import quota
from domovnik.api import deps
from domovnik.api.deps import RequestCtx
from domovnik.context import ActorContext, bind_context
from domovnik.db import get_sessionmaker
from domovnik.db.models import AiConversation, AiMessage
from domovnik.errors import NotFound
from domovnik.services import embeddings, locations
from domovnik.services import settings as settings_service

router = APIRouter(prefix="/ai", tags=["ai"])


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    context_location_id: uuid.UUID | None = Field(
        default=None, description="Kde uživatel právě je („jsem tady“ po naskenování QR)."
    )
    channel: Literal["text", "voice"] = "text"


class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    style: Literal["text", "voice"] = "voice"
    conversation_id: uuid.UUID | None = None
    session: str | None = Field(
        default=None, description="Stabilní identifikátor hlasové relace (např. místnost z HA)."
    )
    context_location_id: uuid.UUID | None = None


class ApplyIn(BaseModel):
    skip_operation_ids: list[uuid.UUID] = Field(default_factory=list)


def _context_text(rc: RequestCtx, location_id: uuid.UUID | None) -> str | None:
    if location_id is None:
        return None
    return locations.location_full_names(rc.db, [location_id]).get(location_id)


# --- Stav -----------------------------------------------------------------------------------


@router.get("/status")
def ai_status(rc: RequestCtx = Depends(deps.ai_chat)) -> dict[str, Any]:
    """Je AI zapnutá a nakonfigurovaná? Kolik požadavků už dnes proběhlo?"""

    def get(key: str) -> Any:
        return settings_service.get_value(rc.db, key)

    provider = str(get("ai.provider_chat"))
    key_setting = {"gemini": "ai.gemini_api_key", "anthropic": "ai.anthropic_api_key"}.get(provider)
    configured = bool(get(key_setting)) if key_setting else bool(get("ai.openai_base_url"))
    return {
        "enabled": bool(get("ai.enabled")),
        "configured": configured,
        "provider": provider,
        "model": str(get("ai.model_chat")),
        "trust_level": str(get("ai.trust_level")),
        "requests_today": quota.today_count,
        "requests_per_day_limit": int(get("ai.max_requests_per_day")),
    }


# --- Chat -----------------------------------------------------------------------------------


def _worker(
    q: queue.Queue[dict[str, Any] | None],
    *,
    user_id: uuid.UUID,
    can_write: bool,
    body_text: str,
    conversation_id: uuid.UUID | None,
    channel: str,
    context_location_id: uuid.UUID | None,
    request_id: str | None,
) -> None:
    ctx = ActorContext(
        actor_id=user_id, source="voice" if channel == "voice" else "ai", request_id=request_id
    )
    with get_sessionmaker()() as db:
        try:
            bind_context(db, ctx)
            names = (
                locations.location_full_names(db, [context_location_id])
                if context_location_id
                else {}
            )
            result = agent.run_turn(
                db,
                ctx,
                user_id=user_id,
                can_write=can_write,
                text=body_text,
                conversation_id=conversation_id,
                channel=channel,
                context_location=names.get(context_location_id) if context_location_id else None,
                on_event=q.put,
            )
            db.commit()
            q.put(
                {
                    "type": "done",
                    "conversation_id": str(result.conversation_id),
                    "reply": result.reply,
                    "model": result.model,
                    "tokens_in": result.usage.tokens_in,
                    "tokens_out": result.usage.tokens_out,
                    "error": result.error,
                }
            )
        except Exception as exc:  # noqa: BLE001 – chybu doručíme klientovi jako událost
            db.rollback()
            q.put({"type": "error", "message": getattr(exc, "message", None) or str(exc)})
        finally:
            q.put(None)


@router.post("/chat")
async def chat(
    body: ChatIn, request: Request, rc: RequestCtx = Depends(deps.ai_chat)
) -> StreamingResponse:
    """Konverzace se streamem událostí: `conversation`, `tool_call`, `change_set`, `message`, `done`."""
    q: queue.Queue[dict[str, Any] | None] = queue.Queue()
    threading.Thread(
        target=_worker,
        daemon=True,
        kwargs=dict(
            q=q,
            user_id=rc.user_id,
            can_write=rc.principal.has("items:write"),
            body_text=body.text,
            conversation_id=body.conversation_id,
            channel=body.channel,
            context_location_id=body.context_location_id,
            request_id=getattr(request.state, "request_id", None),
        ),
    ).start()

    async def stream() -> AsyncIterator[str]:
        while True:
            item = await asyncio.to_thread(q.get)
            if item is None:
                return
            yield f"event: {item['type']}\ndata: {json.dumps(item, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/ask")
def ask(body: AskIn, request: Request, rc: RequestCtx = Depends(deps.ai_chat)) -> dict[str, Any]:
    """Jednorázový dotaz bez streamu – pro Home Assistant a skripty.

    `style=voice` vrací stručnou odpověď bez markdownu. Změny dat se vždy jen navrhnou
    (potvrzují se další zprávou „ano“ ve stejném `conversation_id`, nebo v aplikaci).
    """
    channel = "voice" if body.style == "voice" else "text"
    ctx = ActorContext(
        actor_id=rc.user_id,
        source="voice" if channel == "voice" else "api",
        request_id=getattr(request.state, "request_id", None),
    )
    bind_context(rc.db, ctx)
    result = agent.run_turn(
        rc.db,
        ctx,
        user_id=rc.user_id,
        can_write=rc.principal.has("items:write"),
        text=body.text,
        conversation_id=body.conversation_id,
        channel=channel,
        context_location=_context_text(rc, body.context_location_id),
    )
    rc.commit()
    return {
        "answer": result.reply,
        "conversation_id": str(result.conversation_id),
        "change_sets": result.change_sets,
        "error": result.error,
    }


# --- Konverzace -----------------------------------------------------------------------------


@router.get("/conversations")
def list_conversations(
    limit: int = Query(30, ge=1, le=200), rc: RequestCtx = Depends(deps.ai_chat)
) -> list[dict[str, Any]]:
    rows = rc.db.execute(
        select(AiConversation)
        .where(AiConversation.user_id == rc.user_id, AiConversation.archived.is_(False))
        .order_by(AiConversation.created_at.desc())
        .limit(limit)
    ).scalars()
    return [
        {
            "id": str(c.id),
            "title": c.title,
            "channel": c.channel,
            "created_at": c.created_at.isoformat(),
        }
        for c in rows
    ]


def _own_conversation(rc: RequestCtx, conversation_id: uuid.UUID) -> AiConversation:
    conv = rc.db.get(AiConversation, conversation_id)
    if conv is None or conv.user_id != rc.user_id:
        raise NotFound("Konverzace neexistuje.")
    return conv


@router.get("/conversations/{conversation_id}/messages")
def conversation_messages(
    conversation_id: uuid.UUID, rc: RequestCtx = Depends(deps.ai_chat)
) -> list[dict[str, Any]]:
    conv = _own_conversation(rc, conversation_id)
    rows = rc.db.execute(
        select(AiMessage)
        .where(
            AiMessage.conversation_id == conv.id,
            AiMessage.role.in_(("user", "assistant")),
            AiMessage.content.is_not(None),
        )
        .order_by(AiMessage.id)
    ).scalars()
    return [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in rows
    ]


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: uuid.UUID, rc: RequestCtx = Depends(deps.ai_chat)) -> None:
    rc.db.delete(_own_conversation(rc, conversation_id))
    rc.commit()


# --- Balíčky změn ---------------------------------------------------------------------------


@router.get("/change-sets")
def list_change_sets(
    status: str | None = None,
    limit: int = Query(30, ge=1, le=200),
    rc: RequestCtx = Depends(deps.ai_chat),
) -> list[dict[str, Any]]:
    rows = changesets.list_change_sets(
        rc.db, user_id=None if rc.is_admin else rc.user_id, status=status, limit=limit
    )
    return [changesets.describe_change_set(rc.db, cs) for cs in rows]


@router.get("/change-sets/{cs_id}")
def get_change_set(cs_id: uuid.UUID, rc: RequestCtx = Depends(deps.ai_chat)) -> dict[str, Any]:
    return changesets.describe_change_set(rc.db, changesets.get_change_set(rc.db, cs_id))


@router.post("/change-sets/{cs_id}/apply")
def apply_change_set(
    cs_id: uuid.UUID, body: ApplyIn | None = None, rc: RequestCtx = Depends(deps.write)
) -> dict[str, Any]:
    """Potvrdí a provede navržené změny (volitelně bez některých operací)."""
    cs = changesets.apply_change_set(
        rc.db, rc.ctx, cs_id, skip_op_ids=set(body.skip_operation_ids) if body else None
    )
    rc.commit()
    return changesets.describe_change_set(rc.db, cs)


@router.post("/change-sets/{cs_id}/reject")
def reject_change_set(cs_id: uuid.UUID, rc: RequestCtx = Depends(deps.write)) -> dict[str, Any]:
    cs = changesets.reject_change_set(rc.db, rc.ctx, cs_id)
    rc.commit()
    return changesets.describe_change_set(rc.db, cs)


@router.post("/change-sets/{cs_id}/undo")
def undo_change_set(cs_id: uuid.UUID, rc: RequestCtx = Depends(deps.write)) -> dict[str, Any]:
    """Vrátí provedené změny zpět (pokud to jde)."""
    cs = changesets.undo_change_set(rc.db, rc.ctx, cs_id)
    rc.commit()
    return changesets.describe_change_set(rc.db, cs)


# --- Sémantické hledání -------------------------------------------------------------------


@router.post("/embeddings/sync")
def sync_embeddings(
    limit: int = Query(500, ge=1, le=5000), rc: RequestCtx = Depends(deps.admin)
) -> dict[str, Any]:
    """Dopočítá embeddings věcí (jen změněné). Vyžaduje nastavený model v Nastavení → AI."""
    from domovnik.ai.providers import get_provider

    provider = get_provider(rc.db, "chat")
    result = embeddings.sync(rc.db, provider, limit=limit)
    rc.commit()
    return {"embedded": result.embedded, "skipped": result.skipped, "model": result.model}
