"""Rozpoznání typu souboru podle obsahu a bezpečné zpracování obrázků (bez přístupu k DB).

Zásady (viz CLAUDE.md, pravidlo 11):

* typ určuje **obsah** (magic bytes + dekodér), nikdy přípona ani ``Content-Type`` od klienta,
* každý obrázek se **dekóduje a znovu zakóduje** – tím zmizí vše skryté (připojená data za
  koncem JPEG, polyglot soubory, vložené EXIF/XMP/ICC bloby, komentáře),
* před dekódováním se z hlavičky zkontroluje počet pixelů (ochrana proti „decompression bomb“),
* GPS souřadnice se z výstupu odstraňují vždy; do metadat (``files.exif``) se dostanou jen
  pokud je ``photos.strip_gps`` vypnuto. Výstupní soubor žádné EXIF neobsahuje –
  užitečná metadata (datum, fotoaparát…) žijí jen v DB v bezpečné bílé listině.
"""

from __future__ import annotations

import io
import math
import re
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Literal

import pillow_heif
from PIL import Image, ImageCms, ImageOps

from domovnik.errors import ValidationFailed

pillow_heif.register_heif_opener()  # HEIC/HEIF čtení i zápis (testy)
# Varování Pillow o „bombě“ nahrazujeme vlastní kontrolou velikosti z hlavičky (viz _process).
warnings.filterwarnings("ignore", category=Image.DecompressionBombWarning)

Kind = Literal["jpeg", "png", "gif", "webp", "heif", "pdf"]
IMAGE_KINDS: tuple[Kind, ...] = ("jpeg", "png", "gif", "webp", "heif")
THUMB_SIZES: tuple[int, ...] = (256, 1024)
THUMB_QUALITY = 80

_PIL_FORMAT: dict[str, str] = {
    "jpeg": "JPEG",
    "png": "PNG",
    "gif": "GIF",
    "webp": "WEBP",
    "heif": "HEIF",
}
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"heif"}


