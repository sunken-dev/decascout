#!/usr/bin/env python3
"""Render assets/og-image.png (1200x630) with Pillow. Requires macOS system fonts."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SCALE = 2
W, H = 1200 * SCALE, 630 * SCALE
FONT = "/System/Library/Fonts/HelveticaNeue.ttc"
BLUE, DARK, PALE, SOFT = "#3643ba", "#28339f", "#e8ebff", "#cbd2ff"
INK, MUTED, GREEN = "#101828", "#5d6678", "#0a7d45"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size * SCALE, index=1 if bold else 0)


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, **kwargs) -> None:
    draw.rounded_rectangle([v * SCALE for v in box], radius=radius * SCALE, **kwargs)


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, size: int, fill: str, bold: bool = False, anchor: str = "la") -> None:
    draw.text((xy[0] * SCALE, xy[1] * SCALE), value, font=font(size, bold), fill=fill, anchor=anchor)


def main() -> None:
    image = Image.new("RGB", (W, H), BLUE)
    draw = ImageDraw.Draw(image)

    # soft decorative circles
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.ellipse([v * SCALE for v in (700, -260, 1360, 400)], fill=(255, 255, 255, 18))
    odraw.ellipse([v * SCALE for v in (-200, 380, 360, 940)], fill=(0, 0, 0, 28))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)

    # brand mark + name
    rounded(draw, (72, 64, 128, 120), 14, fill="white")
    cx, cy = 100 * SCALE, 92 * SCALE
    draw.ellipse([cx - 17 * SCALE, cy - 17 * SCALE, cx + 17 * SCALE, cy + 17 * SCALE], outline=BLUE, width=3 * SCALE)
    star = [(0, -18), (4, -4), (18, 0), (4, 4), (0, 18), (-4, 4), (-18, 0), (-4, -4)]
    draw.polygon([(cx + x * SCALE, cy + y * SCALE) for x, y in star], fill=BLUE)
    draw.ellipse([cx - 4 * SCALE, cy - 4 * SCALE, cx + 4 * SCALE, cy + 4 * SCALE], fill="white")
    text(draw, (148, 76), "DecaScout", 40, "white", bold=True)

    # headline
    text(draw, (72, 204), "Same gear.", 70, "white", bold=True)
    text(draw, (72, 286), "Different price.", 70, "white", bold=True)
    text(draw, (72, 392), "Compare Decathlon prices across", 27, SOFT)
    text(draw, (72, 430), "countries and buy in the cheapest market.", 27, SOFT)
    rounded(draw, (72, 508, 392, 560), 26, fill="white")
    text(draw, (232, 534), "decascout.sunken.dev", 24, BLUE, bold=True, anchor="mm")

    # comparison card
    rounded(draw, (660, 80, 1128, 550), 28, fill="white")
    text(draw, (696, 112), "TREKKING BACKPACK 50L", 18, MUTED, bold=True)
    text(draw, (696, 144), "Price by country shop", 30, INK, bold=True)
    rows = [("Poland", "€ 62.40", False), ("Czechia", "€ 64.90", False), ("Germany", "€ 69.99", False), ("France", "€ 74.99", False)]
    # Poland is the cheapest, France the most expensive; bar width scales with price
    top = 226
    for index, (country, price, _) in enumerate(rows):
        y = top + index * 60
        cheapest = index == 0
        if cheapest:
            rounded(draw, (680, y - 8, 1108, y + 46), 14, fill=PALE)
        text(draw, (700, y + 19), country, 24, INK, bold=cheapest, anchor="lm")
        text(draw, (1088, y + 19), price, 26, GREEN if cheapest else INK, bold=True, anchor="rm")
    rounded(draw, (696, 484, 850, 522), 19, fill=GREEN)
    text(draw, (773, 503), "Save 17%", 20, "white", bold=True, anchor="mm")
    text(draw, (870, 503), "vs. most expensive", 18, MUTED, anchor="lm")

    out = ROOT / "assets" / "og-image.png"
    out.parent.mkdir(exist_ok=True)
    image.resize((1200, 630), Image.LANCZOS).save(out, optimize=True)
    print(out)


if __name__ == "__main__":
    main()
