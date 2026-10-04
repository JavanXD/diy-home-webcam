"""Locate the monorepo root (directory that contains cameras/ + shared/)."""

from __future__ import annotations

from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    if here.is_file():
        here = here.parent
    for candidate in [here, *here.parents]:
        if (candidate / "cameras").is_dir() and (candidate / "shared").is_dir():
            return candidate
    raise FileNotFoundError(
        f"could not find repo root (cameras/ + shared/) above {here}"
    )
