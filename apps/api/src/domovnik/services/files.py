"""Soubory: nahrání, bezpečné uložení, deduplikace, vazby na věci / umístění a mazání.

Rozhodnutí a pravidla (viz také docs/adr/0001-uloziste-souboru.md):

**Typ souboru** určuje obsah (``imaging.sniff`` + dekodér), ne přípona ani ``Content-Type``.
Obrázky: JPEG, PNG, WebP, HEIC/HEIF a GIF (první snímek). Dokumenty: PDF (uloží se beze změny,
jen s kontrolou hlavičky a konce). Cokoli jiného (SVG, HTML, ZIP, EXE…) se odmítne.

**Deduplikace přes SHA-256 původních (nahraných) bajtů.** Hash se počítá *před* jakýmkoli
zpracováním, takže nahrání téhož souboru podruhé (opakovaný pokus z offline fronty, stejná fotka
vybraná dvakrát) se pozná, aniž by se musel obrázek znovu dekódovat. Důsledek: dvě různé
původní fotky, které by po re-enkódování dopadly na stejné bajty, se uloží zvlášť (je to
vzácné a neškodné). ``files.sha256`` je tedy otisk originálu, ne uloženého výstupu.

**Úložiště** (``config.files_dir``, relativní ``storage_path`` v DB)::

    <files_dir>/<hash[:2]>/<hash>.<jpg|webp|pdf>   uložený (znovu zakódovaný) soubor
    <files_dir>/thumbs/<hash>_256.webp             náhledy (WebP)
    <files_dir>/thumbs/<hash>_1024.webp
    <files_dir>/originals/<hash[:2]>/<hash>.bin    jen při ``photos.keep_original`` (neservíruje se)

Cesty se skládají výhradně z hexadecimálního hashe a pevných přípon; název od klienta se do cesty
nikdy nedostane (do DB jde jen očištěný ``original_name`` jako popisek ke stažení). Při čtení se
cesta ještě ověří, že zůstává uvnitř ``files_dir``.

**Náhledy** (256 a 1024 px, WebP) i blurhash se vytvářejí **synchronně při nahrání** (jsou
levné: obrázek je už dekódovaný a zmenšený). ``ensure_thumbs`` je doplní líně, kdyby na disku
chyběly (např. po obnově ze zálohy bez náhledů), a nastaví ``thumbs_ready``.

**Zápis na disk a transakce.** Služby necommitují. Soubory se na disk zapíšou atomicky
(dočasný soubor + ``os.replace``) *před* vložením řádku do DB; při rollbacku transakce proto
mohou na disku zůstat „sirotčí“ soubory – jsou adresované obsahem, takže další nahrání téhož
obsahu je přepíše stejnými bajty a ``gc_orphans`` / ``domovnik files-gc`` je uklidí. Naopak
**mazání z disku je odloženo až po commitu**: ``delete_file`` jen zapíše cesty do
``db.info`` a volající (router) po ``commit()`` zavolá ``run_pending_deletes``.

**Primární fotka.** Pro každou věc i umístění platí: má-li alespoň jednu fotku v roli
``primary``/``gallery``, má právě jednu vazbu s rolí ``primary`` (vynucuje i částečný unikátní
index z migrace 0004). U věcí je ``items.primary_file_id`` zrcadlem této vazby. Funkce
``_normalize`` to po každé změně dorovná: první nahraná fotka se stane primární; při odpojení
primární fotky se vybere další (nejnižší ``sort_order``, pak nejstarší) nebo NULL.

**Mazání souboru.** ``delete_file`` standardně selže (409), pokud na soubor něco odkazuje;
s ``detach_links=True`` vazby nejdřív odpojí (včetně přeurčení primární fotky). Soubor z disku
se smaže až po commitu a jen pokud ho mezitím nepoužil jiný řádek se stejným hashem.
"""

from __future__ import annotations

