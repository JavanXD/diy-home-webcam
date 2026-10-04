"""Private/variant JPEG serve — disk fail-safe + no UnboundLocalError on profile load."""

from __future__ import annotations

import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.serve_private import make_handler  # noqa: E402
from app.state import PipelineState  # noqa: E402


def test_variant_jpeg_disk_failsafe_when_map_empty(tmp_path: Path):
    """When in-memory variant map is empty, still serve JPEG from disk via profile path."""
    import shutil

    sample = ROOT / "tests/fixtures/sample.jpg"
    variants_dir = tmp_path / "data" / "schellbronn" / "variants"
    variants_dir.mkdir(parents=True)
    private_jpg = variants_dir / "private.jpg"
    shutil.copy(sample, private_jpg)

    # Minimal camera profile so load_camera_profile finds storage.variants_dir
    cam_dir = tmp_path / "cameras" / "schellbronn"
    cam_dir.mkdir(parents=True)
    (cam_dir / "camera.yaml").write_text(
        "id: schellbronn\n"
        "display_name: Test\n"
        "source:\n  url: http://127.0.0.1:8080/raw.jpg\n"
        "storage:\n  original_dir: data/schellbronn/original\n"
        "  variants_dir: data/schellbronn/variants\n"
        "publish:\n  enabled: false\n"
        "timezone: Europe/Berlin\n",
        encoding="utf-8",
    )
    (cam_dir / "variants").mkdir()
    (cam_dir / "variants" / "private.yaml").write_text(
        "name: private\n"
        "visibility: private\n"
        "output:\n  filename: private.jpg\n  width: 640\n  height: 360\n",
        encoding="utf-8",
    )

    state = PipelineState(
        version="test",
        config={"publish": {"enabled": False}},
        repo_root=tmp_path,
    )
    # Intentionally empty cameras map — forces disk fail-safe path.
    assert state.resolve_variant_path("schellbronn", "private") is None

    handler = make_handler(state, tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.error
        import urllib.request

        # Hit schedule/placeholder first so nested-import shadowing would have bitten.
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/schedule/placeholder.jpg?camera=schellbronn"
        ) as resp:
            assert resp.status == 200
            assert resp.read()[:2] == b"\xff\xd8"

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/cameras/example/variants/private.jpg"
        ) as resp:
            body = resp.read()
        assert body[:2] == b"\xff\xd8"
        assert len(body) == private_jpg.stat().st_size

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/private/schellbronn.jpg"
        ) as resp:
            alias = resp.read()
        assert alias == body

        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/cameras/example/variants/missing.jpg"
            )
            assert False, "expected 404"
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
            err = json.loads(exc.read().decode())
            assert err["error"] == "variant not found"
            assert "UnboundLocalError" not in (err.get("detail") or "")
    finally:
        server.shutdown()


def test_ha_cache_bust_skips_304_and_uses_no_store(tmp_path: Path):
    """HA template image uses ?t=; never answer that with an empty 304 body."""
    import shutil
    import urllib.request

    sample = ROOT / "tests/fixtures/sample.jpg"
    variants_dir = tmp_path / "data" / "schellbronn" / "variants"
    variants_dir.mkdir(parents=True)
    private_jpg = variants_dir / "private.jpg"
    shutil.copy(sample, private_jpg)

    cam_dir = tmp_path / "cameras" / "schellbronn"
    cam_dir.mkdir(parents=True)
    (cam_dir / "camera.yaml").write_text(
        "id: schellbronn\n"
        "display_name: Test\n"
        "source:\n  url: http://127.0.0.1:8080/raw.jpg\n"
        "storage:\n  original_dir: data/schellbronn/original\n"
        "  variants_dir: data/schellbronn/variants\n"
        "publish:\n  enabled: false\n"
        "timezone: Europe/Berlin\n",
        encoding="utf-8",
    )
    (cam_dir / "variants").mkdir()
    (cam_dir / "variants" / "private.yaml").write_text(
        "name: private\nvisibility: private\n"
        "output:\n  filename: private.jpg\n  width: 640\n  height: 360\n",
        encoding="utf-8",
    )

    state = PipelineState(
        version="test",
        config={"publish": {"enabled": False}},
        repo_root=tmp_path,
    )
    handler = make_handler(state, tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/cameras/example/variants/private.jpg"
        req1 = urllib.request.Request(url + "?t=1000")
        with urllib.request.urlopen(req1) as resp:
            assert resp.status == 200
            assert resp.headers.get("Cache-Control") == "no-store"
            etag = resp.headers.get("ETag")
            body1 = resp.read()
        assert body1[:2] == b"\xff\xd8"
        assert etag

        req2 = urllib.request.Request(
            url + "?t=1001",
            headers={"If-None-Match": etag},
        )
        with urllib.request.urlopen(req2) as resp:
            assert resp.status == 200
            assert resp.headers.get("Cache-Control") == "no-store"
            body2 = resp.read()
        assert body2 == body1

        # Gallery thumb still supports 304 when not cache-busted.
        req3 = urllib.request.Request(url + "?w=240")
        with urllib.request.urlopen(req3) as resp:
            assert resp.status == 200
            thumb_etag = resp.headers.get("ETag")
            assert resp.headers.get("Cache-Control") == "private, max-age=15"
            thumb = resp.read()
        assert thumb[:2] == b"\xff\xd8"
        req4 = urllib.request.Request(
            url + "?w=240",
            headers={"If-None-Match": thumb_etag},
        )
        try:
            urllib.request.urlopen(req4)
            assert False, "expected 304"
        except urllib.error.HTTPError as exc:
            assert exc.code == 304
    finally:
        server.shutdown()


def test_health_next_steps_not_empty_on_start():
    state = PipelineState(
        version="test",
        config={"publish": {"enabled": False}},
        repo_root=REPO,
    )
    health = state.health()
    assert "next_steps" in health
