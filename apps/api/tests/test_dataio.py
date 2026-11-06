"""Import / export CSV."""

from __future__ import annotations

import csv
import io
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.errors import ValidationFailed
from domovnik.schemas import ItemCreate, PlacementIn
from domovnik.services import dataio, items, locations
from domovnik.services import search as search_service
from domovnik.services.search import ItemFilter


def rows(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text), delimiter=";"))


def test_export_defaults_for_czech_excel(db: Session, ctx: ActorContext) -> None:
    garaz = locations.get_or_create_path(db, ctx, ["Dům", "Garáž"])
    dilna = locations.get_or_create_path(db, ctx, ["Dům", "Dílna"])
    items.create_item(
        db,
        ctx,
        ItemCreate(
            name="Šroub; 4 mm",
            tags=["spojovací", "kov"],
            purchase_price=Decimal("12.5"),
            notes="=SUM(A1)",
            placements=[
                PlacementIn(location_id=garaz.id, quantity=Decimal("10.5")),
                PlacementIn(location_id=dilna.id, quantity=Decimal(5)),
            ],
        ),
    )
    page = search_service.search_items(db, ItemFilter(limit=50))
    data = dataio.export_csv(
        db,
        page.items,
        columns=["label_code", "name", "location", "quantity", "purchase_price", "notes", "tags"],
    )
    assert data.startswith(b"\xef\xbb\xbf")  # BOM pro Excel
    table = rows(data)
    assert table[0] == ["Štítek", "Název", "Umístění", "Množství", "Cena", "Poznámky", "Tagy"]
    assert len(table) == 3  # jeden řádek na umístění
    assert table[1][1] == "Šroub; 4 mm"  # středník v hodnotě je správně uvozen
    assert {table[1][3], table[2][3]} == {"10,5", "5"}  # desetinná čárka
    assert table[1][4] == "12,5"
    assert table[1][5] == "'=SUM(A1)"  # ochrana proti vzorcům
    one = rows(dataio.export_csv(db, page.items, columns=["name", "location"], per_placement=False))
    assert len(one) == 2 and "Dům › Garáž" in one[1][1] and "Dům › Dílna" in one[1][1]
    with pytest.raises(ValidationFailed):
        dataio.export_csv(db, page.items, columns=["nonsense"])


CSV = (
    "Název;Kategorie;Umístění;Množství;Značka;Cena;Záruka do;Tagy;Stav\n"
    "Akušroubovák;Nářadí > Elektrické;Dům/Garáž;1;Bosch;2 490,50;31. 12. 2027;nářadí, elektro;Uloženo\n"
    "Baterie AA;Elektronika;Dům › Kuchyně;12;Duracell;99;;baterie;\n"
    ";Něco;;;;;;;\n"
    "Špatná cena;;;1;;abc;;;\n"
    "Špatné datum;;;1;;;zítra;;\n"
)


def test_import_dry_run_reports_without_saving_then_commits(db: Session, ctx: ActorContext) -> None:
    data = CSV.encode("utf-8-sig")
    dry = dataio.import_csv(db, ctx, data, dry_run=True)
    assert (
        dry.delimiter == ";"
        and dry.mapping["Název"] == "name"
        and dry.mapping["Záruka do"] == "warranty_until"
    )
    assert (dry.created, dry.errors) == (2, 3)
    assert sorted(dry.new_categories) == ["Elektronika", "Nářadí › Elektrické"]
    assert "Dům › Garáž" in dry.new_locations
    errors = {r.row: r.message for r in dry.rows if r.action == "error"}
    assert set(errors) == {4, 5, 6} and "název" in (errors[4] or "").lower()
    assert search_service.search_items(db, ItemFilter()).total == 0  # nic se neuložilo

    real = dataio.import_csv(db, ctx, data, dry_run=False)
    assert real.created == 2
    page = search_service.search_items(db, ItemFilter(sort="name"))
    assert [i.name for i in page.items] == ["Akušroubovák", "Baterie AA"]
    drill = page.items[0]
    assert drill.brand == "Bosch" and drill.purchase_price == Decimal("2490.50")
    assert str(drill.warranty_until) == "2027-12-31" and drill.tags == ["elektro", "nářadí"]
    assert (
        drill.category_path == "Nářadí › Elektrické"
        and drill.placements[0].location_path == "Dům › Garáž"
    )


def test_import_duplicates_skip_or_update_and_encoding(db: Session, ctx: ActorContext) -> None:
    first = "Název,EAN,Množství,Umístění\nRouter,8591111111111,1,Dům/Pracovna\n"
    assert dataio.import_csv(db, ctx, first.encode(), dry_run=False).created == 1
    again = "Název,EAN,Množství,Umístění,Značka\nRouter nový název,8591111111111,3,Dům/Pracovna,TP-Link\n"
    skipped = dataio.import_csv(db, ctx, again.encode(), dry_run=False)  # výchozí skip
    assert skipped.skipped == 1 and skipped.created == 0
    updated = dataio.import_csv(db, ctx, again.encode(), dry_run=False, on_duplicate="update")
    assert updated.updated == 1
    item = search_service.search_items(db, ItemFilter()).items[0]
    assert item.name == "Router nový název" and item.brand == "TP-Link" and item.total_quantity == 3

    cp1250 = "Název;Množství\nŽárovka;2\n".encode("cp1250")
    r = dataio.import_csv(db, ctx, cp1250, dry_run=False)
    assert r.created == 1 and search_service.search_items(db, ItemFilter(q="zarovka")).total == 1


def test_import_validation(db: Session, ctx: ActorContext) -> None:
    with pytest.raises(ValidationFailed):
        dataio.import_csv(db, ctx, b"")
    with pytest.raises(ValidationFailed):
        dataio.import_csv(db, ctx, b"Kategorie;Cena\nA;1\n")  # bez názvu
    custom = dataio.import_csv(
        db, ctx, "Věc;Kolik\nTužka;4\n".encode(), mapping={"Věc": "name", "Kolik": "quantity"}
    )
    assert custom.mapping == {"Věc": "name", "Kolik": "quantity"} and custom.created == 1


def test_data_http_roundtrip(clean_db: None) -> None:
    from fastapi.testclient import TestClient

    from domovnik.main import app

    with TestClient(app) as c:
        me = c.post(
            "/api/v1/auth/setup", json={"username": "admin", "password": "correct horse battery"}
        ).json()
        h = {"X-CSRF-Token": me["csrf_token"]}
        files = {"file": ("import.csv", CSV.encode("utf-8-sig"), "text/csv")}
        dry = c.post("/api/v1/data/import", files=files, data={"dry_run": "true"}, headers=h).json()
        assert dry["created"] == 2 and dry["errors"] == 3 and dry["dry_run"] is True
        assert c.get("/api/v1/items").json()["total"] == 0
        done = c.post(
            "/api/v1/data/import", files=files, data={"dry_run": "false"}, headers=h
        ).json()
        assert done["created"] == 2
        assert c.get("/api/v1/items").json()["total"] == 2

        exp = c.get("/api/v1/data/export.csv", params={"columns": "name,location,quantity"})
        assert exp.status_code == 200 and exp.headers["content-type"].startswith("text/csv")
        assert "attachment" in exp.headers["content-disposition"]
        table = rows(exp.content)
        assert table[0] == ["Název", "Umístění", "Množství"] and len(table) == 3
        assert c.get("/api/v1/data/columns").json()["name"] == "Název"