import hashlib
import logging
import os
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import ColumnElement, case, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domovnik.config import get_settings
from domovnik.context import ActorContext
from domovnik.db.models import FileLink, FileRecord, Item, Location, User
from domovnik.errors import Conflict, DomainError, NotFound, PayloadTooLarge, ValidationFailed
from domovnik.schemas import FileLinkOut, FileOut
from domovnik.services import imaging
from domovnik.services import items as item_service
from domovnik.services import settings as settings_service
from domovnik.services.common import emit, flush, get_or_404

logger = logging.getLogger(__name__)

ROLES = ("primary", "gallery", "manual", "receipt", "warranty", "other")
_CANDIDATE_ROLES = ("primary", "gallery")  # role, ze kterých se vybírá primární fotka
_PENDING_DELETES = "pending_file_deletes"
ALLOWED_TYPES_HINT = "obrázky JPEG, PNG, WebP, HEIC a GIF a dokumenty PDF"


# --- cesty a úložiště ---------------------------------------------------------------------


def files_root() -> Path:
    return Path(get_settings().files_dir).resolve()


def _resolve(root: Path, relative: str) -> Path:
    """Sestaví absolutní cestu a ověří, že zůstává uvnitř kořene úložiště."""
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise DomainError("Neplatná cesta k souboru v úložišti.")
    return target


def main_path(rec: FileRecord) -> Path:
    """Absolutní cesta k uloženému souboru (originál po re-enkódování / PDF)."""
    return _resolve(files_root(), rec.storage_path)


def thumb_path(rec: FileRecord, size: int) -> Path:
    if size not in imaging.THUMB_SIZES:
        raise ValidationFailed(f"Náhled {size} px neexistuje (povoleno: {imaging.THUMB_SIZES}).")
    return _resolve(files_root(), f"thumbs/{rec.sha256.hex()}_{size}.webp")


def _original_path(root: Path, digest_hex: str) -> Path:
    return _resolve(root, f"originals/{digest_hex[:2]}/{digest_hex}.bin")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def safe_filename(name: str | None) -> str | None:
    """Očistí název od klienta: jen poslední složka cesty, bez řídicích znaků, max 200 znaků."""
    if not name:
        return None
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFC", base)
    base = "".join(ch for ch in base if ch.isprintable()).strip(" .")
    return base[:200] or None


def download_name(rec: FileRecord) -> str:
    """Název pro hlavičku Content-Disposition (přípona podle skutečného uloženého formátu)."""
    suffix = Path(rec.storage_path).suffix
    stem = Path(rec.original_name).stem if rec.original_name else ""
    return f"{stem or 'soubor'}{suffix}"


# --- nastavení a pomůcky ------------------------------------------------------------------


def max_upload_bytes(db: Session) -> int:
    return int(settings_service.get_value(db, "photos.max_upload_mb")) * 1024 * 1024


def _localize(db: Session, ctx: ActorContext, taken: datetime | None) -> datetime | None:
    """Čas z EXIF bez zóny = místní čas fotoaparátu → zóna nahrávajícího uživatele."""
    if taken is None or taken.tzinfo is not None:
        return taken
    tzname = "UTC"
    if ctx.actor_id is not None and (user := db.get(User, ctx.actor_id)) is not None:
        tzname = user.timezone
    try:
        zone: Any = ZoneInfo(tzname)
    except (ZoneInfoNotFoundError, ValueError):
        zone = UTC
    return taken.replace(tzinfo=zone)


@dataclass
class UploadResult:
    file: FileRecord
    created: bool  # False = stejný obsah už v úložišti byl (deduplikace)
    link: FileLink | None


# --- nahrání ------------------------------------------------------------------------------


