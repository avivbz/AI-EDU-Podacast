#!/usr/bin/env python3
"""
Generate cover.jpg for the podcast.

Apple Podcasts requires square artwork between 1400x1400 and 3000x3000 px.
This produces a 1500x1500 JPEG that mirrors the project's cover design:
a navy background, a small node graph, an open book, and the title
"AI IN EDUCATION PUBLICATIONS".

Run:  python make_cover.py
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont

SIZE = 1500
NAVY = (20, 36, 61)
CREAM = (242, 236, 224)
ORANGE = (224, 138, 60)
TEAL = (46, 139, 139)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        return ImageFont.load_default()


def draw_node(draw: ImageDraw.ImageDraw, x: int, y: int, r: int,
              fill: tuple[int, int, int]) -> None:
    draw.ellipse([x - r, y - r, x + r, y + r], fill=fill,
                 outline=CREAM, width=6)


def main() -> None:
    img = Image.new("RGB", (SIZE, SIZE), NAVY)
    draw = ImageDraw.Draw(img)

    # Thin cream border.
    margin = 60
    draw.rectangle([margin, margin, SIZE - margin, SIZE - margin],
                   outline=CREAM, width=6)

    cx = SIZE // 2

    # --- Node graph ---------------------------------------------------------
    r = 34
    top_y = 300
    mid_y = 400
    center_x = cx
    apex_top = (center_x, top_y)
    apex_bottom = (center_x, 470)
    left_far = (center_x - 300, top_y)
    right_far = (center_x + 300, top_y)
    left_mid = (center_x - 165, mid_y)
    right_mid = (center_x + 165, mid_y)

    edges = [
        (left_far, left_mid), (left_mid, apex_top), (left_mid, apex_bottom),
        (apex_top, apex_bottom), (apex_top, right_mid), (right_mid, apex_bottom),
        (right_mid, right_far),
    ]
    for a, b in edges:
        draw.line([a, b], fill=TEAL, width=8)

    # Line from bottom node down to the book.
    draw.line([apex_bottom, (center_x, 620)], fill=CREAM, width=6)

    draw_node(draw, *left_far, r, TEAL)
    draw_node(draw, *right_far, r, TEAL)
    draw_node(draw, *left_mid, r, TEAL)
    draw_node(draw, *right_mid, r, TEAL)
    draw_node(draw, *apex_top, r + 4, ORANGE)
    draw_node(draw, *apex_bottom, r + 4, ORANGE)

    # --- Open book ----------------------------------------------------------
    by = 640
    bh = 200
    spine = (center_x, by + 20)
    left_pts = [(center_x - 320, by + 40), spine,
                (center_x, by + bh), (center_x - 320, by + bh - 10)]
    right_pts = [spine, (center_x + 320, by + 40),
                 (center_x + 320, by + bh - 10), (center_x, by + bh)]
    draw.line(left_pts + [left_pts[0]], fill=CREAM, width=8, joint="curve")
    draw.line(right_pts + [right_pts[0]], fill=CREAM, width=8, joint="curve")
    for i in range(4):
        yy = by + 80 + i * 22
        draw.line([(center_x - 250, yy + 20), (center_x - 30, yy)],
                  fill=CREAM, width=4)
        draw.line([(center_x + 30, yy), (center_x + 250, yy + 20)],
                  fill=CREAM, width=4)

    # --- Title text ---------------------------------------------------------
    def centered(text: str, y: int, font: ImageFont.FreeTypeFont,
                 fill: tuple[int, int, int]) -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        draw.text((cx - w / 2, y), text, font=font, fill=fill)

    big = load_font(150)
    centered("AI IN", 980, big, CREAM)
    centered("EDUCATION", 1140, big, CREAM)
    centered("PUBLICATIONS", 1300, big, ORANGE)

    img.save("cover.jpg", "JPEG", quality=90)
    print(f"Wrote cover.jpg ({SIZE}x{SIZE})")


if __name__ == "__main__":
    main()
