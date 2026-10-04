"""Public live publish precedence: schedule offline > maintenance > live.

Private HA variants always render from the acquired raw original — never Wartung,
never the night placeholder.
"""

from __future__ import annotations

import hashlib
import io
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.acquire import AcquireResult  # noqa: E402
from app.main import process_camera  # noqa: E402
from app.publish_r2 import Publisher  # noqa: E402
from app.render import render_one  # noqa: E402
from app.schedule import PublicSchedule  # noqa: E402
from app.state import PipelineState  # noqa: E402
from app.weather import WeatherSnapshot  # noqa: E402
from shared.brand_overlay import WARTUNG_TITLE  # noqa: E402


CAMERA_ID = "testcam"
LIVE_KEY = "live/testcam-live-webcam.jpg"


def _write_mini_repo(root: Path) -> Path:
    cam = root / "cameras" / CAMERA_ID
    (cam / "variants").mkdir(parents=True)
    (cam / "camera.yaml").write_text(
        yaml.dump(
            {
                "id": CAMERA_ID,
                "display_name": "Test Cam",
                "source": {"url": "http://127.0.0.1:9/raw.jpg", "timeout_seconds": 2},
                "poll_interval_seconds": 60,
                "storage": {
                    "original_dir": f"data/{CAMERA_ID}/original",
                    "variants_dir": f"data/{CAMERA_ID}/variants",
                    "keep_original_history": 0,
                },
                "publish": {
                    "enabled": True,
                    "public_live_key": LIVE_KEY,
                    "history": {"enabled": True, "min_interval_seconds": 0},
                },
                "timezone": "Europe/Berlin",
                "weather": {"url": "http://127.0.0.1:9/weather", "ttl_seconds": 300},
            }
        ),
        encoding="utf-8",
    )
    (cam / "variants" / "landscape.yaml").write_text(
        yaml.dump(
            {
                "name": "landscape",
                "visibility": "public",
                "crop": {"mode": "full"},
                "output": {
                    "width": 320,
                    "height": 180,
                    "jpeg_quality": 80,
                    "filename": "landscape.jpg",
                    "r2_live_key": LIVE_KEY,
                    "r2_history_variant": "landscape",
                },
                "watermark": {"enabled": False},
                "site_badge": {"enabled": False},
                "timestamp": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )
    (cam / "variants" / "private.yaml").write_text(
        yaml.dump(
            {
                "name": "private",
                "visibility": "private",
                "crop": {"mode": "full"},
                "output": {
                    "width": 320,
                    "height": 240,
                    "jpeg_quality": 80,
                    "filename": "private.jpg",
                },
                "watermark": {"enabled": False},
                "site_badge": {"enabled": False},
                "timestamp": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )
    # Schedule: fixed window that is offline at 03:00 Berlin.
    sched_dir = root / "data" / "schedule" / CAMERA_ID
    sched_dir.mkdir(parents=True)
    (sched_dir / "config.json").write_text(
        __import__("json").dumps(
            {
                "enabled": True,
                "mode": "fixed",
                "timezone": "Europe/Berlin",
                "latitude": 48.7855,
                "longitude": 8.7490,
                "fixed": {"start": "07:00", "stop": "21:00"},
                "placeholder": {"overlay_back_at": True},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _private_cfg() -> dict:
    return {
        "name": "private",
        "visibility": "private",
        "crop": {"mode": "full"},
        "output": {"width": 320, "height": 240, "jpeg_quality": 80},
        "watermark": {"enabled": False},
        "site_badge": {"enabled": False},
        "timestamp": {"enabled": False},
    }


def test_schedule_offline_overrides_maintenance_for_public_live(tmp_path: Path, monkeypatch):
    root = _write_mini_repo(tmp_path / "repo")
    outbox = tmp_path / "outbox"
    fixture = (ROOT / "tests/fixtures/sample.jpg").read_bytes()
    # Distinct solid color so Wartung / Nacht cannot match private live pixels.
    solid = Image.new("RGB", (640, 480), (12, 84, 160))
    buf = io.BytesIO()
    solid.save(buf, format="JPEG", quality=90)
    fixture = buf.getvalue()

    monkeypatch.setattr(
        "app.main.acquire_image",
        lambda *a, **k: AcquireResult(
            ok=True,
            data=fixture,
            sha256=hashlib.sha256(fixture).hexdigest(),
            maintenance=False,  # /raw.jpg never sets the header
        ),
    )
    # Simulate GET /maintenance → enabled (raw JPEG has no X-Webcam-Maintenance).
    monkeypatch.setattr("app.main.fetch_maintenance_flag", lambda **kwargs: True)

    class _Wx:
        def get(self, *, force: bool = False) -> WeatherSnapshot:
            return WeatherSnapshot(temp_c=None, fetched_at=None, source="none")

    monkeypatch.setattr("app.main.get_weather_cache", lambda **kwargs: _Wx())

    tz = ZoneInfo("Europe/Berlin")
    night = datetime(2026, 1, 10, 3, 15, tzinfo=tz)
    real_evaluate = PublicSchedule.evaluate

    def _evaluate_offline(self, now=None):
        return real_evaluate(self, now=night)

    monkeypatch.setattr(PublicSchedule, "evaluate", _evaluate_offline)

    publisher = Publisher(
        {"enabled": True, "backend": "local", "local_outbox": str(outbox)},
        repo_root=root,
    )
    state = PipelineState(
        version="test",
        config={"publish": {"enabled": True, "backend": "local"}},
        repo_root=root,
    )

    result = process_camera(CAMERA_ID, root, state, publisher, force=True)
    assert result["ok"] is True
    assert state.cameras[CAMERA_ID]["stages"]["acquire"]["maintenance"] is True
    assert state.cameras[CAMERA_ID]["stages"]["acquire"]["maintenance_source"] == "api"

    live_path = outbox / LIVE_KEY
    assert live_path.exists()
    published = live_path.read_bytes()

    # Must be the schedule offline placeholder — not the maintenance-rendered variant.
    landscape = root / f"data/{CAMERA_ID}/variants/landscape.jpg"
    private = root / f"data/{CAMERA_ID}/variants/private.jpg"
    assert landscape.exists()
    assert private.exists()
    assert published != landscape.read_bytes()
    assert published != private.read_bytes()

    schedule = PublicSchedule(root, CAMERA_ID)
    status = schedule.evaluate()
    assert status.public_online is False
    expected = schedule.render_public_placeholder(
        status,
        size=(320, 180),
        brand="Test Cam",
    ).read_bytes()
    assert hashlib.sha256(published).hexdigest() == hashlib.sha256(expected).hexdigest()

    assert any(r.get("schedule_offline") for r in state.cameras[CAMERA_ID]["stages"]["publish"]["results"])
    assert any(
        r.get("maintenance_overridden")
        for r in state.cameras[CAMERA_ID]["stages"]["publish"]["results"]
    )
    # History must not be written for schedule-offline public live.
    assert list((outbox / "history").rglob("*.jpg")) == []

    # Private HA: always from raw original — not Wartung, not Nacht.
    original = Image.open(io.BytesIO(fixture)).convert("RGB")
    expected_private = render_one(
        original,
        _private_cfg(),
        1_700_000_000,
        "Europe/Berlin",
        maintenance=False,
    )
    wartung_private = render_one(
        original,
        _private_cfg(),
        1_700_000_000,
        "Europe/Berlin",
        repo_root=root,
        maintenance=True,
        brand="Test Cam",
    )
    got_private = Image.open(private).convert("RGB")
    assert got_private.size == expected_private.size
    assert got_private.tobytes() == expected_private.tobytes()
    assert got_private.tobytes() != wartung_private.tobytes()
    assert Image.open(landscape).size == (320, 180)
    _ = WARTUNG_TITLE  # document intent: local public may be Wartung; live key is Nacht