def store(
    db: Session, ctx: ActorContext, data: bytes, filename: str | None
) -> tuple[FileRecord, bool]:
    """Zvaliduje, zpracuje a uloží soubor; vrací ``(záznam, vytvořen)``.

    Stejný obsah (SHA-256 nahraných bajtů) se neukládá podruhé – vrátí se existující záznam.
    """
    limit = max_upload_bytes(db)
    if len(data) > limit:
        raise PayloadTooLarge(
            f"Soubor je příliš velký (limit {limit // 1024 // 1024} MB).", max_bytes=limit
        )
    if not data:
        raise ValidationFailed("Soubor je prázdný.")

    digest = hashlib.sha256(data).digest()
    existing = _by_digest(db, digest)
    if existing is not None:
        return existing, False

    kind = imaging.sniff(data)
    if kind is None:
        raise ValidationFailed(
            f"Nepodporovaný typ souboru (rozpoznáno z obsahu). Povoleno: {ALLOWED_TYPES_HINT}."
        )

    hexhash = digest.hex()
    root = files_root()
    thumbs: dict[int, bytes] = {}
    blurhash: str | None = None
    exif: dict[str, Any] | None = None
    taken_at: datetime | None = None
    width = height = None
    if kind == "pdf":
        imaging.validate_pdf(data)
        file_kind, mime, ext, stored = "document", "application/pdf", "pdf", data
    else:
        get = settings_service.get_value
        processed = imaging.process_image(
            data,
            kind,
            max_dimension=int(get(db, "photos.max_dimension")),
            quality=int(get(db, "photos.jpeg_quality")),
            strip_gps=bool(get(db, "photos.strip_gps")),
            max_pixels=int(get(db, "photos.max_megapixels")) * 1_000_000,
        )
        file_kind, mime, ext, stored = "photo", processed.mime, processed.ext, processed.data
        thumbs, blurhash = processed.thumbs, processed.blurhash
        exif = processed.exif or None
        taken_at = _localize(db, ctx, processed.taken_at)
        width, height = processed.width, processed.height

    relative = f"{hexhash[:2]}/{hexhash}.{ext}"
    _write_atomic(_resolve(root, relative), stored)
    for size, blob in thumbs.items():
        _write_atomic(_resolve(root, f"thumbs/{hexhash}_{size}.webp"), blob)
    if file_kind == "photo" and bool(settings_service.get_value(db, "photos.keep_original")):
        _write_atomic(_original_path(root, hexhash), data)

    rec = FileRecord(
        kind=file_kind,
        sha256=digest,
        storage_path=relative,
        original_name=safe_filename(filename),
        mime=mime,
        size_bytes=len(stored),
        width=width,
        height=height,
        taken_at=taken_at,
        exif=exif,
        blurhash=blurhash,
        thumbs_ready=bool(thumbs),
        uploaded_by=ctx.actor_id,
    )
    try:
        with db.begin_nested():
            db.add(rec)
            db.flush()
    except IntegrityError:  # souběžné nahrání téhož obsahu – vyhrál ten druhý
        existing = _by_digest(db, digest)
        if existing is None:
            raise
        return existing, False
    emit(
        db,
        ctx,
        "file.uploaded",
        "file",
        rec.id,
        {"kind": file_kind, "mime": mime, "size_bytes": len(stored), "name": rec.original_name},
    )
    return rec, True


def _by_digest(db: Session, digest: bytes) -> FileRecord | None:
    return db.execute(select(FileRecord).where(FileRecord.sha256 == digest)).scalar_one_or_none()


def upload(
    db: Session,
    ctx: ActorContext,
    data: bytes,
    filename: str | None,
    *,
    item_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    role: str | None = None,
    caption: str | None = None,
) -> UploadResult:
    """Nahraje soubor a (je-li zadána věc nebo umístění) ho k ní rovnou připojí.

    Popisek patří vazbě; bez vazby se uloží jako popisek souboru. Cíl a role se kontrolují
    dřív než drahé zpracování obrázku.
    """
    target = _target(item_id, location_id) if (item_id or location_id) else None
    _check_role(role)
    if target is not None:
        _lock_target(db, target, lock=False, include_deleted=False)
    rec, created = store(db, ctx, data, filename)
    caption = _clean_caption(caption)
    link: FileLink | None = None
    if target is not None:
        link = attach(
            db, ctx, rec.id, item_id=item_id, location_id=location_id, role=role, caption=caption
        )
    elif caption and created:
        rec.caption = caption
        flush(db)
    return UploadResult(file=rec, created=created, link=link)


