"""LAN favicon assets + HTML head links (camera :8080 + pipeline :8090).

LAN appliance icon (camera mark). The public site keeps its own favicons.
favicon and not the Bollenhut logo. Served from ``shared/lan_ui/assets/``.
"""

from __future__ import annotations

from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# URL path → (filename under ASSETS_DIR, Content-Type)
FAVICON_ROUTES: dict[str, tuple[str, str]] = {
    "/favicon.ico": ("favicon.ico", "image/x-icon"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/favicon-16.png": ("favicon-16.png", "image/png"),
    "/favicon-32.png": ("favicon-32.png", "image/png"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
}

# Long-ish private cache: assets are process-static until service restart/sync.
_CACHE_CONTROL = "private, max-age=86400"


def favicon_head_html() -> str:
    """``<link rel="icon">`` tags for every ``lan_ui.page(...)`` document."""
    return """\
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" type="image/png" sizes="32x32">
<link rel="icon" href="/favicon-16.png" type="image/png" sizes="16x16">
<link rel="shortcut icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png" sizes="180x180">"""


def lookup_favicon(path: str) -> tuple[bytes, str] | None:
    """Return ``(body, content_type)`` for a favicon URL path, or ``None``."""
    entry = FAVICON_ROUTES.get(path)
    if entry is None:
        return None
    name, content_type = entry
    file_path = ASSETS_DIR / name
    if not file_path.is_file():
        return None
    return file_path.read_bytes(), content_type


def send_favicon(handler, path: str) -> bool:
    """If ``path`` is a known favicon route, write the response and return True.

    ``handler`` is a ``BaseHTTPRequestHandler`` (camera or pipeline).
    """
    found = lookup_favicon(path)
    if found is None:
        return False
    body, content_type = found
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", _CACHE_CONTROL)
    handler.end_headers()
    handler.wfile.write(body)
    return True
