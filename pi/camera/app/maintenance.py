from __future__ import annotations

import hashlib
import io
import logging
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("camera-appliance")

_ASSET = Path(__file__).resolve().parent / "assets" / "maintenance.jpg"


def _placeholder_jpeg() -> bytes:
    """Shipped photo, or a plain slide when that file was removed."""
    if _ASSET.is_file():
        return _ASSET.read_bytes()
    from PIL import ImageDraw

    from shared.brand_overlay import StatusCopy, draw_status_overlay, plain_status_background

    copy = StatusCopy.english()
    img = plain_status_background((1280, 720))
    draw_status_overlay(
        ImageDraw.Draw(img),
        width=img.width,
        height=img.height,
        title=copy.maintenance_title,
        body=copy.maintenance_body,
    )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


class MaintenanceMode:
    """Serve a fixed placeholder at /feed.jpg without stopping capture.

    Flag file content:
      - ``manual`` — operator enabled (survives restart; not auto-cleared)
      - ``auto:<reason>`` — auto-enabled for production fail-safe (cleared on recovery)
    """

    def __init__(self, flag_path: Path, jpeg: bytes | None = None) -> None:
        self.flag_path = flag_path
        data = jpeg if jpeg is not None else _placeholder_jpeg()
        if len(data) < 100 or data[:2] != b"\xff\xd8":
            raise ValueError("maintenance placeholder is not a JPEG")
        self.jpeg = data
        digest = hashlib.sha256(data).hexdigest()[:16]
        self.etag = f'W/"maintenance-{len(data)}-{digest}"'
        self._lock = threading.Lock()
        self.enabled = False
        self.auto = False
        self.reason: str | None = None
        self._load_flag()

    def _load_flag(self) -> None:
        if not self.flag_path.exists():
            self.enabled = False
            self.auto = False
            self.reason = None
            return
        raw = self.flag_path.read_text(encoding="utf-8").strip()
        self.enabled = True
        if raw.startswith("auto:"):
            self.auto = True
            self.reason = raw[5:].strip() or "unknown"
        elif raw in ("", "1", "manual"):
            # Legacy ``1`` / empty treated as manual
            self.auto = False
            self.reason = None
        else:
            self.auto = False
            self.reason = None

    def _write_flag(self) -> None:
        self.flag_path.parent.mkdir(parents=True, exist_ok=True)
        if self.auto:
            body = f"auto:{self.reason or 'unknown'}\n"
        else:
            body = "manual\n"
        self.flag_path.write_text(body, encoding="utf-8")

    def _persist(self, *, want_flag: bool) -> bool:
        """Best-effort flag file sync. In-memory state always wins for /feed.jpg.

        Mid-sync chown of data/ to the SSH user used to raise PermissionError here
        and kill the capture-loop thread. Fail soft instead.
        """
        try:
            if want_flag:
                self._write_flag()
            else:
                self.flag_path.unlink(missing_ok=True)
            return True
        except OSError as exc:
            log.warning(
                "[maintenance] could not persist flag %s (%s) — in-memory state kept; "
                "run sudo /opt/home-webcam-pipeline/pi/scripts/fix-data-perms.sh if this continues",
                self.flag_path,
                exc,
            )
            return False

    def set_enabled(self, enabled: bool, *, auto: bool = False, reason: str | None = None) -> bool:
        """Enable or disable. Manual calls use auto=False (default)."""
        with self._lock:
            if enabled:
                self.enabled = True
                self.auto = bool(auto)
                self.reason = reason if auto else None
                self._persist(want_flag=True)
            else:
                self.enabled = False
                self.auto = False
                self.reason = None
                self._persist(want_flag=False)
            return self.enabled

    def auto_enable(self, reason: str) -> bool:
        """Turn on Wartungsbild for a production failure.

        - Newly enables → returns True
        - Already auto → refreshes reason if needed; returns False
        - Already manual while we need auto → upgrades to auto; returns True

        Never raises on disk errors (in-memory enable still applies).
        """
        with self._lock:
            reason = reason or "unknown"
            if self.enabled and self.auto:
                if reason != self.reason:
                    self.reason = reason
                    self._persist(want_flag=True)
                return False
            if self.enabled and not self.auto:
                # Upgrade legacy/manual flag so health shows maintenance_auto + reason
                self.auto = True
                self.reason = reason
                self._persist(want_flag=True)
                return True
            self.enabled = True
            self.auto = True
            self.reason = reason
            self._persist(want_flag=True)
            return True

    def auto_clear(self) -> bool:
        """Clear only if auto-enabled (capture recovered). Manual stays on."""
        with self._lock:
            if not self.enabled or not self.auto:
                return False
            self.enabled = False
            self.auto = False
            self.reason = None
            self._persist(want_flag=False)
            return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            note = (
                "Placeholder is served at /feed.jpg. Raw (/raw.jpg) stays the live capture for aiming."
                if self.enabled
                else "Live capture is served at /feed.jpg (same as /raw.jpg)."
            )
            if self.enabled and self.auto:
                note = (
                    f"Auto Wartungsbild ({self.reason or 'unknown'}): placeholder at /feed.jpg. "
                    "Raw (/raw.jpg) stays live; capture keeps retrying underneath."
                )
            return {
                "enabled": self.enabled,
                "auto": self.auto,
                "maintenance_auto": self.auto,
                "reason": self.reason,
                "header": "X-Webcam-Maintenance",
                "note": note,
            }
