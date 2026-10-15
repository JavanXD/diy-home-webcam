"""CCTV-style timestamp burn-in for LAN MJPEG frames."""

from __future__ import annotations

import io
import logging
from datetime import datetime
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("webcam-stream")

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/Library/Fonts/Courier New.ttf",
)


@lru_cache(maxsize=8)
def _load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def overlay_config(cfg: dict[str, Any]) -> dict[str, Any]:
    return cfg.get("overlay") if isinstance(cfg.get("overlay"), dict) else {}


def format_timestamp(
    epoch: float,
    *,
    timezone: str = "Europe/Berlin",
    fmt: str = "%d/%m/%Y %H:%M:%S %a",
) -> str:
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        log.warning("[osd] unknown timezone %r — using UTC", timezone)
        tz = ZoneInfo("UTC")
    text = datetime.fromtimestamp(float(epoch), tz).strftime(fmt)
    # Classic OSD weekdays are uppercase (WED); keep digits unchanged.
    return text.upper()


def _draw_outlined_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    fill: tuple[int, int, int] = (255, 255, 255),
    outline: tuple[int, int, int] = (0, 0, 0),
    outline_width: int = 1,
) -> None:
    x, y = xy
    w = max(1, int(outline_width))
    for dx in range(-w, w + 1):
        for dy in range(-w, w + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=outline)
    draw.text((x, y), text, font=font, fill=fill)


def burn_timestamp(
    jpeg: bytes,
    epoch: float,
    *,
    timezone: str = "Europe/Berlin",
    fmt: str = "%d/%m/%Y %H:%M:%S %a",
    margin: int = 12,
    font_scale: float = 0.035,
    jpeg_quality: int = 72,
) -> bytes:
    """Return JPEG with a top-left white monospace timestamp + black outline."""
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    text = format_timestamp(epoch, timezone=timezone, fmt=fmt)
    # ~3.5% of the short side; clamp so small test JPEGs stay readable.
    size = max(12, min(48, int(min(img.size) * float(font_scale))))
    font = _load_font(size)
    draw = ImageDraw.Draw(img)
    _draw_outlined_text(draw, (int(margin), int(margin)), text, font=font)
    out = io.BytesIO()
    quality = max(40, min(95, int(jpeg_quality)))
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def maybe_burn_in(
    jpeg: bytes,
    *,
    cfg: dict[str, Any],
    frame_epoch: float | None,
    ingest_epoch: float | None = None,
) -> bytes:
    """Burn OSD when enabled. Prefer camera Last-Modified; else ingest time."""
    ov = overlay_config(cfg)
    if not bool(ov.get("enabled", True)):
        return jpeg
    epoch = frame_epoch if frame_epoch is not None else ingest_epoch
    if epoch is None:
        return jpeg
    stream = cfg.get("stream") if isinstance(cfg.get("stream"), dict) else {}
    try:
        return burn_timestamp(
            jpeg,
            epoch,
            timezone=str(ov.get("timezone") or "Europe/Berlin"),
            fmt=str(ov.get("format") or "%d/%m/%Y %H:%M:%S %a"),
            margin=int(ov.get("margin") or 12),
            font_scale=float(ov.get("font_scale") or 0.035),
            jpeg_quality=int(stream.get("jpeg_quality") or 72),
        )
    except Exception as exc:  # noqa: BLE001 — never break the stream for OSD
        log.warning("[osd] burn-in failed: %s", exc)
        return jpeg
