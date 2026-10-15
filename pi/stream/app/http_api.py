"""LAN HTTP: health, single snapshot, multipart MJPEG for go2rtc."""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from . import __version__
from .config import source_fetch_url
from .frame_buffer import FrameBuffer


def make_handler(
    cfg: dict[str, Any],
    buffer: FrameBuffer,
    *,
    started_at: float,
) -> type[BaseHTTPRequestHandler]:
    enabled = bool(cfg.get("enabled", True))
    fps = float((cfg.get("stream") or {}).get("fps") or 2.0)
    boundary = str((cfg.get("stream") or {}).get("boundary") or "frame")
    frame_interval = 1.0 / max(0.2, min(fps, 15.0))
    source_url = source_fetch_url(cfg)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = f"webcam-stream/{__version__}"

        def log_message(self, fmt: str, *args: Any) -> None:
            # Keep journal quiet; health/stream are high-volume.
            if self.path.startswith("/health"):
                return
            super().log_message(fmt, *args)

        def _send_json(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Webcam-Stream", "lan-only")
            self.end_headers()
            self.wfile.write(body)

        def _send_bytes(
            self,
            code: int,
            data: bytes,
            *,
            content_type: str,
            extra: dict[str, str] | None = None,
        ) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Webcam-Stream", "lan-only")
            if extra:
                for k, v in extra.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path == "/":
                self._send_json(
                    200,
                    {
                        "application": "webcam-stream",
                        "version": __version__,
                        "enabled": enabled,
                        "endpoints": [
                            "GET /health",
                            "GET /snapshot.jpg",
                            "GET /stream.mjpg",
                            "GET /stream",
                        ],
                        "note": (
                            "LAN-only uncensored MJPEG Extra. "
                            "Pulls /raw.jpg from webcam-camera — does not open the CSI sensor. "
                            "Do not port-forward or publish this stream."
                        ),
                    },
                )
                return
            if path == "/health":
                snap = buffer.snapshot()
                status = "DISABLED" if not enabled else (
                    "HEALTHY" if snap["has_frame"] else "DEGRADED"
                )
                self._send_json(
                    200,
                    {
                        "application": "webcam-stream",
                        "version": __version__,
                        "status": status,
                        "enabled": enabled,
                        "bind_port": int(cfg.get("bind_port") or 8081),
                        "source_url": source_url,
                        "fps": fps,
                        "uptime_seconds": round(time.time() - started_at, 1),
                        "frame": snap,
                        "summary": (
                            "disabled in config"
                            if not enabled
                            else (
                                "serving latest uncensored frame as MJPEG"
                                if snap["has_frame"]
                                else "waiting for first frame from webcam-camera"
                            )
                        ),
                        "next_steps": (
                            []
                            if snap["has_frame"] or not enabled
                            else [
                                "Confirm webcam-camera is up: curl -fsS http://127.0.0.1:8080/health",
                                "curl -fsS -o /tmp/raw.jpg http://127.0.0.1:8080/raw.jpg",
                                "journalctl -u webcam-stream -n 50 --no-pager",
                            ]
                        ),
                    },
                )
                return
            if path in ("/snapshot.jpg", "/snapshot"):
                if not enabled:
                    self._send_json(503, {"error": "stream disabled", "enabled": False})
                    return
                jpeg, _ = buffer.get()
                if jpeg is None:
                    self._send_json(503, {"error": "no frame yet"})
                    return
                self._send_bytes(200, jpeg, content_type="image/jpeg")
                return
            if path in ("/stream.mjpg", "/stream.mjpeg", "/stream"):
                self._serve_mjpeg()
                return
            self._send_json(
                404,
                {
                    "error": "not found",
                    "endpoints": ["/", "/health", "/snapshot.jpg", "/stream.mjpg"],
                },
            )

        def _serve_mjpeg(self) -> None:
            if not enabled:
                self._send_json(503, {"error": "stream disabled", "enabled": False})
                return
            self.send_response(200)
            self.send_header(
                "Content-Type",
                f"multipart/x-mixed-replace; boundary={boundary}",
            )
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("X-Webcam-Stream", "lan-only")
            self.end_headers()

            try:
                while True:
                    jpeg, _ts = buffer.get()
                    if jpeg is None:
                        time.sleep(min(0.5, frame_interval))
                        continue
                    # Re-emit the latest JPEG at fps when capture has not updated
                    # yet (still-JPEG appliance; freshness follows camera interval).
                    header = (
                        f"--{boundary}\r\n"
                        f"Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpeg)}\r\n"
                        f"\r\n"
                    ).encode("ascii")
                    self.wfile.write(header)
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                    time.sleep(frame_interval)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

    return Handler


def serve(
    cfg: dict[str, Any],
    buffer: FrameBuffer,
    *,
    started_at: float,
) -> ThreadingHTTPServer:
    host = str(cfg.get("bind_host") or "0.0.0.0")
    port = int(cfg.get("bind_port") or 8081)
    handler = make_handler(cfg, buffer, started_at=started_at)
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd
