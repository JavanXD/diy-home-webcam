"""Sharpness of a chosen box on the frame. Higher means crisper edges."""

from __future__ import annotations

import io
import json
import math
import os
import threading
from pathlib import Path

from PIL import Image, ImageFilter

# Fraction trimmed from each edge. The score uses the remaining middle until moved.
FOCUS_INSET = 0.30
# Smallest box, as a fraction of the frame, so a tower can still be isolated.
MIN_SPAN = 0.02


def focus_region() -> dict[str, float]:
    """Default box: the middle of the frame, as fractions of width and height."""
    span = 1.0 - 2.0 * FOCUS_INSET
    return {
        "left": FOCUS_INSET,
        "top": FOCUS_INSET,
        "width": span,
        "height": span,
    }


def clamp_region(raw: object) -> dict[str, float]:
    """Keep a box inside the frame. Bad input falls back to the middle."""
    default = focus_region()
    if not isinstance(raw, dict):
        return default
    try:
        left = float(raw["left"])
        top = float(raw["top"])
        width = float(raw["width"])
        height = float(raw["height"])
    except (KeyError, TypeError, ValueError):
        return default
    if not all(math.isfinite(v) for v in (left, top, width, height)):
        return default
    width = min(1.0, max(MIN_SPAN, width))
    height = min(1.0, max(MIN_SPAN, height))
    left = min(max(0.0, left), 1.0 - width)
    top = min(max(0.0, top), 1.0 - height)
    return {
        "left": round(left, 4),
        "top": round(top, 4),
        "width": round(width, 4),
        "height": round(height, 4),
    }


class FocusRegionStore:
    """Saved measurement box next to the camera JPEG. Survives restarts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._region = self._read()

    def get(self) -> dict[str, float]:
        with self._lock:
            return dict(self._region)

    def save(self, raw: object) -> dict[str, float]:
        cleaned = clamp_region(raw)
        payload = json.dumps(cleaned).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with self._lock:
            with open(tmp, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
            self._region = cleaned
            return dict(cleaned)

    def _read(self) -> dict[str, float]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return focus_region()
        return clamp_region(raw)


def sharpness_score(jpeg: bytes, region: dict | None = None) -> float | None:
    """Variance of a Laplacian on the center of a downscaled frame.

    Optical defocus cannot be undone. This only tells you which way the
    focus ring last moved the picture: turn until the number stops rising.
    """
    if not jpeg:
        return None
    try:
        image = Image.open(io.BytesIO(jpeg)).convert("L")
    except OSError:
        return None
    image.thumbnail((480, 320))
    width, height = image.size
    if width < 16 or height < 16:
        return None
    box = clamp_region(region) if region is not None else focus_region()
    left = int(round(width * box["left"]))
    top = int(round(height * box["top"]))
    right = min(width, left + max(8, int(round(width * box["width"]))))
    bottom = min(height, top + max(8, int(round(height * box["height"]))))
    if right - left < 8 or bottom - top < 8:
        return None
    center = image.crop((left, top, right, bottom))
    edges = center.filter(
        ImageFilter.Kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), scale=1, offset=0)
    )
    hist = edges.histogram()
    count = sum(hist)
    if count <= 0:
        return None
    mean = sum(index * count_i for index, count_i in enumerate(hist)) / count
    variance = sum(count_i * (index - mean) ** 2 for index, count_i in enumerate(hist)) / count
    return round(variance, 1)
