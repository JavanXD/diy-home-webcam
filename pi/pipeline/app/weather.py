"""Station temperature for the public JPEG badge.

The URL comes from ``cameras/<id>/camera.yaml`` ``weather.url``. The JSON
must expose ``current.temp_c``. Fail-soft: never raises to callers; keeps the
last known temperature across brief outages. An empty URL skips the fetch.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("pipeline.weather")

DEFAULT_WEATHER_URL = ""
DEFAULT_TTL_SECONDS = 300.0
DEFAULT_TIMEOUT_SECONDS = 4.0


@dataclass
class WeatherSnapshot:
    temp_c: float | None
    fetched_at: float | None
    source: str  # "live" | "cache" | "stale" | "none"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "temp_c": self.temp_c,
            "fetched_at": self.fetched_at,
            "source": self.source,
            "error": self.error,
        }


class WeatherCache:
    """Process-wide TTL cache for station temperature."""

    def __init__(
        self,
        *,
        url: str = DEFAULT_WEATHER_URL,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.url = url
        self.ttl_seconds = max(30.0, float(ttl_seconds))
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self._lock = threading.Lock()
        self._temp_c: float | None = None
        self._fetched_at: float | None = None
        self._last_error: str | None = None

    def get(self, *, force: bool = False) -> WeatherSnapshot:
        if not (self.url or "").strip():
            return WeatherSnapshot(temp_c=None, fetched_at=None, source="none", error="no weather url")
        now = time.time()
        with self._lock:
            fresh = (
                self._fetched_at is not None
                and (now - self._fetched_at) < self.ttl_seconds
                and self._temp_c is not None
            )
            if fresh and not force:
                return WeatherSnapshot(
                    temp_c=self._temp_c,
                    fetched_at=self._fetched_at,
                    source="cache",
                )

        try:
            temp = self._fetch_temp_c()
        except Exception as exc:  # noqa: BLE001 — fail soft
            err = str(exc)
            log.warning("[weather] fetch failed: %s — using last known", err)
            with self._lock:
                self._last_error = err
                if self._temp_c is not None:
                    return WeatherSnapshot(
                        temp_c=self._temp_c,
                        fetched_at=self._fetched_at,
                        source="stale",
                        error=err,
                    )
                return WeatherSnapshot(temp_c=None, fetched_at=None, source="none", error=err)

        with self._lock:
            self._temp_c = temp
            self._fetched_at = now
            self._last_error = None
            return WeatherSnapshot(temp_c=temp, fetched_at=now, source="live")

    def _fetch_temp_c(self) -> float:
        req = urllib.request.Request(
            self.url,
            headers={"Accept": "application/json", "User-Agent": "home-webcam-pipeline/weather"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        current = data.get("current") if isinstance(data, dict) else None
        if not isinstance(current, dict) or current.get("temp_c") is None:
            raise ValueError("weather JSON missing current.temp_c")
        return float(current["temp_c"])


_default: WeatherCache | None = None
_default_lock = threading.Lock()


def get_weather_cache(
    *,
    url: str | None = None,
    ttl_seconds: float | None = None,
    timeout_seconds: float | None = None,
) -> WeatherCache:
    """Shared cache; reconfigured when URL/TTL change (camera.yaml)."""
    global _default
    with _default_lock:
        want_url = url or DEFAULT_WEATHER_URL
        want_ttl = DEFAULT_TTL_SECONDS if ttl_seconds is None else float(ttl_seconds)
        want_timeout = (
            DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else float(timeout_seconds)
        )
        if (
            _default is None
            or _default.url != want_url
            or _default.ttl_seconds != want_ttl
            or _default.timeout_seconds != want_timeout
        ):
            _default = WeatherCache(
                url=want_url,
                ttl_seconds=want_ttl,
                timeout_seconds=want_timeout,
            )
        return _default
