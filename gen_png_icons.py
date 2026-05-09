#!/usr/bin/env python3
"""
gen_png_icons.py — Generate raster PNG versions of the headphones app icon.

Some Android Chrome versions need a PNG manifest icon (not just SVG) to
treat the page as a rich media app for lockscreen media notifications and
background-audio decisions. This script produces icons/headphones-192.png
and icons/headphones-512.png from the same shape as icons/headphones.svg.

Both 'any' and 'maskable' purposes are emitted: the maskable variant has
the headphones glyph centered inside the safe inner ~80% so Android can
crop the icon to a circle/squircle without clipping content.

Run:  python gen_png_icons.py
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "icons"
OUT.mkdir(exist_ok=True)

AMBER = (251, 191, 36, 255)   # --accent
INK   = (26, 16, 4, 255)      # --accent-ink


def draw_headphones(img: Image.Image, *, scale_box: float = 1.0) -> None:
    """Draw the headphones glyph onto img, scaled to fit a 192-unit canvas
    multiplied by `scale_box`. The icon is composed within the inner area;
    the surrounding bg is assumed already drawn."""
    draw = ImageDraw.Draw(img, "RGBA")
    W, _ = img.size
    s = (W / 192.0) * scale_box
    cx, cy = W / 2, W / 2  # we recenter inside maskable safe area
    # Original SVG coords assume 192x192. Compute offsets so the glyph
    # is centered at (cx, cy) — useful for the maskable variant where
    # we shrink scale_box and want the glyph still middle of canvas.
    ox = cx - 96 * s
    oy = cy - 96 * s
    # Headband arc: spans 180°→360° (top half) inside box (44,64)-(148,168)
    arc_box = (
        ox + 44 * s, oy + 64 * s,
        ox + 148 * s, oy + 168 * s,
    )
    draw.arc(arc_box, start=180, end=360, fill=INK, width=max(1, round(6 * s)))
    # Left cup: rect (36,104) 22x42 with rx 8
    draw.rounded_rectangle(
        (ox + 36 * s, oy + 104 * s, ox + (36 + 22) * s, oy + (104 + 42) * s),
        radius=max(1, round(8 * s)),
        fill=INK,
    )
    # Right cup: rect (134,104) 22x42 with rx 8
    draw.rounded_rectangle(
        (ox + 134 * s, oy + 104 * s, ox + (134 + 22) * s, oy + (104 + 42) * s),
        radius=max(1, round(8 * s)),
        fill=INK,
    )


def make_any(size: int) -> Image.Image:
    """Standard purpose='any' icon: amber rounded square + headphones glyph."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    rx = round(40 * size / 192)
    draw.rounded_rectangle((0, 0, size, size), rx, fill=AMBER)
    draw_headphones(img)
    return img


def make_maskable(size: int) -> Image.Image:
    """purpose='maskable' icon: full-bleed amber background (no rounded
    corners — the OS applies the mask) and the glyph at ~75% so it stays
    inside the safe area when the icon is cropped to a circle/squircle."""
    img = Image.new("RGBA", (size, size), AMBER)
    draw_headphones(img, scale_box=0.78)
    return img


def main() -> None:
    targets = [
        (OUT / "headphones-192.png",          192, make_any),
        (OUT / "headphones-512.png",          512, make_any),
        (OUT / "headphones-maskable-192.png", 192, make_maskable),
        (OUT / "headphones-maskable-512.png", 512, make_maskable),
    ]
    for path, size, fn in targets:
        img = fn(size)
        img.save(path, optimize=True)
        print(f"  wrote {path.relative_to(OUT.parent)}  ({size}x{size})")
    print(f"Done. {len(targets)} PNGs in {OUT.relative_to(OUT.parent)}/")


if __name__ == "__main__":
    main()
