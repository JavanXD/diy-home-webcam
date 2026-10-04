#!/usr/bin/env python3
"""Generate the public Open Graph still (og-image-v5.jpg).

Composes a 1200×630 branded card from a live landscape JPEG: soft cream/tannen
veil, LIVE pill, Playfair title + Inter subtitle/URL. Matches the accepted
2026-10-02 v5 art (no underline rule, no left accent bar, no cream ghost).

Run from repo root:
  python3 scripts/generate-og-image.py --source path/to/landscape.jpg
  python3 scripts/generate-og-image.py --source https://webcam.example.com/example-live-webcam.jpg

Fonts: scripts/assets/og-fonts/{PlayfairDisplay,Inter}-Variable.ttf (OFL).
"""
from __future__ import annotations

import argparse
import io
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "webhosting/site/og-image-v5.jpg"
FONT_DIR = Path(__file__).resolve().parent / "assets" / "og-fonts"

W, H = 1200, 630
CREME = (247, 243, 236)
SAGE = (157, 196, 173)
TANNEN = (47, 74, 61)


def load_font(path: Path, size: int, weight: float | None = None, opsz: float | None = None):
    f = ImageFont.truetype(str(path), size)
    axes = f.get_variation_axes()
    names = [
        a["name"].decode() if isinstance(a["name"], bytes) else a["name"] for a in axes
    ]
    vals = []
    for a, n in zip(axes, names):
        if n.lower().startswith("optical") and opsz is not None:
            vals.append(float(opsz))
        elif n.lower().startswith("weight") and weight is not None:
            vals.append(float(weight))
        else:
            vals.append(float(a["default"]))
    if vals:
        f.set_variation_by_axes(vals)
    return f


def scenic_crop(im: Image.Image, tw: int = W, th: int = H) -> Image.Image:
    sw, sh = im.size
    target_ar = tw / th
    # Clear baked site-badge strip at top + timestamp at bottom
    top_cut = int(sh * 0.075)
    bottom_cut = int(sh * 0.12)
    usable_h = sh - top_cut - bottom_cut
    usable_w = int(round(usable_h * target_ar))
    if usable_w > sw:
        usable_w = sw
        usable_h = int(round(usable_w / target_ar))
        top_cut = max(0, sh - usable_h - bottom_cut)
    left = max(0, (sw - usable_w) // 2 + int(sw * 0.02))
    if left + usable_w > sw:
        left = sw - usable_w
    return im.crop((left, top_cut, left + usable_w, top_cut + usable_h)).resize(
        (tw, th), Image.Resampling.LANCZOS
    )


def add_warmth(im: Image.Image) -> Image.Image:
    im = ImageEnhance.Color(im).enhance(1.12)
    im = ImageEnhance.Contrast(im).enhance(1.06)
    im = ImageEnhance.Brightness(im).enhance(1.05)
    return Image.blend(im, Image.new("RGB", im.size, CREME), 0.04)


def draw_veil(base: Image.Image) -> Image.Image:
    """Soft bottom-left readability veil — elliptical only, no panel edge / rules."""
    rgba = base.convert("RGBA")
    blur_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(blur_mask).ellipse((-60, 280, 780, 680), fill=255)
    blur_mask = blur_mask.filter(ImageFilter.GaussianBlur(55))
    blurred = base.filter(ImageFilter.GaussianBlur(7))
    locally_soft = Image.composite(blurred, base, blur_mask).convert("RGBA")

    alpha = Image.new("L", (W, H), 0)
    ad = ImageDraw.Draw(alpha)
    ad.ellipse((-120, 180, 900, 760), fill=180)
    ad.ellipse((-40, 250, 680, 720), fill=255)
    alpha = alpha.filter(ImageFilter.GaussianBlur(82))
    veil = Image.merge(
        "RGBA",
        (
            Image.new("L", (W, H), CREME[0]),
            Image.new("L", (W, H), CREME[1]),
            Image.new("L", (W, H), CREME[2]),
            alpha.point(lambda p: int(p * 0.50)),
        ),
    )
    bloom = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(bloom).ellipse((-40, 300, 560, 720), fill=(*SAGE, 20))
    bloom = bloom.filter(ImageFilter.GaussianBlur(72))
    return Image.alpha_composite(Image.alpha_composite(locally_soft, veil), bloom)


def text_bbox(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int, int]:
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0], b[1], b[3]


