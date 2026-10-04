"""Ferienhaus / Bollenhut brand tokens + Pillow helpers for JPEG overlays.

Typography: Ferienhaus web uses Playfair Display (headings) + Inter (body) via
next/font — not vendored as TTF. On Pi/Mac we approximate with system fonts:
  - serif display → Palatino / Georgia / DejaVu Serif
  - sans body     → Arial / Helvetica / DejaVu Sans

Colors match Ferienhaus dark-mode cream-on-forest (globals.css).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

# Dark overlay tokens (Ferienhaus .dark + brand)
CREME = (247, 243, 236)  # --brand-creme #f7f3ec
MUTED = (220, 228, 222)  # cream × white-green body
ACCENT = (157, 196, 173)  # dark --accent #9dc4ad
STREUOBST = (216, 200, 168)  # --brand-streuobst #d8c8a8
VEIL = (16, 24, 20)  # dark --surface #101814

_SERIF_CANDIDATES: Sequence[str] = (
    "/System/Library/Fonts/Supplemental/Palatino.ttc",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/Library/Fonts/Palatino.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
)

_SANS_CANDIDATES: Sequence[str] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)

_SANS_BOLD_CANDIDATES: Sequence[str] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)


def cover_fit(
    im: Image.Image,
    size: tuple[int, int],
    *,
    centering: tuple[float, float] = (0.5, 0.45),
) -> Image.Image:
    """Crop to target aspect then LANCZOS-resize — never stretch."""
    rgb = ImageOps.exif_transpose(im.convert("RGB"))
    return ImageOps.fit(rgb, size, method=Image.Resampling.LANCZOS, centering=centering)


def load_font(
    size: int,
    *,
    serif: bool = False,
    bold: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a proportional FreeType face; never scale axes independently."""
    if serif:
        candidates = _SERIF_CANDIDATES
    elif bold:
        candidates = list(_SANS_BOLD_CANDIDATES) + list(_SANS_CANDIDATES)
    else:
        candidates = _SANS_CANDIDATES
    for path in candidates:
        try:
            return ImageFont.truetype(path, size, index=0)
        except OSError:
            continue
    return ImageFont.load_default()


def format_back_at_lines(
    back_at: datetime,
    *,
    now: datetime | None = None,
    tz_name: str = "Europe/Berlin",
    copy: StatusCopy | None = None,
) -> tuple[str, str]:
    """Label + time for the night slide, e.g. ``Back at`` / ``tomorrow 08:00``.

    Wording comes from ``copy``. When ``copy`` is omitted the English default
    is used. A site camera may pass a German block from ``camera.yaml``.
    """
    text = copy or StatusCopy.english()
    tz = ZoneInfo(tz_name)
    back = back_at.astimezone(tz) if back_at.tzinfo else back_at.replace(tzinfo=tz)
    if now is None:
        ref = datetime.now(tz)
    elif now.tzinfo is None:
        ref = now.replace(tzinfo=tz)
    else:
        ref = now.astimezone(tz)
    clock = back.strftime("%H:%M")
    today = ref.date()
    target = back.date()
    if target == today:
        day = text.today
    elif target == today + timedelta(days=1):
        day = text.tomorrow
    else:
        day = text.weekdays[target.weekday()]
    return text.back_at_label, f"{day} {clock}"


def format_back_at_sample() -> tuple[str, str]:
    """Static sample for shipped offline-placeholder.jpg."""
    return "Wieder da ab", "morgen 08:00"


