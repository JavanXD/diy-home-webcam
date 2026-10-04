"""Project settings stored in ``cameras/<id>/camera.yaml``.

The Setup and Timelapse pages read and write this file. Wi-Fi passwords are not part of it.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from shared.brand_overlay import StatusCopy

_MAX_NAME = 80
_MAX_URL = 500
_CAMERA_ID = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
_STATUS_LANGS = frozenset({"english", "german", "custom"})


def camera_yaml_path(repo_root: Path, camera_id: str) -> Path:
    if not camera_id or "/" in camera_id or camera_id.startswith("."):
        raise ValueError("invalid camera id")
    return repo_root / "cameras" / camera_id / "camera.yaml"


def read_site(repo_root: Path, camera_id: str) -> dict[str, Any]:
    path = camera_yaml_path(repo_root, camera_id)
    raw = _load(path)
    loc = raw.get("location") if isinstance(raw.get("location"), dict) else {}
    wx = raw.get("weather") if isinstance(raw.get("weather"), dict) else {}
    tl = raw.get("timelapse") if isinstance(raw.get("timelapse"), dict) else {}
    return {
        "camera_id": camera_id,
        "yaml_path": f"cameras/{camera_id}/camera.yaml",
        "display_name": str(raw.get("display_name") or "").strip(),
        "timezone": str(raw.get("timezone") or "").strip(),
        "latitude": loc.get("latitude"),
        "longitude": loc.get("longitude"),
        "weather_url": str(wx.get("url") or "").strip(),
        "weather_ttl_seconds": int(wx.get("ttl_seconds") or 300),
        "weather_timeout_seconds": int(wx.get("timeout_seconds") or 4),
        "public_live_key": str((raw.get("publish") or {}).get("public_live_key") or "").strip()
        if isinstance(raw.get("publish"), dict)
        else "",
        "site_label": _site_label_from_variants(repo_root, camera_id),
        "poll_interval_seconds": int(raw.get("poll_interval_seconds") or 60),
        "status_language": _detect_status_language(raw.get("status_text")),
        "timelapse_enabled": bool(tl.get("enabled", True)) if tl else True,
        "timelapse_max_gb": float(tl.get("max_gb") if tl.get("max_gb") is not None else 40),
        "timelapse_retention_days": int(tl.get("retention_days") or 400),
        "timelapse_min_interval_seconds": int(tl.get("min_interval_seconds") or 120),
    }


def save_site(repo_root: Path, camera_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Update display name, place, and weather URL. Other YAML keys stay."""
    path = camera_yaml_path(repo_root, camera_id)
    if not path.is_file():
        raise ValueError(f"missing {path.name} for {camera_id}")
    raw = _load(path)
    _apply(raw, patch, repo_root, camera_id)
    text = yaml.safe_dump(raw, sort_keys=False, default_flow_style=False, allow_unicode=True)
    if not text.endswith("\n"):
        text += "\n"
    header = (
        "# Project settings. The Setup page rewrites this file and drops comments.\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(header + text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return read_site(repo_root, camera_id)


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("camera.yaml not found")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"camera.yaml is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("camera.yaml root must be a mapping")
    return raw


def _apply(raw: dict[str, Any], patch: dict[str, Any], repo_root: Path, camera_id: str) -> None:
    if "display_name" in patch:
        name = str(patch.get("display_name") or "").strip()
        if not name or len(name) > _MAX_NAME or any(c in name for c in "\r\n"):
            raise ValueError("display name must be 1–80 characters on one line")
        raw["display_name"] = name
    if "timezone" in patch:
        tz_name = str(patch.get("timezone") or "").strip()
        if not tz_name:
            raise ValueError("timezone is required")
        try:
            ZoneInfo(tz_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {tz_name}") from exc
        raw["timezone"] = tz_name
    if "latitude" in patch or "longitude" in patch:
        loc = dict(raw.get("location") or {})
        if "latitude" in patch:
            loc["latitude"] = _coord(patch.get("latitude"), "latitude", -90.0, 90.0)
        if "longitude" in patch:
            loc["longitude"] = _coord(patch.get("longitude"), "longitude", -180.0, 180.0)
        if loc.get("latitude") is None or loc.get("longitude") is None:
            raise ValueError("latitude and longitude are both required")
        raw["location"] = loc
    if any(k in patch for k in ("weather_url", "weather_ttl_seconds", "weather_timeout_seconds")):
        wx = dict(raw.get("weather") or {})
        if "weather_url" in patch:
            wx["url"] = _weather_url(patch.get("weather_url"))
        if "weather_ttl_seconds" in patch:
            wx["ttl_seconds"] = _int_range(patch.get("weather_ttl_seconds"), "weather ttl", 30, 86400)
        if "weather_timeout_seconds" in patch:
            wx["timeout_seconds"] = _int_range(
                patch.get("weather_timeout_seconds"), "weather timeout", 1, 30
            )
        raw["weather"] = wx
    if "public_live_key" in patch:
        key = _live_key(patch.get("public_live_key"))
        publish = dict(raw.get("publish") or {})
        publish["public_live_key"] = key
        raw["publish"] = publish
        _set_variant_live_keys(repo_root, camera_id, key)
    if "site_label" in patch:
        _set_site_label(repo_root, camera_id, _site_label(patch.get("site_label")))
    if "poll_interval_seconds" in patch:
        raw["poll_interval_seconds"] = _int_range(
            patch.get("poll_interval_seconds"), "poll interval", 15, 600
        )
    if "status_language" in patch:
        _apply_status_language(raw, patch.get("status_language"))
    if any(
        k in patch
        for k in (
            "timelapse_enabled",
            "timelapse_max_gb",
            "timelapse_retention_days",
            "timelapse_min_interval_seconds",
        )
    ):
        _apply_timelapse(raw, patch)


def _detect_status_language(raw: Any) -> str:
    """english (default / omit block), german (known preset), or custom (YAML escape hatch)."""
    if not isinstance(raw, dict) or not raw:
        return "english"
    de = StatusCopy.german()
    en = StatusCopy.english()
    title = str(raw.get("night_title") or "").strip()
    maint = str(raw.get("maintenance_title") or "").strip()
    if title == de.night_title or maint == de.maintenance_title:
        # Exact German preset (or close enough on primary titles).
        if (
            title in {"", de.night_title}
            and maint in {"", de.maintenance_title}
            and str(raw.get("back_at_label") or "").strip() in {"", de.back_at_label}
        ):
            return "german"
        return "custom"
    if title in {"", en.night_title} and maint in {"", en.maintenance_title}:
        return "english"
    return "custom"


def _status_copy_as_dict(copy: StatusCopy) -> dict[str, Any]:
    return {
        "maintenance_title": copy.maintenance_title,
        "maintenance_body": copy.maintenance_body,
        "night_title": copy.night_title,
        "night_body": copy.night_body,
        "back_at_label": copy.back_at_label,
        "today": copy.today,
        "tomorrow": copy.tomorrow,
        "weekdays": list(copy.weekdays),
    }


def _apply_status_language(raw: dict[str, Any], value: Any) -> None:
    lang = str(value or "").strip().lower()
    if lang not in _STATUS_LANGS:
        raise ValueError("status language must be english, german, or custom")
    if lang == "custom":
        # Keep whatever is already in YAML; UI must not wipe a custom block.
        return
    if lang == "english":
        raw.pop("status_text", None)
        return
    raw["status_text"] = _status_copy_as_dict(StatusCopy.german())


def _apply_timelapse(raw: dict[str, Any], patch: dict[str, Any]) -> None:
    tl = dict(raw.get("timelapse") or {})
    if "timelapse_enabled" in patch:
        tl["enabled"] = bool(patch.get("timelapse_enabled"))
    if "timelapse_max_gb" in patch:
        try:
            gb = float(patch.get("timelapse_max_gb"))
        except (TypeError, ValueError) as exc:
            raise ValueError("timelapse budget must be a number of gigabytes") from exc
        if gb < 1 or gb > 2000:
            raise ValueError("timelapse budget must be between 1 and 2000 GB")
        tl["max_gb"] = round(gb, 3)
        tl.pop("max_bytes", None)
    if "timelapse_retention_days" in patch:
        tl["retention_days"] = _int_range(
            patch.get("timelapse_retention_days"), "timelapse retention", 7, 5000
        )
    if "timelapse_min_interval_seconds" in patch:
        tl["min_interval_seconds"] = _int_range(
            patch.get("timelapse_min_interval_seconds"),
            "timelapse frame interval",
            30,
            3600,
        )
    raw["timelapse"] = tl


def _coord(value: Any, label: str, lo: float, hi: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if num < lo or num > hi:
        raise ValueError(f"{label} must be between {lo:g} and {hi:g}")
    return round(num, 6)


def _weather_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if len(url) > _MAX_URL or any(c in url for c in " \t\r\n"):
        raise ValueError("weather URL is too long or contains spaces")
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError("weather URL must start with http:// or https://")
    return url


def _int_range(value: Any, label: str, lo: int, hi: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a whole number") from exc
    if num < lo or num > hi:
        raise ValueError(f"{label} must be between {lo} and {hi}")
    return num


def _live_key(value: Any) -> str:
    key = str(value or "").strip()
    if (
        not key
        or len(key) > 120
        or ".." in key
        or key.startswith("/")
        or any(c in key for c in " \t\r\n")
        or not key.endswith(".jpg")
    ):
        raise ValueError("public live key must be a relative path ending in .jpg")
    return key


def _site_label(value: Any) -> str:
    site = str(value or "").strip()
    if not site:
        return ""
    if len(site) > 80 or any(c in site for c in " \t\r\n"):
        raise ValueError("site label must be one line, at most 80 characters")
    return site


def _variant_files(repo_root: Path, camera_id: str) -> list[Path]:
    folder = repo_root / "cameras" / camera_id / "variants"
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.yaml"))


def _site_label_from_variants(repo_root: Path, camera_id: str) -> str:
    for path in _variant_files(repo_root, camera_id):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(raw, dict) or str(raw.get("visibility") or "") != "public":
            continue
        site = str((raw.get("site_badge") or {}).get("site") or "").strip()
        if site:
            return site
    return ""


def _write_variant(path: Path, raw: dict[str, Any]) -> None:
    text = yaml.safe_dump(raw, sort_keys=False, default_flow_style=False, allow_unicode=True)
    if not text.endswith("\n"):
        text += "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _set_variant_live_keys(repo_root: Path, camera_id: str, key: str) -> None:
    for path in _variant_files(repo_root, camera_id):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict) or str(raw.get("visibility") or "") != "public":
            continue
        output = dict(raw.get("output") or {})
        if "r2_live_key" not in output:
            continue
        output["r2_live_key"] = key
        raw["output"] = output
        _write_variant(path, raw)


def _set_site_label(repo_root: Path, camera_id: str, site: str) -> None:
    for path in _variant_files(repo_root, camera_id):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict) or str(raw.get("visibility") or "") != "public":
            continue
        badge = dict(raw.get("site_badge") or {})
        badge["site"] = site
        badge["enabled"] = bool(site)
        raw["site_badge"] = badge
        _write_variant(path, raw)


def check_camera_id(camera_id: str) -> str:
    cid = str(camera_id or "").strip()
    if not _CAMERA_ID.match(cid):
        raise ValueError("camera id must be lowercase letters, digits, and hyphens")
    return cid


def create_camera(
    repo_root: Path,
    camera_id: str,
    display_name: str,
    *,
    config_paths: list[Path] | None = None,
) -> dict[str, Any]:
    """Copy examples/cameras/example and register the id on the pipeline camera list."""
    cid = check_camera_id(camera_id)
    name = str(display_name or "").strip() or cid
    if len(name) > _MAX_NAME or any(c in name for c in "\r\n"):
        raise ValueError("display name must be 1–80 characters on one line")
    dest = repo_root / "cameras" / cid
    if dest.exists():
        raise ValueError(f"camera {cid} already exists")
    src = repo_root / "examples" / "cameras" / "example"
    if not src.is_dir():
        raise ValueError("missing examples/cameras/example")
    shutil.copytree(src, dest)
    live_key = f"live/{cid}-live-webcam.jpg"
    for path in dest.rglob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        text = text.replace("id: example", f"id: {cid}")
        text = text.replace("display_name: Example Webcam", f"display_name: {name}")
        text = text.replace("data/example", f"data/{cid}")
        text = text.replace("history/example", f"history/{cid}")
        text = text.replace("live/example-live-webcam.jpg", live_key)
        path.write_text(text, encoding="utf-8")
    registered = append_camera_id(
        repo_root,
        cid,
        config_paths=config_paths if config_paths is not None else pipeline_config_paths(repo_root),
    )
    created = read_site(repo_root, cid)
    created["registered_in"] = registered
    return created


def pipeline_config_paths(repo_root: Path) -> list[Path]:
    """Running pipeline files. Existing pipeline example files on disk are left unchanged."""
    found: list[Path] = []
    for path in (
        Path("/etc/webcam-pipeline/pipeline.yaml"),
        repo_root / "pi" / "pipeline" / "config" / "pipeline.yaml",
    ):
        if path.is_file():
            found.append(path)
    return found


def append_camera_id(
    repo_root: Path,
    camera_id: str,
    *,
    config_paths: list[Path] | None = None,
) -> list[str]:
    written: list[str] = []
    paths = config_paths if config_paths is not None else pipeline_config_paths(repo_root)
    for path in paths:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            continue
        cams = [str(item) for item in (raw.get("cameras") or []) if str(item).strip()]
        if camera_id not in cams:
            cams.append(camera_id)
        raw["cameras"] = cams
        text = yaml.safe_dump(raw, sort_keys=False, default_flow_style=False, allow_unicode=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        os.replace(tmp, path)
        written.append(str(path))
    return written
