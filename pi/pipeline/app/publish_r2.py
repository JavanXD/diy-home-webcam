from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("pipeline.publish")


@dataclass
class PublishResult:
    ok: bool
    live_key: str | None = None
    history_key: str | None = None
    detail: str = ""
    skipped: bool = False


class Publisher:
    def __init__(self, publish_cfg: dict[str, Any], repo_root: Path) -> None:
        self.cfg = publish_cfg or {}
        self.repo_root = repo_root
        self.enabled = bool(self.cfg.get("enabled"))
        self.backend = str(self.cfg.get("backend") or "local")
        self.outbox = repo_root / (self.cfg.get("local_outbox") or "data/outbox")
        self._last_history_at: dict[str, float] = {}
        self._s3 = None
        self.fallback_note: str | None = None
        self.init_error: str | None = None

        if not self.enabled:
            log.info("[publish] disabled — public variants stay local only")
            return

        if self.backend == "r2":
            self._init_r2()
        else:
            self.outbox.mkdir(parents=True, exist_ok=True)
            log.info("[publish] backend=local outbox=%s", self.outbox)

    def _init_r2(self) -> None:
        import boto3

        r2 = self.cfg.get("r2") or {}
        endpoint = r2.get("endpoint_url") or os.environ.get("AWS_ENDPOINT_URL")
        if not endpoint:
            self.init_error = "R2 enabled but endpoint_url / AWS_ENDPOINT_URL missing"
            self.fallback_note = "falling back to local outbox (fail-safe)"
            log.warning("[publish] %s — %s", self.init_error, self.fallback_note)
            self.backend = "local"
            self.outbox.mkdir(parents=True, exist_ok=True)
            return
        self.bucket = r2.get("bucket") or os.environ.get("R2_BUCKET")
        if not self.bucket:
            self.init_error = "R2_BUCKET / r2.bucket missing"
            self.fallback_note = "falling back to local outbox (fail-safe)"
            log.warning("[publish] %s — %s", self.init_error, self.fallback_note)
            self.backend = "local"
            self.outbox.mkdir(parents=True, exist_ok=True)
            return
        if not os.environ.get("AWS_ACCESS_KEY_ID") or not os.environ.get("AWS_SECRET_ACCESS_KEY"):
            log.warning(
                "[publish] AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY not set in environment "
                "(uploads will fail until configured)"
            )
        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=r2.get("region") or "auto",
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
        log.info("[publish] R2 ready bucket=%s endpoint=%s", self.bucket, endpoint)

    def info(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "backend": self.backend,
            "outbox": str(self.outbox),
            "init_error": self.init_error,
            "fallback_note": self.fallback_note,
            "bucket": getattr(self, "bucket", None),
        }

    def publish_public(
        self,
        *,
        camera_id: str,
        variant_name: str,
        local_path: Path,
        live_key: str | None,
        history_variant: str | None,
        history_cfg: dict[str, Any],
        captured_at: float,
        skip_history: bool = False,
        skip_history_reason: str = "placeholder",
    ) -> PublishResult:
        if not self.enabled:
            return PublishResult(ok=True, skipped=True, detail="publish disabled")

        if not local_path.exists():
            msg = f"local file missing: {local_path}"
            log.error("[publish] %s", msg)
            return PublishResult(ok=False, detail=msg)

        key = live_key or f"live/{camera_id}-{variant_name}.jpg"
        try:
            self._put(key, local_path)
        except Exception as exc:  # noqa: BLE001 — do not crash pipeline
            msg = f"live upload failed key={key}: {exc}"
            log.error("[publish] %s", msg)
            log.error("[publish] fail-safe: local variant kept at %s", local_path)
            return PublishResult(ok=False, live_key=key, detail=msg)

        history_key = None
        hist = history_cfg or {}
        if skip_history:
            log.info(
                "[publish] history skipped (%s) variant=%s",
                skip_history_reason,
                variant_name,
            )
        elif hist.get("enabled", True):
            min_interval = float(hist.get("min_interval_seconds", 60))
            hist_id = f"{camera_id}/{history_variant or variant_name}"
            last = self._last_history_at.get(hist_id, 0.0)
            now = time.time()
            if now - last < min_interval:
                log.debug(
                    "[publish] history skipped (min_interval=%.0fs) variant=%s",
                    min_interval,
                    variant_name,
                )
            else:
                stamp = time.strftime("%Y/%m/%d/%H%M%S", time.gmtime(captured_at))
                history_key = f"history/{camera_id}/{history_variant or variant_name}/{stamp}.jpg"
                try:
                    self._put(history_key, local_path)
                    self._last_history_at[hist_id] = now
                    log.info("[publish] history ok %s", history_key)
                except Exception as exc:  # noqa: BLE001
                    msg = f"history upload failed key={history_key}: {exc}"
                    log.error("[publish] %s (live already written)", msg)
                    return PublishResult(
                        ok=False,
                        live_key=key,
                        history_key=history_key,
                        detail=msg,
                    )

        return PublishResult(
            ok=True,
            live_key=key,
            history_key=history_key,
            detail=f"published via {self.backend}",
        )

    def _put(self, key: str, path: Path) -> None:
        if self.backend == "r2" and self._s3 is not None:
            extra = {"ContentType": "image/jpeg", "CacheControl": "public, max-age=60"}
            self._s3.upload_file(str(path), self.bucket, key, ExtraArgs=extra)
            log.info("[publish] uploaded s3://%s/%s (%s bytes)", self.bucket, key, path.stat().st_size)
            return

        dest = self.outbox / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
        log.info("[publish] wrote outbox %s (%s bytes)", dest, dest.stat().st_size)