def _center_text(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    width: int,
) -> tuple[int, int, int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (width - tw) // 2
    draw.text((x, y), text, font=font, fill=fill)
    return x, y, tw, th


def draw_back_at_block(
    draw: ImageDraw.ImageDraw,
    *,
    width: int,
    height: int,
    label: str,
    time_line: str,
    y_frac: float = 0.52,
    panel: bool = True,
) -> None:
    """Draw quiet cream label + large accent time; optional dark panel behind."""
    # Scale fonts with frame height (1080p baseline) without non-uniform stretch.
    scale = max(0.55, min(1.35, height / 1080.0))
    label_f = load_font(max(18, int(28 * scale)), bold=False)
    time_f = load_font(max(36, int(64 * scale)), bold=True)

    label_bbox = draw.textbbox((0, 0), label, font=label_f)
    time_bbox = draw.textbbox((0, 0), time_line, font=time_f)
    label_h = label_bbox[3] - label_bbox[1]
    time_h = time_bbox[3] - time_bbox[1]
    label_w = label_bbox[2] - label_bbox[0]
    time_w = time_bbox[2] - time_bbox[0]
    gap = max(6, int(10 * scale))
    block_w = max(label_w, time_w)
    block_h = label_h + gap + time_h

    y0 = int(height * y_frac)
    # Keep block on-frame
    y0 = max(int(height * 0.08), min(y0, height - block_h - int(height * 0.08)))
    pad_x = max(20, int(36 * scale))
    pad_y = max(14, int(22 * scale))

    if panel:
        cx = width // 2
        left = cx - block_w // 2 - pad_x
        right = cx + block_w // 2 + pad_x
        top = y0 - pad_y
        bottom = y0 + block_h + pad_y
        draw.rectangle((left, top, right, bottom), fill=VEIL)

    _center_text(draw, y0, label, label_f, MUTED, width)
    _center_text(draw, y0 + label_h + gap, time_line, time_f, ACCENT, width)


def draw_back_at_on_image(
    im: Image.Image,
    back_at: datetime | None,
    *,
    now: datetime | None = None,
    tz_name: str = "Europe/Berlin",
    sample: bool = False,
    y_frac: float = 0.52,
    panel: bool = True,
) -> Image.Image:
    """Composite Wieder-da block onto an RGB image (mutates a copy)."""
    out = im.convert("RGB")
    draw = ImageDraw.Draw(out)
    if sample or back_at is None:
        label, time_line = format_back_at_sample()
    else:
        label, time_line = format_back_at_lines(back_at, now=now, tz_name=tz_name)
    draw_back_at_block(
        draw,
        width=out.width,
        height=out.height,
        label=label,
        time_line=time_line,
        y_frac=y_frac,
        panel=panel,
    )
    return out


def compose_slide_background(
    photo: Image.Image,
    size: tuple[int, int],
    *,
    centering: tuple[float, float] = (0.5, 0.45),
) -> Image.Image:
    """Cover-fit photo, then dim/veil for readable typography — never stretch."""
    base = cover_fit(photo, size, centering=centering)
    base = ImageEnhance.Brightness(base).enhance(0.55)
    base = ImageEnhance.Contrast(base).enhance(1.05)
    base = base.filter(ImageFilter.GaussianBlur(radius=0.6))
    veil = Image.new("RGB", size, VEIL)
    return Image.blend(base, veil, 0.30)


def draw_status_overlay(
    draw: ImageDraw.ImageDraw,
    *,
    width: int,
    height: int,
    title: str,
    body: str,
    brand: str = "Webcam",
    back_at_label: str | None = None,
    back_at_time: str | None = None,
    back_at_panel: bool = False,
) -> None:
    """Centered Wartung/Nacht title + body at *final* pixel size (badge-style fonts).

    Scale faces with frame height (1080p baseline). Never draw on a canvas that will
    later be resized anisotropically — call this after cover_fit to the output size.
    """
    scale = max(0.55, min(1.35, height / 1080.0))
    title_px = 84 if len(title) < 20 else 72
    title_f = load_font(max(40, int(title_px * scale)), serif=True)
    body_f = load_font(max(20, int(34 * scale)), bold=False)
    brand_f = load_font(max(16, int(26 * scale)), bold=False)

    ay = int(height * 0.38)
    draw.line(
        (int(width * 0.36), ay, int(width * 0.64), ay),
        fill=STREUOBST,
        width=max(1, int(2 * scale)),
    )
    _center_text(draw, int(height * 0.26), title, title_f, CREME, width)
    _center_text(draw, int(height * 0.44), body, body_f, MUTED, width)

    if back_at_label and back_at_time:
        draw_back_at_block(
            draw,
            width=width,
            height=height,
            label=back_at_label,
            time_line=back_at_time,
            y_frac=0.54,
            panel=back_at_panel,
        )
        brand_y = int(height * 0.78)
    else:
        brand_y = int(height * 0.56)
    _center_text(draw, brand_y, brand, brand_f, STREUOBST, width)


def compose_status_slide(
    photo: Image.Image,
    size: tuple[int, int],
    *,
    title: str,
    body: str,
    brand: str = "Webcam",
    back_at_label: str | None = None,
    back_at_time: str | None = None,
    back_at_panel: bool = False,
    centering: tuple[float, float] = (0.5, 0.45),
) -> Image.Image:
    """Cover-fit photo first, then draw overlay glyphs at the target pixel size."""
    base = compose_slide_background(photo, size, centering=centering)
    draw = ImageDraw.Draw(base)
    draw_status_overlay(
        draw,
        width=size[0],
        height=size[1],
        title=title,
        body=body,
        brand=brand,
        back_at_label=back_at_label,
        back_at_time=back_at_time,
        back_at_panel=back_at_panel,
    )
    return base


# The bake script may still use these German strings. Runtime slides use
# StatusCopy: English unless cameras/<id>/camera.yaml sets status_text.
WARTUNG_TITLE = "Wartung"
WARTUNG_BODY = "Die Live-Webcam ist vorübergehend nicht verfügbar."
NACHT_TITLE = "Nachts offline"
NACHT_BODY = "Die Live-Webcam pausiert in der Nacht"


@dataclass(frozen=True)
class StatusCopy:
    """Words burned into the night and maintenance slides."""

    maintenance_title: str
    maintenance_body: str
    night_title: str
    night_body: str
    back_at_label: str
    today: str
    tomorrow: str
    weekdays: tuple[str, str, str, str, str, str, str]

    @staticmethod
    def english() -> StatusCopy:
        return StatusCopy(
            maintenance_title="Maintenance",
            maintenance_body="The live webcam is temporarily unavailable.",
            night_title="Offline at night",
            night_body="The live webcam pauses overnight.",
            back_at_label="Back at",
            today="today",
            tomorrow="tomorrow",
            weekdays=("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
        )

    @staticmethod
    def german() -> StatusCopy:
        """This site's wording. A copied project opts in by writing camera.yaml."""
        return StatusCopy(
            maintenance_title=WARTUNG_TITLE,
            maintenance_body=WARTUNG_BODY,
            night_title=NACHT_TITLE,
            night_body=NACHT_BODY,
            back_at_label="Wieder da ab",
            today="heute",
            tomorrow="morgen",
            weekdays=("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"),
        )


def _status_line(value: Any, fallback: str, limit: int) -> str:
    if value is None:
        return fallback
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return fallback
    return text[:limit]


def status_copy_from_mapping(raw: Any) -> StatusCopy:
    """English, with any non-empty ``status_text`` keys from camera.yaml."""
    base = StatusCopy.english()
    if not isinstance(raw, dict):
        return base
    weeks = base.weekdays
    listed = raw.get("weekdays")
    if isinstance(listed, list) and len(listed) == 7:
        cleaned = tuple(_status_line(item, "", 12) for item in listed)
        if all(cleaned):
            weeks = cleaned  # type: ignore[assignment]
    return StatusCopy(
        maintenance_title=_status_line(raw.get("maintenance_title"), base.maintenance_title, 60),
        maintenance_body=_status_line(raw.get("maintenance_body"), base.maintenance_body, 160),
        night_title=_status_line(raw.get("night_title"), base.night_title, 60),
        night_body=_status_line(raw.get("night_body"), base.night_body, 160),
        back_at_label=_status_line(raw.get("back_at_label"), base.back_at_label, 40),
        today=_status_line(raw.get("today"), base.today, 20),
        tomorrow=_status_line(raw.get("tomorrow"), base.tomorrow, 20),
        weekdays=weeks,
    )


def plain_status_background(size: tuple[int, int]) -> Image.Image:
    """Dark slide used when no night or maintenance photo is installed."""
    width = max(2, int(size[0]))
    height = max(2, int(size[1]))
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    top = (12, 22, 32)
    bottom = (28, 42, 48)
    span = max(height - 1, 1)
    for y in range(height):
        blend = y / span
        color = tuple(int(top[i] + (bottom[i] - top[i]) * blend) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)
    return img


def format_temp_c_de(temp_c: float) -> str:
    """German temperature label: always one decimal with comma (``12,4 °C`` / ``17,0 °C``)."""
    s = f"{float(temp_c):.1f}".replace(".", ",")
    return f"{s} °C"


def format_site_badge(site: str, temp_c: float | None = None) -> str:
    """Top-left micro label for public JPEGs.

    Examples: ``example.com`` or ``example.com  ·  12,4 °C``.
    """
    label = (site or "").strip()
    if not label:
        return ""
    if temp_c is None:
        return label
    return f"{label}  ·  {format_temp_c_de(temp_c)}"


# Canonical wall-clock for all JPEG overlays (live burn-in + Wartung/Nacht).
# Europe/Berlin local; avoid %Z / %z (CEST/CET look like a second clock).
DEFAULT_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"


def format_wall_clock(
    when: datetime | float | None = None,
    *,
    tz_name: str = "Europe/Berlin",
    fmt: str | None = None,
) -> str:
    """Canonical Europe/Berlin wall clock for overlays: ``2026-09-30 09:15``.

    Shared by live timestamp burn-in and Wartung / Nacht bottom-left clocks so
    formats cannot drift. Prefer formats without ``%Z`` / ``%z``.
    """
    tz = ZoneInfo(tz_name or "Europe/Berlin")
    if when is None:
        dt = datetime.now(tz)
    elif isinstance(when, (int, float)):
        dt = datetime.fromtimestamp(float(when), tz=tz)
    elif when.tzinfo is None:
        dt = when.replace(tzinfo=tz)
    else:
        dt = when.astimezone(tz)
    return dt.strftime(fmt or DEFAULT_TIMESTAMP_FORMAT)


def format_live_clock(
    when: datetime | float | None = None,
    *,
    tz_name: str = "Europe/Berlin",
) -> str:
    """Wall-clock label for placeholder liveness (same format as live burn-in).

    Uses *now* (or ``when``), never a stale capture timestamp — so Wartung / Nacht
    frames prove the pipeline is still publishing.
    """
    return format_wall_clock(when, tz_name=tz_name)


# Shared corner inset for top-left site badge + bottom-left clock.
# Was max(12, 16×scale) ≈ 12–16px — too tight on the left edge of public frames.
DEFAULT_OVERLAY_MARGIN = 28
# Absolute px when YAML omits font_size (landscape ~1600×900); slightly larger than
# the old max(18, 24×scale) so brand weight matches the bottom-left clock.
DEFAULT_OVERLAY_FONT_SIZE = 26
# Even dark halo around cream glyphs (Pillow stroke_*). Replaces the old
# bottom-right-biased multi-offset drop shadow that looked uneven on sky.
DEFAULT_OVERLAY_STROKE_WIDTH = 2
# Draw overlays at 2× then LANCZOS-downsample for cleaner FreeType edges on JPEGs.
DEFAULT_OVERLAY_SUPERSAMPLE = 2


def overlay_corner_pad(height: int, margin: int | None = None) -> int:
    """Pixel inset from frame edge for badge/clock overlays."""
    if margin is not None:
        return int(margin)
    scale = max(0.55, min(1.35, height / 1080.0))
    return max(24, int(DEFAULT_OVERLAY_MARGIN * scale))


def overlay_font_size(height: int, font_size: int | None = None) -> int:
    """Resolve badge/clock face size; explicit YAML wins, else height-scaled default."""
    if font_size is not None:
        return int(font_size)
    scale = max(0.55, min(1.35, height / 1080.0))
    return max(20, int(DEFAULT_OVERLAY_FONT_SIZE * scale))


def overlay_stroke_width(stroke_width: int | None = None) -> int:
    """Even outline width in px (0 = fill only)."""
    if stroke_width is None:
        return DEFAULT_OVERLAY_STROKE_WIDTH
    return max(0, int(stroke_width))


def draw_halo_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    *,
    fill: tuple[int, int, int] = CREME,
    stroke_fill: tuple[int, int, int] = VEIL,
    stroke_width: int | None = None,
    supersample: int | None = None,
) -> None:
    """Cream glyphs with a uniform dark outline — no offset drop-shadow.

    Pillow ``stroke_width`` / ``stroke_fill`` draws an even halo. Optional 2×
    supersample + LANCZOS downscale softens FreeType edges before JPEG encode.
    """
    sw = overlay_stroke_width(stroke_width)
    ss = DEFAULT_OVERLAY_SUPERSAMPLE if supersample is None else max(1, int(supersample))
    base = getattr(draw, "_image", None)

    def _paint(target: ImageDraw.ImageDraw, pos: tuple[int, int], face, stroke: int) -> None:
        if stroke > 0:
            target.text(
                pos,
                text,
                font=face,
                fill=fill,
                stroke_width=stroke,
                stroke_fill=stroke_fill,
            )
        else:
            target.text(pos, text, font=face, fill=fill)

    if ss <= 1 or base is None or not hasattr(font, "size"):
        _paint(draw, xy, font, sw)
        return

    face_size = int(getattr(font, "size"))
    big_font = load_font(face_size * ss, bold=False)
    big_sw = sw * ss
    # Measure on a scratch draw so we allocate a tight RGBA tile.
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    bbox = scratch.textbbox((0, 0), text, font=big_font, stroke_width=big_sw)
    pad = max(2, big_sw + 2)
    tile_w = max(1, (bbox[2] - bbox[0]) + pad * 2)
    tile_h = max(1, (bbox[3] - bbox[1]) + pad * 2)
    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    # textbbox origin can be negative (bearing); shift into the tile.
    ox, oy = pad - bbox[0], pad - bbox[1]
    if big_sw > 0:
        tile_draw.text(
            (ox, oy),
            text,
            font=big_font,
            fill=(*fill, 255),
            stroke_width=big_sw,
            stroke_fill=(*stroke_fill, 255),
        )
    else:
        tile_draw.text((ox, oy), text, font=big_font, fill=(*fill, 255))
    out_w = max(1, (tile_w + ss - 1) // ss)
    out_h = max(1, (tile_h + ss - 1) // ss)
    small = tile.resize((out_w, out_h), Image.Resampling.LANCZOS)
    # Align tile so glyph origin matches xy (same bearing as 1× textbbox).
    bbox1 = draw.textbbox((0, 0), text, font=font, stroke_width=sw)
    dest = (xy[0] + bbox1[0] - (pad // ss), xy[1] + bbox1[1] - (pad // ss))
    if base.mode != "RGBA":
        rgba = base.convert("RGBA")
        rgba.alpha_composite(small, dest=dest)
        base.paste(rgba.convert(base.mode))
    else:
        base.alpha_composite(small, dest=dest)


def draw_live_clock(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    width: int,
    height: int,
    margin: int | None = None,
    font_size: int | None = None,
    stroke_width: int | None = None,
) -> None:
    """Bottom-left cream clock label (pairs with top-left site/temp badge)."""
    if not text:
        return
    size = overlay_font_size(height, font_size)
    pad = overlay_corner_pad(height, margin)
    font = load_font(size, bold=False)
    # Include stroke in bbox so the halo does not clip the bottom edge.
    sw = overlay_stroke_width(stroke_width)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=sw)
    th = bbox[3] - bbox[1]
    x, y = pad, height - pad - th
    draw_halo_text(draw, (x, y), text, font, stroke_width=sw)


def draw_site_badge(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    width: int,
    height: int,
    margin: int | None = None,
    font_size: int | None = None,
    stroke_width: int | None = None,
) -> None:
    """Top-left cream site/temp label with an even dark outline for photo contrast."""
    if not text:
        return
    size = overlay_font_size(height, font_size)
    pad = overlay_corner_pad(height, margin)
    font = load_font(size, bold=False)
    x, y = pad, pad
    draw_halo_text(draw, (x, y), text, font, stroke_width=stroke_width)


def draw_site_badge_on_image(
    im: Image.Image,
    text: str,
    *,
    margin: int | None = None,
    font_size: int | None = None,
    stroke_width: int | None = None,
) -> Image.Image:
    """Composite site badge onto an RGB image (returns a copy)."""
    out = im.convert("RGB")
    if not text:
        return out
    draw = ImageDraw.Draw(out)
    draw_site_badge(
        draw,
        text=text,
        width=out.width,
        height=out.height,
        margin=margin,
        font_size=font_size,
        stroke_width=stroke_width,
    )
    return out


def font_paths_in_use() -> dict[str, str | None]:
    """Diagnostic: which faces resolved (for ops / TODO notes)."""

    def _probe(cands: Sequence[str]) -> str | None:
        for path in cands:
            if Path(path).is_file():
                return path
        return None

    return {
        "serif": _probe(_SERIF_CANDIDATES),
        "sans": _probe(_SANS_CANDIDATES),
        "sans_bold": _probe(_SANS_BOLD_CANDIDATES),
    }
