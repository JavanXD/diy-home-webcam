from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .live_preview import DEFAULT_DURATION_SECONDS, DEFAULT_INTERVAL_SECONDS


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")
    required = ["bind_host", "bind_port", "capture_backend", "storage", "capture"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"missing config keys: {missing}")
    data.setdefault("logging", {"level": "INFO"})
    data.setdefault("http", {"capture_min_interval_seconds": 2, "max_body_bytes": 65536})
    health = data.setdefault("health", {})
    if not isinstance(health, dict):
        raise ValueError("health must be a mapping")
    # Default stale window scales with capture interval (≈5×); floor 5s for 1s live capture.
    try:
        interval = float((data.get("capture") or {}).get("interval_seconds", 1))
    except (TypeError, ValueError):
        interval = 1.0
    health.setdefault("stale_after_seconds", max(5.0, interval * 5.0))
    # Production: auto Wartungsbild after N consecutive capture failures (startup no-device is immediate)
    health.setdefault("auto_maintenance_after_failures", 2)
    live = data.setdefault("live_preview", {})
    if not isinstance(live, dict):
        raise ValueError("live_preview must be a mapping")
    live.setdefault("duration_seconds", DEFAULT_DURATION_SECONDS)
    live.setdefault("interval_seconds", DEFAULT_INTERVAL_SECONDS)
    return data