def load_source(source: str) -> Image.Image:
    if source.startswith("http://") or source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=60) as resp:  # noqa: S310
            data = resp.read()
        return Image.open(io.BytesIO(data)).convert("RGB")
    path = Path(source).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"--source not found: {path}")
    return Image.open(path).convert("RGB")


def generate(source: str, out: Path) -> Path:
    playfair = FONT_DIR / "PlayfairDisplay-Variable.ttf"
    inter = FONT_DIR / "Inter-Variable.ttf"
    if not playfair.is_file() or not inter.is_file():
        raise FileNotFoundError(
            f"Missing OG fonts under {FONT_DIR} "
            "(need PlayfairDisplay-Variable.ttf and Inter-Variable.ttf)"
        )

    src = load_source(source)
    base = add_warmth(scenic_crop(src))
    canvas = draw_veil(base)

    title_font = load_font(playfair, 64, weight=600)
    sub_font = load_font(inter, 24, weight=500, opsz=18)
    url_font = load_font(inter, 20, weight=550, opsz=16)
    live_font = load_font(inter, 13, weight=650, opsz=14)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    title = "Home webcam"
    subtitle = "Blick auf die St.-Nikolaus-Kirche"
    url = "webcam.example.com"
    live_label = "LIVE"
    _, _t_top, t_bot = text_bbox(draw, title, title_font)
    _, s_top, s_bot = text_bbox(draw, subtitle, sub_font)
    _, u_top, u_bot = text_bbox(draw, url, url_font)
    lw, l_top, l_bot = text_bbox(draw, live_label, live_font)
    lh = l_bot - l_top

    pill_h, pill_pad_x = 26, 11
    pill_w = pill_pad_x * 2 + 8 + 7 + lw
    gap_pill_title, gap_title_sub, gap_sub_url = 18, 16, 10
    stack_h = (
        pill_h
        + gap_pill_title
        + t_bot
        + gap_title_sub
        + (s_bot - s_top)
        + gap_sub_url
        + (u_bot - u_top)
    )
    x0, y0 = 72, H - 68 - stack_h
    pill_y = y0

    draw.rounded_rectangle(
        (x0, pill_y, x0 + pill_w, pill_y + pill_h),
        radius=pill_h // 2,
        fill=(*TANNEN, 232),
    )
    dot_cx, dot_cy = x0 + pill_pad_x + 3, pill_y + pill_h // 2
    draw.ellipse(
        (dot_cx - 3.5, dot_cy - 3.5, dot_cx + 3.5, dot_cy + 3.5),
        fill=(*SAGE, 255),
    )
    draw.text(
        (dot_cx + 11, pill_y + (pill_h - lh) / 2 - 1 - l_top),
        live_label,
        font=live_font,
        fill=(*CREME, 255),
    )

    ty = pill_y + pill_h + gap_pill_title
    draw.text((x0, ty), title, font=title_font, fill=(*TANNEN, 255))
    sy = ty + t_bot + gap_title_sub - s_top
    draw.text((x0, sy), subtitle, font=sub_font, fill=(*TANNEN, 220))
    uy = sy + s_bot + gap_sub_url - u_top
    draw.text((x0, uy), url, font=url_font, fill=(*TANNEN, 168))

    final = Image.alpha_composite(canvas, layer).convert("RGB")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    final.save(tmp, "JPEG", quality=91, optimize=True, progressive=True)
    tmp.replace(out)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--source",
        required=True,
        help="Local JPEG path or HTTPS URL of the landscape still",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output path (default: {DEFAULT_OUT.relative_to(ROOT)})",
    )
    args = p.parse_args()
    out = generate(args.source, args.out.resolve())
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
