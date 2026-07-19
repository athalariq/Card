"""Regenerate assets/stars/star.png — a beveled, gem-like five-point star.

The asset is grayscale + alpha: CardRenderer tints it per rarity with a
multiply tint (star pixels = accent * gray / 255), so the shading baked here
survives tinting — a bright faceted face with a dark colored rim. Rendered at
4x and downscaled for smooth edges.
"""

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

FINAL = 128
S = 4  # supersample
C = FINAL * S
CX = CY = C / 2
R_OUT = C * 0.44
R_IN = R_OUT * 0.43
RIM_SCALE = 0.86  # inner mask scale: area between 1.0x and 0.86x is the rim


def _star_points(
    cx: float, cy: float, r_out: float, r_in: float
) -> list[tuple[float, float]]:
    points = []
    for i in range(10):
        radius = r_out if i % 2 == 0 else r_in
        angle = math.radians(-90 + i * 36)
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def _star_mask(scale: float) -> Image.Image:
    mask = Image.new("L", (C, C), 0)
    ImageDraw.Draw(mask).polygon(
        _star_points(CX, CY, R_OUT * scale, R_IN * scale), fill=255
    )
    return mask


def main() -> None:
    body_mask = _star_mask(1.0)

    # vertical metallic falloff: bright top, mid-gray bottom
    gradient = Image.new("L", (C, C), 0)
    draw = ImageDraw.Draw(gradient)
    top = CY - R_OUT
    bottom = CY + R_OUT
    for y in range(C):
        p = min(1.0, max(0.0, (y - top) / (bottom - top)))
        ease = p * p * (3 - 2 * p)
        draw.line((0, y, C, y), fill=int(252 - ease * (252 - 208)))

    star = Image.new("RGBA", (C, C), (0, 0, 0, 0))
    opaque = Image.new("L", (C, C), 255)
    body = Image.merge("RGBA", (gradient, gradient, gradient, opaque))
    star.paste(body, (0, 0), body_mask)

    # dark bevel rim: darker tint emerges naturally when multiplied
    inner = _star_mask(RIM_SCALE)
    rim_zone = ImageChops.subtract(body_mask, inner)
    star.paste(Image.new("RGBA", (C, C), (148, 148, 148, 255)), (0, 0), rim_zone)

    # crisp outer edge line
    outline = ImageDraw.Draw(star)
    points = _star_points(CX, CY, R_OUT * 0.995, R_IN * 0.995)
    outline.line(points + [points[0]], fill=(96, 96, 96, 255), width=max(1, C // 96), joint=True)

    # raised facet: bright inner star soft-merged over the body
    facet_mask = _star_mask(0.62).filter(ImageFilter.GaussianBlur(C * 0.02))
    blank = Image.new("RGBA", (C, C), (0, 0, 0, 0))
    facet = Image.new("RGBA", (C, C), (255, 255, 255, 140))
    star.alpha_composite(Image.composite(facet, blank, facet_mask))

    # sparkle glint near the upper-left arm
    glint = Image.new("RGBA", (C, C), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glint)
    gx, gy = CX - R_OUT * 0.30, CY - R_OUT * 0.38
    arm = C * 0.055
    thin = C * 0.012
    white = (255, 255, 255, 190)
    gd.rounded_rectangle((gx - arm, gy - thin, gx + arm, gy + thin), radius=thin, fill=white)
    gd.rounded_rectangle((gx - thin, gy - arm, gx + thin, gy + arm), radius=thin, fill=white)
    dot = thin * 1.4
    gd.ellipse((gx - dot, gy - dot, gx + dot, gy + dot), fill=(255, 255, 255, 255))
    glint = glint.filter(ImageFilter.GaussianBlur(C * 0.004))
    glint.putalpha(ImageChops.multiply(glint.getchannel("A"), body_mask))
    star.alpha_composite(glint)

    final = star.resize((FINAL, FINAL), Image.Resampling.LANCZOS)
    out = Path(__file__).parent / "star.png"
    final.save(out)
    print(f"Generated {out.name} (beveled grayscale star, tintable)")


if __name__ == "__main__":
    main()
