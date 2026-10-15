from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import yaml


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")

    data.setdefault("enabled", True)
    data.setdefault("bind_host", "0.0.0.0")
    data.setdefault("bind_port", 8081)

    source = data.setdefault("source", {})
    if not isinstance(source, dict):
        raise ValueError("source must be a mapping")
    source.setdefault("url", "http://127.0.0.1:8080/raw.jpg")
    source.setdefault("width", 960)
    source.setdefault("timeout_seconds", 8.0)

    stream = data.setdefault("stream", {})
    if not isinstance(stream, dict):
        raise ValueError("stream must be a mapping")
    stream.setdefault("fps", 2.0)
    stream.setdefault("jpeg_quality", 72)
    stream.setdefault("boundary", "frame")

    overlay = data.setdefault("overlay", {})
    if not isinstance(overlay, dict):
        raise ValueError("overlay must be a mapping")
    overlay.setdefault("enabled", True)
    # Default frame clock timezone for the LAN Extra (override in stream.yaml).
    overlay.setdefault("timezone", "Europe/Berlin")
    # Uppercased at render time so %a becomes WED.
    overlay.setdefault("format", "%d/%m/%Y %H:%M:%S %a")
    overlay.setdefault("margin", 12)
    overlay.setdefault("font_scale", 0.035)

    data.setdefault("logging", {"level": "INFO"})
    return data


def source_fetch_url(cfg: dict[str, Any]) -> str:
    """Build the HTTP URL used to pull frames (adds ``?w=`` when width is set)."""
    source = cfg.get("source") or {}
    base = str(source.get("url") or "http://127.0.0.1:8080/raw.jpg").strip()
    width = int(source.get("width") or 0)
    if width < 32:
        return base
    parsed = urlparse(base)
    q = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "w" not in q:
        q["w"] = str(width)
    return urlunparse(parsed._replace(query=urlencode(q)))
