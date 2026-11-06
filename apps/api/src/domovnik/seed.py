"""Generátor realistických testovacích dat: český dům, ~40 umístění, ~300 věcí.

Použití: ``domovnik seed``. Určeno pro vývoj a ukázky – NEpouštět na ostré databázi.
"""

from __future__ import annotations

import random
from decimal import Decimal

from sqlalchemy.orm import Session

from domovnik.context import ActorContext, bind_context
from domovnik.schemas import ItemCreate, LocationCreate, PlacementIn
from domovnik.services import categories, items, locations

# (cesta umístění, druh)
LOCATIONS: list[tuple[str, str]] = [
    ("Dům", "building"),
    ("Dům/Přízemí", "floor"),
    ("Dům/Přízemí/Kuchyně", "room"),
    ("Dům/Přízemí/Kuchyně/Horní skříňka u okna", "furniture"),
    ("Dům/Přízemí/Kuchyně/Spodní skříňka u dřezu", "furniture"),
    ("Dům/Přízemí/Kuchyně/Zásuvka s příbory", "drawer"),
    ("Dům/Přízemí/Kuchyně/Spíž", "furniture"),
    ("Dům/Přízemí/Obývák", "room"),
    ("Dům/Přízemí/Obývák/Knihovna", "furniture"),
    ("Dům/Přízemí/Obývák/Knihovna/Police 1", "shelf"),
    ("Dům/Přízemí/Obývák/Knihovna/Police 2", "shelf"),
    ("Dům/Přízemí/Obývák/TV stolek", "furniture"),
    ("Dům/Přízemí/Předsíň", "room"),
    ("Dům/Přízemí/Předsíň/Botník", "furniture"),
    ("Dům/Patro", "floor"),
    ("Dům/Patro/Ložnice", "room"),
    ("Dům/Patro/Ložnice/Šatní skříň", "furniture"),
    ("Dům/Patro/Ložnice/Noční stolek", "furniture"),
    ("Dům/Patro/Pracovna", "room"),
    ("Dům/Patro/Pracovna/Pracovní stůl", "furniture"),
    ("Dům/Patro/Pracovna/Krabice Elektronika", "box"),
    ("Dům/Patro/Koupelna", "room"),
    ("Dům/Patro/Koupelna/Skříňka nad umyvadlem", "furniture"),
    ("Dům/Sklep", "floor"),
    ("Dům/Sklep/Regál A", "furniture"),
    ("Dům/Sklep/Regál A/Police 1", "shelf"),
    ("Dům/Sklep/Regál A/Police 2", "shelf"),
    ("Dům/Sklep/Regál A/Police 3", "shelf"),
    ("Dům/Sklep/Regál B", "furniture"),
    ("Dům/Sklep/Regál B/Krabice Vánoce", "box"),
    ("Dům/Sklep/Regál B/Krabice Kabely", "box"),
    ("Dům/Garáž", "room"),
    ("Dům/Garáž/Dílna", "zone"),
    ("Dům/Garáž/Dílna/Nástěnka s nářadím", "furniture"),
    ("Dům/Garáž/Dílna/Zásuvky pracovního stolu", "furniture"),
    ("Dům/Garáž/Kufr s nářadím", "box"),
    ("Dům/Garáž/Zimní pneumatiky", "zone"),
    ("Zahrada", "building"),
    ("Zahrada/Zahradní domek", "room"),
    ("Zahrada/Zahradní domek/Police se zahradním nářadím", "shelf"),
]

CATEGORIES: list[str] = [
    "Nářadí",
    "Nářadí/Ruční",
    "Nářadí/Elektrické",
    "Elektronika",
    "Elektronika/Kabely",
    "Elektronika/Baterie",
    "Domácnost",
    "Domácnost/Nádobí",
    "Domácnost/Textil",
    "Domácnost/Čistící prostředky",
    "Knihy",
    "Zahrada",
    "Oblečení",
    "Sezónní",
    "Sezónní/Vánoce",
    "Hobby",
    "Dokumenty",
]

