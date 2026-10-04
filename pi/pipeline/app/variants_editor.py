"""LAN Variants editor: list/get/create/validate/save YAML + dry-run JPEG preview."""

from __future__ import annotations

import copy
import io
import os
import re
import time
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

from .camera_profile import load_camera_profile
from .public_live import PublicLiveSelection, is_public_live_eligible
from .render import render_one

_CROP_MODES = frozenset({"", "full", "centered", "arbitrary"})
_MASK_MODES = frozenset({"blur", "pixelate", "black", "solid"})
_MASK_TYPES = frozenset({"rect"})
_TS_POSITIONS = frozenset({"bottom-left", "bottom-right", "top-left", "top-right"})
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
_TEMPLATES = frozenset({"private", "landscape-public", "landscape"})
_TEMPLATE_FILES = {
    "private": "private.yaml",
    "landscape": "landscape-public.yaml",
    "landscape-public": "landscape-public.yaml",
}

# Short English help for the LAN editor (and API consumers).
FIELD_HELP: dict[str, str] = {
    "description": "Optional note — saved in the settings file only.",
    "crop.mode": "How to pick the area of the full camera frame: entire frame, centered box, or custom left/top/right/bottom edges.",
    "crop.ltrb": "Custom crop edges as fractions of the full frame (0 = left/top edge, 1 = right/bottom edge). Used only in arbitrary mode.",
    "crop.width_frac": "Centered mode: how much of the frame width to keep (0.5 = half width), before zoom.",
    "crop.height_frac": "Centered mode: how much of the frame height to keep (0.5 = half height), before zoom.",
    "crop.zoom": "1 = no zoom. Values above 1 zoom into the center of the crop without stretching.",
    "crop.aspect_ratio": "Crop width:height (e.g. 16:9) before scaling to output size. Match the output size for a clean scale.",
    "output.width": "Final image width in pixels. The crop is scaled to fill this size without squashing.",
    "output.height": "Final image height in pixels.",
    "output.jpeg_quality": "JPEG quality from 1 (small) to 95 (large). Public frames are usually 78–85.",
    "privacy.masks": "Hide neighbors. Drag a rectangle on the preview, or type one line as left,top,right,bottom,mode,strength — optional label after #. Labels stay in the settings file only.",
    "timestamp.enabled": "Draw the capture time on the image (camera timezone).",
    "timestamp.position": "Which corner shows the timestamp.",
    "timestamp.opacity": "Text opacity from 0 (invisible) to 1 (solid).",
    "timestamp.font_size": "Timestamp size in pixels at the final image size.",
    "timestamp.margin": "Padding from the chosen corner, in pixels.",
    "timestamp.stroke_width": "Dark outline around the timestamp (0 = none). Default 2.",
    "site_badge.enabled": "Draw a site name / temperature label in the top-left.",
    "site_badge.site": "Hostname shown in the badge (for example example.com).",
    "site_badge.temperature": "Append outdoor °C from the camera weather feed when available.",
    "site_badge.font_size": "Badge text size in pixels.",
    "site_badge.margin": "Padding from the top-left corner, in pixels.",
    "site_badge.stroke_width": "Dark outline around the badge (0 = none). Default 2.",
    "artistic.horizontal_stretch": "Optional wide look (0.85–1.25). Leave empty for none.",
    "artistic.vertical_compress": "Optional vertical squeeze (0.85–1.0) for a panoramic feel. Leave empty for none.",
}

_EDITABLE = [
    "description",
    "crop",
    "privacy.masks",
    "output.width",
    "output.height",
    "output.jpeg_quality",
    "timestamp",
    "site_badge",
    "artistic",
]
_READ_ONLY = [
    "name",
    "visibility",
    "output.filename",
    "output.r2_live_key",
    "output.r2_history_variant",
    "publish",
    "watermark",
]


def _strip_internal(cfg: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in cfg.items() if not str(k).startswith("_")}


def _yaml_basename(path: str | Path) -> str:
    return Path(path).name


def _served_url(camera_id: str, filename: str) -> str:
    return f"/cameras/{camera_id}/variants/{filename}"


