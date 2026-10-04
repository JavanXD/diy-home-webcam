"""Document shell + dual-port navbar."""

from __future__ import annotations

from html import escape

from .favicon import favicon_head_html
from .js_helpers import client_js, nav_more_js, nav_mobile_js, nav_rewrite_js
from .styles import css


BRAND = "Webcam"

# Cross-service nav: same links on every LAN page (jumps across ports are OK).
# Page bodies stay service-scoped — no combined Overview hub.
_NAV_CAM: tuple[dict[str, object], ...] = (
    {"id": "camera", "label": "Camera home", "port": 8080, "path": "/"},
    {"id": "maintenance", "label": "Maintenance", "port": 8080, "path": "/debug/ui"},
)
_NAV_PIPE: tuple[dict[str, object], ...] = (
    {"id": "pipeline", "label": "Pipeline home", "port": 8090, "path": "/"},
    {"id": "schedule", "label": "Schedule", "port": 8090, "path": "/schedule/ui"},
    {"id": "variants", "label": "Variants", "port": 8090, "path": "/variants/ui"},
    {"id": "setup", "label": "Setup", "port": 8090, "path": "/setup/ui"},
    {"id": "timelapse", "label": "Timelapse", "port": 8090, "path": "/timelapse/ui"},
)

# Raw JSON / JPEG ops endpoints only — no UI pages (those live in _NAV_*).
# Optional "port" on an item overrides the menu's default (cross-port jumps).
# Labels are plain English; paths stay the real API routes.
_MORE_CAM: tuple[dict[str, str | int], ...] = (
    {"label": "Health (JSON)", "path": "/health"},
    {"label": "Status (JSON)", "path": "/status"},
    {"label": "Debug (JSON)", "path": "/debug"},
    {"label": "Maintenance (JSON)", "path": "/maintenance"},
    {"label": "Raw JPEG (always live)", "path": "/raw.jpg"},
    {"label": "Feed JPEG (maintenance-aware)", "path": "/feed.jpg"},
)
_MORE_PIPE: tuple[dict[str, str | int], ...] = (
    {"label": "Health (JSON)", "path": "/health"},
    {"label": "Status (JSON)", "path": "/status"},
    {"label": "Debug (JSON)", "path": "/debug"},
    {"label": "System status (JSON)", "path": "/system/status"},
    {"label": "System logs (JSON)", "path": "/system/logs"},
    {"label": "Schedule (JSON)", "path": "/schedule"},
    {"label": "Schedule status (JSON)", "path": "/schedule/status"},
    {"label": "Variants list (JSON)", "path": "/variants"},
    {"label": "Public livestream (JSON)", "path": "/public-live"},
)


def _nav_link(item: dict[str, object], active: str | None) -> str:
    iid = str(item["id"])
    label = escape(str(item["label"]))
    port = int(item["port"])  # type: ignore[arg-type]
    path = str(item["path"])
    cls = ' class="active"' if active and iid == active else ""
    return (
        f'<a{cls} data-lan-port="{port}" data-lan-path="{escape(path, quote=True)}" '
        f'href="http://home-webcam.local:{port}{escape(path, quote=True)}">{label}</a>'
    )


def _more_item(item: dict[str, str | int], default_port: int) -> str:
    label = escape(str(item["label"]))
    path = str(item["path"])
    port = int(item["port"]) if "port" in item else default_port
    return (
        f'<a role="menuitem" data-lan-port="{port}" '
        f'data-lan-path="{escape(path, quote=True)}" '
        f'href="http://home-webcam.local:{port}{escape(path, quote=True)}">{label}</a>'
    )


def _nav_more(port: int, menu_id: str, items: tuple[dict[str, str | int], ...] | list[dict[str, str | int]]) -> str:
    links = "\n      ".join(_more_item(i, port) for i in items)
    return f"""<div class="nav-more">
    <button type="button" class="nav-more-btn" aria-expanded="false"
      aria-haspopup="menu" aria-controls="{escape(menu_id)}" id="{escape(menu_id)}-btn">More</button>
    <div class="nav-more-menu" id="{escape(menu_id)}" role="menu" hidden
      aria-labelledby="{escape(menu_id)}-btn">
      {links}
    </div>
  </div>"""


def nav_html(active: str | None = None, pipe_more: list[dict[str, str]] | None = None) -> str:
    """Unified top navbar with green (:8080) and red (:8090) clusters + More menus.

    Narrow viewports use a compact bar (port chips + Menu) that expands stacked
    clusters; desktop keeps both clusters side-by-side.

    ``pipe_more`` adds JPEG shortcuts from the configured camera's variant files.
    """
    cam_links = "\n    ".join(_nav_link(i, active) for i in _NAV_CAM)
    pipe_links = "\n    ".join(_nav_link(i, active) for i in _NAV_PIPE)
    cam_more = _nav_more(8080, "nav-more-cam", _MORE_CAM)
    pipe_items: list[dict[str, str | int]] = list(_MORE_PIPE)
    if pipe_more:
        pipe_items.extend(pipe_more)
    pipe_more_html = _nav_more(8090, "nav-more-pipe", pipe_items)
    return f"""<nav class="nav" aria-label="LAN navigation">
  <div class="nav-bar">
    <div class="nav-identity" aria-hidden="true">
      <span class="nav-chip nav-chip-cam">:8080</span>
      <span class="nav-chip nav-chip-pipe">:8090</span>
    </div>
    <button type="button" class="nav-toggle" id="nav-toggle"
      aria-expanded="false" aria-controls="nav-panels">Menu</button>
  </div>
  <div class="nav-panels" id="nav-panels">
    <div class="nav-group nav-cam" aria-label="Camera :8080">
      <span class="nav-port">:8080</span>
      <div class="nav-links">
        {cam_links}
        {cam_more}
      </div>
    </div>
    <div class="nav-group nav-pipe" aria-label="Pipeline :8090">
      <span class="nav-port">:8090</span>
      <div class="nav-links">
        {pipe_links}
        {pipe_more_html}
      </div>
    </div>
  </div>
</nav>"""


def _body_svc_class(active: str | None) -> str:
    if active in ("camera", "maintenance"):
        return "svc-cam"
    if active in ("pipeline", "schedule", "variants", "setup", "timelapse"):
        return "svc-pipe"
    return ""


def page(
    title: str,
    body: str,
    *,
    active: str | None = None,
    extra_head: str = "",
    lang: str = "en",
    brand: str | None = None,
    pipe_more: list[dict[str, str]] | None = None,
) -> str:
    """Full HTML document with shared CSS + colored navbar.

    The document title is the generic ``Webcam`` label. A camera's
    ``display_name`` belongs on that project's public site and JPEGs, not here.
    """
    brand_name = (brand or BRAND).strip() or BRAND
    full_title = title if title.startswith(brand_name) else f"{brand_name} — {title}"
    body_cls = _body_svc_class(active)
    body_attr = f' class="{body_cls}"' if body_cls else ""
    return f"""<!DOCTYPE html>
<html lang="{escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{escape(full_title)}</title>
{favicon_head_html()}
<style>
{css()}
</style>
<script>
{client_js()}
</script>
{extra_head}
</head>
<body{body_attr}>
{nav_html(active, pipe_more)}
<main>
{body}
</main>
<script>
{nav_rewrite_js()}
{nav_more_js()}
{nav_mobile_js()}
</script>
</body>
</html>
"""
