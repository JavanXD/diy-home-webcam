"""Raspberry Pi camera appliance — capture + LAN HTTP API."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .capture import create_backend
from .config import load_config
from .http_api import make_handler
from .live_preview import DEFAULT_DURATION_SECONDS, DEFAULT_INTERVAL_SECONDS, LivePreview
from .maintenance import MaintenanceMode
from .state import AppState
from .storage import ImageStore

log = logging.getLogger("camera-appliance")


def setup_logging(level: str) -> None:
    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from shared.logging_util import setup_logging as _setup

    _setup(level, name="camera-appliance")


def _auto_maintenance_reason(state: AppState, error: str) -> str:
    err = (error or "").lower()
    if not state.camera_info.get("detected"):
        return "no_camera"
    if "open failed" in err or "not found" in err or "no camera" in err:
        return "no_camera"
    return "capture_failed"


def capture_loop(
    state: AppState,
    store: ImageStore,
    backend,
    interval: float,
    stop: threading.Event,
    *,
    maintenance: MaintenanceMode | None = None,
    live_preview: LivePreview | None = None,
    auto_after_failures: int = 2,
    quiet_success_every: int = 12,
) -> None:
    """Periodic capture. Failures never wipe the last good JPEG.

    On hardware backends: after enough consecutive failures, auto-enable
    Wartungsbild so /feed.jpg stays available while capture keeps retrying.

    While live_preview is active, wait uses the short preview interval so
    /raw.jpg refreshes often enough for aiming/focus; otherwise normal interval.
    """
    cycle = 0
    last_fail_key: str | None = None
    while not stop.is_set():
        cycle += 1
        started = time.monotonic()
        preview_active = bool(live_preview and live_preview.active())
        try:
            data = backend.capture()
            path, meta = store.save_jpeg(data)
            duration = time.monotonic() - started
            state.record_success(path, meta, duration)
            last_fail_key = None
            # Refresh camera_info after a late open (HardwareCaptureBackend)
            try:
                state.camera_info = backend.info()
            except Exception:  # noqa: BLE001
                pass
            if maintenance is not None and state.backend_name != "simulation":
                if maintenance.auto_clear():
                    log.info(
                        "[capture] auto Wartungsbild cleared after successful capture cycle=%d",
                        cycle,
                    )
            msg = (
                f"[capture] ok cycle={cycle} size={meta['size_bytes']}B "
                f"duration={duration*1000:.0f}ms path={path}"
                + (" preview=1" if preview_active else "")
            )
            # Preview sessions are chatty at DEBUG; log INFO every N or first
            if preview_active:
                if cycle == 1 or cycle % max(1, quiet_success_every * 2) == 0:
                    log.info(msg)
                else:
                    log.debug(msg)
            elif cycle == 1 or cycle % quiet_success_every == 0:
                log.info(msg)
            else:
                log.debug(msg)
        except Exception as exc:  # noqa: BLE001 — keep service alive
            duration = time.monotonic() - started
            state.record_failure(str(exc), duration)
            try:
                state.camera_info = backend.info()
            except Exception:  # noqa: BLE001
                pass
            health = state.health(
                maintenance=maintenance.snapshot() if maintenance is not None else None
            )
            fail_key = str(exc)
            # Full next_steps on new error / first two / every quiet_success_every after
            detail = (
                fail_key != last_fail_key
                or state.consecutive_failures <= 2
                or state.consecutive_failures % max(1, quiet_success_every) == 0
            )
            if detail:
                log.warning(
                    "[capture] FAILED cycle=%d duration=%.0fms error=%s | fail-safe=%s | status=%s",
                    cycle,
                    duration * 1000,
                    exc,
                    health["fail_safe"]["note"],
                    health["status"],
                )
                for step in health.get("next_steps") or []:
                    log.warning("[capture] next: %s", step)
            else:
                log.warning(
                    "[capture] FAILED cycle=%d consecutive=%d error=%s (repeat; next_steps suppressed)",
                    cycle,
                    state.consecutive_failures,
                    exc,
                )
            last_fail_key = fail_key

            if (
                maintenance is not None
                and state.backend_name != "simulation"
                and auto_after_failures > 0
                and state.consecutive_failures >= auto_after_failures
            ):
                reason = _auto_maintenance_reason(state, str(exc))
                # auto_enable never raises; disk persist is fail-soft
                if maintenance.auto_enable(reason):
                    log.warning(
                        "[capture] auto Wartungsbild ON reason=%s consecutive_failures=%d",
                        reason,
                        state.consecutive_failures,
                    )
        # Adaptive wait: short chunks so turning preview on mid-interval reacts soon.
        slept = 0.0
        while not stop.is_set():
            active = bool(live_preview and live_preview.active())
            target = (
                float(live_preview.interval_seconds)
                if live_preview and active
                else float(interval)
            )
            if slept >= target:
                break
            chunk = min(0.25, target - slept)
            if stop.wait(chunk):
                break
            slept += chunk


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Webcam camera appliance")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parents[1] / "config" / "camera.yaml"),
        help="Path to camera.yaml",
    )
    parser.add_argument("--verbose", action="store_true", help="DEBUG logging")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if not config_path.exists():
        example = config_path.with_name("camera.example.yaml")
        if example.exists() and config_path.name == "camera.yaml":
            config_path = example
        else:
            print(f"Config not found: {config_path}", file=sys.stderr)
            print("Copy config/camera.example.yaml → config/camera.yaml", file=sys.stderr)
            return 1

    cfg = load_config(config_path)
    level = "DEBUG" if args.verbose else cfg["logging"]["level"]
    setup_logging(level)

    root = Path(__file__).resolve().parents[1]
    log.info(
        "starting camera-appliance version=%s config=%s backend=%s",
        __version__,
        config_path,
        cfg.get("capture_backend"),
    )

    store = ImageStore(
        image_path=root / cfg["storage"]["image_path"],
        keep_history=int(cfg["storage"].get("keep_history", 0)),
        history_dir=root / cfg["storage"].get("history_dir", "data/history"),
    )

    try:
        backend = create_backend(cfg, root)
    except Exception as exc:  # noqa: BLE001
        # Fixture backend (or unknown) can fail create_backend hard;
        # hardware backends defer open failure into HardwareCaptureBackend.
        log.error("[startup] camera backend failed: %s", exc)
        if str(cfg.get("capture_backend", "")).lower() == "simulation":
            log.error("[startup] next: fix fixture image path or JPEG")
        else:
            log.error("[startup] next: check capture_backend / camera.yaml")
            log.error("[startup] next: install python3-picamera2 / rpicam-still on the Pi")
        return 1

    state = AppState(version=__version__, config=cfg, backend_name=backend.name)
    state.camera_info = backend.info()
    log.info("[startup] camera info: %s", state.camera_info)

    maintenance = MaintenanceMode(store.image_path.parent / "maintenance.on")
    if maintenance.enabled:
        log.warning(
            "[startup] maintenance placeholder is ON auto=%s reason=%s — /feed.jpg is not the live frame (/raw.jpg stays live)",
            maintenance.auto,
            maintenance.reason,
        )

    lp_cfg = cfg.get("live_preview") or {}
    live_preview = LivePreview(
        duration_seconds=float(lp_cfg.get("duration_seconds", DEFAULT_DURATION_SECONDS)),
        interval_seconds=float(lp_cfg.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)),
    )

    # Hardware: no device at startup → Wartungsbild immediately
    if state.backend_name != "simulation" and not state.camera_info.get("detected"):
        if maintenance.auto_enable("no_camera"):
            log.warning(
                "[startup] no camera detected — auto Wartungsbild ON "
                "(capture will keep retrying)"
            )
        open_err = state.camera_info.get("open_error")
        if open_err:
            log.warning("[startup] camera open error: %s", open_err)

    if store.image_path.exists():
        try:
            meta = store.stat_current()
            state.record_success(store.image_path, meta, 0.0, cold_start=True)
            log.info(
                "[startup] loaded existing image size=%sB mtime=%s (will keep on failure)",
                meta["size_bytes"],
                meta.get("mtime_iso"),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("[startup] could not load existing image: %s", exc)
    else:
        if maintenance.enabled:
            log.info(
                "[startup] no live JPEG yet — /feed.jpg serves Wartungsbild; /raw.jpg returns 503 until capture recovers"
            )
        else:
            log.info("[startup] no existing image yet — /raw.jpg and /feed.jpg will 503 until first capture")

    stop = threading.Event()

    def on_signal(signum, _frame):
        log.info("[shutdown] signal %s received", signum)
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    interval = float(cfg["capture"]["interval_seconds"])
    auto_after = int(cfg.get("health", {}).get("auto_maintenance_after_failures", 2))
    worker = threading.Thread(
        target=capture_loop,
        args=(state, store, backend, interval, stop),
        kwargs={
            "maintenance": maintenance,
            "live_preview": live_preview,
            "auto_after_failures": auto_after,
        },
        name="capture-loop",
        daemon=True,
    )
    worker.start()
    log.info(
        "[startup] capture loop interval=%ss live_preview duration=%ss interval=%ss "
        "auto_maintenance_after_failures=%s",
        interval,
        live_preview.duration_seconds,
        live_preview.interval_seconds,
        auto_after,
    )

    handler = make_handler(state, store, backend, cfg, maintenance, live_preview)
    host = cfg["bind_host"]
    port = int(cfg["bind_port"])
    # Quiet BrokenPipe/ConnectionReset from browsers aborting mid-JPEG
    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from shared.http_server import QuietThreadingHTTPServer

    server = QuietThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    http_thread = threading.Thread(target=server.serve_forever, name="http", daemon=True)
    http_thread.start()

    log.info("[startup] HTTP listening on http://%s:%s/", host, port)
    log.info(
        "[startup] endpoints: /  /raw.jpg  /feed.jpg  /health  /status  /debug  /debug/ui  "
        "POST /capture  POST /maintenance/on|off  GET|POST /live-preview"
    )

    try:
        while not stop.is_set():
            stop.wait(0.5)
    finally:
        stop.set()
        server.shutdown()
        backend.close()
        log.info("[shutdown] stopped cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
