from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import httpx


@dataclass
class AcquireResult:
    ok: bool
    data: bytes = b""
    sha256: str = ""
    error: str | None = None
    not_modified: bool = False
    etag: str | None = None
    last_modified: str | None = None
    maintenance: bool = False


def _parse_maintenance_payload(payload: object) -> bool | None:
    """Extract enabled flag from GET /maintenance or /health JSON."""
    if not isinstance(payload, dict):
        return None
    maint = payload.get("maintenance")
    if isinstance(maint, dict) and "enabled" in maint:
        return bool(maint.get("enabled"))
    if "enabled" in payload and maint is None:
        # GET /maintenance returns {enabled, auto, …} at the top level.
        return bool(payload.get("enabled"))
    return None


def maintenance_api_url(*, source_url: str | None = None, health_url: str | None = None) -> str | None:
    """Derive camera ``/maintenance`` from health_url or the JPEG source base."""
    for candidate in (health_url, source_url):
        if not candidate:
            continue
        parsed = urlparse(candidate)
        if not parsed.scheme or not parsed.netloc:
            continue
        return urlunparse((parsed.scheme, parsed.netloc, "/maintenance", "", "", ""))
    return None


def fetch_maintenance_flag(
    *,
    maintenance_url: str | None = None,
    health_url: str | None = None,
    timeout: float = 5.0,
) -> bool | None:
    """Probe camera maintenance state.

    Prefers ``GET /maintenance``; falls back to ``GET /health`` → ``maintenance.enabled``.
    Returns ``None`` when neither endpoint answers usefully (caller may use JPEG header).
    """
    urls: list[str] = []
    if maintenance_url:
        urls.append(maintenance_url)
    if health_url and health_url not in urls:
        urls.append(health_url)

    for url in urls:
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                resp = client.get(url)
            if resp.status_code != 200:
                continue
            try:
                payload = resp.json()
            except Exception:  # noqa: BLE001
                continue
            flag = _parse_maintenance_payload(payload)
            if flag is not None:
                return flag
        except Exception:  # noqa: BLE001
            continue
    return None


def acquire_image(
    url: str,
    timeout: float = 10.0,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
) -> AcquireResult:
    """GET JPEG with optional conditional headers to skip unchanged downloads.

    ``maintenance`` from ``X-Webcam-Maintenance`` is a fallback only — ``/raw.jpg``
    never sets that header; callers should probe ``GET /maintenance`` separately.
    """
    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            resp = client.get(url, headers=headers)

        if resp.status_code == 304:
            maintenance = (resp.headers.get("x-webcam-maintenance") or "").strip() in (
                "1",
                "true",
                "on",
            )
            return AcquireResult(
                ok=True,
                not_modified=True,
                etag=etag,
                last_modified=last_modified,
                maintenance=maintenance,
            )

        if resp.status_code != 200:
            return AcquireResult(ok=False, error=f"HTTP {resp.status_code}")

        data = resp.content
        if len(data) < 100:
            return AcquireResult(ok=False, error="response too small")
        if data[:2] != b"\xff\xd8":
            return AcquireResult(ok=False, error="response is not JPEG")

        digest = hashlib.sha256(data).hexdigest()
        maintenance = (resp.headers.get("x-webcam-maintenance") or "").strip() in ("1", "true", "on")
        return AcquireResult(
            ok=True,
            data=data,
            sha256=digest,
            etag=resp.headers.get("etag") or resp.headers.get("ETag"),
            last_modified=resp.headers.get("last-modified") or resp.headers.get("Last-Modified"),
            maintenance=maintenance,
        )
    except Exception as exc:  # noqa: BLE001
        return AcquireResult(ok=False, error=str(exc))
