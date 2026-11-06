"""Testy fáze F4: nahrávání souborů (bezpečnost, re-enkódování, dedupe), vazby a HTTP API."""

from __future__ import annotations

import hashlib
import io
import struct
import uuid
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from PIL.TiffImagePlugin import IFDRational
from sqlalchemy import select
from sqlalchemy.orm import Session

from domovnik.config import get_settings
from domovnik.context import ActorContext
from domovnik.db.models import AuditLog, EventOutbox, FileLink, FileRecord, Item
from domovnik.errors import Conflict, DomainError, NotFound, PayloadTooLarge, ValidationFailed
from domovnik.main import app
from domovnik.ratelimit import login_limiter
from domovnik.schemas import ItemCreate, LocationCreate
from domovnik.services import files, imaging, items, locations
from domovnik.services import settings as settings_service

PASSWORD = "correct horse battery"


# --- pomůcky ------------------------------------------------------------------------------


@pytest.fixture
def files_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Úložiště souborů v dočasném adresáři (přepis ``config.files_dir`` přes prostředí)."""
    root = tmp_path / "files"
    monkeypatch.setenv("FILES_DIR", str(root))
    get_settings.cache_clear()
    yield root.resolve()
    monkeypatch.undo()
    get_settings.cache_clear()


def img(
    fmt: str = "JPEG",
    size: tuple[int, int] = (64, 48),
    color: int | tuple[int, ...] = (200, 30, 30),
    mode: str = "RGB",
    **save: Any,
) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format=fmt, **save)
    return buf.getvalue()


def jpeg_with_exif(
    *,
    size: tuple[int, int] = (80, 60),
    orientation: int | None = None,
    gps: bool = False,
    taken: str | None = "2023:05:04 10:20:30",
    color: tuple[int, int, int] = (10, 120, 200),
) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "TestCam"
    exif[0x0110] = "Model X"
    if orientation:
        exif[0x0112] = orientation
    sub: dict[int, Any] = {0x829A: IFDRational(1, 100), 0x8827: 200}
    if taken:
        sub[0x9003] = taken
    exif[0x8769] = sub
    if gps:
        exif[0x8825] = {
            1: "N",
            2: (IFDRational(50), IFDRational(5), IFDRational(30)),
            3: "E",
            4: (IFDRational(14), IFDRational(25), IFDRational(0)),
        }
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def heic_sample() -> bytes:
    try:
        return img("HEIF", size=(96, 64))
    except Exception:  # pragma: no cover - závisí na platformě
        pytest.skip("pillow-heif neumí vytvořit vzorek HEIC")


def bomb_png(width: int = 100_000, height: int = 100_000) -> bytes:
    """Platná hlavička PNG s obřími rozměry a nepatrnými daty (nikdy se nerozbalí)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 64))
        + chunk(b"IEND", b"")
    )


def pdf_bytes(extra: bytes = b"") -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
        b"trailer<</Root 1 0 R>>\n" + extra + b"%%EOF\n"
    )


def stored_bytes(rec: FileRecord) -> bytes:
    return files.main_path(rec).read_bytes()


def stored_image(rec: FileRecord) -> Image.Image:
    return Image.open(io.BytesIO(stored_bytes(rec)))


def set_setting(db: Session, ctx: ActorContext, key: str, value: Any) -> None:
    settings_service.set_value(db, ctx, key, value, actor_is_admin=True)


def new_item(db: Session, ctx: ActorContext, name: str = "Vrtačka") -> Item:
    return items.create_item(db, ctx, ItemCreate(name=name))


def photo(n: int) -> bytes:
    """Každé n dává jiný obsah (a tedy jiný hash)."""
    return img(size=(40 + n, 30 + n), color=(n * 10 % 256, 100, 50))


# --- typy a bezpečnost --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (img("JPEG"), "image/jpeg"),
        (img("PNG"), "image/jpeg"),  # neprůhledné PNG → JPEG
        (img("WEBP"), "image/jpeg"),
        (img("GIF", mode="P", color=5), "image/jpeg"),
        (img("PNG", mode="RGBA", color=(255, 0, 0, 90)), "image/webp"),  # průhlednost zůstane
    ],
    ids=["jpeg", "png", "webp", "gif", "png-alfa"],
)
def test_upload_images_reencoded_with_thumbs(
    db: Session, ctx: ActorContext, files_dir: Path, data: bytes, mime: str
) -> None:
    rec, created = files.store(db, ctx, data, "foto.bin")
    assert created and rec.kind == "photo" and rec.mime == mime
    assert rec.sha256.hex() in rec.storage_path and (files_dir / rec.storage_path).is_file()
    assert (rec.width, rec.height) == (64, 48)
    assert rec.thumbs_ready and rec.blurhash and len(rec.blurhash) == 28
    for size in (256, 1024):
        thumb = Image.open(files.thumb_path(rec, size))
        assert thumb.format == "WEBP" and max(thumb.size) <= size
    assert Image.open(io.BytesIO(stored_bytes(rec))).size == (64, 48)


def test_upload_heic(db: Session, ctx: ActorContext, files_dir: Path) -> None:
    rec, _ = files.store(db, ctx, heic_sample(), "IMG_0001.HEIC")
    assert rec.kind == "photo" and rec.mime == "image/jpeg"
    assert stored_image(rec).format == "JPEG" and (rec.width, rec.height) == (96, 64)
    assert files.download_name(rec) == "IMG_0001.jpg"


