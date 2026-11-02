#!/usr/bin/env python3
"""Turn raw Steam images (e.g. 460x215) into 1280x720 YouTube thumbnails.

The image is scaled to the full width and centred. The leftover space at the top and bottom is
filled with the stream's hex-grid background, tinted purple (top) and cyan (bottom), and the
image fades into it so there is no hard edge.

Every image in RAW_THUMBS_DIR becomes "<same name>.jpg" in THUMBS_DIR. Images whose output already
exists (and is newer) are skipped unless you pass --force.

    python make_thumbnails.py            # everything new
    python make_thumbnails.py --force    # redo everything (after changing the look below)
    python make_thumbnails.py --only "Slag Run"    # only files whose name contains this

    pip install pillow numpy
"""

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from playtest_paths import RAW_THUMBS_DIR, THUMBS_DIR

# =========================================================================== #
# LOOK: tweak freely, then re-run with --force
# =========================================================================== #
W, H = 1280, 720

VOID, PURPLE, CYAN, DIM = (13, 15, 20), (124, 58, 237), (0, 245, 255), (30, 40, 70)

FEATHER = 56            # px at the image's top/bottom edge that fade out into the backdrop
HEX_DIM = 0.30          # 0 = full-brightness hex grid in the bars, 1 = plain void (hexes invisible)
VIGNETTE = 0.45         # darkening towards the corners, 0 = none (the stream background uses 0.85)
GLOW_SIZE = 190         # px over which the purple (top) and cyan (bottom) glow fades out
GLOW_STRENGTH = 0.75    # 0..1
ACCENT_LINES = True     # thin purple→cyan→purple line along the very top and bottom
ACCENT_THICKNESS = 5
SHARPEN = True          # the source is upscaled ~2.8x, a little sharpening helps
JPEG_QUALITY = 92       # lowered automatically if the file would exceed YouTube's 2 MB limit
# =========================================================================== #

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_BYTES = 2 * 1024 * 1024


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def hex_grid(w, h, supersample=2):
    """The hex grid from background.html (same maths), drawn once and scaled to the thumbnail size."""
    ss = supersample
    img = Image.new("RGB", (w * ss, h * ss), VOID)
    draw = ImageDraw.Draw(img, "RGBA")

    scale = w / 1920                                   # background.html is designed for 1920 wide
    size, gap = 38 * scale * ss, 2 * scale * ss
    hw, hh = math.sqrt(3) * size + gap, 2 * size * 0.75 + gap
    tick = 72                                          # which moment of the pulse animation to freeze
    rot = math.radians(-30)

    for row in range(-2, int(h * ss / hh) + 3):
        for col in range(-2, int(w * ss / hw) + 3):
            cx = col * hw
            cy = row * hh + (0 if col % 2 == 0 else hh / 2)
            dist = math.hypot(cx - w * ss / 2, cy - h * ss / 2) / ss / scale
            wave = math.sin(dist * 0.012 - tick * 0.008) * 0.5 + 0.5
            bright = wave ** 2.5
            r, g, b = mix(DIM, mix(PURPLE, CYAN, wave), bright * 0.85)
            alpha = 0.3 + bright * 0.55
            pts = [(cx + size * math.cos(rot + math.pi / 3 * i), cy + size * math.sin(rot + math.pi / 3 * i))
                   for i in range(6)]
            draw.polygon(pts, fill=(r, g, b, round(alpha * 255)))
    return img.resize((w, h), Image.LANCZOS)


def backdrop():
    base = hex_grid(W, H)
    base = Image.blend(base, Image.new("RGB", (W, H), VOID), HEX_DIM)

    # purple glow from the top edge, cyan glow from the bottom edge
    y = np.arange(H, dtype=np.float32)[:, None]
    top = np.clip(1 - y / GLOW_SIZE, 0, 1) ** 2
    bottom = np.clip(1 - (H - 1 - y) / GLOW_SIZE, 0, 1) ** 2
    arr = np.asarray(base, dtype=np.float32)
    for mask, colour in ((top, PURPLE), (bottom, CYAN)):
        a = (mask * GLOW_STRENGTH)[:, :, None]
        arr = arr * (1 - a) + np.array(colour, dtype=np.float32) * a

    # vignette like the stream background, but weaker so the hexes stay visible across the bars
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (0.9 * W)) ** 2 + ((yy - H / 2) / (0.8 * H)) ** 2)
    v = np.clip((d - 0.4) / 0.6, 0, 1)[:, :, None] * VIGNETTE
    arr = arr * (1 - v) + np.array(VOID, dtype=np.float32) * v
    return Image.fromarray(arr.clip(0, 255).astype("uint8"))


