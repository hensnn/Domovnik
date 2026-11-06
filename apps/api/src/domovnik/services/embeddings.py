"""Sémantické hledání: embeddings věcí (pgvector) a hybridní hledání s fulltextem.

Embedding se přepočítá jen když se změnil text věci (`content_hash`). Dimenze je pevně 1024
(sloupec `item_embeddings.embedding`); provideři ji nastavují parametrem při volání.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from domovnik.ai.providers.base import Provider, ProviderError
from domovnik.db.models import Item
from domovnik.schemas import ItemOut
from domovnik.services import items as item_service
from domovnik.services import settings as settings_service
from domovnik.services.search import ItemFilter, search_items

DIMENSIONS = 1024
BATCH = 32


def item_text(out: ItemOut) -> str:
    """Text, ze kterého se embedding počítá (název, aliasy, značka, kategorie, tagy, popis)."""
    parts = [
        out.name,
        *out.aliases,
        out.brand or "",
        out.model or "",
        out.category_path or "",
        ", ".join(out.tags),
        out.description or "",
        out.notes or "",
    ]
    return " | ".join(p for p in parts if p).strip()


def _vector(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.7g}" for v in values) + "]"


@dataclass
class SyncResult:
    embedded: int
    skipped: int
    model: str


def is_enabled(db: Session) -> bool:
    return bool(settings_service.get_value(db, "search.semantic_enabled")) and bool(
        str(settings_service.get_value(db, "ai.model_embeddings") or "").strip()
    )


def sync(db: Session, provider: Provider, *, limit: int = 500) -> SyncResult:
    """Dopočítá chybějící / zastaralé embeddings (nejvýš `limit` věcí najednou)."""
    model = str(settings_service.get_value(db, "ai.model_embeddings") or provider.model)
    rows = list(
        db.execute(
            select(Item).where(Item.deleted_at.is_(None)).order_by(Item.updated_at.desc())
        ).scalars()
    )
    existing: dict[uuid.UUID, str] = {
        row[0]: row[1]
        for row in db.execute(text("SELECT item_id, content_hash FROM item_embeddings")).all()
    }
    outs = {o.id: o for o in item_service.to_out(db, rows)}
    todo: list[tuple[uuid.UUID, str, str]] = []
    skipped = 0
    for item in rows:
        content = item_text(outs[item.id])
        digest = hashlib.sha256(f"{model}:{content}".encode()).hexdigest()
        if existing.get(item.id) == digest:
            skipped += 1
            continue
        todo.append((item.id, content, digest))
    todo = todo[:limit]

    done = 0
    for start in range(0, len(todo), BATCH):
        chunk = todo[start : start + BATCH]
        vectors = provider.embed([c for _, c, _ in chunk], dimensions=DIMENSIONS)
        if len(vectors) != len(chunk):
            raise ProviderError("Provider vrátil jiný počet vektorů, než se čekalo.")
        for (item_id, _, digest), vec in zip(chunk, vectors, strict=True):
            if len(vec) != DIMENSIONS:
                raise ProviderError(f"Embedding má {len(vec)} dimenzí, očekává se {DIMENSIONS}.")
            db.execute(
                text(
                    """
                    INSERT INTO item_embeddings (item_id, model, content_hash, embedding, updated_at)
                    VALUES (:id, :model, :hash, CAST(:vec AS vector), now())
                    ON CONFLICT (item_id) DO UPDATE
                      SET model = EXCLUDED.model, content_hash = EXCLUDED.content_hash,
                          embedding = EXCLUDED.embedding, updated_at = now()
                    """
                ),
                {"id": item_id, "model": model, "hash": digest, "vec": _vector(vec)},
            )
            done += 1
    # embeddings smazaných věcí zmizí kaskádou (FK ON DELETE CASCADE)
    return SyncResult(embedded=done, skipped=skipped, model=model)


def semantic_ids(
    db: Session, provider: Provider, query: str, *, limit: int = 20
) -> list[uuid.UUID]:
    """Id věcí seřazená podle kosinové podobnosti dotazu (jen věci, které mají embedding)."""
    vec = provider.embed([query], dimensions=DIMENSIONS)[0]
    rows = db.execute(
        text(
            """
            SELECT e.item_id
              FROM item_embeddings e JOIN items i ON i.id = e.item_id AND i.deleted_at IS NULL
             ORDER BY e.embedding <=> CAST(:vec AS vector)
             LIMIT :limit
            """
        ),
        {"vec": _vector(vec), "limit": limit},
    ).all()
    return [r[0] for r in rows]


def hybrid_search(
    db: Session,
    provider: Provider | None,
    query: str,
    *,
    limit: int = 10,
    fuzzy_threshold: float = 0.3,
) -> list[ItemOut]:
    """Sloučí fulltext a sémantické výsledky (reciprocal rank fusion). Bez provideru = jen fulltext."""
    fts = search_items(
        db, ItemFilter(q=query, limit=limit * 2, fuzzy_threshold=fuzzy_threshold)
    ).items
    if provider is None or not is_enabled(db):
        return fts[:limit]
    try:
        sem_ids = semantic_ids(db, provider, query, limit=limit * 2)
    except ProviderError:
        return fts[:limit]  # sémantika je bonus – při chybě zůstane fulltext
    scores: dict[uuid.UUID, float] = {}
    for rank, o in enumerate(fts):
        scores[o.id] = scores.get(o.id, 0.0) + 1.0 / (60 + rank)
    for rank, item_id in enumerate(sem_ids):
        scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (60 + rank)
    by_id = {o.id: o for o in fts}
    missing = [i for i in scores if i not in by_id]
    if missing:
        loaded = list(db.execute(select(Item).where(Item.id.in_(missing))).scalars())
        by_id.update({o.id: o for o in item_service.to_out(db, loaded)})
    ranked = sorted(scores, key=lambda i: scores[i], reverse=True)
    return [by_id[i] for i in ranked[:limit] if i in by_id]
