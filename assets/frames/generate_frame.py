"""Regenerate assets/frames/base.png — a premium metallic card frame.

The frame is a *border-only* transparent overlay: the renderer draws artwork
covered by nothing but this rim, then adds the bottom gradient, rarity stars,
badge, and text programmatically. Do not bake stars, badges, or gradients into
this file — they are rarity-dependent and get tinted at render time.

Geometry contract (must stay in sync with assets/frames/base.json and
CardRenderer's corner mask):

* Outer edge is a rounded rect flush with the canvas (0, 0, 400, 554),
  corner radius 22 — identical to the final alpha mask the renderer applies.
* The metal band is 8px wide, so the inner edge is inset 8px with radius 14.
  Classic artwork is clipped inside exactly that box (viewport inset 8,
  clip_radius 14), so art tucks seamlessly under the rim.
* Rendered at 4x and downscaled for anti-aliased edges.
"""

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

FINAL_W, FINAL_H = 401, 555
S = 4  # supersampling factor
W, H = FINAL_W * S, FINAL_H * S
R_OUT = 22 * S
BAND = 8 * S

GEM_CENTER = 9.9 * S  # corner-gem distance from each edge
GEM_RADIUS = 3.2 * S


def _rounded_fill(bbox: tuple[int, int, int, int], radius: int) -> Image.Image:
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(bbox, radius=radius, fill=255)
    return mask


def _ring_mask(bbox: tuple[int, int, int, int], radius: int, width: int) -> Image.Image:
    """Mask of a rounded-rect stroke extending `width` inward from `bbox`."""
    outer = _rounded_fill(bbox, radius)
    left, top, right, bottom = bbox
    inner = _rounded_fill(
        (left + width, top + width, right - width, bottom - width),
        max(0, radius - width),
    )
    return ImageChops.subtract(outer, inner)


def _alpha_ramp(
    top_alpha: int, bottom_alpha: int, top_end: float, bottom_start: float
) -> Image.Image:
    """Vertical alpha image: `top_alpha` until `top_end`*H, `bottom_alpha` after
    `bottom_start`*H, linear between."""
    ramp = Image.new("L", (W, H), 0)
    draw = ImageDraw.Draw(ramp)
    y_a = int(H * top_end)
    y_b = int(H * bottom_start)
    for y in range(H):
        if y <= y_a:
            a = top_alpha
        elif y >= y_b:
            a = bottom_alpha
        else:
            p = (y - y_a) / max(1, y_b - y_a)
            a = int(top_alpha + (bottom_alpha - top_alpha) * p)
        draw.line((0, y, W, y), fill=a)
    return ramp


def _metallic_sweep(band_mask: Image.Image) -> Image.Image:
    """Brushed-silver sweep around the card: gleams on the top-left and
    bottom-right diagonals, dark troughs opposite — so every edge shows
    metal contrast instead of a flat gray band."""
    dark = (60, 65, 79)
    bright = (238, 242, 250)
    img = Image.new("RGB", (W, H))
    px = img.load()
    mask_px = band_mask.load()
    assert px is not None and mask_px is not None
    cx, cy = W / 2.0, H / 2.0
    for y in range(H):
        for x in range(W):
            if not mask_px[x, y]:
                continue
            theta = math.atan2(y - cy, x - cx)
            t = 0.5 + 0.5 * math.sin(2.0 * theta - math.pi / 4.0)
            t = t ** 0.75
            px[x, y] = tuple(int(d + (b - d) * t) for d, b in zip(dark, bright, strict=True))
    return img


def _gem_tile(radius: int) -> Image.Image:
    """A silver bezel gem with radial shading and a glint, sized 2*radius px."""
    ss = 6
    ts = radius * 2 * ss
    c = (ts - 1) / 2
    tile = Image.new("RGBA", (ts, ts), (0, 0, 0, 0))
    def _ramp(c0: tuple[int, int, int], c1: tuple[int, int, int], p: float) -> tuple[int, int, int]:
        return tuple(int(a + (b - a) * p) for a, b in zip(c0, c1, strict=True))

    pixels = []
    for yy in range(ts):
        for xx in range(ts):
            d = min(1.0, (((xx - c) ** 2 + (yy - c) ** 2) ** 0.5) / (ts / 2))
            if d <= 1.0:
                if d < 0.55:
                    col = _ramp((252, 254, 255), (205, 214, 230), d / 0.55)
                else:
                    col = _ramp((205, 214, 230), (112, 120, 140), (d - 0.55) / 0.45)
                alpha = 255 if d < 0.97 else int(255 * (1 - d) / 0.03)
                pixels.append((*col, min(255, max(0, alpha))))
            else:
                pixels.append((0, 0, 0, 0))
    tile.putdata(pixels)
    # glint dot, upper-left
    glint = Image.new("RGBA", (ts, ts), (0, 0, 0, 0))
    gr = ts * 0.10
    gx, gy = c - ts * 0.16, c - ts * 0.16
    ImageDraw.Draw(glint).ellipse((gx - gr, gy - gr, gx + gr, gy + gr), fill=(255, 255, 255, 235))
    tile.alpha_composite(glint)
    return tile.resize((radius * 2, radius * 2), Image.Resampling.LANCZOS)


