"""Poll webcam-camera over HTTP — never opens the CSI sensor."""

from __future__ import annotations

import email.utils
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from .config import source_fetch_url
from .frame_buffer import FrameBuffer
from .osd import maybe_burn_in

log = logging.getLogger("webcam-stream")

_USER_AGENT = "home-webcam-stream/1.0"


def _parse_http_date(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(email.utils.parsedate_to_datetime(value).timestamp())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def fetch_loop(
    cfg: dict[str, Any],
    buffer: FrameBuffer,
    stop: threading.Event,
) -> None:
    url = source_fetch_url(cfg)
    timeout = float((cfg.get("source") or {}).get("timeout_seconds") or 8.0)
    fps = float((cfg.get("stream") or {}).get("fps") or 2.0)
    interval = 1.0 / max(0.2, min(fps, 15.0))
    etag: str | None = None
    log.info("[fetch] polling %s every %.2fs", url, interval)

    while not stop.is_set():
        started = time.monotonic()
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "image/jpeg,*/*",
                    **({"If-None-Match": etag} if etag else {}),
                },
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200) or 200
                data = resp.read()
                new_etag = resp.headers.get("ETag")
                ctype = (resp.headers.get("Content-Type") or "").lower()
                source_mtime = _parse_http_date(resp.headers.get("Last-Modified"))
            if status == 304 and buffer.snapshot()["has_frame"]:
                pass
            else:
                is_jpeg = bool(data) and (
                    "jpeg" in ctype or data[:3] == b"\xff\xd8\xff"
                )
                if not is_jpeg:
                    buffer.record_error(
                        f"non-JPEG response status={status} type={ctype!r}",
                        status=status,
                    )
                else:
                    if new_etag:
                        etag = new_etag
                    # Burn OSD once at ingest so /snapshot.jpg, /stream.mjpg, and
                    # go2rtc ffmpeg→H264 all see the same stamped JPEG. Timestamp
                    # prefers camera Last-Modified (frame age); frozen frames keep
                    # a stale clock while the multipart stream still ticks.
                    stamped = maybe_burn_in(
                        data,
                        cfg=cfg,
                        frame_epoch=source_mtime,
                        ingest_epoch=time.time(),
                    )
                    # Lag ≈ wall clock when Extra ingested a still vs camera Last-Modified.
                    buffer.put(
                        stamped,
                        etag=etag,
                        status=status,
                        source_mtime=source_mtime,
                    )
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and buffer.snapshot()["has_frame"]:
                pass
            else:
                buffer.record_error(f"HTTP {exc.code}: {exc.reason}", status=exc.code)
                log.warning("[fetch] HTTP %s from %s", exc.code, url)
        except Exception as exc:  # noqa: BLE001
            buffer.record_error(str(exc))
            log.warning("[fetch] %s", exc)

        elapsed = time.monotonic() - started
        stop.wait(timeout=max(0.01, interval - elapsed))
