"""Společné pomůcky služeb: události (outbox), překlad chyb DB, slug."""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.db.models import Base, EventOutbox
from domovnik.errors import Conflict, NotFound

_CONSTRAINT_MESSAGES = {
    "locations_sibling_name_uq": "Umístění se stejným názvem už na této úrovni existuje.",
    "locations_label_code_key": "Štítek umístění už existuje.",
    "categories_sibling_name_uq": "Kategorie se stejným názvem už na této úrovni existuje.",
    "categories_slug_key": "Kategorie s tímto označením už existuje.",
    "items_label_code_key": "Štítek věci už existuje.",
    "users_username_key": "Uživatelské jméno už existuje.",
    "tags_name_key": "Štítek (tag) s tímto názvem už existuje.",
}


def flush(db: Session) -> None:
    """flush() s překladem porušení omezení na srozumitelnou chybu 409."""
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        message = _CONSTRAINT_MESSAGES.get(name or "", "Porušení omezení v databázi.")
        raise Conflict(message, constraint=name) from exc


def get_or_404[M: Base](
    db: Session, model: type[M], pk: uuid.UUID, *, lock: bool = False, what: str = ""
) -> M:
    stmt = select(model).where(model.id == pk)  # type: ignore[attr-defined]
    if lock:
        stmt = stmt.with_for_update()
    obj = db.execute(stmt).scalar_one_or_none()
    if obj is None:
        raise NotFound(f"{what or model.__name__} {pk} neexistuje.")
    return obj


def emit(
    db: Session,
    ctx: ActorContext,
    event_type: str,
    entity_type: str,
    entity_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
) -> None:
    """Zapíše událost do outboxu (stejná transakce jako změna dat)."""
    db.add(
        EventOutbox(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload={
                "actor_id": str(ctx.actor_id) if ctx.actor_id else None,
                "source": ctx.source,
                **(payload or {}),
            },
        )
    )


def slugify(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", norm).strip("-").lower()
    return slug or "kategorie"


def check_version(current: int, expected: int | None) -> None:
    if expected is not None and expected != current:
        raise Conflict(
            "Záznam mezitím někdo změnil. Načti ho znovu a zkus to ještě jednou.",
            current_version=current,
        )
