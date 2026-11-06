"""Import a export CSV (české výchozí nastavení pro Excel: `;`, UTF-8 s BOM, desetinná čárka).

Import používá stejné služby jako ostatní kanály (audit, události, validace). „Zkušební běh“
(dry-run) projde přesně stejnou cestou a na konci transakci zahodí – report je tedy věrný.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.db.models import Item
from domovnik.errors import DomainError, ValidationFailed
from domovnik.schemas import ItemCreate, ItemOut, ItemUpdate, PlacementIn
from domovnik.services import categories, items, locations
from domovnik.services import settings as settings_service

SEP = " › "
MAX_ROWS = 20_000

# Sloupce exportu (klíč → záhlaví)
EXPORT_COLUMNS: dict[str, str] = {
    "label_code": "Štítek",
    "name": "Název",
    "category": "Kategorie",
    "location": "Umístění",
    "quantity": "Množství",
    "unit": "Jednotka",
    "status": "Stav",
    "tags": "Tagy",
    "brand": "Značka",
    "model": "Model",
    "serial_no": "Sériové číslo",
    "ean": "EAN",
    "purchase_date": "Datum nákupu",
    "purchase_price": "Cena",
    "warranty_until": "Záruka do",
    "expires_at": "Expirace",
    "notes": "Poznámky",
    "description": "Popis",
    "aliases": "Aliasy",
}
DEFAULT_COLUMNS = list(EXPORT_COLUMNS)

# Synonyma záhlaví pro automatické mapování importu (bez diakritiky, malá písmena)
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "label_code": ("stitek", "label", "label_code", "kod", "id"),
    "name": ("nazev", "name", "polozka", "vec", "title"),
    "category": ("kategorie", "category", "typ"),
    "location": ("umisteni", "location", "misto", "kde"),
    "quantity": ("mnozstvi", "quantity", "pocet", "ks", "qty"),
    "unit": ("jednotka", "unit"),
    "status": ("stav", "status"),
    "tags": ("tagy", "tags", "stitky", "klicova slova"),
    "brand": ("znacka", "brand", "vyrobce"),
    "model": ("model",),
    "serial_no": ("seriove cislo", "serial", "serial_no", "sn"),
    "ean": ("ean", "carovy kod", "barcode"),
    "purchase_date": ("datum nakupu", "purchase_date", "koupeno"),
    "purchase_price": ("cena", "price", "purchase_price"),
    "warranty_until": ("zaruka do", "zaruka", "warranty_until", "warranty"),
    "expires_at": ("expirace", "expires_at", "expires", "spotreba do"),
    "notes": ("poznamky", "poznamka", "notes", "note"),
    "description": ("popis", "description"),
    "aliases": ("aliasy", "aliases", "synonyma"),
}

_STATUS_CS = {
    "uloženo": "stored",
    "používá se": "in_use",
    "půjčeno": "lent",
    "v opravě": "repair",
    "vyřazeno": "discarded",
    "prodáno": "sold",
    "ztraceno": "lost",
}


def fold(value: str) -> str:
    norm = unicodedata.normalize("NFKD", value)
    return "".join(c for c in norm if not unicodedata.combining(c)).lower().strip()


# --- Export -------------------------------------------------------------------------------


def _fmt_decimal(value: Decimal | None, comma: bool) -> str:
    if value is None:
        return ""
    text = format(value.normalize(), "f")
    return text.replace(".", ",") if comma else text


def export_csv(
    db: Session,
    rows: list[ItemOut],
    *,
    columns: list[str] | None = None,
    per_placement: bool = True,
) -> bytes:
    """Vyrobí CSV dle nastavení (oddělovač, BOM, desetinná čárka)."""
    cols = [c for c in (columns or DEFAULT_COLUMNS) if c in EXPORT_COLUMNS]
    if not cols:
        raise ValidationFailed("Žádný platný sloupec k exportu.")
    delimiter = str(settings_service.get_value(db, "export.csv_delimiter"))
    bom = bool(settings_service.get_value(db, "export.csv_bom"))
    comma = bool(settings_service.get_value(db, "export.decimal_comma"))

    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow([EXPORT_COLUMNS[c] for c in cols])
    for item in rows:
        variants: list[tuple[str, Decimal | None]]
        if per_placement and item.placements:
            variants = [(p.location_path or "", p.quantity) for p in item.placements]
        elif item.placements:
            variants = [
                (" | ".join(p.location_path or "" for p in item.placements), item.total_quantity)
            ]
        else:
            variants = [("", None)]
        for location, qty in variants:
            values: dict[str, Any] = {
                "label_code": item.label_code,
                "name": item.name,
                "category": item.category_path or "",
                "location": location,
                "quantity": _fmt_decimal(qty, comma),
                "unit": item.unit,
                "status": item.status,
                "tags": ", ".join(item.tags),
                "brand": item.brand or "",
                "model": item.model or "",
                "serial_no": item.serial_no or "",
                "ean": item.ean or "",
                "purchase_date": item.purchase_date.isoformat() if item.purchase_date else "",
                "purchase_price": _fmt_decimal(item.purchase_price, comma),
                "warranty_until": item.warranty_until.isoformat() if item.warranty_until else "",
                "expires_at": item.expires_at.isoformat() if item.expires_at else "",
                "notes": item.notes or "",
                "description": item.description or "",
                "aliases": ", ".join(item.aliases),
            }
            writer.writerow([_safe_cell(values[c]) for c in cols])
    data = out.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if bom else data


def _safe_cell(value: Any) -> str:
    """Ochrana před „CSV injection“: buňka začínající = + - @ by se v Excelu vyhodnotila jako vzorec."""
    text = "" if value is None else str(value)
    return (
        "'" + text
        if text[:1] in ("=", "+", "@") or (text[:1] == "-" and not _is_number(text))
        else text
    )


def _is_number(text: str) -> bool:
    try:
        Decimal(text.replace(",", "."))
        return True
    except InvalidOperation:
        return False


# --- Import -------------------------------------------------------------------------------


@dataclass
class RowResult:
    row: int  # číslo řádku v souboru (záhlaví = 1)
    action: str  # create | update | skip | error
    name: str = ""
    message: str | None = None


@dataclass
class ImportReport:
    dry_run: bool
    delimiter: str
    mapping: dict[str, str]  # sloupec CSV → pole
    unmapped: list[str]
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    new_categories: list[str] = field(default_factory=list)
    new_locations: list[str] = field(default_factory=list)
    rows: list[RowResult] = field(default_factory=list)


def decode_csv(data: bytes) -> str:
    """UTF-8 (s BOM i bez), jinak Windows-1250 (typické pro český Excel)."""
    for encoding in ("utf-8-sig", "cp1250"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationFailed("Soubor se nepodařilo přečíst (očekává se UTF-8 nebo Windows-1250).")


def detect_delimiter(text: str) -> str:
    head = text.splitlines()[0] if text.splitlines() else ""
    counts = {d: head.count(d) for d in (";", ",", "\t")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > 0 else ";"


def auto_mapping(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for header in headers:
        key = fold(header)
        for field_name, names in _SYNONYMS.items():
            if field_name not in used and key in names:
                mapping[header] = field_name
                used.add(field_name)
                break
    return mapping


def _to_decimal(value: str) -> Decimal | None:
    text = value.strip().replace(" ", "").replace(" ", "")
    if not text:
        return None
    text = text.replace(",", ".") if text.count(",") == 1 and "." not in text else text
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValidationFailed(f"„{value}“ není číslo.") from exc


def _to_date(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    m = re.fullmatch(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", text)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    raise ValidationFailed(f"Datum „{value}“ nerozpoznáno (použij RRRR-MM-DD nebo D. M. RRRR).")


def _split_path(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\s*(?:›|>|/|\\)\s*", text) if p.strip()]


def import_csv(
    db: Session,
    ctx: ActorContext,
    data: bytes,
    *,
    mapping: dict[str, str] | None = None,
    dry_run: bool = True,
    on_duplicate: str = "skip",
    delimiter: str | None = None,
) -> ImportReport:
    """Importuje věci z CSV. `on_duplicate`: skip | update (shoda dle štítku, EAN nebo sér. čísla)."""
    if on_duplicate not in ("skip", "update"):
        raise ValidationFailed("on_duplicate musí být skip nebo update.")
    text = decode_csv(data)
    delim = delimiter or detect_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    try:
        headers = [h.strip() for h in next(reader)]
    except StopIteration as exc:
        raise ValidationFailed("Soubor je prázdný.") from exc
    mapped = {h: f for h, f in (mapping or auto_mapping(headers)).items() if f in EXPORT_COLUMNS}
    report = ImportReport(
        dry_run=dry_run,
        delimiter=delim,
        mapping=mapped,
        unmapped=[h for h in headers if h not in mapped],
    )
    if "name" not in mapped.values():
        raise ValidationFailed("Chybí sloupec s názvem věci (Název / Name).")

    rows = list(reader)
    if len(rows) > MAX_ROWS:
        raise ValidationFailed(f"Příliš mnoho řádků (max. {MAX_ROWS}).")
    outer = db.begin_nested()
    try:
        for index, raw in enumerate(rows, start=2):
            if not any(cell.strip() for cell in raw):
                continue
            record = {
                mapped[h]: raw[i].strip()
                for i, h in enumerate(headers)
                if h in mapped and i < len(raw)
            }
            result = RowResult(row=index, action="error", name=record.get("name", ""))
            try:
                with db.begin_nested():
                    _import_row(db, ctx, record, on_duplicate, result, report)
            except DomainError as exc:
                result.action, result.message = "error", exc.message
            report.rows.append(result)
            if result.action == "create":
                report.created += 1
            elif result.action == "update":
                report.updated += 1
            elif result.action == "skip":
                report.skipped += 1
            else:
                report.errors += 1
    finally:
        if dry_run:
            outer.rollback()
        else:
            outer.commit()
    return report


def _find_existing(db: Session, record: dict[str, str]) -> Item | None:
    for field_name, column in (
        ("label_code", Item.label_code),
        ("ean", Item.ean),
        ("serial_no", Item.serial_no),
    ):
        value = record.get(field_name, "").strip()
        if value:
            hit = (
                db.execute(select(Item).where(column == value, Item.deleted_at.is_(None)))
                .scalars()
                .first()
            )
            if hit:
                return hit
    return None


def _import_row(
    db: Session,
    ctx: ActorContext,
    record: dict[str, str],
    on_duplicate: str,
    result: RowResult,
    report: ImportReport,
) -> None:
    name = record.get("name", "").strip()
    if not name:
        raise ValidationFailed("Chybí název.")
    existing = _find_existing(db, record)
    if existing is not None and on_duplicate == "skip":
        result.action, result.message = "skip", f"Už existuje ({existing.label_code})."
        return

    fields: dict[str, Any] = {"name": name}
    for key in ("brand", "model", "serial_no", "ean", "notes", "description", "unit"):
        if record.get(key):
            fields[key] = record[key]
    if record.get("status"):
        status = _STATUS_CS.get(record["status"].lower(), record["status"].lower())
        fields["status"] = status
    if record.get("tags"):
        fields["tags"] = [t.strip() for t in re.split(r"[,;|]", record["tags"]) if t.strip()]
    if record.get("aliases"):
        fields["aliases"] = [t.strip() for t in re.split(r"[,;|]", record["aliases"]) if t.strip()]
    for key in ("purchase_date", "warranty_until", "expires_at"):
        if record.get(key):
            fields[key] = _to_date(record[key])
    if record.get("purchase_price"):
        fields["purchase_price"] = _to_decimal(record["purchase_price"])

    if record.get("category"):
        path = _split_path(record["category"])
        if path and not categories.path_exists(db, path):
            report.new_categories.append(SEP.join(path))
        fields["category_id"] = categories.get_or_create_path(db, ctx, path).id if path else None

    quantity = _to_decimal(record.get("quantity", "")) if record.get("quantity") else Decimal(1)
    location_id = None
    if record.get("location"):
        path = _split_path(record["location"])
        if path:
            if not locations.path_exists(db, path):
                report.new_locations.append(SEP.join(path))
            location_id = locations.get_or_create_path(db, ctx, path).id

    if existing is None:
        placements = (
            [PlacementIn(location_id=location_id, quantity=quantity)]
            if (location_id and quantity and quantity > 0)
            else []
        )
        try:
            payload = ItemCreate.model_validate(fields | {"placements": placements})
        except ValueError as exc:
            raise ValidationFailed(f"Neplatná hodnota: {exc}") from exc
        item = items.create_item(db, ctx, payload)
        result.action, result.message = "create", item.label_code
    else:
        try:
            patch = ItemUpdate.model_validate(fields)
        except ValueError as exc:
            raise ValidationFailed(f"Neplatná hodnota: {exc}") from exc
        items.update_item(db, ctx, existing.id, patch)
        if location_id and quantity is not None:
            items.adjust_quantity(db, ctx, existing.id, location_id, quantity)
        result.action, result.message = "update", existing.label_code
