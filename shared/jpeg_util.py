"""Small JPEG helpers for LAN UI thumbs (Pi CPU-friendly)."""

from __future__ import annotations

import io
from typing import Any


def parse_max_width(raw: Any, *, default: int | None = None, cap: int = 1280) -> int | None:
    """Parse ``?w=`` query value. Returns None when absent/invalid."""
    if raw is None or raw == "":
        return default
    try:
        w = int(raw)
    except (TypeError, ValueError):
        return default
    if w < 32:
        return default
    return min(w, cap)


def downscale_jpeg(data: bytes, max_width: int, *, quality: int = 72) -> bytes:
    """Return a JPEG no wider than ``max_width`` (keeps aspect). No-op if already smaller."""
    if max_width < 32 or not data:
        return data
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGB")
        w, h = img.size
        if w <= max_width:
            return data
        new_h = max(1, round(h * (max_width / float(w))))
        out = img.resize((max_width, new_h), Image.Resampling.BILINEAR)
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