def _publish_flag(cfg: dict[str, Any]) -> bool:
    if "publish" in cfg:
        return bool(cfg.get("publish"))
    return str(cfg.get("visibility") or "") == "public"


def _summary(
    camera_id: str,
    cfg: dict[str, Any],
    *,
    jpeg_path: Path | None = None,
    public_live_variant: str | None = None,
) -> dict[str, Any]:
    out = cfg.get("output") or {}
    filename = str(out.get("filename") or f"{cfg.get('name') or 'unnamed'}.jpg")
    path = cfg.get("_path")
    name = str(cfg.get("name") or "")
    item: dict[str, Any] = {
        "name": name,
        "visibility": str(cfg.get("visibility") or ""),
        "filename": filename,
        "publish": _publish_flag(cfg),
        "yaml_file": _yaml_basename(path) if path else None,
        "served_url": _served_url(camera_id, filename),
        "description": cfg.get("description") or "",
        "can_be_public_live": is_public_live_eligible(cfg),
        "is_public_live": bool(public_live_variant) and name == public_live_variant,
    }
    if jpeg_path is not None and jpeg_path.is_file():
        st = jpeg_path.stat()
        item["jpeg_mtime_ns"] = int(st.st_mtime_ns)
        item["jpeg_size"] = int(st.st_size)
    return item


def find_variant(
    repo_root: Path, camera_id: str, name: str
) -> tuple[dict[str, Any], Path]:
    """Return (config_with__path, yaml_path). Raises FileNotFoundError / KeyError."""
    profile = load_camera_profile(repo_root, camera_id)
    for cfg in profile.variants:
        if str(cfg.get("name") or "") == name:
            path = Path(str(cfg["_path"]))
            return cfg, path
    raise KeyError(f"variant not found: {name}")


def list_variants(repo_root: Path, camera_id: str) -> dict[str, Any]:
    profile = load_camera_profile(repo_root, camera_id)
    variants_dir = repo_root / profile.storage["variants_dir"]
    pl = PublicLiveSelection(repo_root, camera_id)
    pl_status = pl.status(profile)
    live_name = pl_status["variant"]
    items = []
    for v in profile.variants:
        out = v.get("output") or {}
        filename = str(out.get("filename") or f"{v.get('name') or 'unnamed'}.jpg")
        items.append(
            _summary(
                camera_id,
                v,
                jpeg_path=variants_dir / filename,
                public_live_variant=live_name,
            )
        )
    return {
        "camera": camera_id,
        "display_name": profile.display_name,
        "variants": items,
        "count": len(items),
        "templates": sorted(_TEMPLATES - {"landscape"}),  # prefer landscape-public alias
        "public_live": pl_status,
    }


def _validate_variant_name(name: Any) -> str:
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    n = name.strip().lower()
    if not _NAME_RE.match(n):
        raise ValueError(
            "name must be lowercase letters/digits/hyphens, start with a letter, max 48 chars"
        )
    if n in ("ui", "new", "preview"):
        raise ValueError(f"name {n!r} is reserved")
    return n


def _variants_yaml_dir(repo_root: Path, camera_id: str) -> Path:
    return repo_root / "cameras" / camera_id / "variants"


def _template_path(repo_root: Path, camera_id: str, template: str) -> Path:
    key = str(template or "").strip().lower()
    if key not in _TEMPLATES:
        raise ValueError("template must be private or landscape-public")
    filename = _TEMPLATE_FILES[key]
    # This camera's YAML, then the copy-me example (not a named deployment).
    candidates = [
        _variants_yaml_dir(repo_root, camera_id) / filename,
        repo_root / "examples" / "cameras" / "example" / "variants" / filename,
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"template YAML not found: {filename}")


def _yaml_filename_for(name: str, visibility: str) -> str:
    if visibility == "public":
        return f"{name}-public.yaml"
    return f"{name}.yaml"