def test_pdf_stored_unchanged_and_has_no_thumbs(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    data = pdf_bytes()
    rec, created = files.upload(db, ctx, data, "navod.pdf").file, True
    assert created and rec.kind == "document" and rec.mime == "application/pdf"
    assert stored_bytes(rec) == data and not rec.thumbs_ready and rec.width is None
    with pytest.raises(NotFound):
        files.ensure_thumbs(db, rec)


@pytest.mark.parametrize(
    "data",
    [
        b"<html><body><script>alert(1)</script></body></html>",
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"PK\x03\x04" + b"\x00" * 64,  # ZIP
        b"MZ\x90\x00" + b"\x00" * 64,  # EXE
        b"%!PS-Adobe-3.0 EPSF-3.0\n",
        b"just text",
    ],
    ids=["html", "svg", "zip", "exe", "eps", "text"],
)
def test_fake_extension_rejected_by_content(
    db: Session, ctx: ActorContext, files_dir: Path, data: bytes
) -> None:
    with pytest.raises(ValidationFailed, match="Nepodporovaný typ"):
        files.store(db, ctx, data, "fotka.jpg")
    assert not files_dir.exists() or not any(files_dir.rglob("*.*"))


def test_real_image_with_wrong_name_is_accepted_by_content(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    rec, _ = files.store(db, ctx, img("PNG"), "soubor.exe")
    assert rec.kind == "photo" and rec.mime == "image/jpeg"


def test_empty_and_corrupt_files(db: Session, ctx: ActorContext, files_dir: Path) -> None:
    with pytest.raises(ValidationFailed, match="prázdný"):
        files.store(db, ctx, b"", "a.jpg")
    good = img("JPEG", size=(300, 300))
    for broken in (
        good[:200],  # useknutý JPEG
        b"\xff\xd8\xff" + b"nesmysl" * 50,
        img("PNG")[:40],
        b"RIFF\x00\x00\x00\x00WEBP" + b"x" * 40,
    ):
        with pytest.raises(ValidationFailed, match="poškozen"):
            files.store(db, ctx, broken, "a.jpg")
    with pytest.raises(ValidationFailed, match="PDF"):
        files.store(db, ctx, b"%PDF-1.4\n1 0 obj", "a.pdf")  # bez %%EOF
    assert db.execute(select(FileRecord)).first() is None


def test_oversized_upload_rejected(db: Session, ctx: ActorContext, files_dir: Path) -> None:
    limit = files.max_upload_bytes(db)
    assert limit == 25 * 1024 * 1024
    set_setting(db, ctx, "photos.max_upload_mb", 1)
    with pytest.raises(PayloadTooLarge):
        files.store(db, ctx, b"\xff\xd8\xff" + b"\x00" * (1024 * 1024), "velky.jpg")
    with pytest.raises(PayloadTooLarge):
        files.store(db, ctx, pdf_bytes(b"x" * (1024 * 1024)), "velky.pdf")  # limit platí i pro PDF


def test_decompression_bomb_rejected_before_decoding(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    data = bomb_png()
    assert len(data) < 200
    with pytest.raises(ValidationFailed, match="příliš"):
        files.store(db, ctx, data, "bomba.png")


def test_megapixel_limit_is_configurable(db: Session, ctx: ActorContext, files_dir: Path) -> None:
    data = img("JPEG", size=(1500, 1000))  # 1,5 Mpx
    set_setting(db, ctx, "photos.max_megapixels", 1)
    with pytest.raises(ValidationFailed, match="příliš velký"):
        files.store(db, ctx, data, "a.jpg")
    set_setting(db, ctx, "photos.max_megapixels", 2)
    rec, _ = files.store(db, ctx, data, "a.jpg")
    assert rec.width == 1500


def test_polyglot_trailing_data_is_removed(db: Session, ctx: ActorContext, files_dir: Path) -> None:
    payload = b"<script>alert('x')</script>PK\x03\x04SECRET-TRAILER"
    rec, _ = files.store(db, ctx, img("JPEG") + payload, "a.jpg")
    out = stored_bytes(rec)
    assert b"SECRET-TRAILER" not in out and b"<script>" not in out
    assert rec.sha256.hex() == hashlib.sha256(img("JPEG") + payload).hexdigest()


def test_16bit_png_and_palette_gif_are_converted(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    rec, _ = files.store(db, ctx, img("PNG", mode="I;16", color=40000), "sedá.png")
    assert rec.kind == "photo"
    rec2, _ = files.store(db, ctx, img("GIF", mode="L", color=100), "gif.gif")
    assert rec2.kind == "photo"


def test_animated_gif_uses_first_frame(db: Session, ctx: ActorContext, files_dir: Path) -> None:
    frames = [Image.new("RGB", (30, 20), c) for c in ((255, 0, 0), (0, 0, 255))]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:])
    rec, _ = files.store(db, ctx, buf.getvalue(), "anim.gif")
    pixel = stored_image(rec).convert("RGB").getpixel((5, 5))
    assert isinstance(pixel, tuple) and pixel[0] > 200 and pixel[2] < 80


def test_filename_is_sanitised_and_never_used_in_paths(
    db: Session, ctx: ActorContext, files_dir: Path, tmp_path: Path
) -> None:
    for evil in ("../../evil.jpg", "..\\..\\evil2.jpg", "/etc/passwd.jpg", "a\x00b\nc.jpg"):
        rec, _ = files.store(db, ctx, img(size=(30 + len(evil), 30)), evil)
        assert "/" not in (rec.original_name or "") and "\\" not in (rec.original_name or "")
        assert (rec.original_name or "").isprintable()
        assert files.main_path(rec).is_relative_to(files_dir)
    # nic mimo kořen úložiště nevzniklo
    outside = [p for p in tmp_path.rglob("*") if p.is_file() and not p.is_relative_to(files_dir)]
    assert outside == []
    assert files.safe_filename("..") is None and files.safe_filename("   ") is None
    assert files.safe_filename("x" * 500) == "x" * 200

    rec.storage_path = "../../uniklo.jpg"  # i otrávený záznam z DB se musí zastavit
    with pytest.raises(DomainError):
        files.main_path(rec)


# --- zpracování obrázku -------------------------------------------------------------------


def test_exif_orientation_applied(db: Session, ctx: ActorContext, files_dir: Path) -> None:
    rec, _ = files.store(db, ctx, jpeg_with_exif(size=(80, 60), orientation=6), "a.jpg")
    assert (rec.width, rec.height) == (60, 80)
    out = stored_image(rec)
    assert out.size == (60, 80) and 0x0112 not in out.getexif()


def test_gps_stripped_by_default_and_metadata_whitelisted(
    db: Session, ctx: ActorContext, user: Any, files_dir: Path
) -> None:
    data = jpeg_with_exif(gps=True)
    assert b"Exif" in data
    rec, _ = files.store(db, ctx, data, "a.jpg")
    raw = stored_bytes(rec)
    assert b"Exif" not in raw and b"TestCam" not in raw  # žádné EXIF ve výstupu
    assert not stored_image(rec).getexif().get_ifd(0x8825)
    assert rec.exif is not None and "gps" not in rec.exif
    assert rec.exif["make"] == "TestCam" and rec.exif["iso"] == 200
    assert rec.exif["exposure_time"] == 0.01
    # čas pořízení v zóně uživatele (Europe/Prague, v květnu UTC+2)
    assert rec.taken_at is not None
    assert rec.taken_at.astimezone(UTC) == datetime(2023, 5, 4, 8, 20, 30, tzinfo=UTC)


def test_gps_kept_in_metadata_only_when_setting_allows(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    set_setting(db, ctx, "photos.strip_gps", False)
    rec, _ = files.store(db, ctx, jpeg_with_exif(gps=True), "a.jpg")
    assert rec.exif is not None
    assert rec.exif["gps"] == {
        "lat": pytest.approx(50.091667, abs=1e-5),
        "lon": pytest.approx(14.416667, abs=1e-5),
    }
    assert b"Exif" not in stored_bytes(rec)  # do souboru samotného se GPS nikdy nevrací


def test_bogus_exif_date_ignored(db: Session, ctx: ActorContext, files_dir: Path) -> None:
    rec, _ = files.store(db, ctx, jpeg_with_exif(taken="0000:00:00 00:00:00"), "a.jpg")
    assert rec.taken_at is None
    rec2, _ = files.store(
        db, ctx, jpeg_with_exif(taken="1970:01:01 00:00:00", size=(81, 60)), "b.jpg"
    )
    assert rec2.taken_at is None


def test_resize_to_max_dimension_and_quality(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    set_setting(db, ctx, "photos.max_dimension", 512)
    data = img("JPEG", size=(1600, 1000))
    rec, _ = files.store(db, ctx, data, "velka.jpg")
    assert (rec.width, rec.height) == (512, 320)
    assert max(Image.open(files.thumb_path(rec, 1024)).size) == 512  # zvětšovat se nebude
    assert max(Image.open(files.thumb_path(rec, 256)).size) == 256
    assert rec.size_bytes == len(stored_bytes(rec))


def test_opaque_alpha_png_becomes_jpeg(db: Session, ctx: ActorContext, files_dir: Path) -> None:
    rec, _ = files.store(db, ctx, img("PNG", mode="RGBA", color=(1, 2, 3, 255)), "a.png")
    assert rec.mime == "image/jpeg"


def test_keep_original_option(db: Session, ctx: ActorContext, files_dir: Path) -> None:
    data = img("JPEG", size=(70, 50))
    rec, _ = files.store(db, ctx, data, "a.jpg")
    assert not (files_dir / "originals").exists()
    set_setting(db, ctx, "photos.keep_original", True)
    rec2, _ = files.store(db, ctx, img("JPEG", size=(71, 50)), "b.jpg")
    orig = files_dir / "originals" / rec2.sha256.hex()[:2] / f"{rec2.sha256.hex()}.bin"
    assert orig.is_file() and Image.open(orig).size == (71, 50)
    assert rec.id != rec2.id


def test_blurhash_matches_solid_colour() -> None:
    value = imaging.blurhash_encode(Image.new("RGB", (40, 30), (255, 0, 0)), 4, 3)
    assert len(value) == 6 + 2 * 11 and value[0] == "L"
    # DC složka (znaky 2–5) odpovídá červené 0xFF0000 → 0xFF0000 v base83
    dc = 0
    for ch in value[2:6]:
        dc = dc * 83 + imaging._B83.index(ch)
    assert dc == 0xFF0000
    assert imaging.blurhash_encode(Image.new("RGB", (8, 8)), 1, 1)  # i bez AC složek


def test_missing_thumbnails_are_regenerated(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    rec, _ = files.store(db, ctx, img("JPEG", size=(900, 600)), "a.jpg")
    files.thumb_path(rec, 256).unlink()
    files.thumb_path(rec, 1024).unlink()
    assert files.ensure_thumbs(db, rec) is True
    assert files.thumb_path(rec, 256).is_file() and files.thumb_path(rec, 1024).is_file()
    assert files.ensure_thumbs(db, rec) is False
    with pytest.raises(ValidationFailed):
        files.thumb_path(rec, 300)


# --- deduplikace --------------------------------------------------------------------------


def test_dedupe_by_sha256_of_uploaded_bytes(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    data = photo(1)
    first, created1 = files.store(db, ctx, data, "a.jpg")
    again, created2 = files.store(db, ctx, data, "uplne-jiny-nazev.jpg")
    assert created1 and not created2 and again.id == first.id
    assert first.original_name == "a.jpg"
    assert db.execute(select(FileRecord)).scalars().all() == [first]
    assert len([p for p in files_dir.rglob("*") if p.is_file()]) == 3  # soubor + 2 náhledy
    other, created3 = files.store(db, ctx, photo(2), "b.jpg")
    assert created3 and other.id != first.id


def test_duplicate_upload_to_same_item_is_idempotent(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    item = new_item(db, ctx)
    r1 = files.upload(db, ctx, photo(1), "a.jpg", item_id=item.id)
    r2 = files.upload(db, ctx, photo(1), "a.jpg", item_id=item.id)
    assert r1.created and not r2.created and r1.link is not None and r2.link is not None
    assert r2.link.id == r1.link.id
    assert db.execute(select(FileLink)).scalars().all() == [r1.link]


# --- vazby, primární fotka -----------------------------------------------------------------


def roles(db: Session, item_id: Any) -> list[tuple[str, bool]]:
    return [(x.role, x.is_primary) for x in files.list_for_item(db, item_id)]


def test_first_photo_becomes_primary_and_item_mirrors_it(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    item = new_item(db, ctx)
    v0 = item.version
    r1 = files.upload(db, ctx, photo(1), "1.jpg", item_id=item.id, caption="  zepředu ")
    assert r1.link is not None and r1.link.role == "primary" and r1.link.caption == "zepředu"
    db.refresh(item)
    assert item.primary_file_id == r1.file.id and item.version > v0

    r2 = files.upload(db, ctx, photo(2), "2.jpg", item_id=item.id)
    assert r2.link is not None and r2.link.role == "gallery" and r2.link.sort_order == 1
    db.refresh(item)
    assert item.primary_file_id == r1.file.id
    assert items.get_item_out(db, item.id).file_count == 2


def test_documents_and_special_roles_are_not_primary(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    item = new_item(db, ctx)
    doc = files.upload(db, ctx, pdf_bytes(), "zaruka.pdf", item_id=item.id, role="warranty")
    receipt = files.upload(db, ctx, photo(1), "uctenka.jpg", item_id=item.id, role="receipt")
    assert doc.link is not None and receipt.link is not None
    db.refresh(item)
    assert item.primary_file_id is None  # ani PDF, ani účtenka nejsou „hlavní fotka“
    with pytest.raises(ValidationFailed, match="jen fotka"):
        files.set_primary(db, ctx, doc.link.id)
    with pytest.raises(ValidationFailed, match="jen fotka"):
        files.upload(db, ctx, pdf_bytes(b"x"), "b.pdf", item_id=item.id, role="primary")
    with pytest.raises(ValidationFailed, match="Neznámá role"):
        files.upload(db, ctx, photo(2), "x.jpg", item_id=item.id, role="bogus")

    gallery = files.upload(db, ctx, photo(3), "3.jpg", item_id=item.id)
    db.refresh(item)
    assert item.primary_file_id == gallery.file.id  # první „obyčejná“ fotka
    assert doc.link.role == "warranty" and doc.link.caption is None


def test_set_primary_swaps_and_detach_reelects(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    item = new_item(db, ctx)
    links = [files.upload(db, ctx, photo(n), f"{n}.jpg", item_id=item.id).link for n in (1, 2, 3)]
    a, b, c = (x for x in links if x is not None)

    files.set_primary(db, ctx, c.id)
    db.refresh(item)
    assert item.primary_file_id == c.file_id
    assert [x.role for x in (a, b, c)] == ["gallery", "gallery", "primary"]
    assert roles(db, item.id)[0] == ("primary", True)  # primární je ve výpisu první

    files.detach(db, ctx, c.id)  # odpojení primární → další v pořadí
    db.refresh(item)
    assert item.primary_file_id == a.file_id and a.role == "primary"

    files.detach(db, ctx, b.id)
    files.detach(db, ctx, a.id)  # poslední fotka → žádná primární
    db.refresh(item)
    assert item.primary_file_id is None
    assert files.list_for_item(db, item.id) == []
    assert db.get(FileRecord, a.file_id) is not None  # soubory zůstávají v úložišti


def test_demote_primary_hands_over_but_sole_photo_stays_primary(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    item = new_item(db, ctx)
    a = files.upload(db, ctx, photo(1), "1.jpg", item_id=item.id).link
    assert a is not None
    files.update_link(db, ctx, a.id, {"is_primary": False})
    assert a.role == "primary"  # jediná fotka

    b = files.upload(db, ctx, photo(2), "2.jpg", item_id=item.id).link
    assert b is not None
    files.update_link(db, ctx, a.id, {"is_primary": False})
    db.refresh(item)
    assert (a.role, b.role) == ("gallery", "primary") and item.primary_file_id == b.file_id

    files.update_link(db, ctx, b.id, {"role": "receipt"})  # změna role primární fotky
    db.refresh(item)
    assert (a.role, b.role) == ("primary", "receipt") and item.primary_file_id == a.file_id

    files.update_link(db, ctx, a.id, {"role": "other", "caption": "  nový  ", "sort_order": 7})
    db.refresh(item)
    assert item.primary_file_id is None and a.caption == "nový" and a.sort_order == 7


def test_reorder_and_target_validation(db: Session, ctx: ActorContext, files_dir: Path) -> None:
    item = new_item(db, ctx)
    ls = [files.upload(db, ctx, photo(n), f"{n}.jpg", item_id=item.id).link for n in (1, 2, 3)]
    a, b, c = (x for x in ls if x is not None)
    files.reorder(db, ctx, [c.id, b.id], item_id=item.id)
    assert [x.id for x in files.list_for_item(db, item.id)] == [a.id, c.id, b.id]  # primární první
    assert (c.sort_order, b.sort_order, a.sort_order) == (0, 1, 2)

    other = new_item(db, ctx, "Jiná")
    with pytest.raises(ValidationFailed):
        files.reorder(db, ctx, [a.id], item_id=other.id)
    with pytest.raises(ValidationFailed, match="duplicity"):
        files.reorder(db, ctx, [a.id, a.id], item_id=item.id)

    fid = a.file_id
    with pytest.raises(ValidationFailed, match="právě jedno"):
        files.attach(db, ctx, fid)
    with pytest.raises(ValidationFailed, match="právě jedno"):
        files.attach(db, ctx, fid, item_id=item.id, location_id=other.id)
    with pytest.raises(NotFound):
        files.attach(db, ctx, fid, item_id=uuid.uuid4())
    items.delete_item(db, ctx, other.id)
    with pytest.raises(NotFound):
        files.attach(db, ctx, fid, item_id=other.id)
    with pytest.raises(NotFound):
        files.upload(db, ctx, photo(9), "9.jpg", item_id=other.id)
    assert db.execute(select(FileRecord).where(FileRecord.original_name == "9.jpg")).first() is None


def test_location_files_and_shared_photo(db: Session, ctx: ActorContext, files_dir: Path) -> None:
    loc = locations.create_location(db, ctx, LocationCreate(name="Police B2"))
    item = new_item(db, ctx)
    res = files.upload(db, ctx, photo(1), "police.jpg", location_id=loc.id)
    assert res.link is not None and res.link.role == "primary" and res.link.location_id == loc.id
    files.attach(db, ctx, res.file.id, item_id=item.id)  # tentýž soubor u věci i umístění
    listed = files.list_for_location(db, loc.id)
    assert [x.file.id for x in listed] == [res.file.id] and listed[0].is_primary
    assert listed[0].file.thumb_256_url == f"/api/v1/files/{res.file.id}/thumb?size=256"
    assert files.list_for_item(db, item.id)[0].file.id == res.file.id
    with pytest.raises(NotFound):
        files.list_for_location(db, item.id)


# --- mazání -------------------------------------------------------------------------------


def test_delete_file_blocked_while_linked_then_forced(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    item = new_item(db, ctx)
    a = files.upload(db, ctx, photo(1), "1.jpg", item_id=item.id)
    b = files.upload(db, ctx, photo(2), "2.jpg", item_id=item.id)
    disk = [p for p in files_dir.rglob("*") if p.is_file()]
    with pytest.raises(Conflict, match="připojen"):
        files.delete_file(db, ctx, a.file.id)
    assert files.main_path(a.file).is_file()

    path = files.main_path(a.file)
    thumbs = [files.thumb_path(a.file, s) for s in (256, 1024)]
    files.delete_file(db, ctx, a.file.id, detach_links=True)
    db.refresh(item)
    assert item.primary_file_id == b.file.id  # primární přeurčena na zbývající fotku
    assert path.is_file()  # z disku se maže až po commitu
    assert files.run_pending_deletes(db) >= 3
    assert not path.exists() and not any(t.exists() for t in thumbs)
    assert len([p for p in files_dir.rglob("*") if p.is_file()]) == len(disk) - 3
    assert files.main_path(b.file).is_file()
    assert files.run_pending_deletes(db) == 0
    with pytest.raises(NotFound):
        files.get_file(db, a.file.id)


def test_unlinked_file_deleted_without_force_and_reupload_survives(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    data = photo(1)
    rec, _ = files.store(db, ctx, data, "a.jpg")
    files.delete_file(db, ctx, rec.id)
    again, created = files.store(db, ctx, data, "a.jpg")  # nový záznam se stejným hashem
    assert created and again.id != rec.id
    files.run_pending_deletes(db)  # soubory patří novému záznamu → nesmí zmizet
    assert files.main_path(again).is_file() and files.thumb_path(again, 256).is_file()


def test_gc_orphans_keeps_linked_and_recent_files(
    db: Session, ctx: ActorContext, files_dir: Path
) -> None:
    item = new_item(db, ctx)
    linked = files.upload(db, ctx, photo(1), "1.jpg", item_id=item.id)
    orphan = files.upload(db, ctx, photo(2), "2.jpg").file
    assert files.gc_orphans(db, ctx, older_than=timedelta(days=1)) == 0  # čerstvé zůstanou
    assert files.gc_orphans(db, ctx, older_than=timedelta(seconds=-1)) == 1
    files.run_pending_deletes(db)
    assert not files.main_path(orphan).exists()
    assert files.main_path(linked.file).is_file()


# --- audit a události ---------------------------------------------------------------------


def test_audit_and_outbox_record_file_changes(
    db: Session, ctx: ActorContext, user: Any, files_dir: Path
) -> None:
    item = new_item(db, ctx)
    res = files.upload(db, ctx, photo(1), "1.jpg", item_id=item.id)
    assert res.link is not None
    files.detach(db, ctx, res.link.id)
    audit = (
        db.execute(select(AuditLog).where(AuditLog.entity_type.in_(["files", "file_links"])))
        .scalars()
        .all()
    )
    assert {(a.entity_type, a.action) for a in audit} >= {
        ("files", "insert"),
        ("file_links", "insert"),
        ("file_links", "delete"),
    }
    assert all(a.actor_id == user.id and a.source == "ui" for a in audit)
    events = [
        e.event_type for e in db.execute(select(EventOutbox).order_by(EventOutbox.id)).scalars()
    ]
    assert {"file.uploaded", "file.linked", "file.unlinked", "item.updated"} <= set(events)


# --- HTTP API -----------------------------------------------------------------------------


@pytest.fixture
def anon(clean_db: None, files_dir: Path) -> Iterator[TestClient]:
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


def up(client: TestClient, data: bytes, name: str = "foto.jpg", **form: str) -> Any:
    return client.post(
        "/api/v1/files", files={"file": (name, data, "application/octet-stream")}, data=form
    )


def test_api_upload_download_and_thumbs(client: TestClient, files_dir: Path) -> None:
    data = img("PNG", size=(1200, 800))
    r = up(client, data, "../../ukázka.png")
    body = ok(r, 201)
    assert body["duplicate"] is False and body["link"] is None
    f = body["file"]
    assert f["kind"] == "photo" and f["mime"] == "image/jpeg" and f["original_name"] == "ukázka.png"
    assert f["url"] == f"/api/v1/files/{f['id']}" and f["thumbs_ready"] and f["blurhash"]
    assert r.headers["Location"] == f["url"]

    orig = client.get(f["url"])
    assert orig.status_code == 200 and orig.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(orig.content)).size == (1200, 800)
    h = orig.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["cache-control"].startswith("private, max-age=")
    assert h["content-disposition"].startswith("inline")
    assert "sandbox" in h["content-security-policy"]
    assert h["etag"] == f'"{hashlib.sha256(data).hexdigest()}"'

    cached = client.get(f["url"], headers={"If-None-Match": h["etag"]})
    assert cached.status_code == 304 and cached.content == b""
    assert client.get(f["url"], headers={"Range": "bytes=0-9"}).status_code == 206

    for size, limit in ((None, 256), (256, 256), (1024, 1024)):
        t = client.get(f["url"] + "/thumb", params={"size": size} if size else None)
        assert t.status_code == 200 and t.headers["content-type"] == "image/webp"
        assert t.headers["x-content-type-options"] == "nosniff" and "etag" in t.headers
        im = Image.open(io.BytesIO(t.content))
        assert im.format == "WEBP" and max(im.size) == limit
    assert client.get(f["url"] + "/thumb", params={"size": 300}).status_code == 422
    assert client.get(f"/api/v1/files/{'0' * 8}-0000-0000-0000-{'0' * 12}").status_code == 404

    # chybějící náhled se dogeneruje při prvním čtení
    for p in (files_dir / "thumbs").iterdir():
        p.unlink()
    assert client.get(f["url"] + "/thumb", params={"size": 1024}).status_code == 200


def test_api_pdf_is_served_as_attachment_without_thumb(client: TestClient) -> None:
    data = pdf_bytes()
    body = ok(up(client, data, "Návod k obsluze.pdf"), 201)["file"]
    assert body["kind"] == "document" and body["thumb_256_url"] is None
    r = client.get(body["url"])
    assert r.content == data and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in r.headers["content-security-policy"]
    inline = client.get(body["url"], params={"download": "false"})
    assert inline.headers["content-disposition"].startswith("inline")
    assert client.get(body["url"] + "/thumb").status_code == 404


def test_api_rejects_fake_corrupt_and_oversized(client: TestClient) -> None:
    r = up(client, b"<svg onload=alert(1)></svg>", "obrazek.jpg")
    assert r.status_code == 422 and r.headers["content-type"].startswith("application/problem+json")
    assert "Nepodporovaný typ" in r.json()["detail"]
    assert up(client, b"\xff\xd8\xff" + b"\x00" * 100, "a.jpg").status_code == 422
    assert up(client, bomb_png(), "b.png").status_code == 422
    assert up(client, b"", "c.jpg").status_code == 422
    assert client.post("/api/v1/files").status_code == 422  # chybí soubor
    assert up(client, img(), "x.jpg", role="bogus").status_code == 422

    ok(
        client.put("/api/v1/settings/photos.max_upload_mb", json={"value": 1, "scope": "global"}),
        204,
    )
    r = up(client, b"\xff\xd8\xff" + b"\x00" * (1024 * 1024 + 10), "velky.jpg")
    assert r.status_code == 413 and "limit 1 MB" in r.json()["detail"]
    assert ok(client.get("/api/v1/items"))["total"] == 0


def test_api_item_files_primary_reorder_and_delete(client: TestClient, files_dir: Path) -> None:
    item = ok(client.post("/api/v1/items", json={"name": "Vrtačka"}), 201)
    assert item["file_count"] == 0 and item["primary_file_id"] is None

    first = ok(up(client, photo(1), "1.jpg", item_id=item["id"], caption="Zepředu"), 201)
    second = ok(up(client, photo(2), "2.jpg", item_id=item["id"]), 201)
    third = ok(up(client, pdf_bytes(), "navod.pdf", item_id=item["id"], role="manual"), 201)
    assert first["link"]["is_primary"] and not second["link"]["is_primary"]
    assert third["link"]["role"] == "manual"

    detail = ok(client.get(f"/api/v1/items/{item['id']}"))
    assert detail["primary_file_id"] == first["file"]["id"] and detail["file_count"] == 3
    assert ok(client.get("/api/v1/items"))["items"][0]["file_count"] == 3

    listed = ok(client.get(f"/api/v1/items/{item['id']}/files"))
    assert [x["id"] for x in listed] == [
        first["link"]["id"],
        second["link"]["id"],
        third["link"]["id"],
    ]
    assert listed[0]["caption"] == "Zepředu" and listed[0]["file"]["thumb_256_url"]

    patched = ok(
        client.patch(f"/api/v1/file-links/{second['link']['id']}", json={"is_primary": True})
    )
    assert patched["is_primary"] and patched["role"] == "primary"
    detail = ok(client.get(f"/api/v1/items/{item['id']}"))
    assert detail["primary_file_id"] == second["file"]["id"]
    ok(
        client.patch(
            f"/api/v1/file-links/{third['link']['id']}", json={"caption": "Manuál", "role": "other"}
        )
    )
    bad = client.patch(f"/api/v1/file-links/{third['link']['id']}", json={"is_primary": True})
    assert bad.status_code == 422

    order = [third["link"]["id"], first["link"]["id"]]
    reordered = ok(client.put(f"/api/v1/items/{item['id']}/files/order", json={"link_ids": order}))
    assert [x["id"] for x in reordered][:3] == [second["link"]["id"], *order]

    # odpojení nesmaže soubor; smazání připojeného souboru vyžaduje force
    ok(client.delete(f"/api/v1/file-links/{third['link']['id']}"), 204)
    assert client.get(third["file"]["url"]).status_code == 200
    assert client.delete(f"/api/v1/files/{first['file']['id']}").status_code == 409
    ok(client.delete(f"/api/v1/files/{first['file']['id']}", params={"force": "true"}), 204)
    assert client.get(first["file"]["url"]).status_code == 404
    assert not any(p.name.startswith(first["file"]["id"]) for p in files_dir.rglob("*"))
    assert [x["id"] for x in ok(client.get(f"/api/v1/items/{item['id']}/files"))] == [
        second["link"]["id"]
    ]

    # duplicitní nahrání téhož souboru
    dup = ok(up(client, photo(2), "znovu.jpg", item_id=item["id"]), 200)
    assert dup["duplicate"] is True and dup["file"]["id"] == second["file"]["id"]
    assert dup["link"]["id"] == second["link"]["id"]

    assert client.get(f"/api/v1/items/{'1' * 8}-1111-1111-1111-{'1' * 12}/files").status_code == 404
    assert (
        up(client, photo(5), "x.jpg", item_id="1" * 8 + "-1111-1111-1111-" + "1" * 12).status_code
        == 404
    )
    assert (
        up(client, photo(6), "y.jpg", item_id=item["id"], location_id=item["id"]).status_code == 422
    )


def test_api_location_files(client: TestClient) -> None:
    loc = ok(client.post("/api/v1/locations", json={"name": "Police B2"}), 201)
    body = ok(up(client, photo(1), "police.jpg", location_id=loc["id"]), 201)
    listed = ok(client.get(f"/api/v1/locations/{loc['id']}/files"))
    assert listed[0]["location_id"] == loc["id"] and listed[0]["is_primary"]
    ok(
        client.put(
            f"/api/v1/locations/{loc['id']}/files/order", json={"link_ids": [listed[0]["id"]]}
        )
    )
    ok(client.delete(f"/api/v1/file-links/{body['link']['id']}"), 204)
    assert ok(client.get(f"/api/v1/locations/{loc['id']}/files")) == []


def test_api_batch_upload(client: TestClient) -> None:
    item = ok(client.post("/api/v1/items", json={"name": "Krabice"}), 201)
    ok(up(client, photo(1), "dup.jpg"), 201)
    files_payload = [
        ("files", ("1.jpg", photo(1), "image/jpeg")),  # duplicita
        ("files", ("2.jpg", photo(2), "image/jpeg")),
        ("files", ("falesny.jpg", b"<html></html>", "image/jpeg")),
        ("files", ("3.png", img("PNG", size=(50, 50)), "image/png")),
    ]
    r = ok(client.post("/api/v1/files/batch", files=files_payload, data={"item_id": item["id"]}))
    assert (r["ok"], r["failed"]) == (3, 1)
    flags = [
        (x["filename"], x["ok"], x["upload"] and x["upload"]["duplicate"]) for x in r["results"]
    ]
    assert flags == [
        ("1.jpg", True, True),
        ("2.jpg", True, False),
        ("falesny.jpg", False, None),
        ("3.png", True, False),
    ]
    assert "Nepodporovaný typ" in r["results"][2]["error"]
    assert ok(client.get(f"/api/v1/items/{item['id']}"))["file_count"] == 3

    ok(
        client.put("/api/v1/settings/photos.max_batch_files", json={"value": 2, "scope": "global"}),
        204,
    )
    too_many = client.post("/api/v1/files/batch", files=files_payload)
    assert too_many.status_code == 422


def test_api_permissions_and_tokens(client: TestClient) -> None:
    csrf = client.headers["X-CSRF-Token"]
    item = ok(client.post("/api/v1/items", json={"name": "Věc"}), 201)
    stored = ok(up(client, photo(1), "a.jpg", item_id=item["id"]), 201)
    link_id, file_url = stored["link"]["id"], stored["file"]["url"]

    ok(
        client.post(
            "/api/v1/users", json={"username": "viewer", "password": PASSWORD, "role": "viewer"}
        ),
        201,
    )
    ok(
        client.post(
            "/api/v1/users", json={"username": "clen", "password": PASSWORD, "role": "member"}
        ),
        201,
    )
    with TestClient(app) as v:  # viewer čte, ale nezapisuje
        me = ok(v.post("/api/v1/auth/login", json={"username": "viewer", "password": PASSWORD}))
        h = {"X-CSRF-Token": me["csrf_token"]}
        assert v.get(file_url, headers=h).status_code == 200
        assert v.get(file_url + "/thumb", headers=h).status_code == 200
        assert v.get(f"/api/v1/items/{item['id']}/files").status_code == 200
        assert up_with(v, photo(3), h).status_code == 403
        assert (
            v.post(
                "/api/v1/files/batch",
                files=[("files", ("a.jpg", photo(3), "image/jpeg"))],
                headers=h,
            ).status_code
            == 403
        )
        assert (
            v.patch(f"/api/v1/file-links/{link_id}", json={"caption": "x"}, headers=h).status_code
            == 403
        )
        assert v.delete(f"/api/v1/file-links/{link_id}", headers=h).status_code == 403
        assert v.delete(stored["file"]["url"], headers=h).status_code == 403
    with TestClient(app) as m:  # člen může psát, ale potřebuje CSRF token
        me = ok(m.post("/api/v1/auth/login", json={"username": "clen", "password": PASSWORD}))
        assert up_with(m, photo(4), {}).status_code == 403
        assert up_with(m, photo(4), {"X-CSRF-Token": me["csrf_token"]}).status_code == 201

    read_tok = ok(client.post("/api/v1/tokens", json={"name": "ro", "scopes": ["items:read"]}), 201)
    write_tok = ok(
        client.post("/api/v1/tokens", json={"name": "rw", "scopes": ["items:read", "files:write"]}),
        201,
    )
    with TestClient(app) as api:  # jen Bearer, bez cookie
        ro = {"Authorization": f"Bearer {read_tok['token']}"}
        assert api.get(file_url, headers=ro).status_code == 200
        assert api.get(file_url + "/thumb", headers=ro).status_code == 200
        assert up_with(api, photo(7), ro).status_code == 403
        assert api.delete(f"/api/v1/file-links/{link_id}", headers=ro).status_code == 403
        rw = {"Authorization": f"Bearer {write_tok['token']}"}
        res = up_with(api, photo(7), rw, item_id=item["id"])
        assert res.status_code == 201, res.text
        assert (
            api.delete(f"/api/v1/file-links/{res.json()['link']['id']}", headers=rw).status_code
            == 204
        )
        assert up_with(api, photo(8), {"Authorization": "Bearer dmv_bad"}).status_code == 401

    anon = TestClient(app)
    assert anon.get(file_url).status_code == 401
    assert anon.get(file_url + "/thumb").status_code == 401
    assert (
        anon.post("/api/v1/files", files={"file": ("a.jpg", photo(1), "image/jpeg")}).status_code
        == 401
    )
    assert csrf


def up_with(c: TestClient, data: bytes, headers: dict[str, str], **form: str) -> Any:
    return c.post(
        "/api/v1/files", files={"file": ("a.jpg", data, "image/jpeg")}, data=form, headers=headers
    )


def test_api_audit_shows_file_actions(client: TestClient) -> None:
    item = ok(client.post("/api/v1/items", json={"name": "Věc"}), 201)
    stored = ok(up(client, photo(1), "a.jpg", item_id=item["id"]), 201)
    audit = ok(client.get("/api/v1/audit", params={"entity_type": "file_links"}))
    assert audit and audit[0]["entity_id"] == stored["link"]["id"] and audit[0]["source"] == "ui"


def test_openapi_documents_file_endpoints(anon: TestClient) -> None:
    paths = ok(anon.get("/openapi.json"))["paths"]
    for path in (
        "/api/v1/files",
        "/api/v1/files/batch",
        "/api/v1/files/{file_id}",
        "/api/v1/files/{file_id}/thumb",
        "/api/v1/items/{item_id}/files",
        "/api/v1/locations/{location_id}/files",
        "/api/v1/file-links/{link_id}",
    ):
        assert path in paths, path
    assert "multipart/form-data" in paths["/api/v1/files"]["post"]["requestBody"]["content"]
