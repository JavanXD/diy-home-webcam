from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from shared.host_uptime import system_uptime_seconds

from .render import RenderedVariant


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


class PipelineState:
    def __init__(self, version: str, config: dict[str, Any], repo_root: Path) -> None:
        self.version = version
        self.config = config
        self.repo_root = repo_root
        self.started_at = time.time()
        self._lock = threading.Lock()
        self.cameras: dict[str, dict[str, Any]] = {}
        self.last_cycle_at: float | None = None
        self.last_cycle_summary: str | None = None
        self.publish_info: dict[str, Any] = {
            "enabled": bool((config.get("publish") or {}).get("enabled")),
            "backend": (config.get("publish") or {}).get("backend"),
            "last_error": None,
            "last_success_at": None,
            "fallback_note": None,
        }

    def _cam(self, camera_id: str) -> dict[str, Any]:
        if camera_id not in self.cameras:
            self.cameras[camera_id] = {
                "status": "UNKNOWN",
                "summary": "not processed yet",
                "last_error": None,
                "last_acquire_at": None,
                "last_source_sha": None,
                "last_changed": None,
                "last_cycle": None,
                "stages": {},
                "variants": {},
                "acquire_ok": 0,
                "acquire_fail": 0,
                "consecutive_failures": 0,
                "fail_safe": {
                    "keeping_last_original": False,
                    "keeping_last_variants": False,
                    "note": "On acquire failure, previous original and variants are left untouched.",
                },
                "next_steps": [],
            }
        return self.cameras[camera_id]

    def set_publish_info(self, **kwargs: Any) -> None:
        with self._lock:
            self.publish_info.update(kwargs)

    def record_cycle(
        self,
        camera_id: str,
        *,
        ok: bool,
        summary: str,
        stages: dict[str, Any],
        error: str | None = None,
        source_sha: str | None = None,
        changed: bool | None = None,
        original_path: str | None = None,
        next_steps: list[str] | None = None,
        fail_safe: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            c = self._cam(camera_id)
            now = time.time()
            self.last_cycle_at = now
            self.last_cycle_summary = f"[{camera_id}] {summary}"
            c["last_cycle"] = {
                "at": _iso(now),
                "ok": ok,
                "summary": summary,
                "stages": stages,
            }
            c["stages"] = stages
            c["summary"] = summary
            c["next_steps"] = next_steps or []
            if fail_safe:
                c["fail_safe"] = {**c["fail_safe"], **fail_safe}
            if error:
                c["last_error"] = error
            if original_path:
                c["original_path"] = original_path
            if source_sha:
                c["last_source_sha"] = source_sha
            if changed is not None:
                c["last_changed"] = changed

            if ok:
                c["status"] = "OK"
                c["last_acquire_at"] = now
                c["acquire_ok"] += 1
                c["consecutive_failures"] = 0
                c["last_error"] = None
            else:
                c["status"] = "DEGRADED" if c.get("variants") or c.get("original_path") else "FAILED"
                c["acquire_fail"] += 1
                c["consecutive_failures"] += 1
                c["fail_safe"]["keeping_last_original"] = bool(c.get("original_path"))
                c["fail_safe"]["keeping_last_variants"] = bool(c.get("variants"))

    def record_acquire_success(self, camera_id: str, path: Path, sha: str, changed: bool) -> None:
        # Kept for compatibility with older call sites / tests
        with self._lock:
            c = self._cam(camera_id)
            c["last_error"] = None
            c["last_acquire_at"] = time.time()
            c["last_source_sha"] = sha
            c["last_changed"] = changed
            c["original_path"] = str(path)
            c["acquire_ok"] += 1
            c["consecutive_failures"] = 0
            c["status"] = "OK"

    def record_acquire_failure(self, camera_id: str, error: str) -> None:
        with self._lock:
            c = self._cam(camera_id)
            c["last_error"] = error
            c["acquire_fail"] += 1
            c["consecutive_failures"] += 1
            has_prior = bool(c.get("original_path") or c.get("variants"))
            c["status"] = "DEGRADED" if has_prior else "FAILED"
            c["summary"] = f"acquire failed: {error}"
            c["fail_safe"]["keeping_last_original"] = bool(c.get("original_path"))
            c["fail_safe"]["keeping_last_variants"] = bool(c.get("variants"))
            c["next_steps"] = [
                f"curl -sS -o /dev/null -w '%{{http_code}}' {self._hint_source(camera_id)}",
                "Check Pi: curl -sS http://<pi>:8080/health",
                "GET /debug on this pipeline for full checklist",
            ]

    def _hint_source(self, camera_id: str) -> str:
        return f"<source url for {camera_id}>"

    def record_render(self, camera_id: str, rendered: list[RenderedVariant]) -> None:
        with self._lock:
            c = self._cam(camera_id)
            for item in rendered:
                c["variants"][item.name] = {
                    "path": str(item.path),
                    "visibility": item.visibility,
                    "changed": item.changed,
                    "rendered_at": _iso(time.time()),
                    "exists": item.path.exists(),
                    "size_bytes": item.path.stat().st_size if item.path.exists() else None,
                }

    def record_publish(
        self,
        camera_id: str,
        *,
        variant: str,
        ok: bool,
        detail: str,
        live_key: str | None = None,
        history_key: str | None = None,
    ) -> None:
        with self._lock:
            c = self._cam(camera_id)
            pubs = c.setdefault("publish", {})
            pubs[variant] = {
                "ok": ok,
                "detail": detail,
                "live_key": live_key,
                "history_key": history_key,
                "at": _iso(time.time()),
            }
            if ok:
                self.publish_info["last_success_at"] = _iso(time.time())
                self.publish_info["last_error"] = None
            else:
                self.publish_info["last_error"] = detail

    def health(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            cam_statuses = [c.get("status") for c in self.cameras.values()]
            if not self.cameras:
                overall = "STARTING"
                summary = "no camera cycles yet"
                steps = ["Wait for first poll, or run with --once"]
            elif any(s == "FAILED" for s in cam_statuses):
                overall = "UNHEALTHY"
                summary = "at least one camera has no usable prior image"
                steps = ["Fix acquire path; see cameras.*.next_steps"]
            elif any(s == "DEGRADED" for s in cam_statuses):
                overall = "DEGRADED"
                summary = "acquire/publish issues; serving last good variants where available"
                steps = ["Inspect cameras.*.last_error and fail_safe"]
            elif all(s == "OK" for s in cam_statuses):
                overall = "HEALTHY"
                summary = "all configured cameras processed successfully"
                steps = ["No action needed"]
            else:
                overall = "DEGRADED"
                summary = "mixed camera state"
                steps = ["GET /status for per-camera detail"]

            sys_up = system_uptime_seconds()
            return {
                "status": overall,
                "summary": summary,
                "next_steps": steps,
                "application": "webcam-pipeline",
                "version": self.version,
                "uptime_seconds": round(now - self.started_at, 3),
                "system_uptime_seconds": None if sys_up is None else round(sys_up, 3),
                "last_cycle_at": _iso(self.last_cycle_at),
                "last_cycle_summary": self.last_cycle_summary,
                "camera_count": len(self.cameras),
                "configured_cameras": [str(c) for c in (self.config.get("cameras") or []) if c],
                "publish": dict(self.publish_info),
                "fail_safe": {
                    "acquire_failure_keeps_last_original": True,
                    "acquire_failure_keeps_last_variants": True,
                    "publish_failure_keeps_local_variants": True,
                    "never_publish_private_or_original": True,
                },
            }

    def status(self) -> dict[str, Any]:
        health = self.health()
        with self._lock:
            return {
                **health,
                "repo_root": str(self.repo_root),
                "endpoints": {
                    "health": "GET /health — overall status + next_steps",
                    "status": "GET /status — per-camera stages and variants",
                    "debug": "GET /debug — troubleshooting checklist",
                    "private_image": "GET /cameras/<id>/variants/<file>.jpg",
                },
                "cameras": self.cameras,
            }

    def debug(self) -> dict[str, Any]:
        status = self.status()
        return {
            **status,
            "troubleshoot": {
                "quick_checks": [
                    "curl -sS http://127.0.0.1:8090/health | jq .status,.summary,.next_steps",
                    "curl -sS http://127.0.0.1:8090/status | jq .cameras",
                    "curl -sS -o /tmp/private.jpg -w '%{http_code} %{size_download}\\n' "
                    "http://127.0.0.1:8090/cameras/<id>/variants/private.jpg",
                    "journalctl -u webcam-pipeline -n 80 --no-pager",
                    "./scripts/diagnose.sh",
                ],
                "stages": [
                    "1 acquire — pull JPEG from Pi (reject empty/non-JPEG)",
                    "2 store — atomic save original only if changed/valid",
                    "3 render — variants from original (never variant-from-variant)",
                    "4 publish — public variants only → S3-compatible live/ + history/",
                ],
                "common_failures": {
                    "acquire_HTTP": "Pi down or wrong URL in cameras/<id>/camera.yaml",
                    "acquire_not_JPEG": "Upstream returned HTML/error page",
                    "publish_S3": "Missing AWS_* / endpoint — check /etc/webcam-pipeline/env",
                    "DEGRADED": "Last good private/public files still served locally",
                },
            },
        }

    def resolve_variant_path(self, camera_id: str, variant: str) -> Path | None:
        with self._lock:
            c = self.cameras.get(camera_id) or {}
            info = (c.get("variants") or {}).get(variant)
            if not info:
                return None
            path = Path(info["path"])
            return path if path.exists() else None
