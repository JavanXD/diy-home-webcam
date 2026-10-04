"""Which public variant feeds the fixed public live R2 key / URL.

The public path and R2 live object stay stable (``publish.public_live_key`` in camera.yaml).
Operators pick which rendered public variant's bytes are published there.
Selection is runtime state under data/<camera>/ (LAN-writable), not git YAML.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .camera_profile import CameraProfile, load_camera_profile


def _basename_from_live_key(live_key: str) -> str:
    return Path(str(live_key)).name


def public_url_path_for_key(live_key: str) -> str:
    name = _basename_from_live_key(live_key)
    return f"/{name}" if name else "/"


def is_public_live_eligible(cfg: dict[str, Any]) -> bool:
    """Only visibility:public variants may become public live (never private HA)."""
    return str(cfg.get("visibility") or "").strip().lower() == "public"


def resolve_fixed_live_key(profile: CameraProfile) -> str:
    """Stable R2 live object for this camera (catalog + Worker LIVE_MAP)."""
    # Prefer explicit camera.yaml publish.public_live_key when present.
    # (Loaded via variants' camera.yaml — see CameraProfile; we re-read publish below.)
    cam_yaml = None
    # profile does not currently expose raw publish dict; infer from variants / convention
    for v in profile.variants:
        if not is_public_live_eligible(v):
            continue
        out = v.get("output") or {}
        key = out.get("r2_live_key")
        if key:
            return str(key)
    return f"live/{profile.camera_id}-live-webcam.jpg"


def resolve_fixed_live_key_from_repo(repo_root: Path, camera_id: str) -> str:
    profile = load_camera_profile(repo_root, camera_id)
    cam_path = repo_root / "cameras" / camera_id / "camera.yaml"
    if cam_path.exists():
        import yaml

        raw = yaml.safe_load(cam_path.read_text(encoding="utf-8")) or {}
        publish = raw.get("publish") or {}
        explicit = publish.get("public_live_key")
        if explicit:
            return str(explicit)
    return resolve_fixed_live_key(profile)


def eligible_public_variants(profile: CameraProfile) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for v in profile.variants:
        if not is_public_live_eligible(v):
            continue
        out = v.get("output") or {}
        items.append(
            {
                "name": str(v.get("name") or ""),
                "filename": str(out.get("filename") or f"{v.get('name')}.jpg"),
                "description": v.get("description") or "",
            }
        )
    return items


def default_variant_name(profile: CameraProfile, live_key: str) -> str:
    """Pick default public_live when no runtime selection exists."""
    eligible = [str(v.get("name") or "") for v in profile.variants if is_public_live_eligible(v)]
    if not eligible:
        raise ValueError(f"no public variants for camera {profile.camera_id}")
    for v in profile.variants:
        name = str(v.get("name") or "")
        if name not in eligible:
            continue
        out = v.get("output") or {}
        if str(out.get("r2_live_key") or "") == live_key:
            return name
    if "landscape" in eligible:
        return "landscape"
    return eligible[0]


def publish_live_key_for_variant(
    *,
    variant_name: str,
    visibility: str,
    publish_enabled: bool,
    variant_r2_live_key: str | None,
    public_live_variant: str,
    fixed_live_key: str,
) -> str | None:
    """Return the R2 live key to publish this variant to, or None to skip.

    The designated public_live variant always maps to ``fixed_live_key``.
    Other public variants may still publish to a *different* secondary key when
    ``publish_enabled`` and they have their own ``r2_live_key``.
    """
    if str(visibility or "").lower() != "public":
        return None
    if variant_name == public_live_variant:
        return fixed_live_key
    if not publish_enabled:
        return None
    key = variant_r2_live_key or None
    if not key or key == fixed_live_key:
        # Fixed key is owned exclusively by the selected public_live variant.
        return None
    return key


class PublicLiveSelection:
    """Runtime public-live designation under data/<camera>/public-live.json."""

    def __init__(self, repo_root: Path, camera_id: str = "") -> None:
        self.repo_root = repo_root
        self.camera_id = camera_id
        self.dir = repo_root / "data" / camera_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "public-live.json"
        self._lock = threading.Lock()

    def _read_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def live_key(self) -> str:
        return resolve_fixed_live_key_from_repo(self.repo_root, self.camera_id)

    def variant_name(self, profile: CameraProfile | None = None) -> str:
        profile = profile or load_camera_profile(self.repo_root, self.camera_id)
        live_key = self.live_key()
        with self._lock:
            raw = self._read_raw()
        name = str(raw.get("variant") or "").strip()
        if name:
            for v in profile.variants:
                if str(v.get("name") or "") == name and is_public_live_eligible(v):
                    return name
            # Stale / illegal selection (e.g. private) — fall back
        return default_variant_name(profile, live_key)

    def status(self, profile: CameraProfile | None = None) -> dict[str, Any]:
        profile = profile or load_camera_profile(self.repo_root, self.camera_id)
        live_key = self.live_key()
        variant = self.variant_name(profile)
        eligible = eligible_public_variants(profile)
        with self._lock:
            raw = self._read_raw()
        return {
            "camera": self.camera_id,
            "variant": variant,
            "live_key": live_key,
            "public_url_path": public_url_path_for_key(live_key),
            "eligible": eligible,
            "persisted": bool(raw.get("variant")),
            "path": str(self.path),
            "force_publish": bool(raw.get("force_publish")),
            "note": "The public URL and cloud storage key stay fixed; only which "
            "rendered public variant is published there changes. "
            "Private (LAN-only) variants are never eligible.",
        }

    def set_variant(self, name: str, *, force_publish: bool = True) -> dict[str, Any]:
        profile = load_camera_profile(self.repo_root, self.camera_id)
        name = str(name or "").strip()
        if not name:
            raise ValueError("variant is required")
        match = None
        for v in profile.variants:
            if str(v.get("name") or "") == name:
                match = v
                break
        if match is None:
            raise KeyError(f"variant not found: {name}")
        if not is_public_live_eligible(match):
            raise ValueError(
                f"variant {name!r} is not public — private LAN-only variants "
                "cannot be the public livestream"
            )
        with self._lock:
            data = {
                "variant": name,
                "live_key": self.live_key(),
                "force_publish": bool(force_publish),
            }
            self._write(data)
        return self.status(profile)

    def consume_force_publish(self) -> bool:
        """Return True once if a switch requested immediate republish; clear the flag."""
        with self._lock:
            raw = self._read_raw()
            if not raw.get("force_publish"):
                return False
            raw["force_publish"] = False
            self._write(raw)
            return True