def sniff(data: bytes) -> Kind | None:
    """Rozpozná typ podle magic bytes. Neznámý obsah (SVG, HTML, ZIP, EXE…) vrací None."""
    head = data[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS:
        return "heif"
    if head.startswith(b"%PDF-"):
        return "pdf"
    return None


def validate_pdf(data: bytes) -> None:
    """Základní kontrola PDF (hlavička a konec souboru). Obsah se neinterpretuje ani nemění."""
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
        raise ValidationFailed("PDF je poškozené nebo neúplné (chybí konec souboru).")


@dataclass
class ProcessedImage:
    data: bytes
    mime: str
    ext: str
    width: int
    height: int
    thumbs: dict[int, bytes]
    blurhash: str | None
    exif: dict[str, Any] = field(default_factory=dict)
    taken_at: datetime | None = None  # bez tzinfo = místní čas fotoaparátu (zónu doplní volající)


def process_image(
    data: bytes,
    kind: Kind,
    *,
    max_dimension: int,
    quality: int,
    strip_gps: bool,
    max_pixels: int,
) -> ProcessedImage:
    """Zvaliduje, otočí dle EXIF, zmenší, znovu zakóduje a vytvoří náhledy + blurhash."""
    # Druhá obranná linie: Pillow samo odmítne obrázky nad 2× tento limit už při otevření.
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        return _process(
            data,
            kind,
            max_dimension=max_dimension,
            quality=quality,
            strip_gps=strip_gps,
            max_pixels=max_pixels,
        )
    except ValidationFailed:
        raise
    except Image.DecompressionBombError as exc:
        raise ValidationFailed(
            f"Obrázek má příliš mnoho pixelů (limit {max_pixels / 1e6:.0f} Mpx)."
        ) from exc
    except Exception as exc:  # dekodéry vyhazují nejrůznější výjimky (OSError, ValueError, …)
        raise ValidationFailed("Obrázek je poškozený nebo ho nelze přečíst.") from exc


def _process(
    data: bytes,
    kind: Kind,
    *,
    max_dimension: int,
    quality: int,
    strip_gps: bool,
    max_pixels: int,
) -> ProcessedImage:
    opened = Image.open(io.BytesIO(data), formats=[_PIL_FORMAT[kind]])
    img: Image.Image = opened
    if img.format != _PIL_FORMAT[kind]:
        raise ValidationFailed("Obsah souboru neodpovídá rozpoznanému typu.")
    width, height = img.size
    if width <= 0 or height <= 0:
        raise ValidationFailed("Obrázek má neplatné rozměry.")
    if width * height > max_pixels:
        raise ValidationFailed(
            f"Obrázek je příliš velký ({width}×{height} px, limit {max_pixels / 1e6:.0f} Mpx)."
        )

    meta, taken_at = _read_exif(img, strip_gps=strip_gps)
    icc = img.info.get("icc_profile")
    img.load()
    img = ImageOps.exif_transpose(img)  # po otočení se příznak orientace odstraní

    has_alpha = img.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in img.info
    img = _convert(img, "RGBA" if has_alpha else "RGB")
    if has_alpha and img.getchannel("A").getextrema()[0] == 255:
        img = img.convert("RGB")  # alfa kanál je celý neprůhledný → JPEG
    if isinstance(icc, bytes) and icc:
        img = _to_srgb(img, icc)
    img.info = {}  # nic z původních metadat (EXIF, ICC, XMP, komentáře) se nesmí dostat do výstupu

    if max(img.size) > max_dimension:
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS, reducing_gap=2.0)

    buf = io.BytesIO()
    if img.mode == "RGBA":
        img.save(buf, format="WEBP", quality=quality, method=4)
        mime, ext = "image/webp", "webp"
    else:
        img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
        mime, ext = "image/jpeg", "jpg"

    thumbs: dict[int, bytes] = {}
    current = img
    for size in sorted(THUMB_SIZES, reverse=True):  # menší náhled se dělá z většího
        current = current.copy()
        current.thumbnail((size, size), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        current.save(out, format="WEBP", quality=THUMB_QUALITY, method=4)
        thumbs[size] = out.getvalue()

    w, h = img.size
    cx, cy = (4, 3) if w > h else (3, 4) if h > w else (4, 4)
    return ProcessedImage(
        data=buf.getvalue(),
        mime=mime,
        ext=ext,
        width=w,
        height=h,
        thumbs=thumbs,
        blurhash=blurhash_encode(current, cx, cy),
        exif=meta,
        taken_at=taken_at,
    )


def make_thumbnails(data: bytes) -> dict[int, bytes]:
    """Náhledy z již uloženého (zpracovaného) obrázku – pro doplnění chybějících náhledů."""
    img: Image.Image = Image.open(io.BytesIO(data))
    img.load()
    img = _convert(img, "RGBA" if img.mode == "RGBA" else "RGB")
    thumbs: dict[int, bytes] = {}
    current = img
    for size in sorted(THUMB_SIZES, reverse=True):
        current = current.copy()
        current.thumbnail((size, size), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        current.save(out, format="WEBP", quality=THUMB_QUALITY, method=4)
        thumbs[size] = out.getvalue()
    return thumbs


def _convert(img: Image.Image, mode: str) -> Image.Image:
    """Převod do RGB/RGBA včetně 16bitových režimů, které Pillow převádí jen oklikou."""
    if img.mode == mode:
        return img
    if img.mode.startswith("I;16") or img.mode in ("I", "F"):
        img = img.point(lambda v: v * (1 / 256)).convert("L")
    return img.convert(mode)


def _to_srgb(img: Image.Image, icc: bytes) -> Image.Image:
    """Převede barvy z vloženého ICC profilu do sRGB (profil se do výstupu nekopíruje)."""
    if len(icc) > 4_000_000:
        return img
    try:
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        if "srgb" in ImageCms.getProfileDescription(src).lower():
            return img
        dst = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
        out = ImageCms.profileToProfile(img, src, dst, outputMode=img.mode)
        return out if out is not None else img
    except Exception:  # vadný profil nesmí shodit nahrání – barvy zůstanou beze změny
        return img


# --- EXIF ---------------------------------------------------------------------------------

_TAG_MAKE, _TAG_MODEL = 0x010F, 0x0110
_IFD_EXIF, _IFD_GPS = 0x8769, 0x8825
_TAG_DATETIME_ORIGINAL, _TAG_OFFSET_TIME_ORIGINAL = 0x9003, 0x9011
_OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")


def _clean_str(value: Any) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "ignore")
    if not isinstance(value, str):
        return None
    cleaned = "".join(ch for ch in value if ch.isprintable()).strip()
    return cleaned[:100] or None


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return number if math.isfinite(number) else None


def _dms(values: Any, ref: Any, negative: str) -> float | None:
    try:
        deg, minutes, seconds = (float(v) for v in values)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    result = deg + minutes / 60 + seconds / 3600
    if not math.isfinite(result):
        return None
    return -result if _clean_str(ref) == negative else result


def _read_exif(img: Image.Image, *, strip_gps: bool) -> tuple[dict[str, Any], datetime | None]:
    """Bezpečná podmnožina EXIF (bílá listina) + čas pořízení. GPS jen při strip_gps=False."""
    try:
        exif = img.getexif()
        sub = exif.get_ifd(_IFD_EXIF)
        gps = exif.get_ifd(_IFD_GPS) if not strip_gps else {}
    except Exception:  # poškozený EXIF není důvod odmítnout fotku
        return {}, None

    meta: dict[str, Any] = {}
    for key, value in (
        ("make", _clean_str(exif.get(_TAG_MAKE))),
        ("model", _clean_str(exif.get(_TAG_MODEL))),
        ("lens_model", _clean_str(sub.get(0xA434))),
        ("exposure_time", _num(sub.get(0x829A))),
        ("f_number", _num(sub.get(0x829D))),
        ("focal_length", _num(sub.get(0x920A))),
    ):
        if value is not None:
            meta[key] = round(value, 6) if isinstance(value, float) else value
    iso = sub.get(0x8827)
    if isinstance(iso, tuple):
        iso = iso[0] if iso else None
    if (iso_num := _num(iso)) is not None:
        meta["iso"] = int(iso_num)

    if gps:
        lat = _dms(gps.get(2), gps.get(1), "S")
        lon = _dms(gps.get(4), gps.get(3), "W")
        if lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180:
            meta["gps"] = {"lat": round(lat, 6), "lon": round(lon, 6)}
            alt = _num(gps.get(6))
            if alt is not None:
                meta["gps"]["alt"] = round(-alt if gps.get(5) in (1, b"\x01") else alt, 1)

    return meta, _parse_taken_at(
        _clean_str(sub.get(_TAG_DATETIME_ORIGINAL)), _clean_str(sub.get(_TAG_OFFSET_TIME_ORIGINAL))
    )


def _parse_taken_at(raw: str | None, offset: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.strptime(raw[:19], "%Y:%m:%d %H:%M:%S")  # noqa: DTZ007
    except ValueError:
        return None
    if not 1990 <= parsed.year <= datetime.now(UTC).year + 1:
        return None  # nesmysl (např. výchozí datum fotoaparátu bez hodin)
    if offset and (m := _OFFSET_RE.match(offset)):
        delta = timedelta(hours=int(m[2]), minutes=int(m[3]))
        return parsed.replace(tzinfo=timezone(-delta if m[1] == "-" else delta))
    return parsed


# --- blurhash -----------------------------------------------------------------------------

_B83 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz#$%*+,-.:;=?@[]^_{|}~"
_SRGB_TO_LINEAR = [
    (v / 255 / 12.92) if v / 255 <= 0.04045 else ((v / 255 + 0.055) / 1.055) ** 2.4
    for v in range(256)
]


def _b83(value: int, length: int) -> str:
    return "".join(_B83[(value // 83 ** (length - i)) % 83] for i in range(1, length + 1))


def _linear_to_srgb(value: float) -> int:
    v = max(0.0, min(1.0, value))
    if v <= 0.0031308:
        return int(v * 12.92 * 255 + 0.5)
    return int((1.055 * v ** (1 / 2.4) - 0.055) * 255 + 0.5)


def _sign_pow(value: float, exp: float) -> float:
    return math.copysign(abs(value) ** exp, value)


def blurhash_encode(img: Image.Image, components_x: int = 4, components_y: int = 3) -> str:
    """Blurhash (https://blurha.sh) – krátký řetězec pro rozmazaný placeholder při načítání.

    Vlastní malá implementace (bez numpy); počítá se z obrázku zmenšeného na 32×32 px.
    """
    if img.mode == "RGBA":  # průhlednost podložit bílou
        base = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(base, img)
    small = img.convert("RGB").resize((32, 32), Image.Resampling.BOX)
    width = height = 32
    linear = [_SRGB_TO_LINEAR[b] for b in small.tobytes()]
    cos_x = [[math.cos(math.pi * i * x / width) for x in range(width)] for i in range(components_x)]
    cos_y = [
        [math.cos(math.pi * j * y / height) for y in range(height)] for j in range(components_y)
    ]

    factors: list[tuple[float, float, float]] = []
    for j in range(components_y):
        for i in range(components_x):
            r = g = b = 0.0
            for y in range(height):
                cy = cos_y[j][y]
                row = y * width * 3
                for x in range(width):
                    basis = cos_x[i][x] * cy
                    idx = row + x * 3
                    r += basis * linear[idx]
                    g += basis * linear[idx + 1]
                    b += basis * linear[idx + 2]
            scale = (1.0 if i == 0 and j == 0 else 2.0) / (width * height)
            factors.append((r * scale, g * scale, b * scale))

    dc, ac = factors[0], factors[1:]
    out = _b83((components_x - 1) + (components_y - 1) * 9, 1)
    if ac:
        actual_max = max(abs(c) for f in ac for c in f)
        quantised = max(0, min(82, math.floor(actual_max * 166 - 0.5)))
        max_value = (quantised + 1) / 166
        out += _b83(quantised, 1)
    else:
        max_value = 1.0
        out += _b83(0, 1)
    out += _b83(
        (_linear_to_srgb(dc[0]) << 16) + (_linear_to_srgb(dc[1]) << 8) + _linear_to_srgb(dc[2]), 4
    )

    def quant(v: float) -> int:
        return int(max(0, min(18, math.floor(_sign_pow(v / max_value, 0.5) * 9 + 9.5))))

    for r, g, b in ac:
        out += _b83(quant(r) * 19 * 19 + quant(g) * 19 + quant(b), 2)
    return out
