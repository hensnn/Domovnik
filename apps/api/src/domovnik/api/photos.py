"""Čtení fotek AI: spuštění analýzy, výsledky (detekce), revize a plán uložení."""

from __future__ import annotations

import threading
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from domovnik.ai import changesets, vision
from domovnik.api import deps
from domovnik.api.deps import RequestCtx
from domovnik.context import ActorContext, bind_context
from domovnik.db import get_sessionmaker
from domovnik.db.models import PhotoAnalysis
from domovnik.errors import NotFound

router = APIRouter(prefix="/photos", tags=["photos"])


class AnalyzeIn(BaseModel):
    file_id: uuid.UUID
    context_location_id: uuid.UUID | None = None
    hint: str | None = Field(default=None, max_length=500)


class CommitIn(BaseModel):
    decisions: list[vision.Decision] = Field(min_length=1, max_length=200)


def _run_in_background(analysis_id: uuid.UUID, ctx: ActorContext) -> None:
    with get_sessionmaker()() as db:
        bind_context(db, ctx)
        vision.run_analysis(db, analysis_id)
        db.commit()


def _get(rc: RequestCtx, analysis_id: uuid.UUID) -> PhotoAnalysis:
    analysis = rc.db.get(PhotoAnalysis, analysis_id)
    if analysis is None or (analysis.created_by != rc.user_id and not rc.is_admin):
        raise NotFound("Analýza neexistuje.")
    return analysis


@router.post("/analyze", status_code=202)
def analyze(
    body: AnalyzeIn, request: Request, rc: RequestCtx = Depends(deps.ai_chat)
) -> JSONResponse:
    """Spustí analýzu fotky na pozadí. Výsledek se načítá přes GET /photos/analyses/{id}."""
    analysis = vision.create_analysis(
        rc.db,
        rc.ctx,
        file_id=body.file_id,
        context_location_id=body.context_location_id,
        hint=body.hint,
    )
    rc.commit()
    ctx = ActorContext(
        actor_id=rc.user_id, source="ai", request_id=getattr(request.state, "request_id", None)
    )
    threading.Thread(target=_run_in_background, args=(analysis.id, ctx), daemon=True).start()
    return JSONResponse({"id": str(analysis.id), "status": "queued"}, status_code=202)


@router.get("/analyses")
def list_analyses(
    file_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    rc: RequestCtx = Depends(deps.ai_chat),
) -> list[dict[str, Any]]:
    stmt = select(PhotoAnalysis).order_by(PhotoAnalysis.created_at.desc()).limit(limit)
    if not rc.is_admin:
        stmt = stmt.where(PhotoAnalysis.created_by == rc.user_id)
    if file_id:
        stmt = stmt.where(PhotoAnalysis.file_id == file_id)
    return [
        {
            "id": str(a.id),
            "status": a.status,
            "file_id": str(a.file_id),
            "created_at": a.created_at.isoformat(),
            "error": a.error,
        }
        for a in rc.db.execute(stmt).scalars()
    ]


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: uuid.UUID, rc: RequestCtx = Depends(deps.ai_chat)) -> dict[str, Any]:
    return vision.analysis_out(rc.db, _get(rc, analysis_id))


@router.post("/analyses/{analysis_id}/commit")
def commit(
    analysis_id: uuid.UUID, body: CommitIn, rc: RequestCtx = Depends(deps.write)
) -> dict[str, Any]:
    """Potvrdí revizi: přijaté detekce se uloží jako věci (balíček změn, lze vrátit zpět)."""
    _get(rc, analysis_id)
    result = vision.commit_analysis(rc.db, rc.ctx, analysis_id, body.decisions)
    rc.commit()
    cs = changesets.get_change_set(rc.db, result.change_set_id) if result.change_set_id else None
    return {
        "change_set": changesets.describe_change_set(rc.db, cs) if cs else None,
        "created_item_ids": [str(i) for i in result.created_item_ids],
        "merged_item_ids": [str(i) for i in result.merged_item_ids],
    }


@router.post("/analyses/{analysis_id}/plan")
def plan(analysis_id: uuid.UUID, rc: RequestCtx = Depends(deps.ai_chat)) -> dict[str, Any]:
    """Navrhne postup uložení (Organizer): kroky, kam co dát; nic nemění."""
    _get(rc, analysis_id)
    return vision.storage_plan(rc.db, analysis_id)
