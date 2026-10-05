"""LAN UI chrome + design-system smoke tests (no HTTP server)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from shared import lan_ui  # noqa: E402


def test_lan_title_stays_generic_even_when_camera_has_a_display_name():
    from shared.site_config import display_name_for, variant_menu_items

    assert display_name_for(REPO, "example") == "Example Webcam"
    items = variant_menu_items(REPO, "example")
    html = lan_ui.page("Camera home", "<p>x</p>", active="camera", pipe_more=items)
    assert "<title>Webcam — Camera home</title>" in html
    assert "Example Webcam" not in html


def test_lan_ui_page_chrome_and_tokens():
    html = lan_ui.page("Check", "<p>hello</p>", active="pipeline")
    assert "<title>Webcam — Check</title>" in html
    assert 'rel="icon"' in html
    assert 'href="/favicon.svg"' in html
    assert 'href="/favicon.ico"' in html
    assert 'href="/favicon-32.png"' in html
    assert 'href="/apple-touch-icon.png"' in html
    assert 'class="nav"' in html
    assert "nav-cam" in html and "nav-pipe" in html
    assert "Camera home" in html and "Maintenance" in html
    assert "Overview" not in html
    assert "Pipeline" in html and "Schedule" in html
    assert "Variants" in html
    assert "Timelapse" in html
    assert "Pipeline home" in html
    assert "Health (JSON)" in html
    assert "Raw JPEG (always live)" in html
    assert "Feed JPEG (maintenance-aware)" in html
    assert "image.jpg" not in html
    assert "Public livestream (JSON)" in html
    assert 'class="svc-pipe"' in html
    assert "--bg:" in html and "#e6e9ee" in html
    assert "--radius: 2px" in html
    assert "status-badge" in html
    assert "--fg:" in html and "#12161c" in html
    assert "--brand:" in html and "#8a7350" in html
    assert "--cam:" in html and "#1f6b42" in html
    assert "--pipe:" in html and "#a8342a" in html
    assert "panel-head" in html
    assert "window.lanUi" in html
    assert "fetchJson" in html
    assert "prefers-reduced-motion" in html
    assert ":focus-visible" in html
    assert "hello" in html
    # Mobile compact bar + Menu toggle (≤480px)
    assert 'id="nav-toggle"' in html and 'aria-controls="nav-panels"' in html
    assert "nav-chip-cam" in html and "nav-chip-pipe" in html
    assert "nav-panels" in html and "nav-links" in html
    assert "max-width: 480px" in html
    assert "nav.is-open" in html or ".nav.is-open" in html
    # Per-port More menus (JSON/debug)
    assert html.count(">More</button>") == 2
    assert 'id="nav-more-cam"' in html and 'id="nav-more-pipe"' in html
    assert "nav-more-btn" in html and "aria-haspopup" in html
    assert "nav-more-menu" in html
    # Camera More scoped to :8080 paths only in that menu
    def _menu_block(html_doc: str, menu_id: str) -> str:
        start = html_doc.index(f'id="{menu_id}"')
        end = html_doc.index("</div>", start)
        return html_doc[start:end]

    cam_menu = _menu_block(html, "nav-more-cam")
    pipe_menu = _menu_block(html, "nav-more-pipe")
    assert 'data-lan-path="/health"' in cam_menu
    assert 'data-lan-path="/status"' in cam_menu
    assert 'data-lan-path="/debug"' in cam_menu
    assert 'data-lan-path="/maintenance"' in cam_menu
    assert 'data-lan-path="/raw.jpg"' in cam_menu
    assert 'data-lan-path="/feed.jpg"' in cam_menu
    # More = JSON/JPEG only — UI pages stay in primary nav
    assert "/variants/ui" not in cam_menu
    assert "/schedule/ui" not in cam_menu
    assert "/debug/ui" not in cam_menu
    assert "Variants UI" not in cam_menu
    assert "/schedule" not in cam_menu
    assert "example" not in cam_menu
    assert 'data-lan-port="8090"' in pipe_menu
    assert 'data-lan-path="/health"' in pipe_menu
    assert 'data-lan-path="/schedule"' in pipe_menu
    assert 'data-lan-path="/schedule/status"' in pipe_menu
    assert 'data-lan-path="/variants"' in pipe_menu
    assert 'data-lan-path="/variants/ui"' not in pipe_menu
    assert "Variants UI" not in pipe_menu
    assert 'data-lan-path="/public-live"' in pipe_menu
    assert "example" not in pipe_menu
    assert "/image.jpg" not in pipe_menu
    assert "/raw.jpg" not in pipe_menu
    assert 'data-lan-path="/maintenance"' not in pipe_menu
    # Variants UI reachable via primary red nav (not More)
    assert 'data-lan-path="/variants/ui"' in html
    assert ">Variants</a>" in html or "Variants</a>" in html


def test_lan_ui_favicon_assets():
    assert "/favicon.svg" in lan_ui.FAVICON_ROUTES
    assert "/favicon.ico" in lan_ui.FAVICON_ROUTES
    svg = lan_ui.lookup_favicon("/favicon.svg")
    assert svg is not None
    body, ctype = svg
    assert ctype == "image/svg+xml"
    assert b"<svg" in body
    assert b'aria-label="Webcam"' in body
    ico = lan_ui.lookup_favicon("/favicon.ico")
    assert ico is not None and ico[1] == "image/x-icon" and len(ico[0]) > 0
    png = lan_ui.lookup_favicon("/favicon-32.png")
    assert png is not None and png[1] == "image/png" and png[0][:8] == b"\x89PNG\r\n\x1a\n"
    assert lan_ui.lookup_favicon("/nope") is None
    head = lan_ui.favicon_head_html()
    assert 'href="/favicon.svg"' in head


def test_lan_ui_helpers():
    assert 'pill-cam">:8080' in lan_ui.pill("8080")
    assert 'pill-pipe">JSON' in lan_ui.pill("pipe", "JSON")
    link = lan_ui.lan_link("Go", port=8080, path="/", link_class="link-cam")
    assert 'data-lan-port="8080"' in link
    assert 'class="link-cam"' in link
    card = lan_ui.card("Title", "<p>x</p>", kind="cam")
    assert "card-cam" in card and "<h2>Title</h2>" in card
    untitled = lan_ui.card("", "<p>y</p>", kind="pipe")
    assert "card-pipe" in untitled
    assert "<h2>" not in untitled
    header = lan_ui.page_header("Hello", "Lead text.", title_suffix=" " + lan_ui.pill("8080"))
    assert 'class="page-header"' in header
    assert "<h1>Hello" in header
    assert "Lead text." in header
    assert "empty-state" in lan_ui.empty_state("Nothing here")
    assert "actions-sticky" in lan_ui.actions_bar("<button>Go</button>", sticky=True)
    panel = lan_ui.camera_debug_panel_html()
    assert "Camera status" in panel
    assert 'href="/health"' not in panel  # JSON moved to nav More
    assert "More" in panel
    assert "visibilitychange" in panel
    assert "30000" in panel
    assert "Host uptime" in panel
    assert "Service uptime" in panel
    assert "formatDuration" in panel
    img = lan_ui.preview_img("x", alt="a")
    assert 'loading="lazy"' in img
    assert 'decoding="async"' in img
    assert 'preview-frame' in img
    assert "aspect-ratio:" in img
    unframed = lan_ui.preview_img("z", alt="c", framed=False)
    assert "preview-frame" not in unframed
    eager = lan_ui.preview_img("y", alt="b", loading="eager")
    assert 'loading="eager"' in eager
    assert "aria-busy" in lan_ui.status_placeholder("x")
    assert "lanUi.confirm" in lan_ui.client_js() or "confirmAction" in lan_ui.client_js()
    assert "confirm:" in lan_ui.client_js()
    assert "swapImg" in lan_ui.client_js()
    assert "setPreviewAspect" in lan_ui.client_js()
    assert "preview-frame" in lan_ui.css()
    assert "preview-hint" in lan_ui.css()
    assert "actions-sticky" in lan_ui.css()
    assert "empty-state" in lan_ui.css()
    assert "advanced-panel" in lan_ui.css()
    assert "button.danger" in lan_ui.css()
    assert "h-inline" in lan_ui.css()
    assert "status-badge" in lan_ui.css()
    assert "panel-head" in lan_ui.css()
    assert ".banner[hidden]" in lan_ui.css()
    assert ".banner:empty" in lan_ui.css()
    assert "display: none !important" in lan_ui.css()
    assert 'class="banner" hidden' in lan_ui.banner_slot("msg")
    assert "el.hidden = true" in lan_ui.client_js()
    assert "statusBadgeLabel" in lan_ui.client_js()
    assert 'class="kicker"' in lan_ui.page_header("Hello", kicker=":8080")
    assert "panel-head" in lan_ui.card("Title", "<p>x</p>", kind="cam")
    assert "panel-body" in lan_ui.card("Title", "<p>x</p>", kind="cam")
    assert "#f4f1ea" not in lan_ui.css()  # warm cream retired
    assert "--radius: 2px" in lan_ui.css()


def test_pipeline_ui_strings():
    from app.serve_private import _pipe_home_ui, _schedule_ui, _variants_ui

    home = _pipe_home_ui()
    assert "Schedule" in home
    assert "Variants" in home
    assert "nav-cam" in home and "nav-pipe" in home
    assert ">More</button>" in home
    assert 'id="nav-more-pipe"' in home
    assert 'class="svc-pipe"' in home
    assert "pipeline service only" in home
    assert "Camera overview" not in home
    assert "Capture now" not in home
    assert "Camera status" not in home
    assert "Host uptime" in home
    assert "Service uptime" in home
    assert "formatDuration" in home
    assert 'id="pipe-health"' in home
    assert "Operator tools" not in home
    assert "System" in home
    assert "Restart webcam services" in home
    assert "Reboot Pi" in home
    assert "Shut down Pi" in home
    assert "/system/reboot" in home
    assert "/system/poweroff" in home
    assert "/system/restart-services" in home
    assert "/system/status" in home
    assert "/system/logs" in home
    assert "/system/updates" in home
    assert "System health" in home
    assert "Updates" in home
    assert "Check for updates overnight" in home
    assert "Recent logs" in home
    assert "Network" in home
    assert "lanUi.confirm" in home
    assert "page-header" in home
    # JSON link spam removed from body; endpoints live under More
    assert 'href="/health">Health' not in home
    assert 'href="/status">Status' not in home
    # Cross-service jump lives in green/red nav, not a combined overview body
    assert 'data-lan-port="8080"' in home  # nav Camera link

    sched = _schedule_ui()
    assert "Public schedule" in sched
    assert "Schedule enabled" in sched
    assert "Save schedule" in sched
    assert "window.lanUi" in sched
    assert "Upload placeholder" in sched
    assert ">More</button>" in sched
    assert "actions-sticky" in sched
    assert "panel-solar" in sched and "panel-fixed" in sched
    assert "lanUi.confirm" in sched
    assert "page-header" in sched
    assert "swapImg" in sched
    assert "preview-frame" in sched
    assert 'id="location-readonly"' in sched
    assert 'id="lat"' not in sched and 'id="lon"' not in sched
    assert 'data-lan-path="/setup/ui"' in sched
    assert "status-kv" in lan_ui.client_js()
    assert "Array.isArray(detailOrRows)" in lan_ui.client_js()
    assert "status-kv" in lan_ui.css()

    variants = _variants_ui()
    assert "Variants" in variants
    assert "crop" in variants.lower() or "Crop" in variants
    assert "Preview" in variants
    assert "Save" in variants
    assert "Privacy masks" in variants
    assert "Add mask" in variants
    assert "mask-layer" in variants
    assert "mask-handle" in variants
    assert 'active="variants"' in variants or 'class="svc-pipe"' in variants
    assert "/variants/" in variants
    assert "window.lanUi" in variants
    assert ">More</button>" in variants
    assert "Create variant" in variants
    assert "New variant" in variants
    assert "variantUrl" in variants or "JPEG URL" in variants
    assert "location.hostname" in variants
    assert "privateGallery" in variants
    assert "publicGallery" in variants
    assert "Private (LAN-only)" in variants
    assert "Public variants" in variants
    assert "LAN only" in variants
    assert "not for public website" in variants
    assert "home network" in variants.lower()
    assert "Home Assistant only" not in variants
    assert "Private (Home Assistant)" not in variants
    assert "Copy URL" in variants
    assert "public livestream" in variants.lower()
    assert "Use for public livestream" in variants
    assert "/public-live" in variants
    assert 'id="preview"' in variants
    assert "cameras/" in variants  # YAML path copy; JPEG URLs come from meta.served_url
    assert "scheduleAutoPreview" not in variants
    assert "autoPreviewTimer" not in variants
    assert "not automatic" in variants or "without saving" in variants
    assert "without stretching" in variants.lower() or "without squashing" in variants.lower()
    assert 'id="outWidth"' in variants
    assert 'id="badgeEnabled"' in variants
    assert 'id="tsEnabled"' in variants
    assert 'id="artStretch"' in variants
    assert 'id="variant-advanced"' in variants
    assert "Advanced overlays" in variants
    assert "<details" in variants and "advanced-panel" in variants
    assert "field-help" in variants
    assert "advanced-panel" in lan_ui.css()
    assert "w=240" in variants or "thumbW" in variants or "?w=" in variants
    assert "loading=\"lazy\"" in variants or "loading = \"lazy\"" in variants or 'img.loading = "lazy"' in variants
    assert "Existing variants" not in variants
    assert "Private feed" not in variants
    assert "Not a public template" not in variants
    assert "Set as public live" not in variants
    assert "actions-sticky" in variants
    assert "empty-state" in variants
    assert "lanUi.confirm" in variants
    assert "mask-edit-stage" in variants
    assert "Edit masks" in variants
    assert "crop-edit-stage" in variants
    assert "Edit crop" in variants
    assert 'id="cropSrc"' in variants
    assert 'id="cropBox"' in variants
    assert "original.jpg" in variants
    assert "crop-layer" in lan_ui.css()
    assert "crop-box" in lan_ui.css()
    assert 'class="preview-secondary"' in variants
    assert "preview-frame" in variants
    assert "preview-hint" in variants
    assert "is-sharp" in variants
    assert "80rem" in variants
    # Hint sits above compact Preview dry-run; large Edit crop/masks canvases are earlier
    assert variants.index('h-inline">Edit crop') < variants.index('h-inline">Edit masks')
    assert variants.index('h-inline">Edit masks') < variants.index('class="muted preview-hint"')
    assert variants.index('class="muted preview-hint"') < variants.index('class="preview-secondary"')
    # Compact Preview column has no mask/crop layer (drag only on Edit stages)
    preview_col = variants[variants.index("Preview (unsaved)") : variants.index("actions-sticky")]
    assert "preview-hint" not in preview_col
    assert "mask-layer" not in preview_col
    assert "crop-layer" not in preview_col
    assert "servedMasks" in variants
    assert "previewMasks" not in variants
    assert "swapImg" in variants
    assert "setPreviewAspect" in variants
    assert "page-header" in variants
    assert "visibilitychange" in lan_ui.camera_debug_panel_html()
    assert "30000" in lan_ui.camera_debug_panel_html()
