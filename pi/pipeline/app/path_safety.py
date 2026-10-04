"""Reject path-traversal style ids/filenames on LAN JPEG routes."""

from __future__ import annotations

import re

# Camera ids and JPEG basenames used in /cameras/<id>/… URLs.
_CAMERA_ID = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
_JPEG_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}\.jpe?g$", re.IGNORECASE)


def safe_camera_id(value: str) -> str | None:
    cid = str(value or "").strip()
    if not cid or ".." in cid or "/" in cid or "\\" in cid:
        return None
    if not _CAMERA_ID.match(cid):
        return None
    return cid


def safe_jpeg_filename(value: str) -> str | None:
    name = str(value or "").strip()
    if not name or ".." in name or "/" in name or "\\" in name:
        return None
    if not _JPEG_NAME.match(name):
        return None
    return name
