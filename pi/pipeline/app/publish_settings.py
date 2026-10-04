"""Publish settings (S3-compatible). Secrets go to the env file, never into git or API responses."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .publish_r2 import make_s3_client, s3_settings

# Written / read from /etc/webcam-pipeline/env. AWS_* is the boto3 convention;
# R2_BUCKET remains for existing Pis; S3_BUCKET is an accepted alias.
ENV_KEYS = (
    "CLOUDFLARE_ACCOUNT_ID",
    "R2_BUCKET",
    "S3_BUCKET",
    "AWS_ENDPOINT_URL",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_DEFAULT_REGION",
    "AWS_S3_FORCE_PATH_STYLE",
)

PROVIDERS = frozenset({"off", "r2", "s3", "local"})


def default_env_path() -> Path:
    return Path("/etc/webcam-pipeline/env")


def r2_endpoint_from_account(account_id: str) -> str:
    account = (account_id or "").strip()
    if not account:
        return ""
    return f"https://{account}.r2.cloudflarestorage.com"


def infer_provider(publish: dict[str, Any], env: dict[str, str]) -> str:
    if not bool(publish.get("enabled")):
        return "off"
    backend = str(publish.get("backend") or "local").strip().lower()
    if backend == "local":
        return "local"
    if backend not in {"s3", "r2"}:
        return "off"
    explicit = str(publish.get("provider") or "").strip().lower()
    if explicit in {"r2", "s3", "custom"}:
        return "r2" if explicit == "r2" else "s3"
    endpoint = str(
        (s3_settings(publish).get("endpoint_url") or env.get("AWS_ENDPOINT_URL") or "")
    ).lower()
    if "r2.cloudflarestorage.com" in endpoint or env.get("CLOUDFLARE_ACCOUNT_ID"):
        return "r2"
    return "s3"


def read_publish(pipeline: dict[str, Any], env_file: Path) -> dict[str, Any]:
    publish = pipeline.get("publish") if isinstance(pipeline.get("publish"), dict) else {}
    s3 = s3_settings(publish)
    env = _parse_env(env_file)
    bucket = str(
        s3.get("bucket") or env.get("S3_BUCKET") or env.get("R2_BUCKET") or ""
    ).strip()
    endpoint = str(s3.get("endpoint_url") or env.get("AWS_ENDPOINT_URL") or "").strip()
    if endpoint == "None":
        endpoint = ""
    if not endpoint:
        account = str(env.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
        if account and account != "replace-me":
            endpoint = r2_endpoint_from_account(account)
    region = str(
        s3.get("region") or env.get("AWS_DEFAULT_REGION") or env.get("AWS_REGION") or "auto"
    ).strip()
    path_style = bool(s3.get("force_path_style")) or (
        (env.get("AWS_S3_FORCE_PATH_STYLE") or "").strip().lower() in {"1", "true", "yes", "on"}
    )
    account_id = str(env.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    provider = infer_provider(publish, env)
    return {
        "enabled": bool(publish.get("enabled")),
        "provider": provider,
        "backend": "s3" if provider in {"r2", "s3"} else ("local" if provider == "local" else "off"),
        "bucket": bucket,
        "endpoint_url": endpoint,
        "region": region,
        "force_path_style": path_style,
        "account_id": account_id,
        "access_key_set": bool(env.get("AWS_ACCESS_KEY_ID")),
        "secret_set": bool(env.get("AWS_SECRET_ACCESS_KEY")),
        "env_path": str(env_file),
        "restart_required": True,
    }


def save_publish(
    pipeline: dict[str, Any],
    env_file: Path,
    patch: dict[str, Any],
    *,
    yaml_paths: list[Path],
) -> dict[str, Any]:
    """Update pipeline publish block and the env file. A blank secret keeps the old one."""
    publish = dict(pipeline.get("publish") or {})
    s3 = s3_settings(publish)

    provider = str(patch.get("provider") or "").strip().lower()
    if provider == "custom":
        provider = "s3"
    if provider and provider not in PROVIDERS:
        raise ValueError("provider must be off, r2, s3, or local")

    if provider:
        if provider == "off":
            publish["enabled"] = False
            publish["backend"] = "local"
            publish["provider"] = "off"
        elif provider == "local":
            publish["enabled"] = True
            publish["backend"] = "local"
            publish["provider"] = "local"
        else:
            publish["enabled"] = True
            publish["backend"] = "s3"
            publish["provider"] = provider
    elif "enabled" in patch:
        publish["enabled"] = bool(patch.get("enabled"))
        if publish["enabled"]:
            publish.setdefault("backend", "s3")
        publish.setdefault("provider", infer_provider(publish, _parse_env(env_file)))

    env = _parse_env(env_file)
    account_id: str | None = None
    if "account_id" in patch:
        account_id = str(patch.get("account_id") or "").strip()
        if account_id and (len(account_id) > 64 or any(c in account_id for c in " \t\r\n/")):
            raise ValueError("account id must be one token")

    if "bucket" in patch:
        bucket = str(patch.get("bucket") or "").strip()
        if bucket:
            if len(bucket) > 80 or any(c in bucket for c in " \t\r\n/"):
                raise ValueError("bucket name must be one token")
            s3["bucket"] = bucket
        elif publish.get("enabled") and str(publish.get("backend")) == "s3":
            raise ValueError("bucket name must be one token")

    endpoint: str | None = None
    if "endpoint_url" in patch:
        endpoint = str(patch.get("endpoint_url") or "").strip()

    effective_provider = str(publish.get("provider") or "").strip().lower()
    if effective_provider == "r2":
        aid = account_id if account_id is not None else str(env.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
        if not endpoint and aid:
            endpoint = r2_endpoint_from_account(aid)

    if "endpoint_url" in patch or (effective_provider == "r2" and endpoint):
        if endpoint and not (endpoint.startswith("https://") or endpoint.startswith("http://")):
            raise ValueError("endpoint must start with https:// or http://")
        s3["endpoint_url"] = endpoint or None

    if "region" in patch:
        region = str(patch.get("region") or "").strip() or "auto"
        if len(region) > 64 or any(c in region for c in " \t\r\n"):
            raise ValueError("region must be one token")
        s3["region"] = region

    if "force_path_style" in patch:
        s3["force_path_style"] = bool(patch.get("force_path_style"))

    # Keep both keys so older docs/tools that read publish.r2 still work.
    publish["s3"] = s3
    publish["r2"] = dict(s3)
    if "backend" not in publish:
        publish["backend"] = "s3" if publish.get("enabled") else "local"
    pipeline["publish"] = publish

    if account_id is not None:
        if account_id:
            env["CLOUDFLARE_ACCOUNT_ID"] = account_id
        else:
            env.pop("CLOUDFLARE_ACCOUNT_ID", None)
    if s3.get("bucket"):
        env["R2_BUCKET"] = str(s3["bucket"])
        env["S3_BUCKET"] = str(s3["bucket"])
    if s3.get("endpoint_url"):
        env["AWS_ENDPOINT_URL"] = str(s3["endpoint_url"])
    elif "endpoint_url" in patch and not s3.get("endpoint_url"):
        env.pop("AWS_ENDPOINT_URL", None)
    if s3.get("region"):
        env["AWS_DEFAULT_REGION"] = str(s3["region"])
    if "force_path_style" in s3:
        env["AWS_S3_FORCE_PATH_STYLE"] = "true" if s3["force_path_style"] else "false"
    if str(patch.get("access_key_id") or "").strip():
        env["AWS_ACCESS_KEY_ID"] = str(patch["access_key_id"]).strip()
    if str(patch.get("secret_access_key") or "").strip():
        env["AWS_SECRET_ACCESS_KEY"] = str(patch["secret_access_key"]).strip()
    _reject_secret_shape(env.get("AWS_ACCESS_KEY_ID", ""))
    _reject_secret_shape(env.get("AWS_SECRET_ACCESS_KEY", ""))
    _write_env(env_file, env)
    for path in yaml_paths:
        _write_yaml(path, _merge_publish(path, publish))
    _apply_env_to_process(env)
    saved = read_publish(pipeline, env_file)
    saved["restart_required"] = True
    return saved


def probe_publish_connection(
    pipeline: dict[str, Any],
    env_file: Path,
    patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Head-bucket against current (or form-overridden) S3 settings. Does not write files."""
    patch = patch or {}
    publish = dict(pipeline.get("publish") or {})
    s3 = s3_settings(publish)
    env = _parse_env(env_file)

    provider = str(patch.get("provider") or "").strip().lower()
    if provider == "custom":
        provider = "s3"
    if not provider:
        provider = infer_provider(publish, env)

    if provider == "off":
        return {"ok": True, "provider": "off", "detail": "publish is off — nothing to test"}
    if provider == "local":
        outbox = Path(str(publish.get("local_outbox") or "data/outbox"))
        return {
            "ok": True,
            "provider": "local",
            "detail": f"local outbox mode (no remote upload) — {outbox}",
        }

    if "bucket" in patch and str(patch.get("bucket") or "").strip():
        s3["bucket"] = str(patch["bucket"]).strip()
    if "endpoint_url" in patch:
        s3["endpoint_url"] = str(patch.get("endpoint_url") or "").strip() or None
    if "region" in patch:
        s3["region"] = str(patch.get("region") or "").strip() or "auto"
    if "force_path_style" in patch:
        s3["force_path_style"] = bool(patch.get("force_path_style"))

    account_id = str(patch.get("account_id") or env.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    if provider == "r2" and account_id and not s3.get("endpoint_url"):
        s3["endpoint_url"] = r2_endpoint_from_account(account_id)

    overlay: dict[str, str] = {}
    if s3.get("endpoint_url"):
        overlay["AWS_ENDPOINT_URL"] = str(s3["endpoint_url"])
    elif env.get("AWS_ENDPOINT_URL"):
        overlay["AWS_ENDPOINT_URL"] = env["AWS_ENDPOINT_URL"]
        s3.setdefault("endpoint_url", env["AWS_ENDPOINT_URL"])
    if s3.get("bucket"):
        overlay["R2_BUCKET"] = str(s3["bucket"])
        overlay["S3_BUCKET"] = str(s3["bucket"])
    elif env.get("S3_BUCKET") or env.get("R2_BUCKET"):
        bucket = env.get("S3_BUCKET") or env.get("R2_BUCKET") or ""
        overlay["R2_BUCKET"] = bucket
        overlay["S3_BUCKET"] = bucket
        s3.setdefault("bucket", bucket)
    if s3.get("region"):
        overlay["AWS_DEFAULT_REGION"] = str(s3["region"])
    elif env.get("AWS_DEFAULT_REGION"):
        overlay["AWS_DEFAULT_REGION"] = env["AWS_DEFAULT_REGION"]
    if "force_path_style" in s3:
        overlay["AWS_S3_FORCE_PATH_STYLE"] = "true" if s3["force_path_style"] else "false"
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        form_key = "access_key_id" if key.endswith("KEY_ID") else "secret_access_key"
        if str(patch.get(form_key) or "").strip():
            overlay[key] = str(patch[form_key]).strip()
        elif env.get(key):
            overlay[key] = env[key]
        elif os.environ.get(key):
            overlay[key] = os.environ[key]

    previous = {key: os.environ.get(key) for key in overlay}
    try:
        os.environ.update(overlay)
        client, bucket, endpoint = make_s3_client(s3)
        client.head_bucket(Bucket=bucket)
        return {
            "ok": True,
            "provider": provider or "s3",
            "bucket": bucket,
            "endpoint_url": endpoint,
            "detail": f"connected — head_bucket ok on {bucket}",
        }
    except Exception as exc:  # noqa: BLE001 — surface to UI
        msg = str(exc)
        secrets = [
            overlay.get("AWS_SECRET_ACCESS_KEY"),
            overlay.get("AWS_ACCESS_KEY_ID"),
        ]
        if any(secret and secret in msg for secret in secrets if secret):
            msg = "connection failed (details omitted)"
        return {"ok": False, "detail": msg}
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _apply_env_to_process(env: dict[str, str]) -> None:
    for key in ENV_KEYS:
        if env.get(key):
            os.environ[key] = env[key]
        elif key in os.environ and key in {
            "CLOUDFLARE_ACCOUNT_ID",
            "AWS_ENDPOINT_URL",
            "AWS_S3_FORCE_PATH_STYLE",
        }:
            # Allow clearing optional helper keys when removed from the file.
            if key not in env:
                os.environ.pop(key, None)


def _reject_secret_shape(value: str) -> None:
    if any(c in value for c in "\r\n\x00"):
        raise ValueError("keys must be a single line")


def _parse_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        out[key.strip()] = value
    return out


def _write_env(path: Path, env: dict[str, str]) -> None:
    lines = [
        "# Written by the Setup page. Not in git.",
        "# Restart webcam-pipeline before a new key is used for upload.",
        "# AWS_* names are the boto3 convention (works for R2, MinIO, AWS S3, …).",
    ]
    for key in ENV_KEYS:
        if env.get(key):
            lines.append(f"{key}={env[key]}")
    for key, value in env.items():
        if key not in ENV_KEYS and value:
            lines.append(f"{key}={value}")
    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o660)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o660)
    except OSError:
        pass


def _merge_publish(path: Path, publish: dict[str, Any]) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} is not a mapping")
    raw["publish"] = publish
    return raw


def _write_yaml(path: Path, raw: dict[str, Any]) -> None:
    text = yaml.safe_dump(raw, sort_keys=False, default_flow_style=False, allow_unicode=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    os.replace(tmp, path)