def _clean_caption(caption: str | None) -> str | None:
    return (caption or "").strip()[:1000] or None


def _check_role(role: str | None) -> None:
    if role is not None and role not in ROLES:
        raise ValidationFailed(f"Neznámá role „{role}“ (povoleno: {', '.join(ROLES)}).")


# --- cíl vazby (věc / umístění) -----------------------------------------------------------


@dataclass(frozen=True)
class _Target:
    item_id: uuid.UUID | None
    location_id: uuid.UUID | None

    def clause(self) -> ColumnElement[bool]:
        if self.item_id is not None:
            return FileLink.item_id == self.item_id
        return FileLink.location_id == self.location_id


def _target(item_id: uuid.UUID | None, location_id: uuid.UUID | None) -> _Target:
    if (item_id is None) == (location_id is None):
        raise ValidationFailed("Zadej právě jedno z item_id a location_id.")
    return _Target(item_id, location_id)


def _lock_target(
    db: Session, target: _Target, *, lock: bool = True, include_deleted: bool = True
) -> Item | Location:
    """Načte (a zamkne) věc / umístění; zámek serializuje změny primární fotky."""
    if target.item_id is not None:
        return item_service.get_item(db, target.item_id, lock=lock, include_deleted=include_deleted)
    return get_or_404(db, Location, target.location_id, lock=lock, what="Umístění")  # type: ignore[arg-type]


def _target_of(link: FileLink) -> _Target:
    return _Target(link.item_id, link.location_id)


# --- vazby ---------------------------------------------------------------------------------


def get_file(db: Session, file_id: uuid.UUID) -> FileRecord:
    return get_or_404(db, FileRecord, file_id, what="Soubor")


def get_link(db: Session, link_id: uuid.UUID, *, lock: bool = False) -> FileLink:
    return get_or_404(db, FileLink, link_id, lock=lock, what="Vazba souboru")


