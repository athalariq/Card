"""Regenerate the frame assets under assets/frames/.

Renders at 4x and downscales for anti-aliased edges. Every frame is a
*border-only* transparent overlay: the renderer draws artwork covered by
nothing but these layers, never bake artwork or text into them.

Files produced:

* base.png — neutral silver frame, used as fallback layout "base".
* common.png / legendary.png — chunky per-rarity chrome frames (blue enamel
  for common, gold for legendary) with a baked badge window and a baked glass
  name plate, matching per-rarity common.json / legendary.json.
* common-emblem.png / legendary-emblem.png — the top-left rarity emblems
  (bursting stars / crown sparkle). They live in separate files so the
  renderer can composite them *above* hero-mode characters while the frame
  itself still sits behind.

Geometry contract (per-rarity frames, must stay in sync with
common.json/legendary.json and the renderer's corner mask):

* outer edge: rounded rect (0, 0, 400, 554), corner radius 26
* band: 18px wide (4px outer chrome lip, 10px enamel, 4px inner chrome lip)
* badge window: (269, 28)-(377, 72), glass interior (272, 31)-(374, 69)
* name plate: top edge y=440 (plate painted 436..545, band covers overflow)
* artwork viewport: (18, 18, 383, 537) with clip_radius 10
"""

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

FINAL_W, FINAL_H = 401, 555
S = 4  # supersampling factor
W, H = FINAL_W * S, FINAL_H * S

BaseRGB = tuple[int, int, int]

# --- base (fallback silver) geometry ---
BASE_R = 22 * S
BASE_BAND = 8 * S
GEM_CENTER = 9.9 * S
GEM_RADIUS = 3.2 * S

# --- per-rarity geometry ---
R_OUT = 26 * S
BAND = 18 * S
LIP = 4 * S
WINDOW = (261 * S, 28 * S, 377 * S, 72 * S)
WINDOW_R = 12 * S
GLASS = (264 * S, 31 * S, 374 * S, 69 * S)
PLATE = (24 * S, 436 * S, 377 * S, 545 * S)
PLATE_R = 12 * S

RARITY_PRESETS: dict[str, dict[str, BaseRGB]] = {
    "common": {
        "chrome_dark": (116, 138, 168),
        "chrome_bright": (244, 249, 255),
        "enamel_dark": (24, 42, 98),
        "enamel_bright": (112, 164, 244),
        "gloss": (200, 225, 255),
        "glass_top": (20, 28, 50),
        "glass_bottom": (9, 12, 24),
        "plate_top": (64, 102, 178),
        "plate_bottom": (16, 24, 48),
        "plate_line": (168, 204, 255),
    },
    "legendary": {
        "chrome_dark": (150, 112, 46),
        "chrome_bright": (255, 248, 222),
        "enamel_dark": (118, 74, 18),
        "enamel_bright": (255, 206, 108),
        "gloss": (255, 240, 200),
        "glass_top": (22, 26, 52),
        "glass_bottom": (8, 10, 22),
        "plate_top": (46, 50, 88),
        "plate_bottom": (10, 12, 28),
        "plate_line": (244, 208, 120),
    },
}


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
    """Vertical alpha image: `top_alpha` until `top_end`*H, `bottom_alpha`
    after `bottom_start`*H, linear between."""
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


def _angular_sweep(mask: Image.Image, dark: BaseRGB, bright: BaseRGB) -> Image.Image:
    """Metal sweep around the card: gleams on the top-left and bottom-right
    diagonals, dark troughs opposite — so every edge shows metal contrast."""
    img = Image.new("RGB", mask.size)
    px = img.load()
    mask_px = mask.load()
    assert px is not None and mask_px is not None
    w, h = mask.size
    cx, cy = w / 2.0, h / 2.0
    for y in range(h):
        for x in range(w):
            if not mask_px[x, y]:
                continue
            theta = math.atan2(y - cy, x - cx)
            t = (0.5 + 0.5 * math.sin(2.0 * theta - math.pi / 4.0)) ** 0.75
            px[x, y] = tuple(int(d + (b - d) * t) for d, b in zip(dark, bright, strict=True))
    return img


def _vertical_grad(width: int, height: int, top: BaseRGB, bottom: BaseRGB) -> Image.Image:
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        p = y / max(height - 1, 1)
        color = tuple(int(a + (b - a) * p) for a, b in zip(top, bottom, strict=True))
        draw.line((0, y, width, y), fill=color)
    return img