def accent_lines(canvas):
    """Thin glowing purple→cyan→purple lines, like the webcam frame border."""
    x = np.linspace(0, 1, W, dtype=np.float32)
    k = 1 - np.abs(2 * x - 1)                           # 0 at the sides, 1 in the middle
    row = np.stack([PURPLE[i] + (CYAN[i] - PURPLE[i]) * k for i in range(3)], -1)
    layer = Image.new("RGB", (W, H), (0, 0, 0))
    mask = Image.new("L", (W, H), 0)
    strip = Image.fromarray(np.tile(row[None], (ACCENT_THICKNESS, 1, 1)).clip(0, 255).astype("uint8"))
    for y0 in (0, H - ACCENT_THICKNESS):
        layer.paste(strip, (0, y0))
        mask.paste(255, (0, y0, W, y0 + ACCENT_THICKNESS))
    glow = layer.filter(ImageFilter.GaussianBlur(6))
    glow_mask = mask.filter(ImageFilter.GaussianBlur(6)).point(lambda p: min(255, p * 2))
    canvas.paste(glow, (0, 0), glow_mask)
    canvas.paste(layer, (0, 0), mask)


def make_thumbnail(src_path: Path, dst_path: Path) -> str:
    src = Image.open(src_path).convert("RGB")
    img = src.resize((W, round(src.height * W / src.width)), Image.LANCZOS)
    if SHARPEN:
        img = img.filter(ImageFilter.UnsharpMask(radius=1.4, percent=70, threshold=2))

    note = ""
    if img.height > H:                                  # taller than 16:9: crop the middle
        top = (img.height - H) // 2
        img = img.crop((0, top, W, top + H))
        note = " (cropped)"
    y0 = (H - img.height) // 2

    canvas = backdrop()

    # alpha: opaque in the middle, smooth fade over FEATHER px at the edges that touch the backdrop
    ramp = np.ones(img.height, dtype=np.float32)
    if y0 > 0:
        f = min(FEATHER, img.height // 2)
        t = np.clip(np.arange(img.height, dtype=np.float32) / f, 0, 1)
        t = t * t * (3 - 2 * t)                          # smoothstep
        ramp = np.minimum(ramp, t)
        ramp = np.minimum(ramp, t[::-1])
    mask = Image.fromarray((np.tile(ramp[:, None], (1, W)) * 255).astype("uint8"))
    canvas.paste(img, (0, y0), mask)

    if ACCENT_LINES:
        accent_lines(canvas)

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    quality = JPEG_QUALITY
    while True:
        canvas.save(dst_path, "JPEG", quality=quality, subsampling=0, optimize=True)
        if dst_path.stat().st_size <= MAX_BYTES or quality <= 60:
            break
        quality -= 6
    return f"{src.width}x{src.height} -> {W}x{H}{note}, {dst_path.stat().st_size / 1024:.0f} KB"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="redo images that already have a thumbnail")
    parser.add_argument("--only", default=None, help="only files whose name contains this text")
    args = parser.parse_args()

    if not RAW_THUMBS_DIR.is_dir():
        print(f"Raw folder not found: {RAW_THUMBS_DIR}")
        return 1

    made = skipped = 0
    for src in sorted(RAW_THUMBS_DIR.iterdir()):
        if src.suffix.lower() not in IMAGE_EXTS:
            continue
        if args.only and args.only.lower() not in src.name.lower():
            continue
        dst = THUMBS_DIR / f"{src.stem}.jpg"
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime and not args.force:
            skipped += 1
            continue
        try:
            print(f"MADE  {dst.name}: {make_thumbnail(src, dst)}")
            made += 1
        except OSError as e:
            print(f"FAIL  {src.name}: {e}")
    print(f"\nDone: {made} made, {skipped} already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
