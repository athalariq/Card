from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from larpcard.cards.domain import RenderCard, rarity_style

CARD_SIZE = (401, 555)

DEBUG_VIEWPORT = False


@dataclass(frozen=True)
class FrameLayout:
    viewport: tuple[int, int, int, int] = (10, 14, 391, 541)
    name_top: int = 430
    series_top: int = 476
    star_left: int = 20
    star_top: int = 20
    star_gap: int = 16
    star_size: int = 18
    badge_right: int = 379
    badge_top: int = 18
    badge_width: int = 66
    badge_height: int = 24
    gradient_start_y: int = 280
    text_max_width: int = 340
    name_font_size: int = 28
    name_font_min: int = 16
    series_font_size: int = 14
    series_font_min: int = 10
    badge_font_size: int = 13
    clip_radius: int = 16
    corner_radius: int = 22

    @classmethod
    def from_json(cls, path: Path) -> FrameLayout:
        data = json.loads(path.read_text(encoding="utf-8"))
        vp = data.get("viewport", (10, 14, 391, 541))
        return cls(
            viewport=tuple(vp),
            name_top=data.get("name_top", 430),
            series_top=data.get("series_top", 476),
            star_left=data.get("star_left", 20),
            star_top=data.get("star_top", 20),
            star_gap=data.get("star_gap", 16),
            star_size=data.get("star_size", 18),
            badge_right=data.get("badge_right", 379),
            badge_top=data.get("badge_top", 18),
            badge_width=data.get("badge_width", 66),
            badge_height=data.get("badge_height", 24),
            gradient_start_y=data.get("gradient_start_y", 280),
            text_max_width=data.get("text_max_width", 340),
            name_font_size=data.get("name_font_size", 28),
            name_font_min=data.get("name_font_min", 16),
            series_font_size=data.get("series_font_size", 14),
            series_font_min=data.get("series_font_min", 10),
            badge_font_size=data.get("badge_font_size", 13),
            clip_radius=data.get("clip_radius", 16),
            corner_radius=data.get("corner_radius", 22),
        )