def _radial_fill(
    mask: Image.Image,
    inner: BaseRGB,
    outer: BaseRGB,
    center: tuple[float, float],
    max_dist: float,
) -> Image.Image:
    """Two-tone radial gradient clamped to `mask`'s luminance footprint; the
    gradient reaches `outer` at `max_dist` pixels from `center`."""
    img = Image.new("RGB", mask.size)
    px = img.load()
    mask_px = mask.load()
    assert px is not None and mask_px is not None
    cx, cy = center
    bbox = mask.getbbox() or (0, 0, mask.width, mask.height)
    for y in range(bbox[1], bbox[3]):
        for x in range(bbox[0], bbox[2]):
            if not mask_px[x, y]:
                continue
            d = min(1.0, math.hypot(x - cx, y - cy) / max_dist)
            px[x, y] = tuple(int(a + (b - a) * d) for a, b in zip(inner, outer, strict=True))
    return img


def _save(canvas: Image.Image, name: str) -> None:
    final = canvas.resize((FINAL_W, FINAL_H), Image.Resampling.LANCZOS)
    out = Path(__file__).parent / name
    final.save(out)
    print(f"Generated {name}")


# ---------------------------------------------------------------------------
# base.png — neutral silver frame (fallback)
# ---------------------------------------------------------------------------


def _gem_tile(radius: int) -> Image.Image:
    """A silver bezel gem with radial shading and a glint, sized 2*radius px."""
    ss = 6
    ts = radius * 2 * ss
    c = (ts - 1) / 2

    def _ramp(c0: BaseRGB, c1: BaseRGB, p: float) -> BaseRGB:
        return tuple(int(a + (b - a) * p) for a, b in zip(c0, c1, strict=True))

    tile = Image.new("RGBA", (ts, ts), (0, 0, 0, 0))
    pixels = []
    for yy in range(ts):
        for xx in range(ts):
            d = min(1.0, math.hypot(xx - c, yy - c) / (ts / 2))
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
    glint = Image.new("RGBA", (ts, ts), (0, 0, 0, 0))
    gr = ts * 0.10
    gx, gy = c - ts * 0.16, c - ts * 0.16
    ImageDraw.Draw(glint).ellipse((gx - gr, gy - gr, gx + gr, gy + gr), fill=(255, 255, 255, 235))
    tile.alpha_composite(glint)
    return tile.resize((radius * 2, radius * 2), Image.Resampling.LANCZOS)


