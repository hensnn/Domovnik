"""Vykreslení štítků do PDF (A4, mřížka buněk, QR kód + čitelný text).

Čistě vykreslovací vrstva bez přístupu do databáze. QR kód obsahuje pouze ``label_code``
(např. ``I-000123``); skener ho přes ``GET /api/v1/resolve`` převede na věc / umístění.
Český text zajišťuje vložený font DejaVu Sans Condensed (``assets/fonts``).
"""

from __future__ import annotations

import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from domovnik.errors import ValidationFailed

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT = "DomovnikSans"
FONT_BOLD = "DomovnikSans-Bold"


@dataclass(frozen=True)
class PageFormat:
    key: str
    cols: int
    rows: int

    @property
    def per_page(self) -> int:
        return self.cols * self.rows


FORMATS: dict[str, PageFormat] = {
    f.key: f
    for f in (
        PageFormat("A4_3x8", 3, 8),  # 70 × 37 mm
        PageFormat("A4_2x5", 2, 5),  # 105 × 59 mm (velké štítky na krabice)
        PageFormat("A4_4x12", 4, 12),  # 52,5 × 25 mm (malé štítky)
    )
}


@dataclass(frozen=True)
class LabelData:
    code: str  # text v QR i pod ním
    name: str
    path: str | None = None  # kde štítek patří / kde věc je


_fonts_ready = False


def _register_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return
    pdfmetrics.registerFont(TTFont(FONT, str(FONTS_DIR / "DejaVuSansCondensed.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONTS_DIR / "DejaVuSansCondensed-Bold.ttf")))
    _fonts_ready = True


def get_format(key: str) -> PageFormat:
    fmt = FORMATS.get(key)
    if fmt is None:
        raise ValidationFailed(f"Neznámý formát archu „{key}“.", choices=sorted(FORMATS))
    return fmt


def page_count(count: int, fmt: PageFormat, start: int = 0) -> int:
    return max(1, math.ceil((start + count) / fmt.per_page))


def wrap_text(text: str, font: str, size: float, width: float, max_lines: int) -> list[str]:
    """Zalomí text na řádky o dané šířce; přebytek ukončí výpustkou."""
    measure = pdfmetrics.stringWidth
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        # příliš dlouhé slovo rozděl po znacích
        while measure(word, font, size) > width and len(word) > 1:
            cut = len(word) - 1
            while cut > 1 and measure(word[:cut], font, size) > width:
                cut -= 1
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:cut])
            word = word[cut:]
        trial = f"{current} {word}".strip()
        if measure(trial, font, size) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and measure(last + "…", font, size) > width:
            last = last[:-1].rstrip()
        lines[-1] = last + "…"
    return lines


def _draw_qr(c: Canvas, data: str, x: float, y: float, size: float) -> None:
    widget = QrCodeWidget(data, barLevel="M", barBorder=1)
    x0, y0, x1, y1 = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, c, x, y)


def _draw_label(
    c: Canvas, label: LabelData, x: float, y: float, w: float, h: float, *, show_path: bool
) -> None:
    """Vykreslí jeden štítek do obdélníku (x, y = levý dolní roh)."""
    scale = h / 105.0  # 3×8 (výška 37 mm) = 1
    pad = max(3.0, 5.0 * scale)
    fs_code = max(5.5, 7.5 * scale)
    fs_name = min(max(7.0, 10.5 * scale), 16.0)
    fs_path = max(5.5, 7.0 * scale)

    qr = min(h - 2 * pad - fs_code * 1.5, w * 0.42)
    qx, qy = x + pad, y + h - pad - qr
    _draw_qr(c, label.code, qx, qy, qr)
    c.setFillColor(black)
    c.setFont(FONT_BOLD, fs_code)
    c.drawCentredString(qx + qr / 2, qy - fs_code * 1.15, label.code)

    tx = qx + qr + pad
    tw = x + w - pad - tx
    top = y + h - pad
    name_lines = wrap_text(label.name, FONT_BOLD, fs_name, tw, 3 if h > 90 else 2)
    c.setFont(FONT_BOLD, fs_name)
    cursor = top - fs_name * 0.85
    for line in name_lines:
        c.drawString(tx, cursor, line)
        cursor -= fs_name * 1.15
    if show_path and label.path:
        cursor -= fs_path * 0.3
        c.setFillColor(Color(0.3, 0.3, 0.3))
        c.setFont(FONT, fs_path)
        for line in wrap_text(label.path, FONT, fs_path, tw, 3 if h > 90 else 2):
            if cursor < y + pad:
                break
            c.drawString(tx, cursor, line)
            cursor -= fs_path * 1.2
        c.setFillColor(black)


def render_labels_pdf(
    labels: Sequence[LabelData],
    fmt: str | PageFormat,
    *,
    start: int = 0,
    show_path: bool = True,
    guides: bool = True,
) -> bytes:
    """Vyrobí PDF s archy A4; první štítek začíná v buňce ``start`` (0-based)."""
    page_fmt = get_format(fmt) if isinstance(fmt, str) else fmt
    if not labels:
        raise ValidationFailed("Není co tisknout – vyber alespoň jednu položku.")
    if not 0 <= start < page_fmt.per_page:
        raise ValidationFailed(
            f"Počáteční buňka musí být 0 až {page_fmt.per_page - 1}.", per_page=page_fmt.per_page
        )
    _register_fonts()

    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4, pageCompression=1)
    c.setTitle("Štítky – Domovník")
    c.setAuthor("Domovník")
    page_w, page_h = A4
    cw, ch = page_w / page_fmt.cols, page_h / page_fmt.rows

    for index, label in enumerate(labels):
        slot = start + index
        pos = slot % page_fmt.per_page
        if index > 0 and pos == 0:
            c.showPage()
        row, col = divmod(pos, page_fmt.cols)
        x, y = col * cw, page_h - (row + 1) * ch
        if guides:
            c.setStrokeColor(Color(0.8, 0.8, 0.8))
            c.setLineWidth(0.3)
            c.rect(x, y, cw, ch)
        _draw_label(c, label, x, y, cw, ch, show_path=show_path)
    c.showPage()
    c.save()
    return buf.getvalue()
