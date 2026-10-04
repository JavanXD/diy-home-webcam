from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("pipeline.publish")

# S3-compatible backends (Cloudflare R2, AWS S3, MinIO, Wasabi, B2 S3 API, …).
# "r2" remains accepted as an alias for existing pipeline.yaml files.
S3_BACKENDS = frozenset({"s3", "r2"})


@dataclass
class PublishResult:
    ok: bool
    live_key: str | None = None
    history_key: str | None = None
    detail: str = ""
    skipped: bool = False


def s3_settings(publish_cfg: dict[str, Any]) -> dict[str, Any]:
    """Nested S3 settings: prefer ``s3:``, fall back to legacy ``r2:``."""
    cfg = publish_cfg or {}
    s3 = cfg.get("s3")
    if isinstance(s3, dict) and s3:
        return dict(s3)
    r2 = cfg.get("r2")
    if isinstance(r2, dict):
        return dict(r2)
    return {}


def resolve_bucket(s3: dict[str, Any]) -> str | None:
    return (
        s3.get("bucket")
        or os.environ.get("S3_BUCKET")
        or os.environ.get("R2_BUCKET")
        or None
    )


def resolve_endpoint(s3: dict[str, Any]) -> str | None:
    endpoint = s3.get("endpoint_url") or os.environ.get("AWS_ENDPOINT_URL")
    if endpoint:
        return str(endpoint).strip() or None
    account = (os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    if account and account != "replace-me":
        return f"https://{account}.r2.cloudflarestorage.com"
    return None


def resolve_region(s3: dict[str, Any]) -> str:
    return str(
        s3.get("region")
        or os.environ.get("AWS_DEFAULT_REGION")
        or os.environ.get("AWS_REGION")
        or "auto"
    )


def resolve_force_path_style(s3: dict[str, Any]) -> bool:
    if "force_path_style" in s3:
        return bool(s3.get("force_path_style"))
    raw = (os.environ.get("AWS_S3_FORCE_PATH_STYLE") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def make_s3_client(s3: dict[str, Any]):
    """Build a boto3 S3 client from nested settings + process environment."""
    import boto3
    from botocore.config import Config

    endpoint = resolve_endpoint(s3)
    if not endpoint:
        raise ValueError("endpoint_url / AWS_ENDPOINT_URL missing")
    bucket = resolve_bucket(s3)
    if not bucket:
        raise ValueError("bucket / S3_BUCKET / R2_BUCKET missing")
    access = os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not access or not secret:
        raise ValueError("AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY not set")

    kwargs: dict[str, Any] = {
        "endpoint_url": endpoint,
        "region_name": resolve_region(s3),
        "aws_access_key_id": access,
        "aws_secret_access_key": secret,
    }
    if resolve_force_path_style(s3):
        kwargs["config"] = Config(s3={"addressing_style": "path"})
    client = boto3.client("s3", **kwargs)
    return client, bucket, endpoint


class Publisher:
    def __init__(self, publish_cfg: dict[str, Any], repo_root: Path) -> None:
        self.cfg = publish_cfg or {}
        self.repo_root = repo_root
        self.enabled = bool(self.cfg.get("enabled"))
        raw_backend = str(self.cfg.get("backend") or "local").strip().lower()
        # Normalize legacy "r2" to "s3" for runtime; keep reporting the effective backend.
        self.backend = "s3" if raw_backend in S3_BACKENDS else raw_backend
        self.outbox = repo_root / (self.cfg.get("local_outbox") or "data/outbox")
        self._last_history_at: dict[str, float] = {}
        self._s3 = None
        self.fallback_note: str | None = None
        self.init_error: str | None = None

        if not self.enabled:
            log.info("[publish] disabled — public variants stay local only")
            return

        if self.backend == "s3":
            self._init_s3()
        else:
            self.backend = "local"
            self.outbox.mkdir(parents=True, exist_ok=True)
            log.info("[publish] backend=local outbox=%s", self.outbox)

    def _init_s3(self) -> None:
        s3 = s3_settings(self.cfg)
        try:
            client, bucket, endpoint = make_s3_client(s3)
        except ValueError as exc:
            self.init_error = str(exc)
            self.fallback_note = "falling back to local outbox (fail-safe)"
            log.warning("[publish] %s — %s", self.init_error, self.fallback_note)
            self.backend = "local"
            self.outbox.mkdir(parents=True, exist_ok=True)
            return
        except Exception as exc:  # noqa: BLE001 — do not crash pipeline
            self.init_error = f"S3 client init failed: {exc}"
            self.fallback_note = "falling back to local outbox (fail-safe)"
            log.warning("[publish] %s — %s", self.init_error, self.fallback_note)
            self.backend = "local"
            self.outbox.mkdir(parents=True, exist_ok=True)
            return

        self.bucket = bucket
        self._s3 = client
        path_style = resolve_force_path_style(s3)
        label = "R2" if "r2.cloudflarestorage.com" in endpoint else "S3"
        log.info(
            "[publish] %s ready bucket=%s endpoint=%s region=%s path_style=%s",
            label,
            self.bucket,
            endpoint,
            resolve_region(s3),
            path_style,
        )

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
        if self.backend == "s3" and self._s3 is not None:
            extra = {"ContentType": "image/jpeg", "CacheControl": "public, max-age=60"}
            self._s3.upload_file(str(path), self.bucket, key, ExtraArgs=extra)
            log.info("[publish] uploaded s3://%s/%s (%s bytes)", self.bucket, key, path.stat().st_size)
            return

        dest = self.outbox / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
        log.info("[publish] wrote outbox %s (%s bytes)", dest, dest.stat().st_size)