def paint_base() -> None:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    outer_bbox = (0, 0, W - 1, H - 1)
    inner_bbox = (BASE_BAND, BASE_BAND, W - 1 - BASE_BAND, H - 1 - BASE_BAND)

    band = _ring_mask(outer_bbox, BASE_R, BASE_BAND)
    canvas.paste(_angular_sweep(band, (60, 65, 79), (238, 242, 250)).convert("RGBA"), (0, 0), band)

    # dark outer lip for separation on any chat background
    lip = _ring_mask(outer_bbox, BASE_R, S)
    canvas.paste(Image.new("RGBA", (W, H), (15, 18, 25, 255)), (0, 0), lip)

    # top sheen and bottom shade sweeping the band
    lip2 = _ring_mask(outer_bbox, BASE_R, 2 * S)
    sheen = ImageChops.multiply(lip2, _alpha_ramp(70, 0, 0.0, 0.38))
    canvas.paste(Image.new("RGBA", (W, H), (255, 255, 255, 255)), (0, 0), sheen)
    shade = ImageChops.multiply(lip2, _alpha_ramp(0, 110, 0.55, 1.0))
    canvas.paste(Image.new("RGBA", (W, H), (10, 12, 18, 255)), (0, 0), shade)

    # bevels on the inner edge: bright catch-light top, shadow below
    carve = S
    edge = (
        BASE_BAND - carve,
        BASE_BAND - carve,
        W - 1 - BASE_BAND + carve,
        H - 1 - BASE_BAND + carve,
    )
    zone = _ring_mask(edge, BASE_R - BASE_BAND + carve, carve)
    top_light = ImageChops.multiply(zone, _alpha_ramp(150, 0, 0.0, 0.40))
    canvas.paste(Image.new("RGBA", (W, H), (255, 255, 255, 255)), (0, 0), top_light)
    bottom_dark = ImageChops.multiply(zone, _alpha_ramp(0, 100, 0.60, 1.0))
    canvas.paste(Image.new("RGBA", (W, H), (10, 12, 18, 255)), (0, 0), bottom_dark)

    # ambient shadow where artwork meets the rim
    shade_w = int(3.5 * S)
    ambient = ImageChops.subtract(
        _rounded_fill(inner_bbox, BASE_R - BASE_BAND),
        _rounded_fill(
            (
                BASE_BAND + shade_w,
                BASE_BAND + shade_w,
                W - 1 - BASE_BAND - shade_w,
                H - 1 - BASE_BAND - shade_w,
            ),
            max(0, BASE_R - BASE_BAND - shade_w),
        ),
    )
    canvas.paste(Image.new("RGBA", (W, H), (6, 9, 16, 40)), (0, 0), ambient)

    # corner gems
    gem = _gem_tile(int(GEM_RADIUS))
    ring_w = max(1, S // 2)
    draw = ImageDraw.Draw(canvas)
    for cx in (GEM_CENTER, W - GEM_CENTER):
        for cy in (GEM_CENTER, H - GEM_CENTER):
            x, y = int(cx - GEM_RADIUS), int(cy - GEM_RADIUS)
            draw.ellipse(
                (
                    cx - GEM_RADIUS - ring_w,
                    cy - GEM_RADIUS - ring_w,
                    cx + GEM_RADIUS + ring_w,
                    cy + GEM_RADIUS + ring_w,
                ),
                fill=(12, 15, 22, 210),
            )
            canvas.alpha_composite(gem, (x, y))

    _save(canvas, "base.png")


# ---------------------------------------------------------------------------
# common.png / legendary.png — chunky per-rarity chrome frames
# ---------------------------------------------------------------------------


def _paint_glass_window(canvas: Image.Image, preset: dict[str, BaseRGB]) -> None:
    """The baked badge window: chrome border ring + navy glass interior."""
    left, top, right, bottom = WINDOW
    # soft drop shadow under the window
    shadow_mask = _rounded_fill((left + S, top + 2 * S, right + S, bottom + 2 * S), WINDOW_R)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", (W, H), (0, 0, 0, 90)), (0, 0), shadow_mask)
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(1.5 * S)))

    # chrome border
    ring = _ring_mask(WINDOW, WINDOW_R, 3 * S)
    metal = _angular_sweep(ring, preset["chrome_dark"], preset["chrome_bright"])
    canvas.paste(metal.convert("RGBA"), (0, 0), ring)

    # glass interior
    gl, gt, gr, gb = GLASS
    glass_mask = _rounded_fill(GLASS, WINDOW_R - 3 * S)
    glass = _vertical_grad(W, H, preset["glass_top"], preset["glass_bottom"])
    canvas.paste(glass.convert("RGBA"), (0, 0), glass_mask)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        GLASS, radius=WINDOW_R - 3 * S, outline=(4, 6, 12, 220), width=max(1, S // 2)
    )
    # glass catch-light across the top
    draw.line(
        (gl + 3 * S, gt + S, gr - 3 * S, gt + S), fill=(220, 235, 255, 70), width=max(1, S)
    )


