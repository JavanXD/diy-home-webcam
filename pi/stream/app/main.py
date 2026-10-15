"""webcam-stream — LAN MJPEG Extra for go2rtc / Home Assistant."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .config import load_config, source_fetch_url
from .fetcher import fetch_loop
from .frame_buffer import FrameBuffer
from .http_api import serve

log = logging.getLogger("webcam-stream")


def setup_logging(level: str) -> None:
    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from shared.logging_util import setup_logging as _setup

    _setup(level, name="webcam-stream")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LAN MJPEG Extra (go2rtc-friendly)")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("/etc/webcam-stream/stream.yaml"),
        help="Path to stream.yaml",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    setup_logging(str((cfg.get("logging") or {}).get("level") or "INFO"))

    enabled = bool(cfg.get("enabled", True))
    host = str(cfg.get("bind_host") or "0.0.0.0")
    port = int(cfg.get("bind_port") or 8081)
    started = time.time()
    buffer = FrameBuffer()
    stop = threading.Event()

    log.info(
        "[startup] webcam-stream version=%s enabled=%s bind=%s:%s source=%s",
        __version__,
        enabled,
        host,
        port,
        source_fetch_url(cfg),
    )
    log.info(
        "[startup] LAN-only uncensored Extra — pulls HTTP frames from webcam-camera; "
        "does not open the CSI sensor. Do not port-forward :%s.",
        port,
    )

    fetch_thread: threading.Thread | None = None
    if enabled:
        fetch_thread = threading.Thread(
            target=fetch_loop,
            args=(cfg, buffer, stop),
            name="stream-fetch",
            daemon=True,
        )
        fetch_thread.start()
    else:
        log.warning(
            "[startup] enabled=false — /health stays up; /stream.mjpg returns 503. "
            "Set enabled: true in %s and restart webcam-stream.",
            args.config,
        )

    httpd = serve(cfg, buffer, started_at=started)

    def _shutdown(signum: int, _frame: object) -> None:
        log.info("[shutdown] signal=%s", signum)
        stop.set()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    log.info(
        "[startup] endpoints: /  /health  /snapshot.jpg  /stream.mjpg  on %s:%s",
        host,
        port,
    )
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        stop.set()
        httpd.server_close()
        if fetch_thread is not None:
            fetch_thread.join(timeout=2.0)
        log.info("[shutdown] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
