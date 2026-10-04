"""R2 publish settings. Secrets go to the env file, never into git or API responses."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ENV_KEYS = (
    "R2_BUCKET",
    "AWS_ENDPOINT_URL",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)


def default_env_path() -> Path:
    return Path("/etc/webcam-pipeline/env")


def read_publish(pipeline: dict[str, Any], env_file: Path) -> dict[str, Any]:
    publish = pipeline.get("publish") if isinstance(pipeline.get("publish"), dict) else {}
    r2 = publish.get("r2") if isinstance(publish.get("r2"), dict) else {}
    env = _parse_env(env_file)
    bucket = str(r2.get("bucket") or env.get("R2_BUCKET") or "").strip()
    endpoint = str(r2.get("endpoint_url") or env.get("AWS_ENDPOINT_URL") or "").strip()
    return {
        "enabled": bool(publish.get("enabled")),
        "bucket": bucket,
        "endpoint_url": endpoint if endpoint != "None" else "",
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
    r2 = dict(publish.get("r2") or {})
    if "enabled" in patch:
        publish["enabled"] = bool(patch.get("enabled"))
    if "bucket" in patch:
        bucket = str(patch.get("bucket") or "").strip()
        if not bucket or len(bucket) > 80 or any(c in bucket for c in " \t\r\n/"):
            raise ValueError("bucket name must be one token")
        r2["bucket"] = bucket
    if "endpoint_url" in patch:
        endpoint = str(patch.get("endpoint_url") or "").strip()
        if endpoint and not (endpoint.startswith("https://") or endpoint.startswith("http://")):
            raise ValueError("endpoint must start with https://")
        r2["endpoint_url"] = endpoint or None
    publish["r2"] = r2
    publish.setdefault("backend", "r2")
    pipeline["publish"] = publish

    env = _parse_env(env_file)
    if r2.get("bucket"):
        env["R2_BUCKET"] = str(r2["bucket"])
    if r2.get("endpoint_url"):
        env["AWS_ENDPOINT_URL"] = str(r2["endpoint_url"])
    if str(patch.get("access_key_id") or "").strip():
        env["AWS_ACCESS_KEY_ID"] = str(patch["access_key_id"]).strip()
    if str(patch.get("secret_access_key") or "").strip():
        env["AWS_SECRET_ACCESS_KEY"] = str(patch["secret_access_key"]).strip()
    _reject_secret_shape(env.get("AWS_ACCESS_KEY_ID", ""))
    _reject_secret_shape(env.get("AWS_SECRET_ACCESS_KEY", ""))
    _write_env(env_file, env)
    for path in yaml_paths:
        _write_yaml(path, _merge_publish(path, publish))
    os.environ["R2_BUCKET"] = env.get("R2_BUCKET", "")
    if env.get("AWS_ENDPOINT_URL"):
        os.environ["AWS_ENDPOINT_URL"] = env["AWS_ENDPOINT_URL"]
    if env.get("AWS_ACCESS_KEY_ID"):
        os.environ["AWS_ACCESS_KEY_ID"] = env["AWS_ACCESS_KEY_ID"]
    if env.get("AWS_SECRET_ACCESS_KEY"):
        os.environ["AWS_SECRET_ACCESS_KEY"] = env["AWS_SECRET_ACCESS_KEY"]
    saved = read_publish(pipeline, env_file)
    saved["restart_required"] = True
    return saved


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
