"""Unit tests for the LAN MJPEG Extra (no real camera)."""

from __future__ import annotations

import io
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.config import load_config, source_fetch_url
from app.fetcher import fetch_loop
from app.frame_buffer import FrameBuffer
from app.http_api import make_handler
from app.osd import burn_timestamp, format_timestamp, maybe_burn_in


def _tiny_jpeg(width: int = 64, height: int = 48, color: tuple[int, int, int] = (20, 40, 60)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_source_fetch_url_adds_width():
    cfg = {
        "source": {"url": "http://127.0.0.1:8080/raw.jpg", "width": 960},
    }
    assert source_fetch_url(cfg) == "http://127.0.0.1:8080/raw.jpg?w=960"


def test_source_fetch_url_keeps_existing_w():
    cfg = {
        "source": {"url": "http://127.0.0.1:8080/raw.jpg?w=320", "width": 960},
    }
    assert source_fetch_url(cfg) == "http://127.0.0.1:8080/raw.jpg?w=320"


def test_load_config_defaults(tmp_path: Path):
    p = tmp_path / "stream.yaml"
    p.write_text("enabled: false\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg["enabled"] is False
    assert cfg["bind_port"] == 8081
    assert cfg["source"]["width"] == 960
    assert cfg["stream"]["fps"] == 2.0
    assert cfg["overlay"]["enabled"] is True
    assert cfg["overlay"]["timezone"] == "Europe/Berlin"


def test_format_timestamp_cctv_style():
    # 2026-10-14 07:14:29 Europe/Berlin (CEST, UTC+2) = 05:14:29 UTC
    epoch = 1791954869.0
    text = format_timestamp(epoch, timezone="Europe/Berlin")
    assert text == "14/10/2026 07:14:29 WED"


def test_burn_timestamp_changes_pixels():
    jpeg = _tiny_jpeg(width=320, height=240, color=(10, 10, 10))
    stamped = burn_timestamp(jpeg, 1791954869.0, timezone="Europe/Berlin", jpeg_quality=80)
    assert stamped[:3] == b"\xff\xd8\xff"
    assert stamped != jpeg
    img = Image.open(io.BytesIO(stamped))
    # Top-left should no longer be uniform dark (white OSD + outline).
    corner = img.getpixel((20, 20))
    assert corner != (10, 10, 10)


def test_maybe_burn_in_disabled():
    jpeg = _tiny_jpeg()
    out = maybe_burn_in(
        jpeg,
        cfg={"overlay": {"enabled": False}, "stream": {}},
        frame_epoch=1791954869.0,
    )
    assert out == jpeg


def test_health_and_snapshot_and_mjpeg():
    jpeg = _tiny_jpeg()
    buffer = FrameBuffer()
    buffer.put(jpeg, etag='W/"t-1"', status=200)
    cfg = {
        "enabled": True,
        "bind_host": "127.0.0.1",
        "bind_port": 0,
        "source": {"url": "http://127.0.0.1:8080/raw.jpg", "width": 640},
        "stream": {"fps": 10, "boundary": "frame"},
    }
    port = _free_port()
    handler = make_handler(cfg, buffer, started_at=time.time())
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as resp:
            health = json.loads(resp.read().decode())
        assert health["application"] == "webcam-stream"
        assert health["status"] == "HEALTHY"
        assert health["frame"]["has_frame"] is True

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/snapshot.jpg", timeout=3) as resp:
            body = resp.read()
            assert resp.headers.get("Content-Type", "").startswith("image/jpeg")
        assert body[:3] == b"\xff\xd8\xff"

        req = urllib.request.Request(f"http://127.0.0.1:{port}/stream.mjpg")
        with urllib.request.urlopen(req, timeout=3) as resp:
            ctype = resp.headers.get("Content-Type", "")
            assert "multipart/x-mixed-replace" in ctype
            chunk = resp.read(len(jpeg) + 200)
        assert b"--frame" in chunk
        assert b"\xff\xd8\xff" in chunk
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_disabled_stream_returns_503():
    buffer = FrameBuffer()
    buffer.put(_tiny_jpeg())
    cfg = {
        "enabled": False,
        "source": {"url": "http://127.0.0.1:8080/raw.jpg", "width": 0},
        "stream": {"fps": 2, "boundary": "frame"},
    }
    port = _free_port()
    handler = make_handler(cfg, buffer, started_at=time.time())
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as resp:
            health = json.loads(resp.read().decode())
        assert health["status"] == "DISABLED"
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/stream.mjpg", timeout=3)
        assert exc.value.code == 503
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_fetcher_pulls_from_mock_camera():
    jpeg = _tiny_jpeg(width=160, height=120, color=(90, 10, 10))
    hits = {"n": 0}
    # Fixed Last-Modified so OSD uses frame time, not wall clock.
    last_mod = "Wed, 14 Oct 2026 05:14:29 GMT"

    class CamHandler(BaseHTTPRequestHandler):
        def log_message(self, *_a):  # noqa: ANN001
            return

        def do_GET(self):  # noqa: N802
            hits["n"] += 1
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Last-Modified", last_mod)
            self.send_header("Content-Length", str(len(jpeg)))
            self.end_headers()
            self.wfile.write(jpeg)

    cam_port = _free_port()
    cam = HTTPServer(("127.0.0.1", cam_port), CamHandler)
    cam_thread = threading.Thread(target=cam.serve_forever, daemon=True)
    cam_thread.start()

    buffer = FrameBuffer()
    stop = threading.Event()
    cfg = {
        "source": {
            "url": f"http://127.0.0.1:{cam_port}/raw.jpg",
            "width": 0,
            "timeout_seconds": 2,
        },
        "stream": {"fps": 20, "jpeg_quality": 80},
        "overlay": {
            "enabled": True,
            "timezone": "Europe/Berlin",
            "format": "%d/%m/%Y %H:%M:%S %a",
            "margin": 8,
            "font_scale": 0.08,
        },
    }
    th = threading.Thread(target=fetch_loop, args=(cfg, buffer, stop), daemon=True)
    th.start()
    try:
        deadline = time.time() + 3
        while time.time() < deadline and not buffer.snapshot()["has_frame"]:
            time.sleep(0.05)
        assert buffer.snapshot()["has_frame"] is True
        data, _ = buffer.get()
        assert data is not None
        assert data != jpeg  # OSD re-encoded
        assert buffer.snapshot()["source_mtime"] is not None
        assert hits["n"] >= 1
    finally:
        stop.set()
        cam.shutdown()
        cam.server_close()
