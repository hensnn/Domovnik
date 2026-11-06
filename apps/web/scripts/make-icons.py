"""Vygeneruje ikony PWA (public/icons/*.png). Spuštění z apps/api: `uv run python ../web/scripts/make-icons.py`.

Jednoduchý znak: bílý domek s krabicí na zeleném podkladu (barva značky). Ikona „maskable“
má plnou barvu až do okrajů a znak uvnitř bezpečné zóny (60 %).
"""

from pathlib import Path

from PIL import Image, ImageDraw

BRAND = (15, 138, 102)  # #0f8a66
OUT = Path(__file__).resolve().parent.parent / "public" / "icons"
SS = 4  # supersampling pro hladké hrany


def mark(draw: ImageDraw.ImageDraw, size: int, scale: float) -> None:
    """Domek (střecha + stěny) s krabicí uvnitř; `scale` = podíl plochy, který znak zabírá."""
    c = size / 2
    u = size * scale / 100  # jednotka: 1 % šířky znaku
    white = (255, 255, 255)
    # střecha
    draw.polygon(
        [(c - 48 * u, c - 4 * u), (c, c - 46 * u), (c + 48 * u, c - 4 * u),
         (c + 40 * u, c - 4 * u), (c, c - 38 * u), (c - 40 * u, c - 4 * u)],
        fill=white,
    )
    # stěny
    draw.rectangle([c - 36 * u, c - 6 * u, c - 28 * u, c + 42 * u], fill=white)
    draw.rectangle([c + 28 * u, c - 6 * u, c + 36 * u, c + 42 * u], fill=white)
    draw.rectangle([c - 36 * u, c + 36 * u, c + 36 * u, c + 42 * u], fill=white)
    # krabice uvnitř
    draw.rectangle([c - 16 * u, c + 8 * u, c + 16 * u, c + 36 * u], fill=white)
    draw.rectangle([c - 20 * u, c + 2 * u, c + 20 * u, c + 10 * u], fill=white)
    draw.rectangle([c - 3 * u, c + 16 * u, c + 3 * u, c + 22 * u], fill=BRAND)


def make(size: int, *, maskable: bool, rounded: bool) -> Image.Image:
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle([0, 0, big - 1, big - 1], radius=big // 5, fill=BRAND)
    else:
        d.rectangle([0, 0, big - 1, big - 1], fill=BRAND)
    mark(d, big, 0.36 if maskable else 0.50)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    make(192, maskable=False, rounded=True).save(OUT / "icon-192.png")
    make(512, maskable=False, rounded=True).save(OUT / "icon-512.png")
    make(512, maskable=True, rounded=False).save(OUT / "maskable-512.png")
    make(180, maskable=False, rounded=False).convert("RGB").save(OUT / "apple-touch-icon.png")
    make(48, maskable=False, rounded=True).save(OUT / "favicon-48.png")


if __name__ == "__main__":
    main()
