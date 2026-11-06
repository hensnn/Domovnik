"""Seed data musí jít vytvořit a smysluplně prohledat; základní kontrola výkonu hledání."""

from __future__ import annotations

import time
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.seed import seed
from domovnik.services import locations, search
from domovnik.services.search import ItemFilter


def test_seed_creates_realistic_data(db: Session, ctx: ActorContext) -> None:
    counts = seed(db, ctx)
    assert counts["items"] >= 150 and counts["locations"] >= 35
    garaz = next(x for x in locations.list_locations(db) if x.name == "Garáž")
    assert garaz.item_count > 5
    res = search.search_items(db, ItemFilter(q="vrtacka"))
    assert any("vrtačka" in i.name.lower() for i in res.items)
    assert search.search_items(db, ItemFilter(unplaced=True)).total == 12


def test_search_scales_to_ten_thousand_items(db: Session, ctx: ActorContext) -> None:
    """Hrubý odhad výkonu: 10 000 věcí, hledání pod ~0,5 s i na pomalém stroji."""
    db.execute(
        text(
            "INSERT INTO items (name, aliases, description) "
            "SELECT 'Položka ' || g || ' ' || (ARRAY['šroub','kabel','hrnek','kniha','tričko'])[1 + g % 5], "
            "'{}', 'popis ' || g FROM generate_series(1, 10000) g"
        )
    )
    db.execute(text("ANALYZE items"))
    start = time.perf_counter()
    page = search.search_items(db, ItemFilter(q="sroub 77", limit=20))
    elapsed = time.perf_counter() - start
    assert page.total >= 1
    assert elapsed < 0.5, f"hledání trvalo {elapsed:.2f}s"
    _ = Decimal
