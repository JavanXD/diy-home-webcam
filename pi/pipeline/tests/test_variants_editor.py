"""Variants LAN editor: list/get/save validation + YAML atomic write."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app import variants_editor as vedit  # noqa: E402


def test_list_and_get_schellbronn_variants():
    listing = vedit.list_variants(REPO, "example")
    assert listing["camera"] == "example"
    assert listing["count"] >= 3
    names = {v["name"] for v in listing["variants"]}
    assert {"private", "landscape", "wide"} <= names
    private = next(v for v in listing["variants"] if v["name"] == "private")
    assert private["visibility"] == "private"
    assert private["filename"] == "private.jpg"
    assert private["served_url"].endswith("/private.jpg")

    got = vedit.get_variant(REPO, "example", "landscape")
    assert got["meta"]["name"] == "landscape"
    assert got["meta"]["visibility"] == "public"
    assert "crop" in got["config"]
    assert "editable" in got and "crop" in got["editable"]
    assert "output.width" in got["editable"]
    assert "timestamp" in got["editable"]
    assert "site_badge" in got["editable"]
    assert "field_help" in got and "crop.aspect_ratio" in got["field_help"]
    assert "output.filename" in got["read_only"]
    assert "watermark" in got["read_only"]


def test_validate_crop_and_masks():
    crop = vedit.validate_crop(
        {
            "mode": "arbitrary",
            "left": 0.1,
            "top": 0.0,
            "right": 0.9,
            "bottom": 0.8,
            "zoom": 1.2,
            "aspect_ratio": "16:9",
        }
    )
    assert crop["mode"] == "arbitrary"
    assert crop["zoom"] == 1.2
    assert crop["aspect_ratio"] == "16:9"

    with pytest.raises(ValueError, match="zoom"):
        vedit.validate_crop({"zoom": 0.5})

    with pytest.raises(ValueError, match="mode"):
        vedit.validate_crop({"mode": "diagonal"})

    masks = vedit.validate_masks(
        [
            {
                "type": "rect",
                "left": 0.0,
                "top": 0.4,
                "right": 0.2,
                "bottom": 0.9,
                "mode": "blur",
                "strength": 12,
            }
        ]
    )
    assert len(masks) == 1
    assert masks[0]["mode"] == "blur"
    assert "label" not in masks[0]

    labeled = vedit.validate_masks(
        [
            {
                "type": "rect",
                "left": 0.1,
                "top": 0.5,
                "right": 0.3,
                "bottom": 0.8,
                "mode": "pixelate",
                "strength": 20,
                "label": "  left dormer  ",
            },
            {
                "type": "rect",
                "left": 0.4,
                "top": 0.5,
                "right": 0.5,
                "bottom": 0.7,
                "mode": "blur",
                "note": "legacy note key",
            },
        ]
    )
    assert labeled[0]["label"] == "left dormer"
    assert labeled[1]["label"] == "legacy note key"
    assert "note" not in labeled[1]

    with pytest.raises(ValueError, match="right>left"):
        vedit.validate_masks(
            [{"left": 0.5, "top": 0.1, "right": 0.2, "bottom": 0.3, "mode": "blur"}]
        )

    with pytest.raises(ValueError, match="label"):
        vedit.validate_masks(
            [
                {
                    "left": 0.0,
                    "top": 0.0,
                    "right": 0.1,
                    "bottom": 0.1,
                    "mode": "blur",
                    "label": "x" * 81,
                }
            ]
        )


def test_save_variant_atomic_yaml(tmp_path: Path):
    cam_dir = tmp_path / "cameras" / "schellbronn"
    variants_dir = cam_dir / "variants"
    variants_dir.mkdir(parents=True)
    (cam_dir / "camera.yaml").write_text(
        "id: schellbronn\ndisplay_name: Test\n"
        "source:\n  url: http://127.0.0.1:8080/raw.jpg\n"
        "storage:\n  original_dir: data/schellbronn/original\n"
        "  variants_dir: data/schellbronn/variants\n"
        "timezone: Europe/Berlin\n",
        encoding="utf-8",
    )
    src = REPO / "cameras/example/variants/landscape-public.yaml"
    dest = variants_dir / "landscape-public.yaml"
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    before = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert before["name"] == "landscape"

    result = vedit.save_variant(
        tmp_path,
        "schellbronn",
        "landscape",
        {
            "crop": {
                "mode": "arbitrary",
                "left": 0.12,
                "top": 0.02,
                "right": 0.88,
                "bottom": 0.7,
                "zoom": 1.0,
            },
            "privacy": {
                "masks": [
                    {
                        "type": "rect",
                        "left": 0.1,
                        "top": 0.5,
                        "right": 0.3,
                        "bottom": 0.8,
                        "mode": "pixelate",
                        "strength": 20,
                        "label": "BR blinds window",
                    }
                ]
            },
        },
    )
    assert result["config"]["crop"]["left"] == 0.12
    assert result["config"]["privacy"]["masks"][0]["mode"] == "pixelate"
    assert result["config"]["privacy"]["masks"][0]["label"] == "BR blinds window"
    # Locked fields preserved
    assert result["config"]["name"] == "landscape"
    assert result["config"]["visibility"] == "public"
    assert result["config"]["output"]["filename"] == before["output"]["filename"]

    reloaded = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert reloaded["crop"]["left"] == 0.12
    assert reloaded["privacy"]["masks"][0]["label"] == "BR blinds window"
    assert reloaded["name"] == "landscape"
    assert not dest.with_suffix(".yaml.tmp").exists()

    # Output size/quality editable; filename / R2 stay locked
    sized = vedit.save_variant(
        tmp_path,
        "schellbronn",
        "landscape",
        {
            "crop": reloaded["crop"],
            "privacy": reloaded["privacy"],
            "output": {"width": 1280, "height": 720, "jpeg_quality": 82},
            "timestamp": {"enabled": True, "position": "bottom-right", "font_size": 16},
            "site_badge": {
                "enabled": True,
                "site": "ferienpark-schellbronn.de",
                "temperature": True,
                "font_size": 20,
            },
        },
    )
    assert sized["config"]["output"]["width"] == 1280
    assert sized["config"]["output"]["height"] == 720
    assert sized["config"]["output"]["jpeg_quality"] == 82
    assert sized["config"]["output"]["filename"] == before["output"]["filename"]
    assert sized["config"]["output"].get("r2_live_key") == before["output"].get("r2_live_key")
    assert sized["config"]["timestamp"]["position"] == "bottom-right"
    assert sized["config"]["site_badge"]["font_size"] == 20

    with pytest.raises(ValueError, match="nothing to update"):
        vedit.save_variant(tmp_path, "schellbronn", "landscape", {})

    with pytest.raises(KeyError):
        vedit.get_variant(tmp_path, "schellbronn", "missing")


def _seed_camera(tmp_path: Path) -> Path:
    cam_dir = tmp_path / "cameras" / "schellbronn"
    variants_dir = cam_dir / "variants"
    variants_dir.mkdir(parents=True)
    (cam_dir / "camera.yaml").write_text(
        "id: schellbronn\ndisplay_name: Test\n"
        "source:\n  url: http://127.0.0.1:8080/raw.jpg\n"
        "storage:\n  original_dir: data/schellbronn/original\n"
        "  variants_dir: data/schellbronn/variants\n"
        "timezone: Europe/Berlin\n",
        encoding="utf-8",
    )
    for name in ("private.yaml", "landscape-public.yaml"):
        src = REPO / "cameras/example/variants" / name
        (variants_dir / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return variants_dir


def test_create_variant_from_templates(tmp_path: Path):
    variants_dir = _seed_camera(tmp_path)

    private = vedit.create_variant(
        tmp_path,
        "schellbronn",
        {"name": "courtyard", "template": "private"},
    )
    assert private["meta"]["name"] == "courtyard"
    assert private["meta"]["visibility"] == "private"
    assert private["meta"]["filename"] == "courtyard.jpg"
    assert private["meta"]["served_url"] == "/cameras/example/variants/courtyard.jpg"
    assert private["meta"]["yaml_file"] == "courtyard.yaml"
    assert (variants_dir / "courtyard.yaml").exists()
    disk = yaml.safe_load((variants_dir / "courtyard.yaml").read_text(encoding="utf-8"))
    assert disk["name"] == "courtyard"
    assert disk["output"]["filename"] == "courtyard.jpg"

    public = vedit.create_variant(
        tmp_path,
        "schellbronn",
        {"name": "plaza", "template": "landscape-public"},
    )
    assert public["meta"]["name"] == "plaza"
    assert public["meta"]["visibility"] == "public"
    assert public["meta"]["filename"] == "plaza.jpg"
    assert public["meta"]["served_url"] == "/cameras/example/variants/plaza.jpg"
    assert public["meta"]["yaml_file"] == "plaza-public.yaml"
    assert public["config"]["publish"] is False
    assert public["config"]["output"].get("r2_live_key") is None

    with pytest.raises(ValueError, match="already exists"):
        vedit.create_variant(
            tmp_path, "schellbronn", {"name": "courtyard", "template": "private"}
        )

    with pytest.raises(ValueError, match="name must be"):
        vedit.create_variant(tmp_path, "schellbronn", {"name": "Bad_Name", "template": "private"})

    with pytest.raises(ValueError, match="template"):
        vedit.create_variant(tmp_path, "schellbronn", {"name": "okname", "template": "wide"})

    listing = vedit.list_variants(tmp_path, "schellbronn")
    names = {v["name"] for v in listing["variants"]}
    assert {"private", "landscape", "courtyard", "plaza"} <= names
    assert "landscape-public" in listing["templates"]
    assert "private" in listing["templates"]


def test_create_variant_rejects_filename_collision(tmp_path: Path):
    _seed_camera(tmp_path)
    with pytest.raises(ValueError, match="filename already in use"):
        vedit.create_variant(
            tmp_path,
            "schellbronn",
            {"name": "alias", "template": "private", "filename": "private.jpg"},
        )
