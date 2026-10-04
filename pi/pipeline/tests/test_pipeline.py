from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.render import (
    render_variants,
    _norm_box,
    _apply_artistic,
    format_burnin_timestamp,
    DEFAULT_TIMESTAMP_FORMAT,
)
from app.store import OriginalStore
from app.publish_r2 import Publisher
from PIL import Image


def test_store_rejects_unchanged(tmp_path: Path):
    store = OriginalStore(tmp_path / "orig", keep_history=2)
    data = (ROOT / "tests/fixtures/sample.jpg").read_bytes()
    first = store.save_if_changed(data)
    second = store.save_if_changed(data)
    assert first.changed is True
    assert second.changed is False
    assert first.sha256 == second.sha256


def test_render_variants_from_fixture(tmp_path: Path):
    fixture = ROOT / "tests/fixtures/sample.jpg"
    variants_dir = tmp_path / "variants"
    cam_variants = REPO / "cameras/example/variants"
    configs = []
    for path in sorted(cam_variants.glob("*.yaml")):
        configs.append(yaml.safe_load(path.read_text()))

    rendered = render_variants(
        original_path=fixture,
        source_sha="abc",
        captured_at=1_700_000_000,
        timezone_name="Europe/Berlin",
        variant_configs=configs,
        variants_dir=variants_dir,
        force=True,
        repo_root=REPO,
    )
    assert len(rendered) == 4
    assert all(r.path.exists() for r in rendered)
    names = {r.name for r in rendered}
    assert names == {"private", "landscape", "wide", "tower"}

    # Public variants should be larger once logo is composited vs tiny fixture alone
    landscape = next(r for r in rendered if r.name == "landscape")
    assert landscape.path.stat().st_size > 5_000

    # cache hit
    again = render_variants(
        original_path=fixture,
        source_sha="abc",
        captured_at=1_700_000_000,
        timezone_name="Europe/Berlin",
        variant_configs=configs,
        variants_dir=variants_dir,
        force=False,
        repo_root=REPO,
    )
    assert all(r.changed is False for r in again)


def test_local_publisher_outbox(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(REPO)
    cfg = {
        "enabled": True,
        "backend": "local",
        "local_outbox": str(tmp_path / "outbox"),
    }
    pub = Publisher(cfg, repo_root=REPO)
    src = ROOT / "tests/fixtures/sample.jpg"
    result = pub.publish_public(
        camera_id="example",
        variant_name="landscape",
        local_path=src,
        live_key="live/example-live-webcam.jpg",
        history_variant="landscape",
        history_cfg={"enabled": True, "min_interval_seconds": 0},
        captured_at=1_700_000_000,
    )
    assert result.ok is True
    assert (tmp_path / "outbox/live/example-live-webcam.jpg").exists()
    hist = list((tmp_path / "outbox/history/example/landscape").rglob("*.jpg"))
    assert len(hist) == 1


def test_publisher_skips_history_during_maintenance(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(REPO)
    pub = Publisher(
        {"enabled": True, "backend": "local", "local_outbox": str(tmp_path / "outbox")},
        repo_root=REPO,
    )
    src = ROOT / "tests/fixtures/sample.jpg"
    result = pub.publish_public(
        camera_id="example",
        variant_name="landscape",
        local_path=src,
        live_key="live/example-live-webcam.jpg",
        history_variant="landscape",
        history_cfg={"enabled": True, "min_interval_seconds": 0},
        captured_at=1_700_000_000,
        skip_history=True,
        skip_history_reason="schedule/offline placeholder",
    )
    assert result.ok is True
    assert result.history_key is None
    assert list((tmp_path / "outbox/history").rglob("*.jpg")) == []


def test_publisher_keeps_live_and_skips_history_when_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(REPO)
    pub = Publisher(
        {"enabled": True, "backend": "local", "local_outbox": str(tmp_path / "outbox")},
        repo_root=REPO,
    )
    src = ROOT / "tests/fixtures/sample.jpg"
    result = pub.publish_public(
        camera_id="example",
        variant_name="landscape",
        local_path=src,
        live_key="live/example-live-webcam.jpg",
        history_variant="landscape",
        history_cfg={"enabled": False, "min_interval_seconds": 0},
        captured_at=1_700_000_000,
    )
    assert result.ok is True
    assert result.history_key is None
    assert (tmp_path / "outbox/live/example-live-webcam.jpg").is_file()
    assert list((tmp_path / "outbox/history").rglob("*.jpg")) == []


def test_pipeline_health_has_guidance():
    from app.state import PipelineState

    state = PipelineState(version="test", config={"publish": {"enabled": False}}, repo_root=REPO)
    health = state.health()
    assert health["status"] == "STARTING"
    assert "next_steps" in health
    assert health["fail_safe"]["never_publish_private_or_original"] is True
    debug = state.debug()
    assert "troubleshoot" in debug


def test_format_burnin_timestamp_berlin_cest_and_cet():
    """Freeze known UTC instants → Europe/Berlin wall clock (no CEST/UTC suffix)."""
    from datetime import datetime, timezone

    # 2026-06-21 12:00 UTC → 14:00 Berlin (CEST, UTC+2)
    summer_utc = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc).timestamp()
    assert format_burnin_timestamp(summer_utc, "Europe/Berlin") == "2026-06-21 14:00"
    # 2026-01-15 12:00 UTC → 13:00 Berlin (CET, UTC+1)
    winter_utc = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc).timestamp()
    assert format_burnin_timestamp(winter_utc, "Europe/Berlin") == "2026-01-15 13:00"
    # Default format must not include %Z (ambiguous CEST/CET abbreviations).
    assert "%Z" not in DEFAULT_TIMESTAMP_FORMAT
    assert "CEST" not in format_burnin_timestamp(summer_utc, "Europe/Berlin")
    assert "UTC" not in format_burnin_timestamp(summer_utc, "Europe/Berlin")
    # Custom format still converts via ZoneInfo first.
    assert (
        format_burnin_timestamp(summer_utc, "Europe/Berlin", "%H:%M") == "14:00"
    )


def test_crop_modes_and_artistic():
    box = _norm_box({"mode": "full"}, 1000, 800)
    assert box == (0, 0, 1000, 800)
    box = _norm_box({"mode": "centered", "width_frac": 0.5, "height_frac": 0.5}, 1000, 800)
    assert box[2] - box[0] == 500
    assert box[3] - box[1] == 400
    box = _norm_box(
        {"mode": "arbitrary", "left": 0.1, "top": 0.1, "right": 0.9, "bottom": 0.9, "zoom": 2},
        1000,
        1000,
    )
    assert box[2] - box[0] == 400  # 0.8 * 1000 / 2
    img = Image.new("RGB", (100, 50), (10, 20, 30))
    out = _apply_artistic(img, {"horizontal_stretch": 1.1})
    assert out.width == 110
