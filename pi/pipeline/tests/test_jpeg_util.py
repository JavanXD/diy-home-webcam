"""Tests for shared JPEG thumb helper."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from shared.jpeg_util import downscale_jpeg, parse_max_width  # noqa: E402


def _jpeg(w: int, h: int, *, quality: int = 90) -> bytes:
    img = Image.new("RGB", (w, h), (40, 80, 120))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def test_parse_max_width():
    assert parse_max_width(None) is None
    assert parse_max_width("") is None
    assert parse_max_width("240") == 240
    assert parse_max_width("10") is None  # below floor
    assert parse_max_width("9999", cap=1280) == 1280


def test_downscale_jpeg_shrinks():
    src = _jpeg(1600, 900)
    out = downscale_jpeg(src, 240, quality=70)
    assert out[:2] == b"\xff\xd8"
    assert len(out) < len(src)
    with Image.open(io.BytesIO(out)) as im:
        assert im.size[0] == 240


def test_downscale_noop_when_smaller():
    src = _jpeg(200, 100)
    out = downscale_jpeg(src, 240)
    assert out == src
