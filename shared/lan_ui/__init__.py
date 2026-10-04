"""Shared LAN HTML chrome for camera (:8080) and pipeline (:8090) UIs.

All LAN UI copy is English. Navbar visually splits services:
  green = camera :8080 · red = pipeline :8090

Import: ``from shared import lan_ui`` (same path as the former single module).

Package layout:
  tokens.py     — CSS design tokens (technical ops palette + port colors)
  styles.py     — full stylesheet
  chrome.py     — ``page()``, ``nav_html()``, ``BRAND``
  components.py — panels, pills, debug panel, link helpers
  js_helpers.py — ``window.lanUi`` client API
  favicon.py    — shared favicon head links + static routes
  assets/       — favicon.svg / .ico / PNGs (LAN appliance icon)

See ``docs/LAN-UI.md`` for how to add a page.
"""

from __future__ import annotations

from .chrome import BRAND, nav_html, page
from .favicon import FAVICON_ROUTES, favicon_head_html, lookup_favicon, send_favicon
from .components import (
    actions_bar,
    banner_slot,
    camera_debug_panel_html,
    card,
    empty_state,
    lan_link,
    page_header,
    pill,
    preview_img,
    rewrite_host_links_js,
    stale_hint,
    status_placeholder,
)
from .js_helpers import client_js
from .styles import css

__all__ = [
    "BRAND",
    "FAVICON_ROUTES",
    "actions_bar",
    "banner_slot",
    "camera_debug_panel_html",
    "card",
    "client_js",
    "css",
    "empty_state",
    "favicon_head_html",
    "lan_link",
    "lookup_favicon",
    "nav_html",
    "page",
    "page_header",
    "pill",
    "preview_img",
    "rewrite_host_links_js",
    "send_favicon",
    "stale_hint",
    "status_placeholder",
]
