from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_pipeline_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError("pipeline config must be a mapping")
    if not data.get("cameras"):
        raise ValueError("pipeline config requires cameras: list")
    data.setdefault("logging", {"level": "INFO"})
    data.setdefault("publish", {"enabled": False, "backend": "local"})
    return data


def resolve_repo_root(cfg: dict[str, Any], config_path: Path) -> Path:
    if cfg.get("repo_root"):
        return Path(cfg["repo_root"]).expanduser().resolve()
    # Walk up from pi/pipeline/config/… until cameras/ + shared/ exist
    from shared.repo_root import find_repo_root

    return find_repo_root(config_path)
