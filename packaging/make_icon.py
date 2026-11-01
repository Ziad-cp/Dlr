"""Draw the app icon (packaging/icon.png + icon.icns): the link field's gradient ring and a
download arrow on the app's dark background.   python3 packaging/make_icon.py"""
import math
import pathlib
import shutil
import subprocess

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = pathlib.Path(__file__).resolve().parent
SIZE = 1024
COLORS = [(109, 93, 252), (34, 211, 238), (236, 72, 153), (109, 93, 252)]  # the UI's default glow


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def conic(size):
    """A colour wheel through COLORS, turning around the centre."""
    img = Image.new("RGB", (size, size))
    c, px = size / 2, []
    for y in range(size):
        for x in range(size):
            t = ((math.atan2(y - c, x - c) + math.pi / 2) / (2 * math.pi)) % 1 * (len(COLORS) - 1)
            i = min(int(t), len(COLORS) - 2)
            px.append(lerp(COLORS[i], COLORS[i + 1], t - i))
    img.putdata(px)
    return img


def rounded(size, box, radius):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    return mask


def draw():
    s = SIZE
    icon = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    # macOS icon grid: the tile is ~80% of the canvas
    pad, radius = 100, 185
    tile = (pad, pad, s - pad, s - pad)
    background = Image.new("RGBA", (s, s), (12, 12, 16, 255))
    shade = Image.new("L", (s, s))
    ImageDraw.Draw(shade).ellipse((s * 0.1, s * 0.0, s * 0.9, s * 0.8), fill=60)
    background.paste((40, 34, 70, 255), mask=shade.filter(ImageFilter.GaussianBlur(120)))
    icon.paste(background, mask=rounded(s, tile, radius))

    wheel = conic(s).convert("RGBA")
    # soft glow behind the ring
    ring_outer, ring_w = 300, 26
    c = s // 2
    glow = Image.new("L", (s, s), 0)
    ImageDraw.Draw(glow).ellipse((c - ring_outer, c - ring_outer, c + ring_outer, c + ring_outer), outline=255, width=60)
    glow = ImageChops.multiply(glow.filter(ImageFilter.GaussianBlur(40)), rounded(s, tile, radius))
    icon.paste(wheel, mask=glow.point(lambda v: v * 0.55))
    # the ring itself
    ring = Image.new("L", (s, s), 0)
    ImageDraw.Draw(ring).ellipse((c - ring_outer, c - ring_outer, c + ring_outer, c + ring_outer), outline=255, width=ring_w)
    icon.paste(wheel, mask=ring)

    # download arrow
    arrow = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(arrow)
    w = 46
    top, tip, half = c - 150, c + 95, 115
    d.line((c, top, c, tip), fill=255, width=w)
    d.line((c - half, tip - half, c, tip), fill=255, width=w)
    d.line((c + half, tip - half, c, tip), fill=255, width=w)
    for x, y in ((c, top), (c - half, tip - half), (c + half, tip - half), (c, tip)):
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=255)
    base_y = c + 165
    d.line((c - 150, base_y, c + 150, base_y), fill=255, width=w)
    for x in (c - 150, c + 150):
        d.ellipse((x - w / 2, base_y - w / 2, x + w / 2, base_y + w / 2), fill=255)
    icon.paste((242, 242, 245, 255), mask=arrow)
    return icon


def main():
    icon = draw()
    icon.save(HERE / "icon.png")
    iconset = HERE / "icon.iconset"
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        icon.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
        icon.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "icon.icns")], check=True)
    shutil.rmtree(iconset)
    print("Wrote packaging/icon.png and packaging/icon.icns")


if __name__ == "__main__":
    main()
