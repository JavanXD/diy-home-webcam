"""Acquire helpers: raw JPEG + separate maintenance probe."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.acquire import (  # noqa: E402
    fetch_maintenance_flag,
    maintenance_api_url,
)


def test_maintenance_api_url_from_raw_and_health():
    assert (
        maintenance_api_url(source_url="http://127.0.0.1:8080/raw.jpg")
        == "http://127.0.0.1:8080/maintenance"
    )
    assert (
        maintenance_api_url(health_url="http://127.0.0.1:8080/health")
        == "http://127.0.0.1:8080/maintenance"
    )
    assert maintenance_api_url(source_url="not-a-url") is None


def test_fetch_maintenance_flag_prefers_maintenance_endpoint():
    maint_resp = MagicMock()
    maint_resp.status_code = 200
    maint_resp.json.return_value = {"enabled": True, "auto": False}

    with patch("app.acquire.httpx.Client") as client_cls:
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.get.return_value = maint_resp
        client_cls.return_value = client
        assert (
            fetch_maintenance_flag(
                maintenance_url="http://127.0.0.1:8080/maintenance",
                health_url="http://127.0.0.1:8080/health",
            )
            is True
        )
        assert client.get.call_args[0][0] == "http://127.0.0.1:8080/maintenance"


def test_fetch_maintenance_flag_falls_back_to_health():
    bad = MagicMock()
    bad.status_code = 404
    health = MagicMock()
    health.status_code = 200
    health.json.return_value = {"maintenance": {"enabled": False, "auto": False}}

    with patch("app.acquire.httpx.Client") as client_cls:
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.get.side_effect = [bad, health]
        client_cls.return_value = client
        assert (
            fetch_maintenance_flag(
                maintenance_url="http://127.0.0.1:8080/maintenance",
                health_url="http://127.0.0.1:8080/health",
            )
            is False
        )


def test_render_variants_private_ignores_maintenance(tmp_path: Path):
    """Private HA variants must render from raw original even when maintenance is on."""
    from PIL import Image

    from app.render import render_variants

    photo = Image.new("RGB", (800, 600), (40, 90, 130))
    original = tmp_path / "original.jpg"
    photo.save(original, quality=90)
    asset = tmp_path / "pi/camera/app/assets/maintenance-base.jpg"
    asset.parent.mkdir(parents=True)
    Image.new("RGB", (800, 450), (10, 20, 10)).save(asset, quality=90)

    private = {
        "name": "private",
        "visibility": "private",
        "crop": {"mode": "full"},
        "output": {"width": 400, "height": 300, "filename": "private.jpg", "jpeg_quality": 85},
        "watermark": {"enabled": False},
        "site_badge": {"enabled": False},
        "timestamp": {"enabled": False},
    }
    public = {
        "name": "landscape",
        "visibility": "public",
        "crop": {"mode": "full"},
        "output": {"width": 400, "height": 225, "filename": "landscape.jpg", "jpeg_quality": 85},
        "watermark": {"enabled": False},
        "site_badge": {"enabled": False},
        "timestamp": {"enabled": False},
        "publish": True,
    }
    results = render_variants(
        original_path=original,
        source_sha="abc",
        captured_at=1_700_000_000,
        timezone_name="Europe/Berlin",
        variant_configs=[private, public],
        variants_dir=tmp_path / "variants",
        repo_root=tmp_path,
        maintenance=True,
        brand="Test Cam",
    )
    assert {r.name: r.changed for r in results} == {"private": True, "landscape": True}
    priv = Image.open(tmp_path / "variants/private.jpg").convert("RGB")
    pub = Image.open(tmp_path / "variants/landscape.jpg").convert("RGB")
    # Private keeps the blueish live scene; public Wartung base is dark green/black.
    assert priv.getpixel((20, 20))[2] > 100
    assert pub.getpixel((20, 20))[2] < 60
    cache = json.loads((tmp_path / "variants/.render-cache.json").read_text(encoding="utf-8"))
    assert cache["private"]["maintenance"] is False
    assert cache["landscape"]["maintenance"] is True


def test_maintenance_plain_slide_when_photo_missing(tmp_path, monkeypatch):
    from PIL import Image

    from app import render as render_mod
    from shared.brand_overlay import StatusCopy

    monkeypatch.setattr(render_mod, "_MAINTENANCE_BASE", tmp_path / "missing-base.jpg")
    original = Image.new("RGB", (80, 60), (200, 20, 20))
    variant = {
        "name": "landscape",
        "visibility": "public",
        "crop": {"mode": "full"},
        "output": {"width": 160, "height": 90},
    }
    img = render_mod.render_one(
        original,
        variant,
        1,
        "UTC",
        repo_root=tmp_path,
        maintenance=True,
        brand="Shed",
        status=StatusCopy.german(),
    )
    assert img.size == (160, 90)
    corner = img.getpixel((1, 1))
    assert corner[0] < 40
    assert corner[2] >= corner[0]
    assert corner != (200, 20, 20)
