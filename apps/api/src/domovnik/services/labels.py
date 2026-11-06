"""Štítky: rozlišení naskenovaného kódu a podklady pro tisk PDF."""

from __future__ import annotations

import re
import uuid
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domovnik.db.models import Item, ItemPlacement, Location
from domovnik.errors import NotFound, ValidationFailed
from domovnik.schemas import ResolveOut
from domovnik.services import label_pdf
from domovnik.services.label_pdf import LabelData
from domovnik.services.locations import location_full_names
from domovnik.services.settings import get_value

LabelKind = Literal["item", "location"]
MAX_LABELS = 500

_NON_ALNUM = re.compile(r"[^0-9A-Za-z]+")
_PREFIXED = re.compile(r"^([IL])(\d+)$")


def normalize_code(raw: str) -> str:
    """Odstraní mezery/pomlčky a sjednotí velikost písmen: ``i 000123`` → ``I000123``."""
    return _NON_ALNUM.sub("", raw).upper()


def canonical_forms(raw: str) -> list[str]:
    """Možné podoby kódu v databázi: zadaná, velká písmena a ``I-000123`` / ``L-000004``."""
    text = raw.strip()
    forms = [text, text.upper()]
    m = _PREFIXED.match(normalize_code(raw))
    if m:
        forms.append(f"{m.group(1)}-{int(m.group(2)):06d}")
    return list(dict.fromkeys(forms))


def resolve_code(db: Session, raw: str) -> ResolveOut:
    """Najde věc nebo umístění podle textu z QR / ručně zadaného kódu (bez ohledu na formát)."""
    if not raw or not raw.strip():
        raise ValidationFailed("Kód je prázdný.")
    forms = canonical_forms(raw)
    norm = normalize_code(raw)

    def find_item(*conditions: object) -> Item | None:
        stmt = select(Item).where(*conditions).limit(1)  # type: ignore[arg-type]
        return db.execute(stmt).scalar_one_or_none()

    def find_location(*conditions: object) -> Location | None:
        stmt = select(Location).where(*conditions).limit(1)  # type: ignore[arg-type]
        return db.execute(stmt).scalar_one_or_none()

    item = find_item(Item.label_code.in_(forms))
    location = None if item else find_location(Location.label_code.in_(forms))
    if item is None and location is None and norm:
        # tolerantní shoda: bez pomlček a mezer, bez ohledu na velikost písmen
        squashed_item = func.upper(func.regexp_replace(Item.label_code, "[^0-9A-Za-z]", "", "g"))
        squashed_loc = func.upper(func.regexp_replace(Location.label_code, "[^0-9A-Za-z]", "", "g"))
        item = find_item(squashed_item == norm)
        if item is None:
            location = find_location(squashed_loc == norm)

    if item is not None:
        path = _first_location_path(db, item.id)
        return ResolveOut(
            type="item",
            id=item.id,
            name=item.name,
            label_code=item.label_code,
            full_name=path,
            deleted=item.deleted_at is not None,
        )
    if location is not None:
        names = location_full_names(db, [location.id])
        return ResolveOut(
            type="location",
            id=location.id,
            name=location.name,
            label_code=location.label_code,
            full_name=names.get(location.id),
            deleted=location.archived_at is not None,
        )
    raise NotFound(f"Kód „{raw.strip()}“ neodpovídá žádné věci ani umístění.")


def _first_location_path(db: Session, item_id: uuid.UUID) -> str | None:
    loc_id = db.execute(
        select(ItemPlacement.location_id)
        .where(ItemPlacement.item_id == item_id)
        .order_by(ItemPlacement.placed_at)
        .limit(1)
    ).scalar_one_or_none()
    if loc_id is None:
        return None
    return location_full_names(db, [loc_id]).get(loc_id)


def _parent_path(full_name: str | None, own_name: str) -> str | None:
    """Cesta nadřazených umístění (bez názvu samotného umístění)."""
    if not full_name:
        return None
    suffix = f" › {own_name}"
    if full_name.endswith(suffix):
        return full_name[: -len(suffix)] or None
    return None if full_name == own_name else full_name


def collect_labels(db: Session, kind: LabelKind, ids: list[uuid.UUID]) -> list[LabelData]:
    """Podklady pro štítky ve stejném pořadí, jak byla zadána ID."""
    if not ids:
        raise ValidationFailed("Chybí ID položek k tisku.")
    if len(ids) > MAX_LABELS:
        raise ValidationFailed(f"Najednou lze vytisknout nejvýše {MAX_LABELS} štítků.")
    unique = list(dict.fromkeys(ids))
    out: dict[uuid.UUID, LabelData] = {}
    if kind == "item":
        items = {
            i.id: i
            for i in db.execute(
                select(Item).where(Item.id.in_(unique), Item.deleted_at.is_(None))
            ).scalars()
        }
        placements = db.execute(
            select(ItemPlacement.item_id, ItemPlacement.location_id)
            .where(ItemPlacement.item_id.in_(unique))
            .order_by(ItemPlacement.placed_at)
        ).all()
        first_loc: dict[uuid.UUID, uuid.UUID] = {}
        for item_id, loc_id in placements:
            first_loc.setdefault(item_id, loc_id)
        names = location_full_names(db, list(set(first_loc.values())))
        for item_id, item in items.items():
            first = first_loc.get(item_id)
            out[item_id] = LabelData(
                code=item.label_code,
                name=item.name,
                path=names.get(first) if first else None,
            )
    else:
        locs = {
            loc.id: loc
            for loc in db.execute(select(Location).where(Location.id.in_(unique))).scalars()
        }
        names = location_full_names(db, list(locs))
        for loc_id, loc in locs.items():
            out[loc_id] = LabelData(
                code=loc.label_code,
                name=loc.name,
                path=_parent_path(names.get(loc_id), loc.name),
            )
    missing = [str(i) for i in unique if i not in out]
    if missing:
        raise NotFound("Některé položky k tisku neexistují (nebo jsou v koši).", ids=missing[:20])
    return [out[i] for i in ids]


def build_pdf(
    db: Session,
    kind: LabelKind,
    ids: list[uuid.UUID],
    *,
    page_format: str | None = None,
    start: int = 0,
    show_path: bool | None = None,
    guides: bool | None = None,
) -> bytes:
    """Vytvoří PDF se štítky; neuvedené volby se berou z nastavení ``labels.*``."""
    labels = collect_labels(db, kind, ids)
    fmt = page_format or str(get_value(db, "labels.page_format"))
    if show_path is None:
        show_path = bool(get_value(db, "labels.show_path"))
    if guides is None:
        guides = bool(get_value(db, "labels.cut_guides"))
    return label_pdf.render_labels_pdf(labels, fmt, start=start, show_path=show_path, guides=guides)
