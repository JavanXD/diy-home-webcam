from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from shared.brand_overlay import StatusCopy, status_copy_from_mapping


@dataclass
class CameraProfile:
    camera_id: str
    display_name: str
    source_url: str
    health_url: str | None
    timeout_seconds: float
    poll_interval_seconds: float
    storage: dict[str, Any]
    history: dict[str, Any]
    timezone: str
    variants: list[dict[str, Any]] = field(default_factory=list)
    publish_enabled: bool = True
    weather: dict[str, Any] = field(default_factory=dict)
    timelapse: dict[str, Any] = field(default_factory=dict)
    status_text: StatusCopy = field(default_factory=StatusCopy.english)


def _env_override(camera_id: str, key: str) -> str | None:
    """Allow WEBCAM_<ID>_SOURCE_URL without editing YAML (ID uppercased, hyphens → underscores)."""
    slug = camera_id.upper().replace("-", "_")
    return os.environ.get(f"WEBCAM_{slug}_{key}") or os.environ.get(f"WEBCAM_{key}")


def load_camera_profile(repo_root: Path, camera_id: str) -> CameraProfile:
    cam_dir = repo_root / "cameras" / camera_id
    cam_path = cam_dir / "camera.yaml"
    if not cam_path.exists():
        raise FileNotFoundError(f"missing camera profile: {cam_path}")
    with cam_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    variants: list[dict[str, Any]] = []
    variants_dir = cam_dir / "variants"
    for path in sorted(variants_dir.glob("*.yaml")):
        with path.open("r", encoding="utf-8") as fh:
            v = yaml.safe_load(fh) or {}
            v["_path"] = str(path)
            variants.append(v)

    source = raw.get("source") or {}
    publish = raw.get("publish") or {}
    # Live JPEG still publishes. History objects in the bucket are off unless
    # publish.history.enabled is explicitly true.
    history = dict(publish.get("history") or {})
    history.setdefault("enabled", False)
    history.setdefault("min_interval_seconds", 300)
    history.setdefault("retention_days", 90)
    timelapse = dict(raw.get("timelapse") or {})
    timelapse.setdefault("enabled", True)
    timelapse.setdefault("min_interval_seconds", 120)
    timelapse.setdefault("retention_days", 400)
    # Explicit size budget under data/<id>/timelapse/ (frames + exports).
    if timelapse.get("max_bytes") is None and timelapse.get("max_gb") is None:
        timelapse.setdefault("max_gb", 40)

    source_url = _env_override(camera_id, "SOURCE_URL") or source["url"]
    health_url = _env_override(camera_id, "HEALTH_URL") or source.get("health_url")

    return CameraProfile(
        camera_id=raw.get("id") or camera_id,
        display_name=raw.get("display_name") or camera_id,
        source_url=source_url,
        health_url=health_url,
        timeout_seconds=float(source.get("timeout_seconds", 10)),
        poll_interval_seconds=float(raw.get("poll_interval_seconds", 30)),
        storage=raw.get("storage") or {},
        history=history,
        timezone=raw.get("timezone") or "UTC",
        variants=variants,
        publish_enabled=bool(publish.get("enabled", True)),
        weather=raw.get("weather") or {},
        timelapse=timelapse,
        status_text=status_copy_from_mapping(raw.get("status_text")),
    )


def public_site_label(profile: CameraProfile) -> str:
    """Hostname burned into the public JPEG, from the first public variant that sets it."""
    for variant in profile.variants:
        if str(variant.get("visibility") or "") != "public":
            continue
        site = str((variant.get("site_badge") or {}).get("site") or "").strip()
        if site:
            return site
    return ""
