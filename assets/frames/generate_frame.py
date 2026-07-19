from pathlib import Path

from PIL import Image, ImageDraw

W, H = 401, 555
OUTER_R = 24
INNER_R = 22
BORDER = 18

img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

for y in range(H):
    t = y / (H - 1)
    r = int(8 + 35 * t)
    g = int(12 + 55 * t)
    b = int(45 + 110 * t + 30 * (1 - abs(t - 0.5) * 2))
    draw.line([(0, y), (W - 1, y)], fill=(r, g, b))

gd = ImageDraw.Draw(img)
gd.rounded_rectangle(
    [(BORDER - 3, BORDER - 3), (W - 1 - BORDER + 3, H - 1 - BORDER + 3)],
    radius=INNER_R,
    outline=(70, 130, 220, 100),
    width=2,
)
gd.rounded_rectangle(
    [(BORDER - 5, BORDER - 5), (W - 1 - BORDER + 5, H - 1 - BORDER + 5)],
    radius=INNER_R,
    outline=(50, 100, 200, 60),
    width=1,
)

ad2 = ImageDraw.Draw(img)
ad2.rounded_rectangle(
    [(BORDER - 5, BORDER - 5), (W - 1 - BORDER + 5, H - 1 - BORDER + 5)],
    radius=INNER_R,
    outline=(180, 155, 80, 180),
    width=1,
)

alpha = Image.new("L", (W, H), 0)
ad = ImageDraw.Draw(alpha)
ad.rounded_rectangle([(0, 0), (W - 1, H - 1)], radius=OUTER_R, fill=255)
ad.rounded_rectangle([(BORDER, BORDER), (W - 1 - BORDER, H - 1 - BORDER)], radius=INNER_R, fill=0)
img.putalpha(alpha)

img.save(Path(__file__).parent / "base.png")
print("Generated base.png")
