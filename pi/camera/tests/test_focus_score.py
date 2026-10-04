"""Center sharpness score: a sharp frame outranks a blurred one."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.focus_score import FocusRegionStore, clamp_region, focus_region, sharpness_score  # noqa: E402


def _jpeg(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_sharp_edges_score_higher_than_blur():
    sharp = Image.new("L", (240, 160), 0)
    for x in range(0, 240, 3):
        for y in range(160):
            sharp.putpixel((x, y), 255)
    blurred = sharp.filter(ImageFilter.GaussianBlur(radius=6))
    sharp_score = sharpness_score(_jpeg(sharp))
    blur_score = sharpness_score(_jpeg(blurred))
    assert sharp_score is not None and blur_score is not None
    assert sharp_score > blur_score * 2


def test_focus_region_is_the_middle_of_the_frame():
    region = focus_region()
    assert region["left"] == region["top"] == 0.3
    assert region["width"] == region["height"] == 0.4


def test_clamp_region_keeps_the_box_inside_the_frame():
    box = clamp_region({"left": 0.95, "top": -1, "width": 0.5, "height": 0.001})
    assert box["top"] == 0
    assert box["height"] == 0.02
    assert box["left"] + box["width"] <= 1.0
    assert clamp_region({"left": "nope"}) == focus_region()


def test_score_uses_the_chosen_box():
    image = Image.new("L", (300, 200), 40)
    for x in range(80):
        for y in range(200):
            image.putpixel((x, y), 255 if (x + y) % 2 == 0 else 0)
    jpeg = _jpeg(image)
    left = sharpness_score(jpeg, {"left": 0.0, "top": 0.1, "width": 0.2, "height": 0.8})
    right = sharpness_score(jpeg, {"left": 0.7, "top": 0.1, "width": 0.2, "height": 0.8})
    assert left is not None and right is not None
    assert left > right * 2


def test_focus_region_store_persists(tmp_path: Path):
    path = tmp_path / "focus-region.json"
    store = FocusRegionStore(path)
    assert store.get() == focus_region()
    saved = store.save({"left": 0.55, "top": 0.12, "width": 0.1, "height": 0.18})
    assert FocusRegionStore(path).get() == saved
