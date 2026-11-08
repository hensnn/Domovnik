"""Testy vyhledávání a filtrování věcí."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.schemas import CategoryCreate, ItemCreate, ItemUpdate, LocationCreate, PlacementIn
from domovnik.services import categories, items, locations, search, stats
from domovnik.services.search import ItemFilter


def names(page: search.ItemPage) -> list[str]:
    return [i.name for i in page.items]


def test_search_ignores_diacritics_typos_aliases_and_prefixes(
    db: Session, ctx: ActorContext
) -> None:
    items.create_item(
        db, ctx, ItemCreate(name="Akušroubovák", aliases=["vrtačka"], tags=["nářadí"])
    )
    items.create_item(db, ctx, ItemCreate(name="Kladivo"))
    items.create_item(db, ctx, ItemCreate(name="Lepicí páska"))

    def q(text: str) -> list[str]:
        return names(search.search_items(db, ItemFilter(q=text)))

    assert q("akusroubovak") == ["Akušroubovák"]
    assert q("akusrou") == ["Akušroubovák"]  # prefix
    assert q("vrtacka") == ["Akušroubovák"]  # alias
    assert q("naradi") == ["Akušroubovák"]  # tag
    assert q("akušroubovak") == ["Akušroubovák"]
    assert "Akušroubovák" in q("akusroubovac")  # překlep (trigramy)
    assert q("lepici pas") == ["Lepicí páska"]  # více slov
    assert q("zzzzzz") == []


def test_search_by_label_ean_and_serial(db: Session, ctx: ActorContext) -> None:
    it = items.create_item(
        db, ctx, ItemCreate(name="Router", ean="8591234567890", serial_no="SN-42")
    )
    for needle in (it.label_code, it.label_code.lower(), "8591234567890", "sn-42"):
        assert names(search.search_items(db, ItemFilter(q=needle))) == ["Router"]


def test_filters_category_subtree_location_subtree_tags_status(
    db: Session, ctx: ActorContext
) -> None:
    elektro = categories.create_category(db, ctx, CategoryCreate(name="Elektro"))
    kabely = categories.create_category(
        db, ctx, CategoryCreate(name="Kabely", parent_id=elektro.id)
    )
    dum = locations.create_location(db, ctx, LocationCreate(name="Dům"))
    garaz = locations.create_location(db, ctx, LocationCreate(name="Garáž", parent_id=dum.id))
    sklep = locations.create_location(db, ctx, LocationCreate(name="Sklep", parent_id=dum.id))
    items.create_item(
        db,
        ctx,
        ItemCreate(
            name="USB kabel",
            category_id=kabely.id,
            tags=["IT"],
            placements=[PlacementIn(location_id=garaz.id)],
        ),
    )
    items.create_item(
        db,
        ctx,
        ItemCreate(
            name="Prodlužovačka",
            category_id=elektro.id,
            placements=[PlacementIn(location_id=sklep.id)],
            status="in_use",
        ),
    )
    items.create_item(db, ctx, ItemCreate(name="Nezařazená věc"))

    def f(**kw: Any) -> list[str]:
        return sorted(names(search.search_items(db, ItemFilter(**kw))))

    assert f(category_id=elektro.id) == ["Prodlužovačka", "USB kabel"]  # včetně podkategorie
    assert f(category_id=kabely.id) == ["USB kabel"]
    assert f(location_id=dum.id) == ["Prodlužovačka", "USB kabel"]  # včetně podstromu
    assert f(location_id=garaz.id) == ["USB kabel"]
    assert f(tags=["it"]) == ["USB kabel"]
    assert f(status="in_use") == ["Prodlužovačka"]
    assert f(unplaced=True) == ["Nezařazená věc"]
    assert f(unplaced=False) == ["Prodlužovačka", "USB kabel"]
    assert f(q="kabel", location_id=sklep.id) == []


def test_low_stock_dates_trash_sort_and_paging(db: Session, ctx: ActorContext) -> None:
    box = locations.create_location(db, ctx, LocationCreate(name="Krabice"))
    today = date.today()
    items.create_item(
        db,
        ctx,
        ItemCreate(
            name="Baterie AA",
            is_consumable=True,
            min_quantity=Decimal(4),
            placements=[PlacementIn(location_id=box.id, quantity=Decimal(2))],
            expires_at=today + timedelta(days=5),
        ),
    )
    items.create_item(
        db,
        ctx,
        ItemCreate(
            name="Žárovky",
            is_consumable=True,
            min_quantity=Decimal(2),
            placements=[PlacementIn(location_id=box.id, quantity=Decimal(10))],
            warranty_until=today + timedelta(days=100),
        ),
    )
    gone = items.create_item(db, ctx, ItemCreate(name="Rozbitá věc"))
    items.delete_item(db, ctx, gone.id)

    assert names(search.search_items(db, ItemFilter(low_stock=True))) == ["Baterie AA"]
    assert names(search.search_items(db, ItemFilter(expires_before=today + timedelta(days=7)))) == [
        "Baterie AA"
    ]
    assert (
        names(search.search_items(db, ItemFilter(warranty_before=today + timedelta(days=30)))) == []
    )
    assert names(search.search_items(db, ItemFilter(trash=True))) == ["Rozbitá věc"]
    assert names(search.search_items(db, ItemFilter(q="rozbita"))) == []  # v koši se nehledá

    page = search.search_items(db, ItemFilter(sort="name", limit=1))
    assert page.total == 2 and names(page) == ["Baterie AA"]
    page2 = search.search_items(db, ItemFilter(sort="name", limit=1, offset=1))
    assert names(page2) == ["Žárovky"]
    desc = search.search_items(db, ItemFilter(sort="name", descending=True))
    assert names(desc) == ["Žárovky", "Baterie AA"]


def test_global_search_duplicates_and_dashboard(db: Session, ctx: ActorContext) -> None:
    locations.create_location(db, ctx, LocationCreate(name="Garáž"))
    categories.create_category(db, ctx, CategoryCreate(name="Garážové vybavení"))
    items.create_item(db, ctx, ItemCreate(name="Garážová vrata - dálkové ovládání"))
    res = search.search_all(db, "garaz")
    assert [x.name for x in res.locations] == ["Garáž"]
    assert [x.name for x in res.categories] == ["Garážové vybavení"]
    assert res.items

    items.create_item(db, ctx, ItemCreate(name="Akušroubovák Bosch"))
    dup = search.find_duplicates(db, "Akusroubovak Bosch")
    assert [d.name for d in dup] == ["Akušroubovák Bosch"]

    d = stats.dashboard(db)
    assert d["counts"]["items"] == 2 and d["counts"]["unplaced"] == 2
    assert d["counts"]["locations"] == 1 and d["counts"]["categories"] == 1


def test_global_search_finds_locations_by_kind(db: Session, ctx: ActorContext) -> None:
    dum = locations.create_location(db, ctx, LocationCreate(name="Dům", kind="building"))
    obyvak = locations.create_location(
        db, ctx, LocationCreate(name="Obývák", kind="room", parent_id=dum.id)
    )
    locations.create_location(
        db, ctx, LocationCreate(name="Skříň TV", kind="furniture", parent_id=obyvak.id)
    )
    locations.create_location(
        db, ctx, LocationCreate(name="Komoda", kind="furniture", parent_id=dum.id)
    )
    locations.create_location(
        db, ctx, LocationCreate(name="Police A", kind="shelf", parent_id=obyvak.id)
    )

    def locs(q: str, **kw: Any) -> list[str]:
        return [x.name for x in search.search_all(db, q, **kw).locations]

    assert sorted(locs("nábytek")) == ["Komoda", "Skříň TV"]  # český název druhu
    assert sorted(locs("nabytek")) == ["Komoda", "Skříň TV"]  # bez diakritiky
    assert locs("mistnost") == ["Obývák"]
    assert locs("budova") == ["Dům"]
    assert locs("police") == ["Police A"]  # název i druh
    # druh + část názvu: jen nábytek v Obýváku
    assert locs("nabytek obyvak") == ["Skříň TV"]
    # filtr druhu zúží výsledek a `scope` omezí typ nálezů
    assert locs("o", kinds=["room"]) == ["Obývák"]
    only_locs = search.search_all(db, "komoda", scope="locations")
    assert only_locs.items == [] and only_locs.totals["locations"] == 1
    assert search.search_all(db, "nabytek", limit=1).totals["locations"] == 2


def test_extended_item_filters(db: Session, ctx: ActorContext) -> None:
    today = date.today()
    skrin = locations.create_location(db, ctx, LocationCreate(name="Skříň", kind="furniture"))
    krabice = locations.create_location(db, ctx, LocationCreate(name="Krabice", kind="box"))
    items.create_item(
        db,
        ctx,
        ItemCreate(
            name="Vrtačka",
            brand="Bosch",
            condition="good",
            purchase_price=Decimal("2500"),
            purchase_date=today - timedelta(days=400),
            warranty_until=today + timedelta(days=30),
            placements=[PlacementIn(location_id=skrin.id, quantity=Decimal("1"))],
        ),
    )
    items.create_item(
        db,
        ctx,
        ItemCreate(
            name="Mléko",
            brand="Pilos",
            condition="new",
            purchase_price=Decimal("25"),
            expires_at=today - timedelta(days=2),
            placements=[PlacementIn(location_id=krabice.id, quantity=Decimal("6"))],
        ),
    )
    items.create_item(db, ctx, ItemCreate(name="Bez místa"))

    def f(**kw: Any) -> list[str]:
        return sorted(names(search.search_items(db, ItemFilter(**kw))))

    assert f(location_kinds=["furniture"]) == ["Vrtačka"]
    assert f(location_kinds=["furniture", "box"]) == ["Mléko", "Vrtačka"]
    assert f(brand="bosc") == ["Vrtačka"]
    assert f(condition="new") == ["Mléko"]
    assert f(min_price=Decimal("100")) == ["Vrtačka"]
    assert f(max_price=Decimal("100")) == ["Mléko"]
    assert f(purchased_before=today - timedelta(days=100)) == ["Vrtačka"]
    assert f(purchased_after=today - timedelta(days=100)) == []
    assert f(min_qty=Decimal("2")) == ["Mléko"]
    assert f(max_qty=Decimal("1")) == ["Bez místa", "Vrtačka"]  # bez umístění = množství 0
    assert f(expired=True) == ["Mléko"]
    assert f(warranty_active=True) == ["Vrtačka"]
    assert f(no_category=True) == ["Bez místa", "Mléko", "Vrtačka"]
    assert f(has_photo=False) == ["Bez místa", "Mléko", "Vrtačka"]
    assert f(has_photo=True) == []
    assert f(created_after=today) == ["Bez místa", "Mléko", "Vrtačka"]
    assert f(created_after=today + timedelta(days=1)) == []
    assert f(updated_after=today + timedelta(days=1)) == []

    by_price = search.search_items(db, ItemFilter(sort="price", descending=True))
    assert names(by_price)[:2] == ["Vrtačka", "Mléko"]
    by_qty = search.search_items(db, ItemFilter(sort="quantity", descending=True))
    assert names(by_qty)[0] == "Mléko"


def test_tag_management_rename_color_merge_delete(db: Session, ctx: ActorContext) -> None:
    from domovnik.errors import Conflict
    from domovnik.services import tags as tag_service

    a = items.create_item(db, ctx, ItemCreate(name="Kladivo", tags=["naradi", "dilna"]))
    b = items.create_item(db, ctx, ItemCreate(name="Pila", tags=["nářadí"]))
    c = items.create_item(db, ctx, ItemCreate(name="Hrábě", tags=["zahrada"]))

    def tag(name: str) -> Any:
        return next(t for t in tag_service.list_tags(db) if t.name == name)

    # přejmenování přepíše i fulltext věcí s tagem
    tag_service.update_tag(db, ctx, tag("zahrada").id, name="Zahrada a dvůr")
    assert names(search.search_items(db, ItemFilter(q="dvur"))) == ["Hrábě"]
    assert names(search.search_items(db, ItemFilter(q="zahrada"))) == ["Hrábě"]
    assert items.get_item_out(db, c.id).tags == ["Zahrada a dvůr"]

    # barva: nastavit, ponechat při přejmenování, odstranit
    t = tag_service.update_tag(db, ctx, tag("dilna").id, color="#ff8800", set_color=True)
    assert t.color == "#ff8800"
    tag_service.update_tag(db, ctx, t.id, name="Dílna")
    assert tag("Dílna").color == "#ff8800"
    tag_service.update_tag(db, ctx, t.id, color=None, set_color=True)
    assert tag("Dílna").color is None

    # přejmenování na existující název (i jiná velikost písmen) je konflikt
    try:
        tag_service.update_tag(db, ctx, tag("naradi").id, name="NÁŘADÍ".lower())
    except Conflict:
        pass
    else:  # pragma: no cover
        raise AssertionError("očekáván konflikt")
    # změna jen velikosti písmen téhož tagu projde
    tag_service.update_tag(db, ctx, tag("naradi").id, name="Naradi")

    # sloučení: věci přejdou na cílový tag, zdrojový zmizí, duplicity se nezdvojí
    items.update_item(db, ctx, b.id, ItemUpdate(tags=["nářadí", "Naradi"]))
    target = tag_service.merge_tags(db, ctx, tag("Naradi").id, tag("nářadí").id)
    assert target.name == "nářadí"
    assert items.get_item_out(db, a.id).tags == ["Dílna", "nářadí"]
    assert items.get_item_out(db, b.id).tags == ["nářadí"]
    assert tag("nářadí").item_count == 2
    assert all(t.name != "Naradi" for t in tag_service.list_tags(db))
    assert sorted(names(search.search_items(db, ItemFilter(tags=["nářadí"])))) == [
        "Kladivo",
        "Pila",
    ]
    try:
        tag_service.merge_tags(db, ctx, target.id, target.id)
    except Exception as exc:
        assert "sám se sebou" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("sloučení se sebou nesmí projít")

    # vytvoření bez věcí a smazání
    new = tag_service.create_tag(db, ctx, "  Zimní   výbava ", "#3366cc")
    assert new.name == "Zimní výbava" and tag("Zimní výbava").item_count == 0
    tag_service.delete_tag(db, ctx, new.id)
    assert all(t.name != "Zimní výbava" for t in tag_service.list_tags(db))
