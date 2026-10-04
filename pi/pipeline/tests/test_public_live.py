"""Public-live selection: fixed R2 key, runtime variant switch."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.public_live import (  # noqa: E402
    PublicLiveSelection,
    default_variant_name,
    publish_live_key_for_variant,
    resolve_fixed_live_key_from_repo,
)
from app.variants_editor import _output_filename_for  # noqa: E402


FIXED = "live/example-live-webcam.jpg"


def test_fixed_live_key_from_camera_yaml():
    assert resolve_fixed_live_key_from_repo(REPO, "example") == FIXED


def test_default_variant_is_landscape():
    from app.camera_profile import load_camera_profile

    profile = load_camera_profile(REPO, "example")
    assert default_variant_name(profile, FIXED) == "landscape"


def test_output_filename_is_variant_slug():
    assert _output_filename_for("example", "landscape", "public") == "landscape.jpg"
    assert _output_filename_for("example", "wide", "public") == "wide.jpg"
    assert _output_filename_for("example", "private", "private") == "private.jpg"


def test_publish_maps_selected_to_fixed_key_regardless_of_variant_key():
    # Selected wide (publish:false, no own key) → still fixed live key
    assert (
        publish_live_key_for_variant(
            variant_name="wide",
            visibility="public",
            publish_enabled=False,
            variant_r2_live_key=None,
            public_live_variant="wide",
            fixed_live_key=FIXED,
        )
        == FIXED
    )
    # Landscape selected → fixed key even if its yaml also lists that key
    assert (
        publish_live_key_for_variant(
            variant_name="landscape",
            visibility="public",
            publish_enabled=True,
            variant_r2_live_key=FIXED,
            public_live_variant="landscape",
            fixed_live_key=FIXED,
        )
        == FIXED
    )
    # Non-selected landscape must not also publish to the fixed key
    assert (
        publish_live_key_for_variant(
            variant_name="landscape",
            visibility="public",
            publish_enabled=True,
            variant_r2_live_key=FIXED,
            public_live_variant="wide",
            fixed_live_key=FIXED,
        )
        is None
    )
    # Private never publishes
    assert (
        publish_live_key_for_variant(
            variant_name="private",
            visibility="private",
            publish_enabled=False,
            variant_r2_live_key=None,
            public_live_variant="private",
            fixed_live_key=FIXED,
        )
        is None
    )
    # Secondary stream: different key + publish true + not selected
    assert (
        publish_live_key_for_variant(
            variant_name="wide",
            visibility="public",
            publish_enabled=True,
            variant_r2_live_key="live/example-wide-webcam.jpg",
            public_live_variant="landscape",
            fixed_live_key=FIXED,
        )
        == "live/example-wide-webcam.jpg"
    )


def test_selection_persists_and_rejects_private(tmp_path: Path):
    cam_dir = tmp_path / "cameras" / "example"
    variants_dir = cam_dir / "variants"
    variants_dir.mkdir(parents=True)
    (cam_dir / "camera.yaml").write_text(
        "id: example\ndisplay_name: Test\n"
        "source:\n  url: http://127.0.0.1:8080/raw.jpg\n"
        "storage:\n  original_dir: data/example/original\n"
        "  variants_dir: data/example/variants\n"
        "publish:\n  public_live_key: live/example-live-webcam.jpg\n"
        "timezone: Europe/Berlin\n",
        encoding="utf-8",
    )
    for src_name, dest_name in (
        ("landscape-public.yaml", "landscape-public.yaml"),
        ("wide-public.yaml", "wide-public.yaml"),
        ("private.yaml", "private.yaml"),
    ):
        src = REPO / "cameras/example/variants" / src_name
        (variants_dir / dest_name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    pl = PublicLiveSelection(tmp_path, "example")
    status = pl.status()
    assert status["live_key"] == FIXED
    assert status["public_url_path"] == "/example-live-webcam.jpg"
    assert status["variant"] == "landscape"
    assert status["persisted"] is False

    updated = pl.set_variant("wide", force_publish=True)
    assert updated["variant"] == "wide"
    assert updated["live_key"] == FIXED
    assert updated["force_publish"] is True
    raw = json.loads((tmp_path / "data/example/public-live.json").read_text(encoding="utf-8"))
    assert raw["variant"] == "wide"
    assert raw["live_key"] == FIXED

    assert pl.consume_force_publish() is True
    assert pl.consume_force_publish() is False
    assert pl.variant_name() == "wide"

    with pytest.raises(ValueError, match="not public"):
        pl.set_variant("private")

    # Stale private selection falls back
    (tmp_path / "data/example/public-live.json").write_text(
        json.dumps({"variant": "private"}) + "\n", encoding="utf-8"
    )
    assert pl.variant_name() == "landscape"


def test_shipped_yaml_filenames_match_slug():
    for name, yaml_file in (
        ("landscape", "landscape-public.yaml"),
        ("wide", "wide-public.yaml"),
        ("private", "private.yaml"),
    ):
        raw = yaml.safe_load(
            (REPO / "cameras/example/variants" / yaml_file).read_text(encoding="utf-8")
        )
        assert raw["name"] == name
        assert raw["output"]["filename"] == f"{name}.jpg"
