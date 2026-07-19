"""Regenerate assets/frames/base.png.

The frame is a *border-only* transparent overlay: the renderer draws artwork
covered by nothing but this rim, then adds the bottom gradient, rarity stars,
badge, and text programmatically. Do not bake stars, badges, or gradients into
this file — they are rarity-dependent and get tinted at render time.
"""

from pathlib import Path

from PIL import Image, ImageDraw

W, H = 401, 555
OUTER_R = 22

img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Main outer rim - cool silver.
draw.rounded_rectangle(
    (2, 2, W - 3, H - 3),
    radius=OUTER_R,
    outline=(168, 176, 195, 230),
    width=4,
)
# Thin gold hairline just inside the rim.
draw.rounded_rectangle(
    (7, 7, W - 8, H - 8),
    radius=OUTER_R - 4,
    outline=(212, 186, 118, 150),
    width=1,
)
# Soft blue inner glow.
draw.rounded_rectangle(
    (10, 10, W - 11, H - 11),
    radius=OUTER_R - 6,
    outline=(80, 120, 210, 60),
    width=2,
)
# Faint inner edge shading for depth against the artwork clip.
draw.rounded_rectangle(
    (13, 13, W - 14, H - 14),
    radius=OUTER_R - 8,
    outline=(8, 10, 16, 45),
    width=1,
)

img.save(Path(__file__).parent / "base.png")
print("Generated base.png (border-only overlay)")
