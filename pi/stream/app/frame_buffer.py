"""Thread-safe latest-JPEG buffer shared by the fetch loop and HTTP handlers."""

from __future__ import annotations

import threading
import time
from typing import Any


class FrameBuffer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._updated_at: float | None = None
        self._etag: str | None = None
        self._bytes: int = 0
        self._fetch_ok: int = 0
        self._fetch_fail: int = 0
        self._last_error: str | None = None
        self._last_status: int | None = None
        self._ingest_lag_seconds: float | None = None
        self._source_mtime: float | None = None
        self._cond = threading.Condition(self._lock)

    def put(
        self,
        jpeg: bytes,
        *,
        etag: str | None = None,
        status: int | None = None,
        source_mtime: float | None = None,
        ingest_lag_seconds: float | None = None,
    ) -> None:
        with self._cond:
            now = time.time()
            self._jpeg = jpeg
            self._updated_at = now
            self._etag = etag
            self._bytes = len(jpeg)
            self._fetch_ok += 1
            self._last_error = None
            self._last_status = status
            self._source_mtime = source_mtime
            if ingest_lag_seconds is not None:
                self._ingest_lag_seconds = max(0.0, float(ingest_lag_seconds))
            elif source_mtime is not None:
                self._ingest_lag_seconds = max(0.0, now - float(source_mtime))
            self._cond.notify_all()

    def record_error(self, error: str, *, status: int | None = None) -> None:
        with self._lock:
            self._fetch_fail += 1
            self._last_error = error
            self._last_status = status

    def get(self) -> tuple[bytes | None, float | None]:
        with self._lock:
            return self._jpeg, self._updated_at

    def wait_next(self, after: float | None, timeout: float) -> tuple[bytes | None, float | None]:
        """Wait until a newer frame arrives, or timeout with the current frame."""
        deadline = time.monotonic() + max(0.01, timeout)
        with self._cond:
            while True:
                jpeg = self._jpeg
                updated = self._updated_at
                if jpeg is not None and (after is None or (updated is not None and updated > after)):
                    return jpeg, updated
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return jpeg, updated
                self._cond.wait(timeout=remaining)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            age = None
            if self._updated_at is not None:
                age = max(0.0, time.time() - self._updated_at)
            return {
                "has_frame": self._jpeg is not None,
                "size_bytes": self._bytes,
                "age_seconds": age,
                "etag": self._etag,
                "fetch_ok": self._fetch_ok,
                "fetch_fail": self._fetch_fail,
                "last_error": self._last_error,
                "last_http_status": self._last_status,
                "updated_at": self._updated_at,
                "source_mtime": self._source_mtime,
                "ingest_lag_seconds": self._ingest_lag_seconds,
            }