class CardRenderer:
    def __init__(self, asset_root: Path | None = None, render_scale: int = 2) -> None:
        if render_scale < 1:
            raise ValueError("render_scale must be at least 1")
        self._asset_root = asset_root
        self._scale = render_scale

    def render(
        self,
        card: RenderCard,
        artwork: Image.Image,
        custom_frame: Image.Image | None = None,
        frame_name: str | None = None,
    ) -> Image.Image:
        s = self._scale
        w, h = CARD_SIZE[0] * s, CARD_SIZE[1] * s
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))

        fn = frame_name or card.rarity.value
        layout = self._get_layout(fn)
        style = rarity_style(card.rarity)

        frame = custom_frame or self._load_asset("frames", card.rarity.value)
        if frame is None:
            frame = self._load_asset("frames", "base")
        if frame is not None:
            frame = frame.resize((w, h), Image.Resampling.LANCZOS)

        self._draw_artwork(canvas, artwork, layout)

        if DEBUG_VIEWPORT:
            self._draw_debug_viewport(canvas, layout)

        self._draw_bottom_gradient(canvas, layout)

        if frame is not None:
            canvas.alpha_composite(frame)

        self._draw_stars(canvas, card, layout, style)
        self._draw_badge(canvas, card, layout, style)
        self._draw_text(canvas, card, layout)

        corner_mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(corner_mask).rounded_rectangle(
            (0, 0, w - 1, h - 1),
            radius=layout.corner_radius * s,
            fill=255,
        )
        r, g, b, a = canvas.split()
        a = ImageChops.multiply(a, corner_mask)
        canvas = Image.merge("RGBA", (r, g, b, a))

        if s != 1:
            canvas = canvas.resize(CARD_SIZE, Image.Resampling.LANCZOS)
        return canvas

    def compose_drop(self, cards: Sequence[Image.Image]) -> Image.Image:
        if not 1 <= len(cards) <= 4:
            raise ValueError("a drop sheet supports between one and four cards")
        columns = 1 if len(cards) == 1 else 2
        rows = math.ceil(len(cards) / columns)
        gap = 16
        margin = 20
        sw = margin * 2 + columns * CARD_SIZE[0] + (columns - 1) * gap
        sh = margin * 2 + rows * CARD_SIZE[1] + (rows - 1) * gap
        sheet = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        for i, card_img in enumerate(cards):
            row, col = divmod(i, columns)
            x = margin + col * (CARD_SIZE[0] + gap)
            y = margin + row * CARD_SIZE[1] + row * gap
            src = card_img.convert("RGBA")
            sheet.alpha_composite(src, (x, y))
        return sheet

    def placeholder_artwork(
        self,
        character_name: str,
        accent: tuple[int, int, int],
    ) -> Image.Image:
        width, height = 720, 980
        img = Image.new("RGB", (width, height), (15, 18, 28))
        draw = ImageDraw.Draw(img)
        for y in range(height):
            p = y / (height - 1)
            draw.line(
                (0, y, width, y),
                fill=(
                    int(14 + accent[0] * 0.16 * p),
                    int(17 + accent[1] * 0.16 * p),
                    int(27 + accent[2] * 0.16 * p),
                ),
            )
        cx, cy = width // 2, height // 2 - 30
        for r, a in ((250, 25), (180, 35), (110, 50)):
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).ellipse(
                (cx - r, cy - r, cx + r, cy + r),
                outline=(*accent, a),
                width=4,
            )
            img = Image.alpha_composite(img.convert("RGBA"), layer)
        fd = ImageDraw.Draw(img)
        initials = "".join(p[0] for p in character_name.split()[:2]).upper() or "LC"
        font = self._font(108, bold=True)
        bb = fd.textbbox((0, 0), initials, font=font)
        fd.text(
            (cx - (bb[2] - bb[0]) / 2, cy - (bb[3] - bb[1]) / 2 - bb[1]),
            initials,
            font=font,
            fill=(238, 240, 248, 235),
        )
        return img

    def _get_layout(self, frame_name: str) -> FrameLayout:
        layout = self._load_layout(frame_name)
        if layout is None:
            layout = self._load_layout("base")
        return layout or FrameLayout()

    def _draw_artwork(
        self, canvas: Image.Image, artwork: Image.Image, layout: FrameLayout
    ) -> None:
        s = self._scale
        l, t, r, b = layout.viewport
        aw, ah = (r - l) * s, (b - t) * s

        source = artwork.convert("RGBA")
        alpha = source.getchannel("A")
        bbox = alpha.getbbox()
        if bbox is not None and bbox != (0, 0, source.width, source.height):
            source = source.crop(bbox)

        fitted = ImageOps.fit(
            source,
            (aw, ah),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

        clip = Image.new("L", (aw, ah), 0)
        ImageDraw.Draw(clip).rounded_rectangle(
            (0, 0, aw - 1, ah - 1),
            radius=layout.clip_radius * s,
            fill=255,
        )
        fitted = Image.composite(
            fitted, Image.new("RGBA", fitted.size, (0, 0, 0, 0)), clip
        )

        canvas.alpha_composite(fitted, (l * s, t * s))

    def _draw_debug_viewport(
        self, canvas: Image.Image, layout: FrameLayout
    ) -> None:
        s = self._scale
        l, t, r, b = layout.viewport
        draw = ImageDraw.Draw(canvas)
        draw.rectangle(
            (l * s, t * s, r * s, b * s),
            outline=(255, 0, 0, 255),
            width=3 * s,
        )

    def _draw_bottom_gradient(
        self, canvas: Image.Image, layout: FrameLayout
    ) -> None:
        s = self._scale
        start = layout.gradient_start_y * s
        gradient = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(gradient)
        denom = max(canvas.height - start, 1)
        for y in range(start, canvas.height):
            p = (y - start) / denom
            a = int(200 * (p**0.65))
            gd.line((0, y, canvas.width, y), fill=(5, 7, 12, a))
        canvas.alpha_composite(gradient)

    def _draw_text(
        self, canvas: Image.Image, card: RenderCard, layout: FrameLayout
    ) -> None:
        s = self._scale
        draw = ImageDraw.Draw(canvas)
        max_w = layout.text_max_width * s
        cx = CARD_SIZE[0] / 2

        name_font = self._fit_font(
            card.character_name, layout.name_font_size, layout.name_font_min, max_w, bold=True
        )
        name_bb = draw.textbbox((0, 0), card.character_name, font=name_font)
        name_w = name_bb[2] - name_bb[0]
        draw.text(
            ((cx * s) - name_w / 2, layout.name_top * s),
            card.character_name,
            font=name_font,
            fill=(250, 250, 253, 255),
            stroke_width=1 * s,
            stroke_fill=(0, 0, 0, 180),
        )

        series_font = self._fit_font(
            card.series_name, layout.series_font_size, layout.series_font_min, max_w, bold=False
        )
        series_bb = draw.textbbox((0, 0), card.series_name.upper(), font=series_font)
        series_w = series_bb[2] - series_bb[0]
        draw.text(
            ((cx * s) - series_w / 2, layout.series_top * s),
            card.series_name.upper(),
            font=series_font,
            fill=(191, 196, 211, 255),
            stroke_width=1 * s,
            stroke_fill=(0, 0, 0, 140),
        )

    def _draw_stars(
        self,
        canvas: Image.Image,
        card: RenderCard,
        layout: FrameLayout,
        style,
    ) -> None:
        star_im = self._load_asset("stars", card.rarity.value)
        if star_im is None:
            star_im = self._load_asset("stars", "star")
        if star_im is None:
            return
        s = self._scale
        star_size = layout.star_size * s
        star = star_im.resize((star_size, star_size), Image.Resampling.LANCZOS)
        star = self._tint_image(star, style.highlight_rgb)
        for i in range(style.stars):
            canvas.alpha_composite(
                star,
                ((layout.star_left + i * layout.star_gap) * s, layout.star_top * s),
            )

    def _draw_badge(
        self,
        canvas: Image.Image,
        card: RenderCard,
        layout: FrameLayout,
        style,
    ) -> None:
        badge_im = self._load_asset("badges", "badge")
        if badge_im is None:
            return
        s = self._scale
        serial = f"#{card.print_number}"
        font = self._font(layout.badge_font_size, bold=True)
        draw = ImageDraw.Draw(canvas)
        bb = draw.textbbox((0, 0), serial, font=font)
        tw = bb[2] - bb[0]
        th = bb[3] - bb[1]
        padding = 10 * s
        bw = tw + padding * 2
        bh = layout.badge_height * s
        badge = badge_im.resize((bw, bh), Image.Resampling.LANCZOS)
        badge = self._tint_image(badge, style.accent_rgb)
        bx = layout.badge_right * s - bw
        by = layout.badge_top * s
        canvas.alpha_composite(badge, (bx, by))
        tx = bx + padding
        ty = by + (bh - th) // 2 - bb[1]
        draw.text(
            (tx, ty),
            serial,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=1 * s,
            stroke_fill=(0, 0, 0, 160),
        )

    def _tint_image(
        self, im: Image.Image, color: tuple[int, int, int]
    ) -> Image.Image:
        alpha = im.getchannel("A")
        if alpha.getbbox() is None:
            return im
        gray = im.convert("L")
        cr, cg, cb = color
        rt = [i * cr // 255 for i in range(256)]
        gt = [i * cg // 255 for i in range(256)]
        bt = [i * cb // 255 for i in range(256)]
        return Image.merge("RGBA", (
            gray.point(rt),
            gray.point(gt),
            gray.point(bt),
            alpha,
        ))

    def _fit_font(
        self,
        text: str,
        preferred: int,
        minimum: int,
        max_width: int,
        *,
        bold: bool,
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        for size in range(preferred, minimum - 1, -1):
            font = self._font(size, bold=bold)
            bb = font.getbbox(text)
            if bb[2] - bb[0] <= max_width:
                return font
        return self._font(minimum, bold=bold)

    def _font(
        self, size: int, *, bold: bool
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        s = self._scale
        family = "SpaceGrotesk"
        weight = "-Bold" if bold else "-Medium"
        candidates: list[Path] = []
        if self._asset_root is not None:
            candidates.append(self._asset_root / "fonts" / f"{family}{weight}.ttf")
            if bold:
                candidates.append(self._asset_root / "fonts" / f"{family}-SemiBold.ttf")
        candidates.extend(
            [
                Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
                Path(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                    if bold
                    else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
                ),
            ]
        )
        for p in candidates:
            if p.is_file():
                return ImageFont.truetype(str(p), size * s)
        return ImageFont.load_default(size=size * s)

    @cache
    def _load_asset(self, subdir: str, name: str) -> Image.Image | None:
        if self._asset_root is None:
            return None
        path = self._asset_root / subdir / f"{name}.png"
        if not path.is_file():
            return None
        im = Image.open(path)
        im.load()
        return im

    @cache
    def _load_layout(self, name: str) -> FrameLayout | None:
        if self._asset_root is None:
            return None
        path = self._asset_root / "frames" / f"{name}.json"
        if not path.is_file():
            return None
        return FrameLayout.from_json(path)