# (název, kategorie, umístění, množství, tagy, značka)
BASE_ITEMS: list[tuple[str, str, str, int, list[str], str | None]] = [
    ("Akušroubovák", "Nářadí/Elektrické", "Dům/Garáž/Kufr s nářadím", 1, ["nářadí"], "Bosch"),
    (
        "Příklepová vrtačka",
        "Nářadí/Elektrické",
        "Dům/Garáž/Kufr s nářadím",
        1,
        ["nářadí"],
        "Makita",
    ),
    (
        "Úhlová bruska",
        "Nářadí/Elektrické",
        "Dům/Garáž/Dílna/Zásuvky pracovního stolu",
        1,
        [],
        "Metabo",
    ),
    ("Kladivo", "Nářadí/Ruční", "Dům/Garáž/Dílna/Nástěnka s nářadím", 2, ["nářadí"], None),
    ("Klešťové kleště", "Nářadí/Ruční", "Dům/Garáž/Dílna/Nástěnka s nářadím", 1, [], None),
    ("Sada šroubováků", "Nářadí/Ruční", "Dům/Garáž/Kufr s nářadím", 1, ["nářadí"], "Wera"),
    ("Metr svinovací 5 m", "Nářadí/Ruční", "Dům/Garáž/Kufr s nářadím", 2, [], None),
    ("Vodováha", "Nářadí/Ruční", "Dům/Garáž/Dílna/Nástěnka s nářadím", 1, [], None),
    ("Pilka na dřevo", "Nářadí/Ruční", "Dům/Garáž/Dílna/Nástěnka s nářadím", 1, [], None),
    (
        "Šrouby do dřeva 4x40",
        "Nářadí",
        "Dům/Garáž/Dílna/Zásuvky pracovního stolu",
        200,
        ["spojovací"],
        None,
    ),
    (
        "Hmoždinky 8 mm",
        "Nářadí",
        "Dům/Garáž/Dílna/Zásuvky pracovního stolu",
        150,
        ["spojovací"],
        None,
    ),
    ("Lepicí páska malířská", "Nářadí", "Dům/Garáž/Dílna/Zásuvky pracovního stolu", 3, [], None),
    (
        "Prodlužovací kabel 10 m",
        "Elektronika/Kabely",
        "Dům/Sklep/Regál B/Krabice Kabely",
        2,
        ["elektro"],
        None,
    ),
    (
        "Prodlužovací kabel 3 m",
        "Elektronika/Kabely",
        "Dům/Sklep/Regál B/Krabice Kabely",
        3,
        ["elektro"],
        None,
    ),
    (
        "HDMI kabel 2 m",
        "Elektronika/Kabely",
        "Dům/Patro/Pracovna/Krabice Elektronika",
        3,
        ["IT"],
        None,
    ),
    (
        "Ethernet kabel 5 m",
        "Elektronika/Kabely",
        "Dům/Patro/Pracovna/Krabice Elektronika",
        4,
        ["IT"],
        None,
    ),
    ("USB-C nabíječka 65 W", "Elektronika", "Dům/Patro/Pracovna/Pracovní stůl", 2, ["IT"], "Anker"),
    (
        "Baterie AA",
        "Elektronika/Baterie",
        "Dům/Přízemí/Kuchyně/Zásuvka s příbory",
        12,
        ["baterie"],
        "Duracell",
    ),
    (
        "Baterie AAA",
        "Elektronika/Baterie",
        "Dům/Přízemí/Kuchyně/Zásuvka s příbory",
        8,
        ["baterie"],
        "Duracell",
    ),
    ("Notebook", "Elektronika", "Dům/Patro/Pracovna/Pracovní stůl", 1, ["IT"], "Lenovo"),
    (
        "Externí disk 2 TB",
        "Elektronika",
        "Dům/Patro/Pracovna/Krabice Elektronika",
        1,
        ["IT", "zálohy"],
        "WD",
    ),
    ("Wi-Fi router", "Elektronika", "Dům/Přízemí/Obývák/TV stolek", 1, ["IT"], "TP-Link"),
    ("Dálkový ovladač TV", "Elektronika", "Dům/Přízemí/Obývák/TV stolek", 1, [], None),
    (
        "Hrnec 5 l",
        "Domácnost/Nádobí",
        "Dům/Přízemí/Kuchyně/Spodní skříňka u dřezu",
        1,
        [],
        "Tescoma",
    ),
    (
        "Pánev 28 cm",
        "Domácnost/Nádobí",
        "Dům/Přízemí/Kuchyně/Spodní skříňka u dřezu",
        2,
        [],
        "Tefal",
    ),
    ("Příbory - sada", "Domácnost/Nádobí", "Dům/Přízemí/Kuchyně/Zásuvka s příbory", 12, [], None),
    (
        "Rychlovarná konvice",
        "Domácnost",
        "Dům/Přízemí/Kuchyně/Horní skříňka u okna",
        1,
        [],
        "Philips",
    ),
    ("Povlečení bavlněné", "Domácnost/Textil", "Dům/Patro/Ložnice/Šatní skříň", 4, [], None),
    ("Ručník velký", "Domácnost/Textil", "Dům/Patro/Koupelna/Skříňka nad umyvadlem", 8, [], None),
    ("Prací gel", "Domácnost/Čistící prostředky", "Dům/Sklep/Regál A/Police 1", 2, [], "Persil"),
    (
        "Tablety do myčky",
        "Domácnost/Čistící prostředky",
        "Dům/Přízemí/Kuchyně/Spodní skříňka u dřezu",
        40,
        [],
        "Finish",
    ),
    (
        "Vánoční řetěz LED",
        "Sezónní/Vánoce",
        "Dům/Sklep/Regál B/Krabice Vánoce",
        3,
        ["sezónní"],
        None,
    ),
    (
        "Vánoční ozdoby - sada",
        "Sezónní/Vánoce",
        "Dům/Sklep/Regál B/Krabice Vánoce",
        2,
        ["sezónní", "křehké"],
        None,
    ),
    (
        "Zimní pneumatiky 205/55 R16",
        "Sezónní",
        "Dům/Garáž/Zimní pneumatiky",
        4,
        ["auto", "sezónní"],
        "Continental",
    ),
    ("Lopata", "Zahrada", "Zahrada/Zahradní domek/Police se zahradním nářadím", 1, [], None),
    ("Hrábě", "Zahrada", "Zahrada/Zahradní domek/Police se zahradním nářadím", 1, [], None),
    ("Zahradní hadice 20 m", "Zahrada", "Zahrada/Zahradní domek", 1, [], "Gardena"),
    ("Sekačka na trávu", "Zahrada", "Zahrada/Zahradní domek", 1, [], "Bosch"),
    ("Zimní bunda", "Oblečení", "Dům/Přízemí/Předsíň/Botník", 2, ["sezónní"], None),
    ("Turistické boty", "Oblečení", "Dům/Přízemí/Předsíň/Botník", 2, [], "Salomon"),
    ("Kytara akustická", "Hobby", "Dům/Přízemí/Obývák", 1, ["hudba"], "Yamaha"),
    ("Deskové hry - krabice", "Hobby", "Dům/Přízemí/Obývák/TV stolek", 6, [], None),
    (
        "Záruční listy - složka",
        "Dokumenty",
        "Dům/Patro/Pracovna/Pracovní stůl",
        1,
        ["doklady"],
        None,
    ),
]

