"""Balíčky změn od AI: návrh → (potvrzení) → provedení → případné vrácení zpět.

Změny se provádějí přes běžné služby v jedné transakci (savepoint); každá operace ukládá
inverzní operaci. Trvalé mazání AI neumí, riziková operace se bez potvrzení neprovede.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from domovnik.ai import ops as ops_mod
from domovnik.context import ActorContext, bind_context
from domovnik.db.models import AiChangeOp, AiChangeSet
from domovnik.errors import Conflict, DomainError, ValidationFailed
from domovnik.services import settings as settings_service
from domovnik.services.common import emit, get_or_404

MAX_OPS = 200


def propose(
    db: Session,
    ctx: ActorContext,
    *,
    summary: str,
    operations: list[dict[str, Any]],
    conversation_id: uuid.UUID | None = None,
) -> AiChangeSet:
    """Vytvoří balíček ve stavu „navrženo“ (nic se zatím nemění)."""
    if not operations:
        raise ValidationFailed("Balíček změn neobsahuje žádné operace.")
    if len(operations) > MAX_OPS:
        raise ValidationFailed(f"Příliš mnoho operací najednou (max. {MAX_OPS}).")
    parsed = [ops_mod.parse_op(o) for o in operations]  # navržené op: jen povolená množina
    cs = AiChangeSet(
        conversation_id=conversation_id,
        user_id=ctx.actor_id,
        summary=summary.strip()[:500] or "Změny",
    )
    db.add(cs)
    db.flush()
    for seq, op in enumerate(parsed):
        db.add(
            AiChangeOp(
                change_set_id=cs.id,
                seq=seq,
                op=op.op,
                payload=op.model_dump(mode="json"),
            )
        )
    db.flush()
    emit(db, ctx, "ai.change_set.proposed", "change_set", cs.id, {"summary": cs.summary})
    return cs


def get_change_set(db: Session, cs_id: uuid.UUID) -> AiChangeSet:
    return get_or_404(db, AiChangeSet, cs_id, what="Balíček změn")


def operations(db: Session, cs_id: uuid.UUID) -> list[AiChangeOp]:
    return list(
        db.execute(
            select(AiChangeOp).where(AiChangeOp.change_set_id == cs_id).order_by(AiChangeOp.seq)
        ).scalars()
    )


def is_risky(ops_list: list[AiChangeOp]) -> bool:
    return any(o.op in ops_mod.RISKY for o in ops_list)


def has_never_auto(ops_list: list[AiChangeOp]) -> bool:
    return any(o.op in ops_mod.NEVER_AUTO for o in ops_list)


def can_auto_apply(db: Session, ops_list: list[AiChangeOp], *, user_id: uuid.UUID | None) -> bool:
    """Rozhodne podle nastavení důvěry (ai.trust_level, ai.bulk_threshold)."""
    level = str(settings_service.get_value(db, "ai.trust_level", user_id))
    if level == "ask" or has_never_auto(ops_list):
        return False
    if level == "auto_all":
        return True
    threshold = int(settings_service.get_value(db, "ai.bulk_threshold"))
    return len(ops_list) <= threshold and not is_risky(ops_list)


def describe_change_set(db: Session, cs: AiChangeSet) -> dict[str, Any]:
    """Podoba pro UI / AI: souhrn, stav a popis každé operace (diff „co se stane“)."""
    rows = operations(db, cs.id)
    return {
        "id": str(cs.id),
        "summary": cs.summary,
        "status": cs.status,
        "auto_applied": cs.auto_applied,
        "created_at": cs.created_at.isoformat() if cs.created_at else None,
        "risky": is_risky(rows),
        "needs_ui_confirmation": has_never_auto(rows),
        "reversible": all(o.inverse is not None for o in rows) if cs.status == "applied" else None,
        "operations": [
            {
                "id": str(o.id),
                "seq": o.seq,
                "op": o.op,
                "status": o.status,
                "error": o.error,
                "description": _describe_row(db, o),
            }
            for o in rows
        ],
    }


def _describe_row(db: Session, row: AiChangeOp) -> str:
    try:
        return ops_mod.describe(db, ops_mod.parse_op(row.payload, internal=True))
    except DomainError:
        return row.op


def apply_change_set(
    db: Session,
    ctx: ActorContext,
    cs_id: uuid.UUID,
    *,
    skip_op_ids: set[uuid.UUID] | None = None,
    auto: bool = False,
) -> AiChangeSet:
    """Provede balíček v jedné transakci. Při chybě se vše vrátí a stav bude „failed“."""
    cs = get_or_404(db, AiChangeSet, cs_id, lock=True, what="Balíček změn")
    if cs.status != "proposed":
        raise Conflict(f"Balíček už je ve stavu „{cs.status}“.")
    skip = skip_op_ids or set()
    rows = operations(db, cs.id)
    inner = replace(ctx, change_set_id=cs.id)
    bind_context(db, inner)
    failure: str | None = None
    failed_id: uuid.UUID | None = None
    try:
        with db.begin_nested():
            for row in rows:
                failed_id = row.id
                if row.id in skip:
                    row.status = "skipped"
                    continue
                op = ops_mod.parse_op(row.payload, internal=True)
                result_id, inverse = ops_mod.execute(db, inner, op)
                row.result_id = result_id
                row.inverse = inverse
                row.status = "applied"
    except DomainError as exc:
        failure = exc.message
        db.expire_all()
        for r in operations(db, cs.id):
            r.status, r.inverse, r.result_id = "pending", None, None
            if r.id == failed_id:
                r.error = exc.message
    finally:
        bind_context(db, ctx)

    cs = get_or_404(db, AiChangeSet, cs_id, lock=True)
    now = datetime.now(UTC)
    cs.decided_at = now
    if failure is not None:
        cs.status = "failed"
        emit(db, ctx, "ai.change_set.failed", "change_set", cs.id, {"error": failure})
        return cs
    cs.status = "partially_applied" if skip else "applied"
    cs.applied_at = now
    cs.auto_applied = auto
    db.flush()
    emit(db, ctx, "ai.change_set.applied", "change_set", cs.id, {"summary": cs.summary})
    return cs


def reject_change_set(db: Session, ctx: ActorContext, cs_id: uuid.UUID) -> AiChangeSet:
    cs = get_or_404(db, AiChangeSet, cs_id, lock=True, what="Balíček změn")
    if cs.status != "proposed":
        raise Conflict(f"Balíček už je ve stavu „{cs.status}“.")
    cs.status = "rejected"
    cs.decided_at = datetime.now(UTC)
    db.flush()
    emit(db, ctx, "ai.change_set.rejected", "change_set", cs.id)
    return cs


def undo_change_set(db: Session, ctx: ActorContext, cs_id: uuid.UUID) -> AiChangeSet:
    """Vrátí provedený balíček zpět (inverzní operace v opačném pořadí)."""
    cs = get_or_404(db, AiChangeSet, cs_id, lock=True, what="Balíček změn")
    if cs.status not in ("applied", "partially_applied"):
        raise Conflict("Vrátit zpět lze jen provedený balíček.")
    rows = [r for r in operations(db, cs.id) if r.status == "applied"]
    irreversible = [r for r in rows if r.inverse is None]
    if irreversible:
        raise Conflict(
            "Tuto změnu nelze vrátit automaticky: "
            + "; ".join(_describe_row(db, r) for r in irreversible[:3])
        )
    inner = replace(ctx, change_set_id=cs.id)
    bind_context(db, inner)
    try:
        with db.begin_nested():
            for row in reversed(rows):
                op = ops_mod.parse_op(row.inverse or {}, internal=True)
                ops_mod.execute(db, inner, op)
                row.status = "undone"
    except DomainError as exc:
        db.expire_all()
        raise Conflict(f"Vrácení se nepovedlo (data se mezitím změnila): {exc.message}") from exc
    finally:
        bind_context(db, ctx)
    cs = get_or_404(db, AiChangeSet, cs_id, lock=True)
    cs.status = "undone"
    cs.undone_at = datetime.now(UTC)
    db.flush()
    emit(db, ctx, "ai.change_set.undone", "change_set", cs.id)
    return cs


def list_change_sets(
    db: Session, *, user_id: uuid.UUID | None = None, status: str | None = None, limit: int = 50
) -> list[AiChangeSet]:
    stmt = select(AiChangeSet).order_by(AiChangeSet.created_at.desc()).limit(limit)
    if user_id is not None:
        stmt = stmt.where(AiChangeSet.user_id == user_id)
    if status:
        stmt = stmt.where(AiChangeSet.status == status)
    return list(db.execute(stmt).scalars())
