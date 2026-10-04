from __future__ import annotations

import json
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
import sys

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.capture import SimulationBackend, create_backend
from app.config import load_config
from app.http_api import make_handler
from app.live_preview import DEFAULT_DURATION_SECONDS, LivePreview
from app.main import capture_loop
from app.maintenance import MaintenanceMode
from app.state import AppState, connectivity_snapshot
from app.storage import ImageStore


@pytest.fixture()
def store(tmp_path: Path) -> ImageStore:
    return ImageStore(tmp_path / "image.jpg", keep_history=2, history_dir=tmp_path / "hist")


def test_atomic_save_and_reject_empty(store: ImageStore):
    fixture = ROOT / "tests" / "fixtures" / "sample.jpg"
    data = fixture.read_bytes()
    path, meta = store.save_jpeg(data)
    assert path.exists()
    assert meta["size_bytes"] == len(data)
    with pytest.raises(ValueError):
        store.save_jpeg(b"")
    with pytest.raises(ValueError):
        store.save_jpeg(b"not-a-jpeg")


def test_simulation_backend():
    backend = SimulationBackend(ROOT / "tests" / "fixtures" / "sample.jpg")
    data = backend.capture()
    assert data[:2] == b"\xff\xd8"
    assert backend.info()["detected"] is True


def test_create_backend_rejects_unknown(tmp_path: Path):
    cfg = load_config(ROOT / "config" / "camera.example.yaml")
    cfg = {**cfg, "capture_backend": "nope"}
    with pytest.raises(ValueError, match="unknown capture_backend"):
        create_backend(cfg, ROOT)


def test_example_config_is_production_picamera2():
    cfg = load_config(ROOT / "config" / "camera.example.yaml")
    assert cfg["capture_backend"] == "picamera2"
    assert cfg["health"]["auto_maintenance_after_failures"] == 2


def test_simulation_config_is_explicit_only():
    cfg = load_config(ROOT / "config" / "camera.simulation.yaml")
    assert cfg["capture_backend"] == "simulation"
    backend = create_backend(cfg, ROOT)
    assert backend.name == "simulation"