def main() -> None:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    outer_bbox = (0, 0, W - 1, H - 1)
    inner_bbox = (BAND, BAND, W - 1 - BAND, H - 1 - BAND)

    # --- metal band -----------------------------------------------------
    band = _ring_mask(outer_bbox, R_OUT, BAND)
    canvas.paste(_metallic_sweep(band).convert("RGBA"), (0, 0), band)

    # dark outer lip for separation on any chat background
    lip = _ring_mask(outer_bbox, R_OUT, S)
    canvas.paste(Image.new("RGBA", (W, H), (15, 18, 25, 255)), (0, 0), lip)

    # top sheen sweeping the upper band, fading by ~38% of the height
    sheen_zone = _ring_mask(outer_bbox, R_OUT, 2 * S)
    sheen = ImageChops.multiply(sheen_zone, _alpha_ramp(70, 0, 0.0, 0.38))
    canvas.paste(Image.new("RGBA", (W, H), (255, 255, 255, 255)), (0, 0), sheen)

    # bottom outer shade for depth
    shade = ImageChops.multiply(sheen_zone, _alpha_ramp(0, 110, 0.55, 1.0))
    canvas.paste(Image.new("RGBA", (W, H), (10, 12, 18, 255)), (0, 0), shade)

    # --- bevels on the inner edge ---------------------------------------
    # carves a "raised" look: bright catch-light along the top, shadow below
    carve = S  # 1px
    top_zone = _ring_mask(
        (BAND - carve, BAND - carve, W - 1 - BAND + carve, H - 1 - BAND + carve),
        R_OUT - BAND + carve,
        carve,
    )
    top_light = ImageChops.multiply(top_zone, _alpha_ramp(150, 0, 0.0, 0.40))
    canvas.paste(Image.new("RGBA", (W, H), (255, 255, 255, 255)), (0, 0), top_light)

    bottom_zone = _ring_mask(
        (BAND - carve, BAND - carve, W - 1 - BAND + carve, H - 1 - BAND + carve),
        R_OUT - BAND + carve,
        carve,
    )
    bottom_dark = ImageChops.multiply(bottom_zone, _alpha_ramp(0, 100, 0.60, 1.0))
    canvas.paste(Image.new("RGBA", (W, H), (10, 12, 18, 255)), (0, 0), bottom_dark)

    # --- ambient shadow where artwork meets the rim ---------------------
    shade_w = int(3.5 * S)
    ambient = ImageChops.subtract(
        _rounded_fill(inner_bbox, R_OUT - BAND),
        _rounded_fill(
            (BAND + shade_w, BAND + shade_w, W - 1 - BAND - shade_w, H - 1 - BAND - shade_w),
            max(0, R_OUT - BAND - shade_w),
        ),
    )
    canvas.paste(Image.new("RGBA", (W, H), (6, 9, 16, 40)), (0, 0), ambient)

    # --- corner gems -----------------------------------------------------
    gem = _gem_tile(int(GEM_RADIUS))
    ring_w = max(1, S // 2)
    for cx in (GEM_CENTER, W - GEM_CENTER):
        for cy in (GEM_CENTER, H - GEM_CENTER):
            x, y = int(cx - GEM_RADIUS), int(cy - GEM_RADIUS)
            # dark bezel ring under the gem
            ImageDraw.Draw(canvas).ellipse(
                (
                    cx - GEM_RADIUS - ring_w,
                    cy - GEM_RADIUS - ring_w,
                    cx + GEM_RADIUS + ring_w,
                    cy + GEM_RADIUS + ring_w,
                ),
                fill=(12, 15, 22, 210),
            )
            canvas.alpha_composite(gem, (x, y))

    final = canvas.resize((FINAL_W, FINAL_H), Image.Resampling.LANCZOS)
    out = Path(__file__).parent / "base.png"
    final.save(out)
    print(f"Generated {out.name} (metallic band, beveled edges, corner gems)")


if __name__ == "__main__":
    main()