def _paint_name_plate(canvas: Image.Image, preset: dict[str, BaseRGB]) -> None:
    """The baked glass name plate the renderer's name/series text sits on."""
    left, top, right, bottom = PLATE
    # soft shadow cast above the plate onto the artwork
    sh_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh_mask).rectangle((left + 2 * S, top - 3 * S, right - 2 * S, top), fill=100)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", (W, H), (0, 0, 0, 120)), (0, 0), sh_mask)
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(2 * S)))

    plate_mask = _rounded_fill(PLATE, PLATE_R)
    glass = _vertical_grad(W, H, preset["plate_top"], preset["plate_bottom"]).convert("RGBA")
    canvas.paste(glass, (0, 0), plate_mask)

    draw = ImageDraw.Draw(canvas)
    line = preset["plate_line"]
    draw.rounded_rectangle(
        (left + S, top + S, right - S, bottom - S),
        radius=PLATE_R - S,
        outline=(*line, 150),
        width=max(1, S),
    )
    draw.rounded_rectangle(
        (left + 3 * S, top + 3 * S, right - 3 * S, bottom - 3 * S),
        radius=PLATE_R - 3 * S,
        outline=(255, 255, 255, 36),
        width=max(1, S // 2),
    )
    draw.rounded_rectangle(PLATE, radius=PLATE_R, outline=(4, 6, 14, 200), width=max(1, S // 2))


def paint_rarity(name: str, preset: dict[str, BaseRGB]) -> None:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    outer_bbox = (0, 0, W - 1, H - 1)

    # name plate first: the band covers its side/bottom overflow
    _paint_name_plate(canvas, preset)
    _paint_glass_window(canvas, preset)

    # outer chrome lip (with a hairline dark edge for separation)
    ch_out = _ring_mask(outer_bbox, R_OUT, LIP)
    metal = _angular_sweep(ch_out, preset["chrome_dark"], preset["chrome_bright"])
    canvas.paste(metal.convert("RGBA"), (0, 0), ch_out)
    hairline = _ring_mask(outer_bbox, R_OUT, S)
    canvas.paste(Image.new("RGBA", (W, H), (12, 14, 20, 230)), (0, 0), hairline)

    # enamel band
    en_bbox = (LIP, LIP, W - 1 - LIP, H - 1 - LIP)
    enamel = _ring_mask(en_bbox, R_OUT - LIP, BAND - 2 * LIP)
    en = _angular_sweep(enamel, preset["enamel_dark"], preset["enamel_bright"])
    canvas.paste(en.convert("RGBA"), (0, 0), enamel)

    # glossy diagonal streak across the enamel (over chrome too, subtle)
    gloss_mask = _ring_mask(outer_bbox, R_OUT, BAND)
    streak = Image.new("L", (W, H), 0)
    ImageDraw.Draw(streak).polygon(
        [(0, 0), (int(W * 0.62), 0), (int(W * 0.10), H), (0, H)], fill=46
    )
    streak = streak.filter(ImageFilter.GaussianBlur(10 * S))
    gloss = ImageChops.multiply(gloss_mask, streak)
    canvas.paste(Image.new("RGBA", (W, H), (*preset["gloss"], 255)), (0, 0), gloss)

    # inner chrome lip
    ch_in_bbox = (BAND - LIP, BAND - LIP, W - 1 - BAND + LIP, H - 1 - BAND + LIP)
    ch_in = _ring_mask(ch_in_bbox, R_OUT - BAND + LIP, LIP)
    metal = _angular_sweep(ch_in, preset["chrome_dark"], preset["chrome_bright"])
    canvas.paste(metal.convert("RGBA"), (0, 0), ch_in)

    # bevel highlights on the lips
    top_light = ImageChops.multiply(ch_out, _alpha_ramp(120, 0, 0.0, 0.35))
    canvas.paste(Image.new("RGBA", (W, H), (255, 255, 255, 255)), (0, 0), top_light)

    # ambient shadow where artwork meets the rim
    inner_bbox = (BAND, BAND, W - 1 - BAND, H - 1 - BAND)
    shade_w = 4 * S
    ambient = ImageChops.subtract(
        _rounded_fill(inner_bbox, R_OUT - BAND),
        _rounded_fill(
            (BAND + shade_w, BAND + shade_w, W - 1 - BAND - shade_w, H - 1 - BAND - shade_w),
            max(0, R_OUT - BAND - shade_w),
        ),
    ).filter(ImageFilter.GaussianBlur(S))
    canvas.paste(Image.new("RGBA", (W, H), (6, 9, 16, 90)), (0, 0), ambient)

    _save(canvas, f"{name}.png")


# ---------------------------------------------------------------------------
# per-rarity top-left emblems (composited above artwork by the renderer)
# ---------------------------------------------------------------------------


def _puffy_star_mask(size: int, radius: float, lobes: int = 6, depth: float = 0.24) -> Image.Image:
    """Rounded cartoon star: polar rose silhouette, pointing straight up."""
    ss = 8
    ts = size * ss
    mask = Image.new("L", (ts, ts), 0)
    c = (ts - 1) / 2
    r_out = radius * ss
    points = []
    for k in range(720):
        t = 2 * math.pi * k / 720
        angle = -math.pi / 2 + t
        r = r_out * (1 - depth + depth * math.cos(lobes * t))
        points.append((c + r * math.cos(angle), c + r * math.sin(angle)))
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def _common_star_tile(radius: int, tilt_deg: float) -> Image.Image:
    """One blue puffy star with a silver outline, glint and drop shadow."""
    pad = int(radius * 1.2)
    big = 2 * (radius + pad)
    c = big / 2.0

    body_mask = _puffy_star_mask(big, float(radius))
    outline_mask = _puffy_star_mask(big, radius * 1.18)

    tile = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    # drop shadow cast onto the frame/artwork behind
    sh = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", (big, big), (8, 12, 28, 100)), (0, 6), outline_mask)
    tile.alpha_composite(sh.filter(ImageFilter.GaussianBlur(radius * 0.3)))

    # silver outline
    outline_grad = _vertical_grad(big, big, (250, 253, 255), (150, 170, 200)).convert("RGBA")
    tile.paste(outline_grad, (0, 0), outline_mask)

    # blue body, light pooling toward the upper-left
    body = _radial_fill(
        body_mask, (215, 238, 255), (44, 100, 232), (c * 0.72, c * 0.66), radius * 1.2
    )
    tile.paste(body.convert("RGBA"), (0, 0), body_mask)

    # glint streak
    glint = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    gw, gh = radius * 0.62, radius * 0.20
    gx, gy = c - radius * 0.26, c - radius * 0.34
    ImageDraw.Draw(glint).ellipse((gx - gw, gy - gh, gx + gw, gy + gh), fill=(255, 255, 255, 195))
    glint = glint.rotate(24, Image.Resampling.BICUBIC, center=(gx, gy))
    glint.putalpha(ImageChops.multiply(glint.getchannel("A"), body_mask))
    tile.alpha_composite(glint)

    if tilt_deg:
        tile = tile.rotate(tilt_deg, Image.Resampling.BICUBIC, expand=True)
    return tile


def paint_common_emblem() -> None:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    radius = 21 * S
    for cx, cy, tilt in ((50 * S, 28 * S, -8), (98 * S, 26 * S, 7)):
        tile = _common_star_tile(radius, tilt)
        canvas.alpha_composite(
            tile, (int(cx - tile.width / 2), int(cy - tile.height / 2))
        )
    _save(canvas, "common-emblem.png")


def _sparkle_mask(size: int, radius: float, inner_ratio: float = 0.30) -> Image.Image:
    """Sharp four-point sparkle (compass star)."""
    ss = 8
    ts = size * ss
    mask = Image.new("L", (ts, ts), 0)
    c = (ts - 1) / 2
    points = []
    for k in range(8):
        angle = -math.pi / 2 + k * math.pi / 4
        r = radius * ss if k % 2 == 0 else radius * ss * inner_ratio
        points.append((c + r * math.cos(angle), c + r * math.sin(angle)))
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def _draw_crown(tile: Image.Image, cx: float, cy: float, width: float) -> None:
    """Solid navy crown silhouette punched into the sparkle, gold tip dots."""
    w = width
    h = w * 0.68
    left = cx - w / 2
    top, base = cy - h / 2, cy + h / 2
    spike_top = top + h * 0.18
    band_top = base - h * 0.30
    point_lx, point_rx = left + w * 0.05, left + w * 0.95
    navy = (24, 30, 60, 255)
    pts = [
        (point_lx, spike_top),
        (left + w * 0.31, band_top + h * 0.12),
        (cx, top),
        (left + w * 0.69, band_top + h * 0.12),
        (point_rx, spike_top),
        (point_rx, band_top),
        (point_lx, band_top),
    ]
    draw = ImageDraw.Draw(tile)
    draw.polygon(pts, fill=navy)
    draw.rounded_rectangle((point_lx, band_top - 1, point_rx, base), radius=h * 0.10, fill=navy)
    # tiny gold dots on the three spike tips
    dot = w * 0.05
    for tx, ty in ((point_lx, spike_top), (cx, top), (point_rx, spike_top)):
        draw.ellipse((tx - dot, ty - dot, tx + dot, ty + dot), fill=(255, 226, 146, 255))


def paint_legendary_emblem() -> None:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    radius = 36 * S
    pad = int(radius * 1.2)
    big = 2 * (radius + pad)
    c = big / 2.0

    body_mask = _sparkle_mask(big, float(radius))
    outline_mask = _sparkle_mask(big, radius * 1.12)

    tile = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    sh = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", (big, big), (10, 10, 24, 110)), (0, 6), outline_mask)
    tile.alpha_composite(sh.filter(ImageFilter.GaussianBlur(radius * 0.28)))

    outline_grad = _vertical_grad(big, big, (255, 250, 230), (196, 158, 84)).convert("RGBA")
    tile.paste(outline_grad, (0, 0), outline_mask)

    body = _radial_fill(
        body_mask, (255, 240, 190), (204, 148, 50), (c * 0.70, c * 0.62), radius * 1.25
    )
    tile.paste(body.convert("RGBA"), (0, 0), body_mask)

    _draw_crown(tile, c, c + radius * 0.05, radius * 0.56)

    canvas.alpha_composite(tile, (int(56 * S - tile.width / 2), int(42 * S - tile.height / 2)))
    _save(canvas, "legendary-emblem.png")


def main() -> None:
    paint_base()
    for name, preset in RARITY_PRESETS.items():
        paint_rarity(name, preset)
    paint_common_emblem()
    paint_legendary_emblem()


if __name__ == "__main__":
    main()
