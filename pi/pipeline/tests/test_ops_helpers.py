from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "pi" / "pipeline"))

from app.camera_profile import load_camera_profile  # noqa: E402


def test_source_url_env_override(monkeypatch):
    monkeypatch.setenv("WEBCAM_EXAMPLE_SOURCE_URL", "http://10.0.0.9:8080/raw.jpg")
    monkeypatch.setenv("WEBCAM_EXAMPLE_HEALTH_URL", "http://10.0.0.9:8080/health")
    profile = load_camera_profile(REPO, "example")
    assert profile.source_url == "http://10.0.0.9:8080/raw.jpg"
    assert profile.health_url == "http://10.0.0.9:8080/health"
    assert profile.history.get("retention_days") == 90
    assert profile.history.get("enabled") is False
    assert profile.timelapse.get("enabled") is True
    assert profile.timelapse.get("max_gb") == 40
    assert profile.timelapse.get("retention_days") == 400
    assert profile.status_text.night_title == "Offline at night"
    assert profile.status_text.maintenance_title == "Maintenance"
    assert profile.status_text.back_at_label == "Back at"


def test_make_timelapse_script(tmp_path: Path):
    from PIL import Image
    import subprocess

    inp = tmp_path / "in"
    inp.mkdir()
    for i in range(4):
        Image.new("RGB", (80, 60), (i * 30, 100, 50)).save(inp / f"{i:02d}.jpg")
    out = tmp_path / "out.gif"
    script = REPO / "scripts" / "make-timelapse.py"
    subprocess.check_call(
        [sys.executable, str(script), "-i", str(inp), "-o", str(out), "--delay-ms", "50"],
    )
    assert out.exists() and out.stat().st_size > 100
