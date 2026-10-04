from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from shared.host_uptime import system_uptime_seconds


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _list_video_devices() -> list[str]:
    try:
        return sorted(str(p) for p in Path("/dev").glob("video*") if p.exists())
    except OSError:
        return []


# libcamera exposes many /dev/video* nodes; dump full list only when diagnosing miss.


def _video_devices_summary(devices: list[str], *, include_full: bool) -> dict[str, Any]:
    """Compact /dev/video* for health/UI — avoid 20+ node noise when camera is OK."""
    count = len(devices)
    if include_full:
        return {
            "video_devices": list(devices),
            "video_devices_count": count,
            "video_devices_truncated": False,
            "video_devices_checked": True,
        }
    # Healthy path: count only (UI shows "N nodes"); full list on miss/fixture.
    return {
        "video_devices": [],
        "video_devices_count": count,
        "video_devices_truncated": count > 0,
        "video_devices_checked": True,
    }


def _picamera2_importable() -> bool:
    try:
        import picamera2  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def connectivity_snapshot(
    backend_name: str,
    camera_info: dict[str, Any],
    *,
    maintenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """UI-friendly camera connectivity summary (missing HW / OK / fixture backend)."""
    detected = bool(camera_info.get("detected"))
    video_devices = _list_video_devices()
    picamera2 = _picamera2_importable()
    fixture_backend = backend_name == "simulation"
    maint_on = bool(maintenance and maintenance.get("enabled"))
    maint_auto = bool(maintenance and maintenance.get("auto"))
    maint_reason = (maintenance or {}).get("reason") if maint_on else None

    if fixture_backend:
        level = "warn"
        ok = True  # intentional local/CI fixture
        label = "Capture unavailable — no camera"
        detail = "No live camera; serving a fixture JPEG for local development."
    elif not detected:
        level = "bad"
        ok = False
        label = "No camera detected"
        open_err = camera_info.get("open_error")
        detail = (
            f"Capture backend: {backend_name}. Check the camera cable, "
            "picamera2, and /dev/video* devices."
        )
        if open_err:
            detail = f"{detail} Open error: {open_err}."
        if maint_auto:
            detail = (
                f"{detail} Maintenance image is ON automatically "
                f"({maint_reason or 'no_camera'}) — /feed.jpg shows the placeholder "
                "while /raw.jpg stays live and capture keeps retrying."
            )
        else:
            detail = (
                f"{detail} Fail-safe: maintenance image turns on automatically "
                "when the camera is missing or capture fails."
            )
    else:
        level = "ok"
        ok = True
        model = camera_info.get("model") or "unknown"
        label = f"Camera connected ({model})"
        detail = f"Capture backend: {backend_name}"
        if maint_on:
            level = "warn"
            if maint_auto:
                label = (
                    f"Camera OK — maintenance image on automatically "
                    f"({maint_reason or 'unknown'})"
                )
                detail = (
                    f"{detail}; auto maintenance reason={maint_reason}. "
                    "Placeholder shown until maintenance is cleared or capture stays healthy."
                )
            else:
                label = "Camera OK — maintenance image on (manual)"
                detail = f"{detail}; maintenance enabled manually"

    # Full /dev/video* only when missing/fixture — healthy imx477 path just needs a count.
    devices_meta = _video_devices_summary(
        video_devices, include_full=(not detected or fixture_backend)
    )
    return {
        "ok": ok,
        "level": level,
        "backend": backend_name,
        "camera_detected": detected,
        "label": label,
        "detail": detail,
        "maintenance_auto": maint_auto,
        "maintenance_reason": maint_reason,
        **devices_meta,
        "picamera2": picamera2,
    }


class AppState:
    def __init__(self, version: str, config: dict[str, Any], backend_name: str) -> None:
        self.version = version
        self.config = config
        self.backend_name = backend_name
        self.started_at = time.time()
        self._lock = threading.Lock()
        self.camera_info: dict[str, Any] = {"detected": False, "model": "unknown"}
        self.image_path: Path | None = None
        self.last_success_at: float | None = None
        self.last_failure_at: float | None = None
        self.last_error: str | None = None
        self.last_capture_duration: float | None = None
        self.last_image_size: int | None = None
        self.success_count = 0
        self.failure_count = 0
        self.consecutive_failures = 0
        self.last_manual_capture_at: float = 0.0
        self.serving_stale_image = False
        self.last_event: str | None = None

    def record_success(
        self,
        path: Path,
        meta: dict[str, Any],
        duration: float,
        *,
        cold_start: bool = False,
    ) -> None:
        with self._lock:
            self.image_path = path
            self.last_success_at = time.time() if not cold_start else meta.get("mtime", time.time())
            self.last_capture_duration = duration
            self.last_image_size = int(meta.get("size_bytes") or 0)
            self.last_error = None
            self.consecutive_failures = 0
            self.serving_stale_image = False
            self.last_event = "cold_start_loaded_existing" if cold_start else "capture_ok"
            if not cold_start:
                self.success_count += 1

    def record_failure(self, error: str, duration: float) -> None:
        with self._lock:
            self.last_failure_at = time.time()
            self.last_error = error
            self.last_capture_duration = duration
            self.failure_count += 1
            self.consecutive_failures += 1
            # Fail-safe: if we still have a file on disk, we keep serving it
            has_image = self.image_path is not None and Path(self.image_path).exists()
            self.serving_stale_image = has_image
            self.last_event = "capture_failed_kept_last_good" if has_image else "capture_failed_no_image"

    def _compute_status_locked(self, now: float) -> tuple[str, list[str], list[str]]:
        """Return status, human reasons, next_steps."""
        age = None if self.last_success_at is None else now - self.last_success_at
        stale_after = float(self.config.get("health", {}).get("stale_after_seconds", 120))
        has_image = self.image_path is not None and Path(self.image_path).exists()
        camera_ok = bool(self.camera_info.get("detected"))
        reasons: list[str] = []
        steps: list[str] = []

        if not camera_ok and self.backend_name != "simulation":
            reasons.append("camera not detected")
            steps.append("Check ribbon cable / `rpicam-hello` / capture_backend in camera.yaml")
            steps.append(
                "Missing camera auto-enables Wartungsbild; fix the hardware — "
                "capture keeps retrying underneath"
            )

        if not has_image:
            status = "UNHEALTHY"
            reasons.append("no valid JPEG on disk")
            steps.append("POST /capture or wait for the capture loop; check journalctl -u webcam-camera")
            steps.append(
                "If Wartungsbild is on, /feed.jpg serves the maintenance placeholder; "
                "/raw.jpg stays the live capture"
            )
            return status, reasons, steps

        if self.consecutive_failures > 0:
            reasons.append(f"{self.consecutive_failures} consecutive capture failure(s)")
            reasons.append("fail-safe: last good JPEG kept on disk (Wartungsbild if maintenance on)")
            steps.append(f"Inspect last_capture_error: {self.last_error}")
            err_l = (self.last_error or "").lower()
            if "permission denied" in err_l:
                steps.append(
                    "Permission denied on camera data/ — often mid-sync chown. "
                    "Run: sudo /opt/home-webcam-pipeline/pi/scripts/fix-data-perms.sh "
                    "(sync-to-pi.sh should no longer chown data/)"
                )
            steps.append("journalctl -u webcam-camera -n 50 --no-pager")

        if age is not None and age > stale_after:
            reasons.append(f"image older than stale_after_seconds ({stale_after:.0f}s)")
            steps.append("Confirm capture_loop is running and interval_seconds is sensible")

        if self.consecutive_failures == 0 and age is not None and age <= stale_after:
            status = "HEALTHY"
            reasons.append("recent successful capture; valid image available")
        else:
            status = "DEGRADED"

        if not steps and status == "HEALTHY":
            steps.append("No action needed. curl /raw.jpg /feed.jpg and /health to verify.")

        return status, reasons, steps

    def health(self, *, maintenance: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            age = None if self.last_success_at is None else now - self.last_success_at
            has_image = self.image_path is not None and Path(self.image_path).exists()
            status, reasons, steps = self._compute_status_locked(now)
            connectivity = connectivity_snapshot(
                self.backend_name, self.camera_info, maintenance=maintenance
            )
            sys_up = system_uptime_seconds()
            maint_on = bool(maintenance and maintenance.get("enabled"))
            if maint_on:
                # Never claim "No action needed" while Wartungsbild is serving /feed.jpg.
                steps = [s for s in steps if not s.lower().startswith("no action needed")]
                if maintenance.get("auto"):
                    steps.insert(
                        0,
                        "Wartungsbild auto-ON — fix camera HW, then clear via /debug/ui "
                        "or POST /maintenance/off",
                    )
                else:
                    steps.insert(
                        0,
                        "Wartungsbild is ON — turn off via /debug/ui or POST /maintenance/off "
                        "to serve live frames on /feed.jpg",
                    )
                if connectivity.get("level") == "warn":
                    steps.append(
                        "Connectivity is warn while maintenance is on — live capture may still "
                        "be OK underneath (/raw.jpg stays live for aiming)"
                    )
                fail_note = (
                    "Wartungsbild (maintenance) is served at /feed.jpg. "
                    "/raw.jpg stays the live capture for aiming. "
                    "Last-good JPEG is kept on disk; capture keeps retrying."
                )
            elif has_image:
                fail_note = (
                    "On capture failure the previous valid JPEG is kept on disk. "
                    "After repeated failures, auto Wartungsbild engages on /feed.jpg."
                )
            else:
                fail_note = (
                    "No valid image yet — /raw.jpg and /feed.jpg return 503 until first success "
                    "(or /feed.jpg serves Wartungsbild if maintenance is on)."
                )

            return {
                "status": status,
                "summary": "; ".join(reasons),
                "fail_safe": {
                    "serving_last_good_image": bool(has_image) and not maint_on,
                    "serving_maintenance_placeholder": maint_on,
                    "never_overwrite_with_bad_capture": True,
                    "note": fail_note,
                },
                "reasons": reasons,
                "next_steps": steps,
                "application": "camera-appliance",
                "version": self.version,
                "camera_detected": bool(self.camera_info.get("detected")),
                "camera_model": self.camera_info.get("model"),
                "backend": self.backend_name,
                "connectivity": connectivity,
                "video_devices": connectivity["video_devices"],
                "video_devices_count": connectivity.get("video_devices_count"),
                "video_devices_truncated": connectivity.get("video_devices_truncated"),
                "last_successful_capture": _iso(self.last_success_at),
                "last_failure_at": _iso(self.last_failure_at),
                "image_age_seconds": None if age is None else round(age, 3),
                "last_capture_duration_seconds": self.last_capture_duration,
                "last_capture_error": self.last_error,
                "last_event": self.last_event,
                "consecutive_failure_count": self.consecutive_failures,
                "total_successful_captures": self.success_count,
                "total_failed_captures": self.failure_count,
                "uptime_seconds": round(now - self.started_at, 3),
                "system_uptime_seconds": None if sys_up is None else round(sys_up, 3),
                "has_valid_image": has_image,
                "last_image_size_bytes": self.last_image_size,
            }

    def status(self) -> dict[str, Any]:
        health = self.health()
        with self._lock:
            cap = self.config.get("capture", {})
            return {
                **health,
                "bind_host": self.config.get("bind_host"),
                "bind_port": self.config.get("bind_port"),
                "endpoints": {
                    "raw": "GET /raw.jpg — always last-good live capture (aim/focus; never Wartungsbild)",
                    "feed": "GET /feed.jpg — downstream feed (Wartungsbild when maintenance on)",
                    "health": "GET /health — short status + next_steps",
                    "status": "GET /status — full operational dump",
                    "debug": "GET /debug — troubleshooting checklist",
                    "debug_ui": "GET /debug/ui — toggle maintenance image",
                    "home": "GET / — camera home (status, preview, live preview, capture)",
                    "maintenance": "GET /maintenance  POST /maintenance/on|/off",
                    "live_preview": "GET /live-preview  POST /live-preview/on|/off — temporary high-rate capture for aiming",
                    "capture": "POST /capture — manual capture (rate-limited)",
                },
                "capture": {
                    "width": cap.get("width"),
                    "height": cap.get("height"),
                    "jpeg_quality": cap.get("jpeg_quality"),
                    "interval_seconds": cap.get("interval_seconds"),
                    "timeout_seconds": cap.get("timeout_seconds"),
                },
                "health_thresholds": self.config.get("health", {}),
                "camera_info": self.camera_info,
                "image_path": str(self.image_path) if self.image_path else None,
            }

    def debug(self) -> dict[str, Any]:
        status = self.status()
        return {
            **status,
            "troubleshoot": {
                "quick_checks": [
                    "curl -sS http://127.0.0.1:8080/health | jq .status,.summary,.next_steps",
                    "curl -sS -o /tmp/raw.jpg -w '%{http_code} %{size_download}\\n' http://127.0.0.1:8080/raw.jpg",
                    "curl -sS -o /tmp/feed.jpg -w '%{http_code} %{size_download}\\n' http://127.0.0.1:8080/feed.jpg",
                    "journalctl -u webcam-camera -n 80 --no-pager",
                    "systemctl status webcam-camera --no-pager",
                ],
                "common_failures": {
                    "UNHEALTHY_no_image": "First boot / empty storage — wait for capture or POST /capture",
                    "DEGRADED_failures": (
                        "Camera busy/disconnected — last good kept on disk; "
                        "auto Wartungsbild after repeated failures"
                    ),
                    "DEGRADED_permission": (
                        "Errno 13 on pi/camera/data — fix-data-perms.sh; "
                        "sync must not chown data/ while units run"
                    ),
                    "DEGRADED_stale": "Capture loop stalled — check interval and service logs",
                    "auto_maintenance": (
                        "no_camera / capture_failed → maintenance_auto; /feed.jpg serves Wartungsbild "
                        "(/raw.jpg stays live when a frame exists)"
                    ),
                },
            },
        }