BOOKS = [
    "Staré pověsti české",
    "Švejk",
    "Babička",
    "Máj",
    "Válka s mloky",
    "Saturnin",
    "Pán prstenů",
    "Hobit",
    "Duna",
    "Neuromancer",
    "Sapiens",
    "Krotitelé dluhů",
    "Kód da Vinci",
    "Harry Potter 1",
    "Harry Potter 2",
    "Harry Potter 3",
    "Malý princ",
    "1984",
    "Farma zvířat",
    "Hrabě Monte Cristo",
    "Anna Karenina",
    "Zločin a trest",
    "Proces",
    "Zámek",
    "Osudy dobrého vojáka Švejka 2",
    "Atlas ptáků",
    "Kuchařka Magdaleny Dobromily",
    "Rok na zahradě",
    "Lexikon hub",
    "Slovník cizích slov",
]


def _ids_by_path(db: Session, ctx: ActorContext, paths: list[tuple[str, str]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for path, kind in paths:
        names = path.split("/")
        parent = out.get("/".join(names[:-1])) if len(names) > 1 else None
        loc = locations.create_location(
            db,
            ctx,
            LocationCreate(
                name=names[-1],
                parent_id=getattr(parent, "id", None),
                kind=kind,  # type: ignore[arg-type]
                is_movable=(kind == "box"),
            ),
        )
        out[path] = loc
    return out


def seed(db: Session, ctx: ActorContext, *, rng_seed: int = 42) -> dict[str, int]:
    """Naplní databázi ukázkovými daty. Vrací počty vytvořených záznamů."""
    bind_context(db, ctx)
    rng = random.Random(rng_seed)
    locs = _ids_by_path(db, ctx, LOCATIONS)
    cats = {path: categories.get_or_create_path(db, ctx, path.split("/")) for path in CATEGORIES}

    def place(path: str, qty: int = 1) -> list[PlacementIn]:
        return [PlacementIn(location_id=locs[path].id, quantity=Decimal(qty))]  # type: ignore[attr-defined]

    created = 0
    for name, cat, where, qty, tags, brand in BASE_ITEMS:
        items.create_item(
            db,
            ctx,
            ItemCreate(
                name=name,
                category_id=cats[cat].id,
                brand=brand,
                tags=tags,
                is_consumable=qty > 10,
                unit="ks",
                placements=place(where, qty),
                min_quantity=Decimal(qty // 4) if qty > 10 else None,
                purchase_price=Decimal(rng.choice([99, 149, 299, 590, 1290, 2490])),
            ),
        )
        created += 1

    shelves = [p for p, _ in LOCATIONS if p.endswith(("Police 1", "Police 2")) and "Knihovna" in p]
    for title in BOOKS:
        items.create_item(
            db,
            ctx,
            ItemCreate(
                name=f"Kniha: {title}",
                category_id=cats["Knihy"].id,
                tags=["kniha"],
                placements=place(rng.choice(shelves)),
            ),
        )
        created += 1

    # hromada věcí „nezařazeno“ (jako po nafocení) a drobnosti navíc
    for i in range(1, 13):
        items.create_item(db, ctx, ItemCreate(name=f"Nezařazená věc {i}"))
        created += 1
    colors = ["bílý", "černý", "modrý", "červený", "zelený", "žlutý"]
    storages = [p for p, _ in LOCATIONS if "skříňka" in p.lower() or "zásuvk" in p.lower()]
    for color in colors:
        for kind, cat in (
            ("Hrnek", "Domácnost/Nádobí"),
            ("Talíř", "Domácnost/Nádobí"),
            ("Tričko", "Oblečení"),
            ("Ponožky", "Oblečení"),
        ):
            items.create_item(
                db,
                ctx,
                ItemCreate(
                    name=f"{kind} {color}",
                    category_id=cats[cat].id,
                    placements=place(rng.choice(storages), rng.randint(1, 6)),
                ),
            )
            created += 1
    # kabely a doplňky různých délek
    for length in (0.5, 1, 1.5, 2, 3, 5):
        for kind in ("Micro USB kabel", "USB-C kabel", "Lightning kabel", "Audio jack kabel"):
            items.create_item(
                db,
                ctx,
                ItemCreate(
                    name=f"{kind} {length} m",
                    category_id=cats["Elektronika/Kabely"].id,
                    tags=["IT"],
                    placements=place("Dům/Sklep/Regál B/Krabice Kabely", rng.randint(1, 3)),
                ),
            )
            created += 1
    # sady šroubků a hřebíků
    for size in (3, 4, 5, 6, 8):
        for length in (20, 30, 40, 50, 60):
            items.create_item(
                db,
                ctx,
                ItemCreate(
                    name=f"Vruty {size}x{length}",
                    category_id=cats["Nářadí"].id,
                    is_consumable=True,
                    tags=["spojovací"],
                    unit="ks",
                    placements=place(
                        "Dům/Garáž/Dílna/Zásuvky pracovního stolu", rng.randint(20, 120)
                    ),
                ),
            )
            created += 1
    return {"locations": len(LOCATIONS), "categories": len(CATEGORIES), "items": created}
