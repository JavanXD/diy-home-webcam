#!/usr/bin/env python3
"""Tiny captive-portal helper: any HTTP request on :80 → setup UI.

Only meant to run while the setup AP is active. If port 80 is already taken
(nginx on a configured Pi), this process exits and the phone uses :8090 directly.
"""

from __future__ import annotations

import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GATEWAY = os.environ.get("SETUP_AP_GATEWAY", "10.42.0.1").strip() or "10.42.0.1"
TARGET = os.environ.get(
    "SETUP_AP_CAPTIVE_URL",
    f"http://{GATEWAY}:8090/setup/ui",
).strip()
BIND = os.environ.get("SETUP_AP_CAPTIVE_BIND", "0.0.0.0")
PORT = int(os.environ.get("SETUP_AP_CAPTIVE_PORT", "80"))


class Handler(BaseHTTPRequestHandler):
    def _redirect(self) -> None:
        self.send_response(302)
        self.send_header("Location", TARGET)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._redirect()

    def do_HEAD(self) -> None:  # noqa: N802
        self._redirect()

    def do_POST(self) -> None:  # noqa: N802
        self._redirect()

    def log_message(self, fmt: str, *args) -> None:
        # Quiet; journald captures unexpected failures from systemd.
        return


def main() -> int:
    try:
        httpd = ThreadingHTTPServer((BIND, PORT), Handler)
    except OSError as exc:
        print(f"captive redirect cannot bind {BIND}:{PORT}: {exc}", flush=True)
        return 1
    # Avoid hanging forever on accept if the interface goes away.
    httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    print(f"captive redirect listening on {BIND}:{PORT} → {TARGET}", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
