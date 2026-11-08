"""Knihovna znalostí pro AI: pravidla uspořádání a zvyky domácnosti.

Záznamy spravuje admin. AI je dostává v systémovém promptu (do limitu znaků), zbytek si
dohledá nástrojem ``search_knowledge``. Záznam navržený AI (``source = 'ai'``) vzniká jako
vypnutý, dokud ho admin neschválí, aby se do promptu nedostal nikdo „podstrčený“ text.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.db.models import AiKnowledge
from domovnik.errors import Conflict, ValidationFailed
from domovnik.schemas import KnowledgeCreate, KnowledgeOut, KnowledgeUpdate
from domovnik.services import settings as settings_service
from domovnik.services.common import check_version, emit, flush, get_or_404
from domovnik.services.search import fold, tokens

TOPIC_LABELS = {
    "household": "Domácnost",
    "rules": "Pravidla uspořádání",
    "naming": "Pojmenování a kategorie",
    "other": "Ostatní",
}
MAX_ENTRIES = 500


def list_entries(
    db: Session, *, enabled_only: bool = False, topic: str | None = None
) -> list[KnowledgeOut]:
    stmt = select(AiKnowledge).order_by(
        AiKnowledge.sort_order, AiKnowledge.created_at, AiKnowledge.id
    )
    if enabled_only:
        stmt = stmt.where(AiKnowledge.enabled.is_(True))
    if topic:
        stmt = stmt.where(AiKnowledge.topic == topic)
    return [KnowledgeOut.model_validate(r) for r in db.execute(stmt).scalars()]


def _clean(value: str, what: str) -> str:
    out = " ".join(value.split()) if what == "title" else value.strip()
    if not out:
        raise ValidationFailed("Název ani text znalosti nesmí být prázdný.")
    return out


def create_entry(
    db: Session,
    ctx: ActorContext,
    data: KnowledgeCreate,
    *,
    source: str = "admin",
    enabled: bool | None = None,
) -> AiKnowledge:
    if db.execute(select(func.count()).select_from(AiKnowledge)).scalar_one() >= MAX_ENTRIES:
        raise Conflict(f"Knihovna je plná (max. {MAX_ENTRIES} záznamů).")
    row = AiKnowledge(
        title=_clean(data.title, "title"),
        content=_clean(data.content, "content"),
        topic=data.topic,
        enabled=data.enabled if enabled is None else enabled,
        source=source,
        sort_order=data.sort_order,
        created_by=ctx.actor_id,
    )
    db.add(row)
    flush(db)
    db.refresh(row)
    emit(db, ctx, "knowledge.created", "knowledge", row.id, {"title": row.title})
    return row


def update_entry(
    db: Session, ctx: ActorContext, entry_id: uuid.UUID, data: KnowledgeUpdate
) -> AiKnowledge:
    row = get_or_404(db, AiKnowledge, entry_id, lock=True, what="Znalost")
    check_version(row.version, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    for key in ("title", "content", "topic", "enabled", "sort_order"):
        if key in changes and changes[key] is None:
            del changes[key]
    if "title" in changes:
        changes["title"] = _clean(changes["title"], "title")
    if "content" in changes:
        changes["content"] = _clean(changes["content"], "content")
    for key, value in changes.items():
        setattr(row, key, value)
    flush(db)
    db.refresh(row)
    emit(db, ctx, "knowledge.updated", "knowledge", row.id, {"fields": sorted(changes)})
    return row


def delete_entry(db: Session, ctx: ActorContext, entry_id: uuid.UUID) -> None:
    row = get_or_404(db, AiKnowledge, entry_id, lock=True, what="Znalost")
    db.delete(row)
    flush(db)
    emit(db, ctx, "knowledge.deleted", "knowledge", entry_id)


# --- Použití v AI -------------------------------------------------------------------------------


@dataclass
class PromptBlock:
    text: str  # prázdný = nic k vložení
    included: int
    omitted: int


def enabled_in_settings(db: Session) -> bool:
    return bool(settings_service.get_value(db, "ai.knowledge_enabled"))


def prompt_block(db: Session, *, max_chars: int | None = None) -> PromptBlock:
    """Zapnuté záznamy ve tvaru odrážek (v pořadí správce) do limitu znaků; zbytek se vynechá."""
    if not enabled_in_settings(db):
        return PromptBlock("", 0, 0)
    limit = max_chars or int(settings_service.get_value(db, "ai.knowledge_max_chars"))
    lines: list[str] = []
    used = 0
    omitted = 0
    for e in list_entries(db, enabled_only=True):
        line = f"- [{TOPIC_LABELS[e.topic]}] {e.title}: {' '.join(e.content.split())}"
        if used + len(line) + 1 > limit:
            omitted += 1
            continue
        lines.append(line)
        used += len(line) + 1
    return PromptBlock("\n".join(lines), len(lines), omitted)


def prompt_section(db: Session, *, tool_hint: bool = True) -> str:
    """Hotová sekce do systémového promptu (prázdná, když není co vložit nebo je vypnuto).

    Záznamy píše admin, proto jde o platná pravidla, ne o data z fotek; navržené AI záznamy
    jsou do schválení vypnuté a sem se nedostanou.
    """
    block = prompt_block(db)
    if not block.text:
        return ""
    out = (
        "Znalosti o domácnosti od správce (platná pravidla; dodržuj je a na to, co tu je, "
        "se uživatele NEPTEJ znovu):\n" + block.text
    )
    if block.omitted and tool_hint:
        out += (
            f"\n(Dalších {block.omitted} záznamů knihovny se sem nevešlo – "
            "dohledej je nástrojem search_knowledge.)"
        )
    return out


def search_entries(db: Session, query: str, *, limit: int = 8) -> list[KnowledgeOut]:
    """Zapnuté záznamy, kde se v názvu nebo textu najdou všechna slova dotazu (bez diakritiky)."""
    toks = tokens(query)
    out: list[KnowledgeOut] = []
    for e in list_entries(db, enabled_only=True):
        hay = fold(f"{e.title} {e.content} {TOPIC_LABELS[e.topic]}")
        if not toks or all(t in hay for t in toks):
            out.append(e)
        if len(out) >= limit:
            break
    return out
