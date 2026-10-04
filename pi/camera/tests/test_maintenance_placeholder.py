"""Camera maintenance JPEG when a custom maintenance photo is not installed."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.maintenance import MaintenanceMode  # noqa: E402


def test_missing_maintenance_asset_is_a_plain_jpeg(tmp_path: Path, monkeypatch):
    import app.maintenance as maintenance

    monkeypatch.setattr(maintenance, "_ASSET", tmp_path / "missing.jpg")
    mode = MaintenanceMode(tmp_path / "flag")
    assert mode.jpeg[:2] == b"\xff\xd8"
    im = Image.open(__import__("io").BytesIO(mode.jpeg))
    assert im.size == (1280, 720)
    corner = im.getpixel((2, 2))
    assert corner[0] < 40
    assert corner[2] >= corner[0]
