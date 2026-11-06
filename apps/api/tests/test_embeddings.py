"""Embeddings a hybridní hledání (s deterministickým falešným poskytovatelem)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from domovnik.ai.providers import override_provider
from domovnik.ai.providers.fake import FakeProvider
from domovnik.context import ActorContext
from domovnik.schemas import ItemCreate
from domovnik.services import embeddings, items
from domovnik.services import settings as settings_service


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    yield
    override_provider(None)


def test_sync_is_incremental_and_search_uses_vectors(db: Session, ctx: ActorContext) -> None:
    settings_service.set_value(db, ctx, "ai.model_embeddings", "fake-embed", actor_is_admin=True)
    provider = FakeProvider()
    a = items.create_item(
        db, ctx, ItemCreate(name="Akušroubovák", description="utahovák šroubů vrtačka")
    )
    items.create_item(db, ctx, ItemCreate(name="Lepicí páska", description="izolepa pro balení"))
    assert embeddings.is_enabled(db)

    first = embeddings.sync(db, provider)
    assert (first.embedded, first.skipped) == (2, 0)
    again = embeddings.sync(db, provider)
    assert (again.embedded, again.skipped) == (0, 2)  # nic se nezměnilo → nic se nepočítá

    items.update_item(db, ctx, a.id, items_update(notes="nové poznámky"))
    assert embeddings.sync(db, provider).embedded == 1  # změněný text → přepočet jen jedné věci

    # sémantický dotaz bez shody názvu: společná slova v popisu
    ids = embeddings.semantic_ids(db, provider, "vrtačka")
    assert ids[0] == a.id
    found = embeddings.hybrid_search(db, provider, "vrtačka", limit=5)
    assert found and found[0].id == a.id

    assert db.execute(text("SELECT count(*) FROM item_embeddings")).scalar_one() == 2


def items_update(**kw: object):  # type: ignore[no-untyped-def]
    from domovnik.schemas import ItemUpdate

    return ItemUpdate.model_validate(kw)


def test_hybrid_falls_back_to_fulltext_when_disabled_or_failing(
    db: Session, ctx: ActorContext
) -> None:
    from domovnik.ai.providers.base import ProviderError

    items.create_item(db, ctx, ItemCreate(name="Kladivo"))
    assert [o.name for o in embeddings.hybrid_search(db, FakeProvider(), "kladivo")] == [
        "Kladivo"
    ]  # vypnuto

    settings_service.set_value(db, ctx, "ai.model_embeddings", "m", actor_is_admin=True)

    class Broken(FakeProvider):
        def embed(self, texts, *, dimensions=1024):  # type: ignore[no-untyped-def]
            raise ProviderError("embeddings nejsou k dispozici")

    assert [o.name for o in embeddings.hybrid_search(db, Broken(), "kladivo")] == ["Kladivo"]