def test_config_validation_missing_keys(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("bind_host: 0.0.0.0\n")
    with pytest.raises(ValueError, match="missing config keys"):
        load_config(bad)


class _FailingBackend:
    name = "picamera2"

    def capture(self) -> bytes:
        raise RuntimeError("camera open failed: no device")

    def info(self) -> dict:
        return {"detected": False, "model": "picamera2-unavailable", "open_error": "no device"}

    def close(self) -> None:
        return None


class _RecoveringBackend:
    name = "picamera2"

    def __init__(self) -> None:
        self.calls = 0
        self._jpeg = (ROOT / "tests" / "fixtures" / "sample.jpg").read_bytes()

    def capture(self) -> bytes:
        self.calls += 1
        if self.calls < 3:
            raise RuntimeError("temporary capture glitch")
        return self._jpeg

    def info(self) -> dict:
        if self.calls < 3:
            return {"detected": True, "model": "glitchy"}
        return {"detected": True, "model": "ok"}

    def close(self) -> None:
        return None


def test_maintenance_auto_enable_survives_readonly_data(tmp_path: Path):
    """Mid-sync PermissionError on flag must not raise; in-memory Wartung still ON."""
    data = tmp_path / "data"
    data.mkdir()
    flag = data / "maintenance.on"
    m = MaintenanceMode(flag)
    data.chmod(0o555)
    try:
        assert m.auto_enable("capture_failed") is True
        assert m.enabled and m.auto and m.reason == "capture_failed"
        # Flag may be missing if persist failed — memory still serves Wartung
        assert m.snapshot()["enabled"] is True
    finally:
        data.chmod(0o755)


def test_capture_loop_survives_permission_on_save(tmp_path: Path):
    """Errno 13 on JPEG save + flag write must not kill the capture-loop thread."""
    cfg = load_config(ROOT / "config" / "camera.example.yaml")
    cfg = {**cfg, "capture": {**cfg["capture"], "interval_seconds": 0.05}}
    data = tmp_path / "data"
    data.mkdir()
    store = ImageStore(data / "image.jpg")
    # Seed a good frame, then lock the dir so further writes fail (sync race).
    good = SimulationBackend(ROOT / "tests" / "fixtures" / "sample.jpg")
    store.save_jpeg(good.capture())
    data.chmod(0o555)

    state = AppState(version="test", config=cfg, backend_name="picamera2")
    state.camera_info = {"detected": True, "model": "imx477"}
    maintenance = MaintenanceMode(data / "maintenance.on")
    stop = threading.Event()
    backend = SimulationBackend(ROOT / "tests" / "fixtures" / "sample.jpg")

    worker = threading.Thread(
        target=capture_loop,
        args=(state, store, backend, 0.05, stop),
        kwargs={"maintenance": maintenance, "auto_after_failures": 2, "quiet_success_every": 100},
        daemon=True,
    )
    worker.start()
    deadline = time.time() + 3.0
    while time.time() < deadline and state.consecutive_failures < 3:
        time.sleep(0.05)
    alive_before_stop = worker.is_alive()
    stop.set()
    worker.join(timeout=2)

    data.chmod(0o755)
    assert alive_before_stop, "capture-loop died on PermissionError (should fail-soft)"
    assert state.consecutive_failures >= 2
    assert maintenance.enabled is True
    assert maintenance.auto is True


def test_capture_loop_auto_maintenance_no_sim_fallback(tmp_path: Path):
    cfg = load_config(ROOT / "config" / "camera.example.yaml")
    cfg = {**cfg, "capture": {**cfg["capture"], "interval_seconds": 0.05}}
    store = ImageStore(tmp_path / "image.jpg")
    state = AppState(version="test", config=cfg, backend_name="picamera2")
    state.camera_info = {"detected": False, "model": "unavailable"}
    maintenance = MaintenanceMode(tmp_path / "maintenance.on")
    stop = threading.Event()
    backend = _FailingBackend()

    worker = threading.Thread(
        target=capture_loop,
        args=(state, store, backend, 0.05, stop),
        kwargs={"maintenance": maintenance, "auto_after_failures": 2},
        daemon=True,
    )
    worker.start()
    deadline = time.time() + 3.0
    while time.time() < deadline and not maintenance.enabled:
        time.sleep(0.05)
    stop.set()
    worker.join(timeout=2)

    assert maintenance.enabled is True
    assert maintenance.auto is True
    assert maintenance.reason == "no_camera"
    assert state.backend_name == "picamera2"
    assert state.consecutive_failures >= 2
    # Fixture backend does not invent hardware; capture stays failed
    assert store.read_jpeg() is None


def test_capture_loop_auto_clears_on_recovery(tmp_path: Path):
    cfg = load_config(ROOT / "config" / "camera.example.yaml")
    store = ImageStore(tmp_path / "image.jpg")
    state = AppState(version="test", config=cfg, backend_name="picamera2")
    state.camera_info = {"detected": True, "model": "glitchy"}
    maintenance = MaintenanceMode(tmp_path / "maintenance.on")
    maintenance.auto_enable("capture_failed")
    stop = threading.Event()
    backend = _RecoveringBackend()

    worker = threading.Thread(
        target=capture_loop,
        args=(state, store, backend, 0.05, stop),
        kwargs={"maintenance": maintenance, "auto_after_failures": 2},
        daemon=True,
    )
    worker.start()
    deadline = time.time() + 3.0
    while time.time() < deadline and maintenance.enabled:
        time.sleep(0.05)
    stop.set()
    worker.join(timeout=2)

    assert maintenance.enabled is False
    assert maintenance.auto is False
    assert store.read_jpeg() is not None
    assert state.consecutive_failures == 0


def test_connectivity_auto_maintenance_wording():
    snap = connectivity_snapshot(
        "picamera2",
        {"detected": False, "open_error": "no device"},
        maintenance={"enabled": True, "auto": True, "reason": "no_camera"},
    )
    assert "simulation" not in snap
    assert snap["maintenance_auto"] is True
    assert "simulation" not in snap["detail"].lower()
    assert "Wartungsbild" in snap["detail"] or "maintenance" in snap["detail"].lower()
    # Missing camera: full /dev/video* list is diagnostic (may be empty on Mac/CI).
    assert snap["video_devices_checked"] is True
    assert "video_devices_count" in snap
    assert isinstance(snap["video_devices"], list)


def test_connectivity_healthy_omits_noisy_video_list(monkeypatch):
    """libcamera exposes many /dev/video* — healthy path should not dump them all."""
    many = [f"/dev/video{i}" for i in range(20)]
    monkeypatch.setattr("app.state._list_video_devices", lambda: many)
    snap = connectivity_snapshot(
        "picamera2",
        {"detected": True, "model": "imx477"},
    )
    assert snap["video_devices_count"] == 20
    assert snap["video_devices"] == []
    assert snap["video_devices_truncated"] is True
    miss = connectivity_snapshot(
        "picamera2",
        {"detected": False},
    )
    assert miss["video_devices"] == many
    assert miss["video_devices_truncated"] is False


def test_connectivity_fixture_backend_neutral():
    snap = connectivity_snapshot(
        "simulation",
        {"detected": True, "model": "fixture"},
    )
    assert "simulation" not in snap
    assert "simulation" not in snap["label"].lower()
    assert "simulation" not in snap["detail"].lower()
    assert "no camera" in snap["label"].lower() or "capture unavailable" in snap["label"].lower()


def test_live_preview_default_duration_is_five_minutes():
    assert DEFAULT_DURATION_SECONDS == 300.0
    lp = LivePreview()
    assert lp.duration_seconds == 300.0
    snap = lp.start()
    assert snap["enabled"] is True
    assert snap["duration_seconds"] == 300.0
    assert snap["remaining_seconds"] is not None
    assert 299.0 <= snap["remaining_seconds"] <= 300.0
    lp.stop()


def test_live_preview_auto_expiry():
    lp = LivePreview(duration_seconds=0.15, interval_seconds=0.05)
    snap = lp.start()
    assert snap["enabled"] is True
    assert snap["remaining_seconds"] is not None
    assert snap["remaining_seconds"] <= 0.15
    assert lp.active() is True
    deadline = time.time() + 1.0
    while time.time() < deadline and lp.active():
        time.sleep(0.02)
    assert lp.active() is False
    assert lp.remaining_seconds() is None
    assert lp.snapshot()["enabled"] is False


def test_live_preview_manual_stop_and_refresh():
    lp = LivePreview(duration_seconds=30, interval_seconds=0.75)
    lp.start()
    assert lp.active()
    first_remaining = lp.remaining_seconds()
    time.sleep(0.05)
    lp.start()  # refresh window
    assert lp.active()
    assert lp.remaining_seconds() >= (first_remaining or 0) - 0.01
    lp.stop()
    assert not lp.active()
    assert lp.snapshot()["enabled"] is False


def test_capture_loop_uses_preview_interval(tmp_path: Path):
    """While live preview is on, capture runs at the short interval (not 30s)."""
    cfg = load_config(ROOT / "config" / "camera.simulation.yaml")
    store = ImageStore(tmp_path / "image.jpg")
    state = AppState(version="test", config=cfg, backend_name="simulation")
    backend = SimulationBackend(ROOT / "tests" / "fixtures" / "sample.jpg")
    state.camera_info = backend.info()
    live_preview = LivePreview(duration_seconds=2.0, interval_seconds=0.08)
    live_preview.start()
    stop = threading.Event()
    worker = threading.Thread(
        target=capture_loop,
        args=(state, store, backend, 30.0, stop),  # normal interval deliberately slow
        kwargs={"live_preview": live_preview, "auto_after_failures": 0},
        daemon=True,
    )
    worker.start()
    deadline = time.time() + 1.5
    while time.time() < deadline and state.success_count < 4:
        time.sleep(0.05)
    stop.set()
    worker.join(timeout=2)
    assert state.success_count >= 4, f"expected fast captures during preview, got {state.success_count}"
    assert store.read_jpeg() is not None
    assert store.read_jpeg()[:2] == b"\xff\xd8"


def test_health_next_steps_while_maintenance_on(tmp_path: Path):
    """HEALTHY capture under Wartungsbild must not say 'No action needed'."""
    cfg = load_config(ROOT / "config" / "camera.simulation.yaml")
    store = ImageStore(tmp_path / "image.jpg")
    backend = SimulationBackend(ROOT / "tests" / "fixtures" / "sample.jpg")
    store.save_jpeg(backend.capture())
    state = AppState(version="test", config=cfg, backend_name="picamera2")
    state.camera_info = {"detected": True, "model": "imx477"}
    state.record_success(store.image_path, store.stat_current(), 0.01)

    health = state.health(
        maintenance={"enabled": True, "auto": False, "reason": "manual"}
    )
    assert health["status"] == "HEALTHY"
    assert health["fail_safe"]["serving_maintenance_placeholder"] is True
    steps = health["next_steps"]
    assert steps
    assert not any(s.lower().startswith("no action needed") for s in steps)
    joined = " ".join(steps)
    assert "Wartungsbild" in joined
    assert "/debug/ui" in joined or "/maintenance/off" in joined
    assert health["connectivity"]["level"] == "warn"


def test_http_endpoints(tmp_path: Path):
    cfg = load_config(ROOT / "config" / "camera.simulation.yaml")
    store = ImageStore(tmp_path / "image.jpg")
    backend = SimulationBackend(ROOT / "tests" / "fixtures" / "sample.jpg")
    data = backend.capture()
    store.save_jpeg(data)
    state = AppState(version="test", config=cfg, backend_name="simulation")
    state.camera_info = backend.info()
    state.record_success(store.image_path, store.stat_current(), 0.01)

    handler = make_handler(
        state,
        store,
        backend,
        cfg,
        MaintenanceMode(tmp_path / "maintenance.on"),
        LivePreview(duration_seconds=0.4, interval_seconds=0.05),
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.error
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as resp:
            health = json.loads(resp.read().decode())
        assert health["status"] in ("HEALTHY", "DEGRADED")
        assert health["version"] == "test"
        assert "next_steps" in health
        assert "fail_safe" in health
        assert "summary" in health
        assert "never_fallback_to_simulation" not in health["fail_safe"]
        assert "simulation" not in (health["fail_safe"].get("note") or "").lower()

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status") as resp:
            status = json.loads(resp.read().decode())
        assert "capture" in status
        assert status["endpoints"]["debug"].startswith("GET")

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/debug") as resp:
            debug = json.loads(resp.read().decode())
        assert "troubleshoot" in debug

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/raw.jpg") as resp:
            body = resp.read()
            assert resp.headers.get("Content-Type", "").startswith("image/jpeg")
            assert resp.headers.get("X-Webcam-Maintenance") is None
        assert body[:2] == b"\xff\xd8"
        assert body == data

        # /image.jpg removed — no alias
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/image.jpg")
            assert False, "expected 404 for /image.jpg"
        except urllib.error.HTTPError as e:
            assert e.code == 404

        # /raw serves the same JPEG as /raw.jpg (no separate alias path)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/raw") as resp:
            assert resp.read() == body
            assert resp.headers.get("Content-Type", "").startswith("image/jpeg")

        # /feed.jpg matches raw when maintenance is off
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/feed.jpg") as resp:
            feed_off = resp.read()
            assert resp.headers.get("X-Webcam-Maintenance") is None
        assert feed_off == body

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/feed") as resp:
            assert resp.read() == body

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/raw.jpg?w=320") as resp:
            thumb = resp.read()
        assert thumb[:2] == b"\xff\xd8"
        assert len(thumb) <= len(body)

        # Conditional GET
        etag = None
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/raw.jpg") as resp:
            etag = resp.headers.get("ETag")
            resp.read()
        if etag:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/raw.jpg",
                headers={"If-None-Match": etag},
            )
            try:
                urllib.request.urlopen(req)
                assert False, "expected 304"
            except urllib.error.HTTPError as e:
                assert e.code == 304

        req = urllib.request.Request(f"http://127.0.0.1:{port}/capture", method="POST", data=b"")
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode())
        assert payload["ok"] is True

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/maintenance/on", method="POST", data=b""
        )
        with urllib.request.urlopen(req) as resp:
            toggled = json.loads(resp.read().decode())
        assert toggled["enabled"] is True
        assert toggled.get("auto") is False
        flag = tmp_path / "maintenance.on"
        assert flag.exists()

        # Maintenance ON: raw stays live; feed becomes Wartungsbild
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/raw.jpg") as resp:
            raw_on = resp.read()
            assert resp.headers.get("X-Webcam-Maintenance") is None
        assert raw_on == store.read_jpeg()
        assert raw_on == data

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/feed.jpg") as resp:
            placeholder = resp.read()
            assert resp.headers.get("X-Webcam-Maintenance") == "1"
        assert placeholder[:2] == b"\xff\xd8"
        assert placeholder != data
        assert placeholder != raw_on

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as resp:
            health = json.loads(resp.read().decode())
        assert "connectivity" in health
        assert "simulation" not in health["connectivity"]
        assert "simulation" not in health["connectivity"]["label"].lower()
        assert "simulation" not in health["connectivity"]["detail"].lower()
        assert "no camera" in health["connectivity"]["label"].lower()
        assert health["maintenance"]["enabled"] is True
        assert health["maintenance"]["auto"] is False
        steps = " ".join(health.get("next_steps") or [])
        assert "No action needed" not in steps
        assert "Wartungsbild" in steps or "maintenance" in steps.lower()
        assert "/debug/ui" in steps or "/maintenance/off" in steps

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            home = resp.read().decode()
        assert "Camera home" in home
        assert "<title>Webcam — Camera home</title>" in home
        assert "Webcam Schellbronn" not in home
        assert "Overview" not in home
        assert "/debug/ui" in home
        assert "Camera status" in home
        assert "leitet hierher" not in home
        assert "Port 80/443" not in home
        assert 'class="nav"' in home
        assert "nav-cam" in home and "nav-pipe" in home
        assert 'id="nav-toggle"' in home
        assert "nav-chip-cam" in home and "max-width: 480px" in home
        assert "Schedule" in home
        assert "Maintenance" in home
        assert "window.lanUi" in home
        assert "--bg:" in home and "#e6e9ee" in home
        assert "status-badge" in home
        assert "panel-head" in home
        assert "--cam:" in home and "--pipe:" in home
        assert 'class="svc-cam"' in home
        assert "focus-visible" in home or "--focus:" in home
        assert "camera service" in home
        assert "Capture now" in home
        assert "Start live preview" in home
        assert "live-preview-toggle" in home
        assert "live-preview-meter" in home
        assert "live-preview-fill" in home
        assert 'id="focus-region"' in home
        assert "focus-handle" in home
        assert "bindFocusBox" in home
        save_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/focus-region",
            data=json.dumps({"left": 0.55, "top": 0.12, "width": 0.1, "height": 0.18}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(save_req) as resp:
            saved = json.loads(resp.read().decode())
        assert saved["region"]["left"] == 0.55
        assert (tmp_path / "focus-region.json").is_file()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/focus-score") as resp:
            scored = json.loads(resp.read().decode())
        assert scored["region"]["width"] == 0.1
        assert 'id="focus-score"' in home
        assert "focus-score" in home and "#ffe14a" in home
        assert "live-start" in home
        assert "/live-preview" in home
        assert "750" in home  # live preview poll ms
        assert "5 min" in home or "5&nbsp;min" in home or "300" in home
        assert "Pipeline" in home  # nav cluster label only
        assert "ferienpark-schellbronn.de" not in home
        assert "Public schedule" not in home
        assert "Private variant" not in home
        assert "LAN hub" not in home
        assert "<h2>Pipeline" not in home
        assert "Live preview" in home or "Live & capture" in home
        assert "preview-frame" in home
        assert "swapImg" in home
        assert ">More</button>" in home
        assert 'id="nav-more-cam"' in home and 'id="nav-more-pipe"' in home
        assert 'data-lan-path="/health"' in home
        assert 'data-lan-path="/raw.jpg"' in home
        assert 'data-lan-path="/feed.jpg"' in home
        assert "/image.jpg" not in home
        assert "/raw.jpg?" in home
        assert "always the last live capture" in home or "always live" in home.lower()
        assert "/feed.jpg" in home
        assert "w=720" not in home
        assert 'class="preview-frame is-sharp"' in home
        assert 'id="focus-cue"' in home
        assert "/raw.jpg?t=" in home
        assert "30000" in home
        assert "visibilitychange" in home
        # Body no longer dumps JSON endpoint link spam
        assert "JSON: <a" not in home
        assert 'href="/health">/health' not in home
        assert "Auto Wartungsbild" in home or "Auto maintenance" in home or "cam-connectivity" in home

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/debug/ui") as resp:
            page = resp.read().decode()
        assert "Maintenance" in page
        assert "What does this mean" in page or "live" in page.lower()
        assert "Start live preview" in page or "Camera home" in page
        assert 'class="nav"' in page
        assert "cam-connectivity-mini" in page
        assert "nav-cam" in page
        assert "window.lanUi" in page
        assert 'class="svc-cam"' in page
        assert "Turn maintenance" in page or "Please wait" in page
        assert "/feed.jpg?" in page
        assert "aim" in page.lower() or "Raw" in page

        # Live preview on: health reports it; raw stays live JPEG (not Wartung)
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/live-preview/on", method="POST", data=b""
        )
        with urllib.request.urlopen(req) as resp:
            lp_on = json.loads(resp.read().decode())
        assert lp_on["ok"] is True
        assert lp_on["enabled"] is True
        assert lp_on["remaining_seconds"] is not None
        assert lp_on["remaining_seconds"] > 0

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as resp:
            health = json.loads(resp.read().decode())
        assert health["live_preview"]["enabled"] is True

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/raw.jpg") as resp:
            raw_preview = resp.read()
            assert resp.headers.get("X-Webcam-Live-Preview") == "1"
            assert resp.headers.get("X-Webcam-Maintenance") is None
        assert raw_preview[:2] == b"\xff\xd8"
        assert raw_preview == store.read_jpeg()

        # Auto-expiry
        snap = {"enabled": True}
        deadline = time.time() + 2.0
        while time.time() < deadline:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/live-preview") as resp:
                snap = json.loads(resp.read().decode())
            if not snap.get("enabled"):
                break
            time.sleep(0.05)
        assert snap["enabled"] is False

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/live-preview/on", method="POST", data=b""
        )
        with urllib.request.urlopen(req) as resp:
            json.loads(resp.read().decode())
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/live-preview/off", method="POST", data=b""
        )
        with urllib.request.urlopen(req) as resp:
            lp_off = json.loads(resp.read().decode())
        assert lp_off["enabled"] is False

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/maintenance",
            data=b'{"enabled": false}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            toggled = json.loads(resp.read().decode())
        assert toggled["enabled"] is False
        assert not flag.exists()

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/raw.jpg") as resp:
            live = resp.read()
            assert resp.headers.get("X-Webcam-Maintenance") is None
        assert live == store.read_jpeg()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/feed.jpg") as resp:
            feed_live = resp.read()
            assert resp.headers.get("X-Webcam-Maintenance") is None
        assert feed_live == live
    finally:
        server.shutdown()