def attach(
    db: Session,
    ctx: ActorContext,
    file_id: uuid.UUID,
    *,
    item_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    role: str | None = None,
    caption: str | None = None,
    sort_order: int | None = None,
) -> FileLink:
    """Připojí soubor k věci nebo umístění. Opakované připojení téhož souboru je idempotentní.

    Bez ``role`` je fotka ``gallery`` (a první fotka ``primary``), dokument ``other``.
    """
    target = _target(item_id, location_id)
    _check_role(role)
    rec = get_file(db, file_id)
    owner = _lock_target(db, target, include_deleted=False)

    existing = db.execute(
        select(FileLink).where(FileLink.file_id == rec.id, target.clause())
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    if role == "primary" and rec.kind != "photo":
        raise ValidationFailed("Primární může být jen fotka, ne dokument.")

    if role is None:
        role = "gallery" if rec.kind == "photo" else "other"
    if sort_order is None:
        sort_order = db.execute(
            select(func.coalesce(func.max(FileLink.sort_order), -1) + 1).where(target.clause())
        ).scalar_one()
    link = FileLink(
        file_id=rec.id,
        item_id=item_id,
        location_id=location_id,
        role="gallery" if role == "primary" else role,
        sort_order=sort_order,
        caption=_clean_caption(caption),
    )
    db.add(link)
    flush(db)
    if role == "primary":
        _make_primary(db, ctx, target, owner, link)
    else:
        _normalize(db, ctx, target, owner)
    emit(db, ctx, "file.linked", "file", rec.id, _link_payload(link))
    return link


def update_link(
    db: Session, ctx: ActorContext, link_id: uuid.UUID, changes: dict[str, Any]
) -> FileLink:
    """Upraví vazbu. ``changes`` smí obsahovat ``role``, ``caption``, ``sort_order``, ``is_primary``.

    ``is_primary=True`` (nebo ``role='primary'``) fotku povýší a dosavadní primární se změní na
    ``gallery``. Odebrání primárního stavu (``is_primary=False`` / jiná role) přenechá primární
    roli další fotce; je-li jediná, zůstane primární.
    """
    link = get_link(db, link_id, lock=True)
    rec = get_file(db, link.file_id)
    target = _target_of(link)
    owner = _lock_target(db, target)
    _check_role(changes.get("role"))

    if "caption" in changes:
        link.caption = _clean_caption(changes["caption"])
    if changes.get("sort_order") is not None:
        link.sort_order = int(changes["sort_order"])

    new_role: str | None = changes.get("role")
    promote = changes.get("is_primary") is True or new_role == "primary"
    if promote:
        if rec.kind != "photo":
            raise ValidationFailed("Primární může být jen fotka, ne dokument.")
        flush(db)
        _make_primary(db, ctx, target, owner, link)
    else:
        demote_to: str | None = None
        if new_role is not None and new_role != link.role:
            demote_to = new_role
        elif changes.get("is_primary") is False and link.role == "primary":
            demote_to = "gallery"
        if demote_to is not None:
            was_primary = link.role == "primary"
            link.role = demote_to
            flush(db)
            _normalize(db, ctx, target, owner, avoid=link.id if was_primary else None)
        else:
            flush(db)
            _normalize(db, ctx, target, owner)
    emit(db, ctx, "file.link_updated", "file", link.file_id, _link_payload(link))
    return link


def set_primary(db: Session, ctx: ActorContext, link_id: uuid.UUID) -> FileLink:
    """Nastaví fotku jako primární (hlavní) fotku věci / umístění."""
    return update_link(db, ctx, link_id, {"is_primary": True})


def detach(db: Session, ctx: ActorContext, link_id: uuid.UUID) -> None:
    """Odpojí soubor od věci / umístění. Soubor samotný zůstává v úložišti."""
    link = get_link(db, link_id, lock=True)
    _detach_link(db, ctx, link)


def _detach_link(db: Session, ctx: ActorContext, link: FileLink) -> None:
    target = _target_of(link)
    owner = _lock_target(db, target)
    payload = _link_payload(link)
    file_id = link.file_id
    db.delete(link)
    flush(db)
    _normalize(db, ctx, target, owner)
    emit(db, ctx, "file.unlinked", "file", file_id, payload)


def reorder(
    db: Session,
    ctx: ActorContext,
    link_ids: list[uuid.UUID],
    *,
    item_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
) -> list[FileLink]:
    """Nastaví pořadí vazeb: ``link_ids`` jdou první, ostatní zůstanou za nimi."""
    target = _target(item_id, location_id)
    _lock_target(db, target)
    links = list(
        db.execute(select(FileLink).where(target.clause()).order_by(*_link_order())).scalars()
    )
    by_id = {link.id: link for link in links}
    if len(set(link_ids)) != len(link_ids):
        raise ValidationFailed("Seznam vazeb obsahuje duplicity.")
    unknown = [str(i) for i in link_ids if i not in by_id]
    if unknown:
        raise ValidationFailed("Některé vazby nepatří k této věci / umístění.", unknown=unknown)
    wanted = set(link_ids)
    ordered = [by_id[i] for i in link_ids] + [link for link in links if link.id not in wanted]
    for index, link in enumerate(ordered):
        if link.sort_order != index:
            link.sort_order = index
    flush(db)
    emit(
        db,
        ctx,
        "file.reordered",
        "item" if item_id else "location",
        item_id or location_id,  # type: ignore[arg-type]
        {"link_ids": [str(i) for i in link_ids]},
    )
    return ordered


def _link_payload(link: FileLink) -> dict[str, Any]:
    return {
        "link_id": str(link.id),
        "file_id": str(link.file_id),
        "item_id": str(link.item_id) if link.item_id else None,
        "location_id": str(link.location_id) if link.location_id else None,
        "role": link.role,
    }


def _link_order() -> tuple[Any, ...]:
    return (
        case((FileLink.role == "primary", 0), else_=1),
        FileLink.sort_order,
        FileLink.created_at,
        FileLink.id,
    )


def _make_primary(
    db: Session, ctx: ActorContext, target: _Target, owner: Item | Location, link: FileLink
) -> None:
    others = list(
        db.execute(
            select(FileLink).where(
                target.clause(), FileLink.role == "primary", FileLink.id != link.id
            )
        ).scalars()
    )
    for other in others:
        other.role = "gallery"
    if others:
        flush(db)  # částečný unikátní index: dosavadní primární musí zmizet dřív
    link.role = "primary"
    flush(db)
    _normalize(db, ctx, target, owner)


def _normalize(
    db: Session,
    ctx: ActorContext,
    target: _Target,
    owner: Item | Location,
    *,
    avoid: uuid.UUID | None = None,
) -> None:
    """Dorovná invariant primární fotky a zrcadlí ji do ``items.primary_file_id``."""
    current = db.execute(
        select(FileLink).where(target.clause(), FileLink.role == "primary")
    ).scalar_one_or_none()
    if current is None:
        current = _next_candidate(db, target, avoid) or (
            _next_candidate(db, target, None) if avoid else None
        )
        if current is not None:
            current.role = "primary"
            flush(db)
    if isinstance(owner, Item):
        new_file_id = current.file_id if current is not None else None
        if owner.primary_file_id != new_file_id:
            owner.primary_file_id = new_file_id
            owner.updated_by = ctx.actor_id
            flush(db)
            db.refresh(owner)
            emit(db, ctx, "item.updated", "item", owner.id, {"fields": ["primary_file_id"]})


def _next_candidate(db: Session, target: _Target, avoid: uuid.UUID | None) -> FileLink | None:
    stmt = (
        select(FileLink)
        .join(FileRecord, FileRecord.id == FileLink.file_id)
        .where(target.clause(), FileRecord.kind == "photo", FileLink.role.in_(_CANDIDATE_ROLES))
        .order_by(FileLink.sort_order, FileLink.created_at, FileLink.id)
        .limit(1)
    )
    if avoid is not None:
        stmt = stmt.where(FileLink.id != avoid)
    return db.execute(stmt).scalar_one_or_none()


# --- čtení / výpisy -----------------------------------------------------------------------


def file_out(rec: FileRecord) -> FileOut:
    is_photo = rec.kind == "photo"
    base = f"/api/v1/files/{rec.id}"
    return FileOut(
        id=rec.id,
        kind=rec.kind,  # type: ignore[arg-type]
        mime=rec.mime,
        size_bytes=rec.size_bytes,
        width=rec.width,
        height=rec.height,
        original_name=rec.original_name,
        caption=rec.caption,
        taken_at=rec.taken_at,
        exif=rec.exif,
        blurhash=rec.blurhash,
        thumbs_ready=rec.thumbs_ready,
        created_at=rec.created_at,
        url=base,
        thumb_256_url=f"{base}/thumb?size=256" if is_photo else None,
        thumb_1024_url=f"{base}/thumb?size=1024" if is_photo else None,
    )


def link_out(link: FileLink, rec: FileRecord) -> FileLinkOut:
    return FileLinkOut(
        id=link.id,
        item_id=link.item_id,
        location_id=link.location_id,
        role=link.role,  # type: ignore[arg-type]
        is_primary=link.role == "primary",
        sort_order=link.sort_order,
        caption=link.caption or rec.caption,
        created_at=link.created_at,
        file=file_out(rec),
    )


def _list(db: Session, target: _Target) -> list[FileLinkOut]:
    rows = db.execute(
        select(FileLink, FileRecord)
        .join(FileRecord, FileRecord.id == FileLink.file_id)
        .where(target.clause())
        .order_by(*_link_order())
    ).all()
    return [link_out(link, rec) for link, rec in rows]


def list_for_item(db: Session, item_id: uuid.UUID) -> list[FileLinkOut]:
    """Soubory věci: primární první, pak dle ``sort_order``. Funguje i pro věc v koši."""
    item_service.get_item(db, item_id, include_deleted=True)
    return _list(db, _Target(item_id, None))


def list_for_location(db: Session, location_id: uuid.UUID) -> list[FileLinkOut]:
    get_or_404(db, Location, location_id, what="Umístění")
    return _list(db, _Target(None, location_id))


def link_out_by_id(db: Session, link_id: uuid.UUID) -> FileLinkOut:
    link = get_link(db, link_id)
    return link_out(link, get_file(db, link.file_id))


# --- náhledy ------------------------------------------------------------------------------


def ensure_thumbs(db: Session, rec: FileRecord) -> bool:
    """Doplní chybějící náhledy z uloženého obrázku; vrací True, pokud se něco vytvořilo."""
    if rec.kind != "photo":
        raise NotFound("Dokument nemá náhled.")
    missing = [s for s in imaging.THUMB_SIZES if not thumb_path(rec, s).exists()]
    if not missing and rec.thumbs_ready:
        return False
    source = main_path(rec)
    if not source.exists():
        raise NotFound("Soubor chybí v úložišti.")
    try:
        blobs = imaging.make_thumbnails(source.read_bytes())
    except Exception as exc:
        raise DomainError("Náhled nelze vytvořit – uložený obrázek je poškozený.") from exc
    for size in missing or imaging.THUMB_SIZES:
        _write_atomic(thumb_path(rec, size), blobs[size])
    rec.thumbs_ready = True
    db.flush()
    return True


# --- mazání -------------------------------------------------------------------------------


def delete_file(
    db: Session, ctx: ActorContext, file_id: uuid.UUID, *, detach_links: bool = False
) -> None:
    """Smaže soubor. Na disku zmizí až po commitu (``run_pending_deletes``).

    Odkazuje-li na soubor nějaká vazba, vyhodí 409, pokud není ``detach_links=True``
    (pak se vazby nejdřív odpojí a primární fotky dotčených věcí se přeurčí).
    """
    rec = get_or_404(db, FileRecord, file_id, lock=True, what="Soubor")
    links = list(db.execute(select(FileLink).where(FileLink.file_id == rec.id)).scalars())
    if links and not detach_links:
        raise Conflict(
            f"Soubor je připojen k {len(links)} záznamům. Nejdřív ho odpoj, "
            "nebo smaž i s vazbami (force).",
            link_count=len(links),
        )
    for link in links:
        _detach_link(db, ctx, link)
    root = files_root()
    hexhash = rec.sha256.hex()
    paths = [_resolve(root, rec.storage_path), _original_path(root, hexhash)]
    paths += [_resolve(root, f"thumbs/{hexhash}_{s}.webp") for s in imaging.THUMB_SIZES]
    digest, name = rec.sha256, rec.original_name
    db.delete(rec)
    flush(db)
    db.info.setdefault(_PENDING_DELETES, []).append((digest, paths))
    emit(db, ctx, "file.deleted", "file", file_id, {"name": name})


def run_pending_deletes(db: Session) -> int:
    """Po commitu smaže z disku soubory zrušených záznamů; vrací počet smazaných souborů."""
    pending: list[tuple[bytes, list[Path]]] = db.info.pop(_PENDING_DELETES, [])
    removed = 0
    for digest, paths in pending:
        if _by_digest(db, digest) is not None:
            continue  # mezitím se stejný obsah nahrál znovu – soubory patří novému záznamu
        for path in paths:
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                logger.warning("Soubor %s se nepodařilo smazat", path, exc_info=True)
    return removed


def gc_orphans(db: Session, ctx: ActorContext, *, older_than: timedelta) -> int:
    """Smaže soubory, na které nic neodkazuje a jsou starší než ``older_than``.

    Po commitu je potřeba zavolat ``run_pending_deletes``. Vrací počet smazaných záznamů.
    """
    cutoff = datetime.now(UTC) - older_than
    ids = list(
        db.execute(
            select(FileRecord.id).where(
                FileRecord.created_at < cutoff,
                ~exists().where(FileLink.file_id == FileRecord.id),
                ~exists().where(Item.primary_file_id == FileRecord.id),
            )
        ).scalars()
    )
    for file_id in ids:
        delete_file(db, ctx, file_id)
    return len(ids)
