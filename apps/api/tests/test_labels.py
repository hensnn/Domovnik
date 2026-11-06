"""Štítky: rozlišení kódů, PDF (počet štítků, diakritika, mřížka) a API."""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.errors import NotFound, ValidationFailed
from domovnik.main import app
from domovnik.ratelimit import login_limiter
from domovnik.schemas import ItemCreate, LocationCreate, PlacementIn
from domovnik.services import items, label_pdf, labels, locations
from domovnik.services.label_pdf import LabelData

PASSWORD = "correct horse battery"


@pytest.fixture
def anon(clean_db: None) -> Iterator[TestClient]:
    login_limiter._events.clear()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(anon: TestClient) -> TestClient:
    r = anon.post("/api/v1/auth/setup", json={"username": "admin", "password": PASSWORD})
    assert r.status_code == 201, r.text
    anon.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return anon


def ok(r: Any, code: int = 200) -> Any:
    assert r.status_code == code, f"{r.status_code}: {r.text}"
    return r.json() if r.content else None


def _setup(db: Session, ctx: ActorContext):  # type: ignore[no-untyped-def]
    dum = locations.create_location(db, ctx, LocationCreate(name="Dům", kind="building"))
    garaz = locations.create_location(
        db, ctx, LocationCreate(name="Garáž", parent_id=dum.id, kind="room")
    )
    regal = locations.create_location(
        db, ctx, LocationCreate(name="Regál č. 3", parent_id=garaz.id, kind="shelf")
    )
    item = items.create_item(
        db,
        ctx,
        ItemCreate(
            name="Příklepová vrtačka Žluťoučký kůň",
            placements=[PlacementIn(location_id=regal.id, quantity=Decimal(1))],
        ),
    )
    return dum, garaz, regal, item


def _pages(pdf: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(pdf))
    return [p.extract_text() or "" for p in reader.pages]


# --- rozlišení kódu -----------------------------------------------------------------------


def test_normalize_and_canonical_forms() -> None:
    assert labels.normalize_code(" i-000 123 ") == "I000123"
    assert "I-000123" in labels.canonical_forms("i000123")
    assert "L-000004" in labels.canonical_forms("l 4")


def test_resolve_item_and_location_tolerant(db: Session, ctx: ActorContext) -> None:
    _, garaz, regal, item = _setup(db, ctx)

    exact = labels.resolve_code(db, item.label_code)
    assert exact.type == "item" and exact.id == item.id and exact.name == item.name
    assert exact.full_name == "Dům › Garáž › Regál č. 3"

    messy = item.label_code.lower().replace("-", " ")  # „i 000001“
    assert labels.resolve_code(db, f"  {messy}  ").id == item.id
    assert labels.resolve_code(db, item.label_code.replace("-", "")).id == item.id

    loc = labels.resolve_code(db, regal.label_code.lower())
    assert loc.type == "location" and loc.id == regal.id
    assert loc.full_name == "Dům › Garáž › Regál č. 3"
    assert labels.resolve_code(db, garaz.label_code.replace("-", "")).id == garaz.id


def test_resolve_custom_location_code_and_unknown(db: Session, ctx: ActorContext) -> None:
    custom = locations.create_location(
        db, ctx, LocationCreate(name="Polička", label_code="L-GAR-A3")
    )
    assert labels.resolve_code(db, "l gar a3").id == custom.id
    with pytest.raises(NotFound):
        labels.resolve_code(db, "I-999999")
    with pytest.raises(ValidationFailed):
        labels.resolve_code(db, "   ")


def test_resolve_flags_trashed_item(db: Session, ctx: ActorContext) -> None:
    _, _, _, item = _setup(db, ctx)
    items.delete_item(db, ctx, item.id)
    assert labels.resolve_code(db, item.label_code).deleted is True


# --- PDF ----------------------------------------------------------------------------------


def test_pdf_contains_czech_diacritics_and_codes(db: Session, ctx: ActorContext) -> None:
    _, garaz, regal, item = _setup(db, ctx)
    pdf = labels.build_pdf(db, "item", [item.id], page_format="A4_3x8", show_path=True)
    assert pdf.startswith(b"%PDF")
    pages = _pages(pdf)
    assert len(pages) == 1
    text = pages[0]
    assert item.label_code in text
    # diakritika přežila (font s českými znaky, ne Helvetica)
    assert "Příklepová" in text.replace("\n", " ") or "Příklepová" in text
    assert "Garáž" in text

    pdf_loc = labels.build_pdf(db, "location", [regal.id], show_path=False)
    loc_text = _pages(pdf_loc)[0]
    assert regal.label_code in loc_text and "Regál" in loc_text
    assert "Garáž" not in loc_text  # show_path=False cestu nevypíše


def test_pdf_page_count_depends_on_format_and_start() -> None:
    data = [LabelData(code=f"I-{i:06d}", name=f"Věc {i}", path="Dům › Garáž") for i in range(1, 25)]
    assert len(_pages(label_pdf.render_labels_pdf(data, "A4_3x8"))) == 1  # 24 buněk
    assert len(_pages(label_pdf.render_labels_pdf(data[: 25 - 1], "A4_3x8", start=1))) == 2
    assert len(_pages(label_pdf.render_labels_pdf(data[:10], "A4_2x5"))) == 1
    assert len(_pages(label_pdf.render_labels_pdf(data[:11], "A4_2x5"))) == 2
    assert len(_pages(label_pdf.render_labels_pdf(data, "A4_4x12"))) == 1
    all_text = "".join(_pages(label_pdf.render_labels_pdf(data, "A4_3x8")))
    for d in data:
        assert d.code in all_text


