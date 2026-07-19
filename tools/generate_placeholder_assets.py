from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def make_star(size: int = 22, color: tuple[int, int, int] = (255, 215, 0)) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size // 2
    pts = []
    for i in range(10):
        a = -90 + i * 36
        r = size // 2 if i % 2 == 0 else size // 4
        pts.append((cx + math.cos(math.radians(a)) * r, cy + math.sin(math.radians(a)) * r))
    draw.polygon(pts, fill=(*color, 255))
    return img


def make_badge(w: int = 74, h: int = 28) -> Image.Image:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, w - 1, h - 1),
        radius=10,
        fill=(12, 14, 22, 230),
        outline=(160, 170, 190, 180),
        width=1,
    )
    return img


def make_frame() -> Image.Image:
    w, h = 401, 555
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((2, 2, w - 3, h - 3), radius=22, outline=(150, 158, 175, 200), width=4)
    draw.rounded_rectangle((7, 7, w - 8, h - 8), radius=18, outline=(200, 210, 230, 70), width=2)
    draw.rounded_rectangle((10, 10, w - 11, h - 11), radius=16, outline=(30, 35, 48, 50), width=1)
    return img


def main() -> None:
    (ASSETS / "frames").mkdir(parents=True, exist_ok=True)
    (ASSETS / "stars").mkdir(parents=True, exist_ok=True)
    (ASSETS / "badges").mkdir(parents=True, exist_ok=True)
    make_frame().save(ASSETS / "frames" / "base.png")
    make_star().save(ASSETS / "stars" / "star.png")
    make_badge().save(ASSETS / "badges" / "badge.png")
    print("Placeholder assets created in assets/frames, assets/stars, assets/badges.")


if __name__ == "__main__":
    main()
