"""Temporary high-rate capture for aiming / focusing the lens.

In-memory session with a deadline (default ~5 min). Does not persist across
restarts — that is fine for a focus/aiming session. Wartungsbild / public
schedule are unaffected; only the capture loop interval and LAN UI poll rate
change while active.
"""

from __future__ import annotations

import threading
import time
from typing import Any

# Defaults (overridable via camera.yaml live_preview.*)
DEFAULT_DURATION_SECONDS = 300.0  # ~5 minutes — enough for lens aiming/focus
DEFAULT_INTERVAL_SECONDS = 0.75


class LivePreview:
    """In-memory live-preview / focus-mode session with auto-expiry."""

    def __init__(
        self,
        *,
        duration_seconds: float = DEFAULT_DURATION_SECONDS,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self.duration_seconds = float(duration_seconds)
        self.interval_seconds = float(interval_seconds)
        self._lock = threading.Lock()
        self._until_mono: float | None = None  # monotonic deadline

    def _expire_locked(self, now: float) -> None:
        if self._until_mono is not None and now >= self._until_mono:
            self._until_mono = None

    def active(self) -> bool:
        with self._lock:
            now = time.monotonic()
            self._expire_locked(now)
            return self._until_mono is not None

    def remaining_seconds(self) -> float | None:
        with self._lock:
            now = time.monotonic()
            self._expire_locked(now)
            if self._until_mono is None:
                return None
            return max(0.0, self._until_mono - now)

    def start(self) -> dict[str, Any]:
        """Start or refresh the preview window from now."""
        with self._lock:
            self._until_mono = time.monotonic() + self.duration_seconds
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._until_mono = None
        return self.snapshot()

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        if enabled:
            return self.start()
        return self.stop()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            self._expire_locked(now)
            enabled = self._until_mono is not None
            remaining = (
                round(max(0.0, self._until_mono - now), 3) if enabled else None
            )
            until_wall = None
            if enabled and self._until_mono is not None:
                # Convert monotonic remaining → wall clock for operators
                until_wall = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(time.time() + (self._until_mono - now)),
                )
            return {
                "enabled": enabled,
                "remaining_seconds": remaining,
                "until": until_wall,
                "duration_seconds": self.duration_seconds,
                "interval_seconds": self.interval_seconds,
                "note": (
                    "High-rate capture for aiming/focus. /raw.jpg refreshes often; "
                    "/feed.jpg, Wartungsbild, and public schedule are unchanged."
                    if enabled
                    else "Off — capture uses the normal interval. Start from Camera home."
                ),
                "ui": "GET /",
                "endpoints": {
                    "status": "GET /live-preview",
                    "on": "POST /live-preview/on",
                    "off": "POST /live-preview/off",
                },
            }
