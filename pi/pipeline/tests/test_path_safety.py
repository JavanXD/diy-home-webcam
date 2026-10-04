"""Path segment guards for LAN JPEG routes."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.path_safety import safe_camera_id, safe_jpeg_filename  # noqa: E402


def test_safe_camera_id_accepts_normal():
    assert safe_camera_id("example") == "example"
    assert safe_camera_id("example") == "example"


def test_safe_camera_id_rejects_traversal():
    assert safe_camera_id("..") is None
    assert safe_camera_id("../etc") is None
    assert safe_camera_id("foo/bar") is None
    assert safe_camera_id("") is None
    assert safe_camera_id("Bad_Name") is None


def test_safe_jpeg_filename():
    assert safe_jpeg_filename("private.jpg") == "private.jpg"
    assert safe_jpeg_filename("landscape.JPG") == "landscape.JPG"
    assert safe_jpeg_filename("../etc/passwd") is None
    assert safe_jpeg_filename("..jpg") is None
    assert safe_jpeg_filename("a/b.jpg") is None