def _output_filename_for(camera_id: str, name: str, visibility: str) -> str:
    """Local JPEG name = variant slug (``{name}.jpg``).

    Public edge/R2 live identity is separate (``camera.yaml`` ``public_live_key`` /
    Worker LIVE_MAP) and must not be baked into per-variant filenames.
    ``camera_id`` / ``visibility`` kept for call-site compatibility.
    """
    _ = (camera_id, visibility)
    return f"{name}.jpg"


def create_variant(
    repo_root: Path,
    camera_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Create a new variant YAML from a template. Atomic write under cameras/<id>/variants/."""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    name = _validate_variant_name(body.get("name"))
    template = str(body.get("template") or "private").strip().lower()
    if template not in _TEMPLATES:
        raise ValueError("template must be private or landscape-public")

    tpl_path = _template_path(repo_root, camera_id, template)
    with tpl_path.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    if not isinstance(cfg, dict):
        raise ValueError("template YAML must be an object")
    cfg = copy.deepcopy(cfg)

    visibility = str(body.get("visibility") or cfg.get("visibility") or "private").strip().lower()
    if visibility not in ("private", "public"):
        raise ValueError("visibility must be private or public")

    # Unique name + unique yaml path + unique output filename
    profile = load_camera_profile(repo_root, camera_id)
    existing_names = {str(v.get("name") or "") for v in profile.variants}
    if name in existing_names:
        raise ValueError(f"variant name already exists: {name}")

    yaml_name = _yaml_filename_for(name, visibility)
    dest = _variants_yaml_dir(repo_root, camera_id) / yaml_name
    if dest.exists():
        raise ValueError(f"variant YAML already exists: {yaml_name}")

    out_filename = str(body.get("filename") or "").strip() or _output_filename_for(
        camera_id, name, visibility
    )
    if "/" in out_filename or "\\" in out_filename or ".." in out_filename:
        raise ValueError("filename must be a bare JPEG name")
    if not out_filename.endswith(".jpg"):
        out_filename = f"{out_filename}.jpg"
    existing_files = {
        str((v.get("output") or {}).get("filename") or "") for v in profile.variants
    }
    if out_filename in existing_files:
        raise ValueError(f"output filename already in use: {out_filename}")

    cfg["name"] = name
    cfg["visibility"] = visibility
    if body.get("description") is not None:
        cfg["description"] = str(body.get("description") or "")
    else:
        cfg["description"] = f"Created from {template} template ({name})."

    output = dict(cfg.get("output") or {})
    output["filename"] = out_filename
    # New public variants stay local-only until explicitly published in git/YAML
    if visibility == "public":
        output["r2_live_key"] = None
        output["r2_history_variant"] = name
        cfg["publish"] = False
    else:
        output.pop("r2_live_key", None)
        output.pop("r2_history_variant", None)
        cfg.pop("publish", None)
    cfg["output"] = output

    atomic_write_yaml(dest, cfg)
    return get_variant(repo_root, camera_id, name)


def get_variant(repo_root: Path, camera_id: str, name: str) -> dict[str, Any]:
    cfg, path = find_variant(repo_root, camera_id, name)
    clean = _strip_internal(cfg)
    profile = load_camera_profile(repo_root, camera_id)
    out = cfg.get("output") or {}
    filename = str(out.get("filename") or f"{cfg.get('name') or 'unnamed'}.jpg")
    jpeg_path = repo_root / profile.storage["variants_dir"] / filename
    pl = PublicLiveSelection(repo_root, camera_id).status(profile)
    meta = _summary(camera_id, cfg, jpeg_path=jpeg_path, public_live_variant=pl["variant"])
    meta["yaml_path"] = str(path)
    return {
        "camera": camera_id,
        "meta": meta,
        "config": clean,
        "public_live": pl,
        "editable": list(_EDITABLE),
        "read_only": list(_READ_ONLY),
        "field_help": dict(FIELD_HELP),
    }


def _frac(val: Any, *, allow_null: bool = True, key: str = "value") -> float | None:
    if val is None:
        if allow_null:
            return None
        raise ValueError(f"{key} is required")
    try:
        f = float(val)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if not 0.0 <= f <= 1.0:
        raise ValueError(f"{key} must be between 0 and 1 (got {f})")
    return f


def _validate_aspect_ratio(ar: Any) -> Any:
    if ar is None or ar == "":
        return None
    if isinstance(ar, (int, float)):
        if float(ar) <= 0:
            raise ValueError("aspect_ratio must be positive")
        return float(ar)
    s = str(ar).strip()
    if not s:
        return None
    parts = s.replace("/", ":").split(":")
    if len(parts) != 2:
        raise ValueError('aspect_ratio must look like "16:9"')
    try:
        w, h = float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise ValueError('aspect_ratio must look like "16:9"') from exc
    if w <= 0 or h <= 0:
        raise ValueError("aspect_ratio parts must be positive")
    return s


def validate_crop(crop: Any) -> dict[str, Any]:
    if crop is None:
        return {}
    if not isinstance(crop, dict):
        raise ValueError("crop must be an object")
    out: dict[str, Any] = {}
    mode = crop.get("mode")
    if mode is not None and mode != "":
        m = str(mode).lower().strip()
        if m not in _CROP_MODES - {""}:
            raise ValueError(f"crop.mode must be one of full|centered|arbitrary (got {mode!r})")
        out["mode"] = m
    for key in ("left", "top", "right", "bottom"):
        if key in crop:
            out[key] = _frac(crop.get(key), key=f"crop.{key}")
    for key in ("width_frac", "height_frac"):
        if key in crop and crop.get(key) is not None:
            f = _frac(crop.get(key), allow_null=False, key=f"crop.{key}")
            assert f is not None
            if f < 0.05:
                raise ValueError(f"crop.{key} must be >= 0.05")
            out[key] = f
    if "zoom" in crop and crop.get("zoom") is not None:
        try:
            z = float(crop["zoom"])
        except (TypeError, ValueError) as exc:
            raise ValueError("crop.zoom must be a number") from exc
        if z < 1.0:
            raise ValueError("crop.zoom must be >= 1.0")
        if z > 8.0:
            raise ValueError("crop.zoom must be <= 8.0")
        out["zoom"] = z
    if "aspect_ratio" in crop:
        out["aspect_ratio"] = _validate_aspect_ratio(crop.get("aspect_ratio"))
    return out


_MASK_LABEL_MAX = 80


def _mask_label(raw: dict[str, Any], index: int) -> str | None:
    """Optional note (`label` or legacy `note`). Settings file only — not drawn on the image."""
    if "label" in raw and raw.get("label") is not None:
        value = raw.get("label")
    elif "note" in raw and raw.get("note") is not None:
        value = raw.get("note")
    else:
        return None
    if not isinstance(value, (str, int, float)):
        raise ValueError(f"privacy.masks[{index}].label must be a string")
    label = str(value).strip()
    if not label:
        return None
    if len(label) > _MASK_LABEL_MAX:
        raise ValueError(
            f"privacy.masks[{index}].label must be at most {_MASK_LABEL_MAX} characters"
        )
    return label


def validate_masks(masks: Any) -> list[dict[str, Any]]:
    if masks is None:
        return []
    if not isinstance(masks, list):
        raise ValueError("privacy.masks must be a list")
    if len(masks) > 32:
        raise ValueError("privacy.masks: at most 32 masks")
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(masks):
        if not isinstance(raw, dict):
            raise ValueError(f"privacy.masks[{i}] must be an object")
        mtype = str(raw.get("type") or "rect").lower()
        if mtype not in _MASK_TYPES:
            raise ValueError(f"privacy.masks[{i}].type must be rect")
        mode = str(raw.get("mode") or "blur").lower()
        if mode not in _MASK_MODES:
            raise ValueError(
                f"privacy.masks[{i}].mode must be one of blur|pixelate|black (got {mode!r})"
            )
        left = _frac(raw.get("left"), allow_null=False, key=f"privacy.masks[{i}].left")
        top = _frac(raw.get("top"), allow_null=False, key=f"privacy.masks[{i}].top")
        right = _frac(raw.get("right"), allow_null=False, key=f"privacy.masks[{i}].right")
        bottom = _frac(raw.get("bottom"), allow_null=False, key=f"privacy.masks[{i}].bottom")
        assert left is not None and top is not None and right is not None and bottom is not None
        if right <= left or bottom <= top:
            raise ValueError(f"privacy.masks[{i}] box must have right>left and bottom>top")
        item: dict[str, Any] = {
            "type": "rect",
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "mode": mode if mode != "solid" else "black",
        }
        if "strength" in raw and raw.get("strength") is not None:
            try:
                strength = int(raw["strength"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"privacy.masks[{i}].strength must be an integer") from exc
            if not 1 <= strength <= 64:
                raise ValueError(f"privacy.masks[{i}].strength must be 1–64")
            item["strength"] = strength
        label = _mask_label(raw, i)
        if label is not None:
            item["label"] = label
        out.append(item)
    return out


def _boolish(val: Any, *, key: str) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)) and val in (0, 1):
        return bool(val)
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
    raise ValueError(f"{key} must be a boolean")


def validate_output_patch(output: Any) -> dict[str, Any]:
    """Editable output knobs only — filename / R2 keys stay locked."""
    if output is None:
        return {}
    if not isinstance(output, dict):
        raise ValueError("output must be an object")
    out: dict[str, Any] = {}
    for key in ("width", "height"):
        if key not in output:
            continue
        val = output.get(key)
        if val is None or val == "":
            continue
        try:
            n = int(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"output.{key} must be an integer") from exc
        if not 64 <= n <= 7680:
            raise ValueError(f"output.{key} must be 64–7680")
        out[key] = n
    if "jpeg_quality" in output and output.get("jpeg_quality") is not None:
        try:
            q = int(output["jpeg_quality"])
        except (TypeError, ValueError) as exc:
            raise ValueError("output.jpeg_quality must be an integer") from exc
        if not 1 <= q <= 95:
            raise ValueError("output.jpeg_quality must be 1–95")
        out["jpeg_quality"] = q
    return out


def validate_timestamp(ts: Any) -> dict[str, Any]:
    if ts is None:
        return {"enabled": False}
    if not isinstance(ts, dict):
        raise ValueError("timestamp must be an object")
    out: dict[str, Any] = {}
    if "enabled" in ts:
        out["enabled"] = _boolish(ts.get("enabled"), key="timestamp.enabled")
    if "position" in ts and ts.get("position") is not None and ts.get("position") != "":
        pos = str(ts.get("position")).strip().lower()
        if pos not in _TS_POSITIONS:
            raise ValueError(
                "timestamp.position must be bottom-left|bottom-right|top-left|top-right"
            )
        out["position"] = pos
    if "format" in ts and ts.get("format") is not None:
        fmt = str(ts.get("format") or "").strip()
        if len(fmt) > 64:
            raise ValueError("timestamp.format too long")
        out["format"] = fmt or "%Y-%m-%d %H:%M"
    if "opacity" in ts and ts.get("opacity") is not None:
        try:
            op = float(ts["opacity"])
        except (TypeError, ValueError) as exc:
            raise ValueError("timestamp.opacity must be a number") from exc
        if not 0.0 <= op <= 1.0:
            raise ValueError("timestamp.opacity must be 0–1")
        out["opacity"] = op
    for key in ("font_size", "margin", "stroke_width"):
        if key not in ts or ts.get(key) is None:
            continue
        try:
            n = int(ts[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"timestamp.{key} must be an integer") from exc
        if key == "font_size":
            lo, hi = 8, 96
        elif key == "stroke_width":
            lo, hi = 0, 8
        else:
            lo, hi = 0, 128
        if not lo <= n <= hi:
            raise ValueError(f"timestamp.{key} must be {lo}–{hi}")
        out[key] = n
    return out


def validate_site_badge(badge: Any) -> dict[str, Any]:
    if badge is None:
        return {"enabled": False}
    if not isinstance(badge, dict):
        raise ValueError("site_badge must be an object")
    out: dict[str, Any] = {}
    if "enabled" in badge:
        out["enabled"] = _boolish(badge.get("enabled"), key="site_badge.enabled")
    if "site" in badge and badge.get("site") is not None:
        site = str(badge.get("site") or "").strip()
        if len(site) > 80:
            raise ValueError("site_badge.site too long")
        out["site"] = site
    if "temperature" in badge:
        out["temperature"] = _boolish(badge.get("temperature"), key="site_badge.temperature")
    for key in ("font_size", "margin", "stroke_width"):
        if key not in badge or badge.get(key) is None:
            continue
        try:
            n = int(badge[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"site_badge.{key} must be an integer") from exc
        if key == "font_size":
            lo, hi = 10, 64
        elif key == "stroke_width":
            lo, hi = 0, 8
        else:
            lo, hi = 0, 64
        if not lo <= n <= hi:
            raise ValueError(f"site_badge.{key} must be {lo}–{hi}")
        out[key] = n
    return out


def validate_artistic(artistic: Any) -> dict[str, Any]:
    if artistic is None:
        return {}
    if not isinstance(artistic, dict):
        raise ValueError("artistic must be an object")
    out: dict[str, Any] = {}
    if "horizontal_stretch" in artistic and artistic.get("horizontal_stretch") is not None:
        try:
            s = float(artistic["horizontal_stretch"])
        except (TypeError, ValueError) as exc:
            raise ValueError("artistic.horizontal_stretch must be a number") from exc
        if not 0.85 <= s <= 1.25:
            raise ValueError("artistic.horizontal_stretch must be 0.85–1.25")
        out["horizontal_stretch"] = s
    if "vertical_compress" in artistic and artistic.get("vertical_compress") is not None:
        try:
            v = float(artistic["vertical_compress"])
        except (TypeError, ValueError) as exc:
            raise ValueError("artistic.vertical_compress must be a number") from exc
        if not 0.85 <= v <= 1.0:
            raise ValueError("artistic.vertical_compress must be 0.85–1.0")
        out["vertical_compress"] = v
    return out


def validate_patch(body: dict[str, Any]) -> dict[str, Any]:
    """Validate editable fields from a PUT/POST body. Returns normalized patch."""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    patch: dict[str, Any] = {}
    if "description" in body:
        desc = body.get("description")
        if desc is None:
            patch["description"] = ""
        else:
            s = str(desc)
            if len(s) > 500:
                raise ValueError("description too long (max 500)")
            patch["description"] = s
    if "crop" in body:
        patch["crop"] = validate_crop(body.get("crop"))
    if "privacy" in body:
        priv = body.get("privacy")
        if priv is None:
            patch["privacy"] = {"masks": []}
        elif not isinstance(priv, dict):
            raise ValueError("privacy must be an object")
        else:
            if "masks" not in priv:
                raise ValueError("privacy must include masks when provided")
            patch["privacy"] = {"masks": validate_masks(priv.get("masks"))}
    elif "masks" in body:
        # Convenience: top-level masks → privacy.masks
        patch["privacy"] = {"masks": validate_masks(body.get("masks"))}
    if "output" in body:
        out_patch = validate_output_patch(body.get("output"))
        if out_patch:
            patch["output"] = out_patch
    if "timestamp" in body:
        patch["timestamp"] = validate_timestamp(body.get("timestamp"))
    if "site_badge" in body:
        patch["site_badge"] = validate_site_badge(body.get("site_badge"))
    if "artistic" in body:
        patch["artistic"] = validate_artistic(body.get("artistic"))
    if not patch:
        raise ValueError(
            "nothing to update — send crop, privacy.masks, output size/quality, "
            "timestamp, site_badge, artistic, and/or description"
        )
    return patch


def apply_patch(cfg: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(_strip_internal(cfg))
    if "description" in patch:
        merged["description"] = patch["description"]
    if "crop" in patch:
        merged["crop"] = patch["crop"]
    if "privacy" in patch:
        privacy = dict(merged.get("privacy") or {})
        privacy["masks"] = patch["privacy"]["masks"]
        merged["privacy"] = privacy
    if "output" in patch:
        output = dict(merged.get("output") or {})
        for key, val in patch["output"].items():
            output[key] = val
        merged["output"] = output
    if "timestamp" in patch:
        ts = dict(merged.get("timestamp") or {})
        ts.update(patch["timestamp"])
        merged["timestamp"] = ts
    if "site_badge" in patch:
        badge = dict(merged.get("site_badge") or {})
        badge.update(patch["site_badge"])
        merged["site_badge"] = badge
    if "artistic" in patch:
        # Empty object clears intentional stretch (UI sends {{}} when fields blank).
        if patch["artistic"]:
            merged["artistic"] = dict(patch["artistic"])
        else:
            merged.pop("artistic", None)
    return merged


def atomic_write_yaml(path: Path, cfg: dict[str, Any]) -> None:
    """Atomically write variant YAML (tmp + replace)."""
    clean = _strip_internal(cfg)
    text = yaml.safe_dump(
        clean,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    if not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def save_variant(
    repo_root: Path,
    camera_id: str,
    name: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Validate patch, atomic-write YAML, return updated get_variant payload."""
    cfg, path = find_variant(repo_root, camera_id, name)
    patch = validate_patch(body)
    merged = apply_patch(cfg, patch)
    # Keep locked identity fields from disk
    merged["name"] = cfg.get("name")
    merged["visibility"] = cfg.get("visibility")
    # Preserve locked output identity (filename / R2) even if patch touched size/quality
    base_out = dict(cfg.get("output") or {})
    edited_out = dict(merged.get("output") or {})
    for lock in ("filename", "r2_live_key", "r2_history_variant"):
        if lock in base_out:
            edited_out[lock] = base_out[lock]
        elif lock in edited_out and lock.startswith("r2_"):
            # Don't invent R2 keys on private variants
            pass
    edited_out["filename"] = base_out.get("filename") or edited_out.get("filename")
    merged["output"] = edited_out
    if "publish" in cfg:
        merged["publish"] = cfg["publish"]
    if "watermark" in cfg:
        merged["watermark"] = cfg["watermark"]
    atomic_write_yaml(path, merged)
    return get_variant(repo_root, camera_id, name)


def original_path(repo_root: Path, camera_id: str) -> Path:
    profile = load_camera_profile(repo_root, camera_id)
    return repo_root / profile.storage["original_dir"] / "latest.jpg"


def preview_jpeg(
    repo_root: Path,
    camera_id: str,
    name: str,
    body: dict[str, Any] | None = None,
) -> bytes:
    """Dry-run render_one → JPEG bytes (no disk / no R2)."""
    cfg, _path = find_variant(repo_root, camera_id, name)
    merged = _strip_internal(cfg)
    if body:
        # Allow preview of unsaved edits without writing
        patch_keys = {
            k: body[k]
            for k in (
                "crop",
                "privacy",
                "masks",
                "output",
                "timestamp",
                "site_badge",
                "artistic",
                "description",
            )
            if k in body
        }
        if patch_keys:
            patch = validate_patch(patch_keys)
            merged = apply_patch(merged, patch)

    src = original_path(repo_root, camera_id)
    if not src.exists():
        raise FileNotFoundError(
            f"no stored original at {src} — run the pipeline once or POST /refresh first"
        )
    original = Image.open(src).convert("RGB")
    profile = load_camera_profile(repo_root, camera_id)
    meta_path = src.with_name("latest.meta.json")
    captured_at = time.time()
    if meta_path.exists():
        try:
            import json

            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            captured_at = float(meta.get("captured_at") or captured_at)
        except Exception:  # noqa: BLE001
            pass

    img = render_one(
        original,
        merged,
        captured_at,
        profile.timezone,
        repo_root=repo_root,
        temp_c=_preview_temp_c(profile),
    )
    quality = int((merged.get("output") or {}).get("jpeg_quality", 85))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _preview_temp_c(profile) -> float | None:
    try:
        from .weather import DEFAULT_WEATHER_URL, get_weather_cache

        wx = profile.weather or {}
        return get_weather_cache(
            url=str(wx.get("url") or DEFAULT_WEATHER_URL),
            ttl_seconds=float(wx.get("ttl_seconds", 300)),
            timeout_seconds=float(wx.get("timeout_seconds", 4)),
        ).get().temp_c
    except Exception:  # noqa: BLE001
        return None