"""Knihovna znalostí pro AI: čtení pro všechny přihlášené, správa jen pro admina."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response

from domovnik.api import deps
from domovnik.api.deps import RequestCtx
from domovnik.schemas import KnowledgeCreate, KnowledgeOut, KnowledgeTopic, KnowledgeUpdate
from domovnik.services import knowledge as knowledge_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("", response_model=list[KnowledgeOut])
def list_knowledge(
    topic: KnowledgeTopic | None = None, rc: RequestCtx = Depends(deps.read)
) -> list[KnowledgeOut]:
    """Záznamy knihovny. Admin vidí i vypnuté a čekající na schválení, ostatní jen zapnuté."""
    return knowledge_service.list_entries(rc.db, enabled_only=not rc.is_admin, topic=topic)


@router.post("", response_model=KnowledgeOut, status_code=201)
def create_knowledge(
    body: KnowledgeCreate, response: Response, rc: RequestCtx = Depends(deps.admin)
) -> KnowledgeOut:
    row = knowledge_service.create_entry(rc.db, rc.ctx, body)
    rc.commit()
    response.headers["Location"] = f"/api/v1/knowledge/{row.id}"
    return KnowledgeOut.model_validate(row)


@router.patch("/{entry_id}", response_model=KnowledgeOut)
def update_knowledge(
    entry_id: uuid.UUID,
    body: KnowledgeUpdate,
    request: Request,
    rc: RequestCtx = Depends(deps.admin),
) -> KnowledgeOut:
    body.version = deps.version_from(request, body.version)
    row = knowledge_service.update_entry(rc.db, rc.ctx, entry_id, body)
    rc.commit()
    return KnowledgeOut.model_validate(row)


@router.delete("/{entry_id}", status_code=204)
def delete_knowledge(entry_id: uuid.UUID, rc: RequestCtx = Depends(deps.admin)) -> None:
    knowledge_service.delete_entry(rc.db, rc.ctx, entry_id)
    rc.commit()