def test_pdf_start_cell_offsets_first_label() -> None:
    one = [LabelData(code="I-000001", name="Jediná")]
    first = PdfReader(io.BytesIO(label_pdf.render_labels_pdf(one, "A4_3x8", start=0)))
    shifted = PdfReader(io.BytesIO(label_pdf.render_labels_pdf(one, "A4_3x8", start=4)))

    def position(reader: PdfReader) -> tuple[float, float]:
        found: list[tuple[float, float]] = []

        def visit(text: str, cm: list[float], tm: list[float], font: object, size: float) -> None:
            if text.strip() == "I-000001":
                found.append((tm[4] * cm[0] + cm[4], tm[5] * cm[3] + cm[5]))

        reader.pages[0].extract_text(visitor_text=visit)
        assert found
        return found[0]

    x0, y0 = position(first)
    x1, y1 = position(shifted)
    assert (
        y1 < y0 - 50 or x1 > x0 + 50
    )  # posunuto o druhý řádek / další sloupec (buňka 4 = 2. řádek)


def test_pdf_validation(db: Session, ctx: ActorContext) -> None:
    one = [LabelData(code="I-000001", name="X")]
    with pytest.raises(ValidationFailed):
        label_pdf.render_labels_pdf(one, "A4_3x8", start=24)
    with pytest.raises(ValidationFailed):
        label_pdf.render_labels_pdf(one, "A5")
    with pytest.raises(ValidationFailed):
        label_pdf.render_labels_pdf([], "A4_3x8")
    with pytest.raises(NotFound):
        labels.collect_labels(db, "item", [uuid.uuid4()])


def test_wrap_text_truncates_with_ellipsis() -> None:
    label_pdf._register_fonts()
    lines = label_pdf.wrap_text(
        "Velmi dlouhý název věci který se nevejde na dva řádky štítku",
        label_pdf.FONT_BOLD,
        10,
        80,
        2,
    )
    assert len(lines) == 2 and lines[-1].endswith("…")
    assert label_pdf.wrap_text("Nadzvukovýnepřetržitě", label_pdf.FONT, 10, 40, 5)


# --- API ----------------------------------------------------------------------------------


def test_api_resolve_and_pdf(client: TestClient) -> None:
    loc = ok(client.post("/api/v1/locations", json={"name": "Půda"}), 201)
    item = ok(
        client.post(
            "/api/v1/items",
            json={"name": "Lyže", "placements": [{"location_id": loc["id"], "quantity": 1}]},
        ),
        201,
    )
    r = ok(client.get("/api/v1/resolve", params={"code": item["label_code"].lower()}))
    assert r["type"] == "item" and r["id"] == item["id"] and r["full_name"] == "Půda"
    r = ok(client.get("/api/v1/resolve", params={"code": loc["label_code"]}))
    assert r["type"] == "location" and r["name"] == "Půda"
    assert client.get("/api/v1/resolve", params={"code": "X-1"}).status_code == 404

    resp = client.get(
        "/api/v1/labels/pdf",
        params={
            "kind": "item",
            "ids": f"{item['id']},{item['id']}",
            "format": "A4_2x5",
            "start": 2,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"].startswith("inline")
    assert item["label_code"] in "".join(_pages(resp.content))

    bad = client.get("/api/v1/labels/pdf", params={"kind": "item", "ids": "nonsense"})
    assert bad.status_code == 422
    assert (
        client.get("/api/v1/labels/pdf", params={"kind": "location", "ids": loc["id"]}).status_code
        == 200
    )
    assert (
        client.get("/api/v1/labels/pdf", params={"kind": "item", "ids": loc["id"]}).status_code
        == 404
    )


def test_api_default_format_from_settings(client: TestClient) -> None:
    loc = ok(client.post("/api/v1/locations", json={"name": "Sklep"}), 201)
    ok(
        client.put(
            "/api/v1/settings/labels.page_format", json={"value": "A4_2x5", "scope": "global"}
        ),
        204,
    )
    ids = ",".join([loc["id"]] * 11)
    resp = client.get("/api/v1/labels/pdf", params={"kind": "location", "ids": ids})
    assert resp.status_code == 200
    assert len(_pages(resp.content)) == 2  # A4_2x5 = 10 štítků na arch


def test_create_with_client_id_is_idempotent(client: TestClient) -> None:
    lid, iid = str(uuid.uuid4()), str(uuid.uuid4())
    a = ok(client.post("/api/v1/locations", json={"id": lid, "name": "Offline kout"}), 201)
    b = ok(client.post("/api/v1/locations", json={"id": lid, "name": "Offline kout"}), 201)
    assert a["id"] == b["id"] == lid and a["label_code"] == b["label_code"]
    body = {"id": iid, "name": "Offline věc", "placements": [{"location_id": lid, "quantity": 2}]}
    x = ok(client.post("/api/v1/items", json=body), 201)
    y = ok(client.post("/api/v1/items", json=body), 201)
    assert x["id"] == y["id"] == iid and y["total_quantity"] == "2.000" or y["total_quantity"] == 2
    page = ok(client.get("/api/v1/items", params={"q": "Offline věc"}))
    assert page["total"] == 1
