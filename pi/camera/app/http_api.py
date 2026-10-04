from __future__ import annotations

import json
import math
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Type
from urllib.parse import parse_qs, urlparse

from shared import lan_ui
from shared.jpeg_util import downscale_jpeg, parse_max_width
from shared.repo_root import find_repo_root
from shared.site_config import primary_site, variant_menu_items

from .capture import CaptureBackend
from .focus_score import FocusRegionStore, focus_region, sharpness_score
from .live_preview import LivePreview
from .maintenance import MaintenanceMode
from .state import AppState
from .storage import ImageStore

# Maintenance page thumb. Camera home uses the full /raw.jpg so focus is not judged on a downscale.
_UI_PREVIEW_QS = "w=720"
_RAW_JPEG_PATH = "/raw.jpg"
_FEED_JPEG_PATH = "/feed.jpg"
# Normal home poll vs live-preview (focus) poll — bypasses the slow 30s cadence.
_UI_POLL_MS = 30000
_UI_PREVIEW_POLL_MS = 750


def _focus_overlay() -> str:
    """Yellow box and number over the preview only — not part of /raw.jpg."""
    region = focus_region()
    left = region["left"] * 100
    top = region["top"] * 100
    width = region["width"] * 100
    height = region["height"] * 100
    return (
        f'<div id="focus-region" class="focus-region" '
        f'style="left:{left:.1f}%;top:{top:.1f}%;width:{width:.1f}%;height:{height:.1f}%">'
        f'<span id="focus-readout" class="focus-readout">'
        f'<span id="focus-cue" class="focus-cue" aria-hidden="true"></span>'
        f'<span id="focus-score" class="focus-score" role="status" aria-live="polite">—</span>'
        f"</span>"
        f'<span class="focus-handle" aria-hidden="true"></span>'
        f"</div>"
    )


def _home_ui(*, pipe_more: list[dict[str, str]] | None = None) -> str:
    cam_body = f"""
  {lan_ui.banner_slot("cam-banner")}
  <p class="muted">Preview is <strong>Raw</strong> (<code>/raw.jpg</code>) — always the last live capture, even during Wartungsbild. Use <strong>Live preview</strong> below to aim and focus (~5&nbsp;min auto-off). Overlays and crops are on <code>:8090</code>. Full-size JPEGs: green nav <strong>More</strong>.</p>
  {lan_ui.preview_img("preview", alt="Raw camera JPEG (/raw.jpg) — always live capture", css_class="thumb", loading="eager", overlay=_focus_overlay(), frame_class="is-sharp")}
  <div id="live-preview-meter" class="live-preview-meter is-off" role="status" aria-live="polite">
    <div class="live-preview-meter-row">
      <span id="live-preview-label" class="live-preview-label">Live preview off</span>
      <span id="live-preview-time" class="live-preview-time">Press Start</span>
    </div>
    <div class="live-preview-track" aria-hidden="true">
      <div id="live-preview-fill" class="live-preview-fill"></div>
    </div>
    <p id="live-preview-status" class="live-preview-hint">Off — preview refreshes about every 30s. Press <strong>Start live preview</strong> to aim and focus (~5&nbsp;min).</p>
  </div>
  <p class="muted">Drag the box onto the tower. Drag the corner to resize it. Yellow arrow: keep turning. Amber arrow: turn back. Green check: the number is high.</p>
  <div class="actions">
    <button type="button" id="live-preview-toggle" class="live-start">Start live preview (5 min)</button>
    <button type="button" id="capture" class="ghost">Capture now</button>
  </div>
  <p class="muted">Live preview speeds up capture (~every 0.75s) for about <strong>5 minutes</strong> so you can aim and focus. Status bar above shows remaining time. Capture now still forces one frame.</p>
"""
    body = f"""
  {lan_ui.page_header("Camera home", "Status and live preview for the camera service on this Pi. Home network only — not the public website.", title_suffix=" " + lan_ui.pill("8080"), kicker=":8080 · capture")}

  {lan_ui.camera_debug_panel_html()}
  {lan_ui.card("Live preview & capture", cam_body, kind="cam")}
<script>
(function () {{
  var pollIdleMs = {_UI_POLL_MS};
  var pollLiveMs = {_UI_PREVIEW_POLL_MS};
  var timer = null;
  var statusTimer = null;
  var previewOn = false;
  var cueKeep = '<svg viewBox="0 0 16 16" width="14" height="14"><path d="M8.2 2.4a5.2 5.2 0 1 1-1.5 10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M8.2 1.2v3.1H5.1" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var cueBack = '<svg viewBox="0 0 16 16" width="14" height="14"><path d="M7.8 2.4a5.2 5.2 0 1 0 1.5 10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M7.8 1.2v3.1h3.1" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var cuePeak = '<svg viewBox="0 0 16 16" width="14" height="14"><path d="M3 8.4 6.4 12 13 4.2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  function previewUrl() {{
    return "{_RAW_JPEG_PATH}?t=" + Date.now();
  }}
  function refreshPreviewImg() {{
    return window.lanUi.swapImg("preview", previewUrl(), {{ followNaturalAspect: true }});
  }}
  var focusPeak = 0;
  var focusSamples = 0;
  var lastScore = null;
  var dragging = false;
  function tick() {{
    if (document.hidden) return;
    refreshPreviewImg();
    refreshFocus();
  }}
  function clampBox(region) {{
    var width = Math.min(1, Math.max(0.02, Number(region.width) || 0.4));
    var height = Math.min(1, Math.max(0.02, Number(region.height) || 0.4));
    var left = Math.min(Math.max(0, Number(region.left) || 0), 1 - width);
    var top = Math.min(Math.max(0, Number(region.top) || 0), 1 - height);
    return {{ left: left, top: top, width: width, height: height }};
  }}
  function placeFocusBox(region, force) {{
    if (dragging && !force) return;
    if (!region) return;
    var box = document.getElementById("focus-region");
    if (!box) return;
    var next = clampBox(region);
    box.style.left = (next.left * 100) + "%";
    box.style.top = (next.top * 100) + "%";
    box.style.width = (next.width * 100) + "%";
    box.style.height = (next.height * 100) + "%";
  }}
  function regionFromBox(box) {{
    var frame = box.closest(".preview-frame");
    if (!frame) return null;
    var fr = frame.getBoundingClientRect();
    var br = box.getBoundingClientRect();
    if (fr.width < 1 || fr.height < 1) return null;
    return clampBox({{
      left: (br.left - fr.left) / fr.width,
      top: (br.top - fr.top) / fr.height,
      width: br.width / fr.width,
      height: br.height / fr.height
    }});
  }}
  var saveBusy = false;
  var saveQueued = null;
  function saveFocusBox(region) {{
    saveQueued = region;
    focusPeak = 0;
    focusSamples = 0;
    lastScore = null;
    setCue("");
    if (saveBusy) return;
    function pump() {{
      if (!saveQueued) {{
        saveBusy = false;
        return;
      }}
      saveBusy = true;
      var body = saveQueued;
      saveQueued = null;
      window.lanUi.fetchJson("/focus-region", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(body)
      }}).then(function (data) {{
        if (saveQueued) {{
          pump();
          return;
        }}
        saveBusy = false;
        if (!dragging && data && data.region) placeFocusBox(data.region);
        refreshFocus();
      }}).catch(function () {{
        saveBusy = false;
        if (saveQueued) pump();
      }});
    }}
    pump();
  }}
  function bindFocusBox() {{
    var box = document.getElementById("focus-region");
    if (!box || box.dataset.bound) return;
    box.dataset.bound = "1";
    var drag = null;
    box.addEventListener("pointerdown", function (ev) {{
      if (ev.button != null && ev.button !== 0) return;
      var start = regionFromBox(box);
      if (!start) return;
      var handle = ev.target.closest ? ev.target.closest(".focus-handle") : null;
      drag = {{
        resize: !!handle,
        px: ev.clientX,
        py: ev.clientY,
        left: start.left,
        top: start.top,
        width: start.width,
        height: start.height
      }};
      dragging = true;
      try {{ box.setPointerCapture(ev.pointerId); }} catch (err) {{}}
      ev.preventDefault();
    }});
    box.addEventListener("pointermove", function (ev) {{
      if (!drag) return;
      var frame = box.closest(".preview-frame");
      if (!frame) return;
      var fr = frame.getBoundingClientRect();
      var dx = (ev.clientX - drag.px) / fr.width;
      var dy = (ev.clientY - drag.py) / fr.height;
      var next = drag.resize
        ? {{ left: drag.left, top: drag.top, width: drag.width + dx, height: drag.height + dy }}
        : {{ left: drag.left + dx, top: drag.top + dy, width: drag.width, height: drag.height }};
      placeFocusBox(next, true);
      ev.preventDefault();
    }});
    function endDrag() {{
      if (!drag) return;
      drag = null;
      dragging = false;
      var region = regionFromBox(box);
      if (region) saveFocusBox(region);
    }}
    box.addEventListener("pointerup", endDrag);
    box.addEventListener("pointercancel", endDrag);
  }}
  function setCue(kind) {{
    var box = document.getElementById("focus-region");
    var cue = document.getElementById("focus-cue");
    if (box) box.className = "focus-region" + (kind ? (" is-" + kind) : "");
    if (!cue) return;
    cue.innerHTML = kind === "keep" ? cueKeep : kind === "back" ? cueBack : kind === "peak" ? cuePeak : "";
  }}
  async function refreshFocus() {{
    var el = document.getElementById("focus-score");
    if (!el) return;
    try {{
      var data = await window.lanUi.fetchJson("/focus-score");
      placeFocusBox(data.region);
      if (data.score == null) {{
        el.textContent = "—";
        el.setAttribute("aria-label", "Sharpness unavailable");
        setCue("");
        return;
      }}
      var score = Math.round(Number(data.score) || 0);
      var band = lastScore == null ? 0 : Math.max(8, Math.round(lastScore * 0.02));
      var rose = lastScore != null && score > lastScore + band;
      var fell = lastScore != null && score < lastScore - band;
      if (score > focusPeak) focusPeak = score;
      focusSamples += 1;
      var nearPeak = focusSamples > 1 && focusPeak > 0 && score >= focusPeak * 0.98 && !rose;
      var kind = "";
      var words = "Sharpness " + score;
      if (fell) {{
        kind = "back";
        words += ", turn the other way";
      }} else if (nearPeak) {{
        kind = "peak";
        words += ", high";
      }} else if (rose) {{
        kind = "keep";
        words += ", keep turning";
      }}
      setCue(kind);
      el.textContent = String(score);
      el.setAttribute("aria-label", words);
      lastScore = score;
    }} catch (e) {{
      el.textContent = "—";
      el.setAttribute("aria-label", "Sharpness unavailable");
    }}
  }}
  function restartPoll() {{
    if (timer) {{ clearInterval(timer); timer = null; }}
    if (document.hidden) return;
    var ms = previewOn ? pollLiveMs : pollIdleMs;
    timer = setInterval(tick, ms);
  }}
  function stopPoll() {{
    if (!timer) return;
    clearInterval(timer);
    timer = null;
  }}
  function formatRemaining(sec) {{
    var s = Math.max(0, Math.ceil(Number(sec) || 0));
    var m = Math.floor(s / 60);
    var r = s % 60;
    return m + ":" + (r < 10 ? "0" : "") + r;
  }}
  function setPreviewUi(snap) {{
    var on = !!(snap && snap.enabled);
    previewOn = on;
    var btn = document.getElementById("live-preview-toggle");
    var meter = document.getElementById("live-preview-meter");
    var labelEl = document.getElementById("live-preview-label");
    var timeEl = document.getElementById("live-preview-time");
    var fillEl = document.getElementById("live-preview-fill");
    var statusEl = document.getElementById("live-preview-status");
    var duration = Math.max(1, Number(snap && snap.duration_seconds) || 300);
    var remaining = on ? Math.max(0, Number(snap.remaining_seconds || 0)) : 0;
    var pct = on ? Math.max(0, Math.min(100, (remaining / duration) * 100)) : 0;
    if (btn) {{
      btn.disabled = false;
      btn.textContent = on ? "Stop live preview" : "Start live preview (5 min)";
      btn.className = on ? "live-stop" : "live-start";
      btn.dataset.enabled = on ? "1" : "0";
      delete btn.dataset.lanLabel;
    }}
    if (meter) {{
      meter.className = "live-preview-meter " + (on ? "is-on" : "is-off");
    }}
    if (labelEl) {{
      labelEl.textContent = on ? "Live preview running" : "Live preview off";
    }}
    if (timeEl) {{
      timeEl.textContent = on ? (formatRemaining(remaining) + " left") : "Press Start";
    }}
    if (fillEl) {{
      fillEl.style.width = pct.toFixed(1) + "%";
    }}
    if (statusEl) {{
      if (on) {{
        statusEl.innerHTML = "High-rate capture (~every " +
          (snap.interval_seconds || 0.75) +
          "s). Auto-offs when the bar reaches zero — or press <strong>Stop</strong>.";
      }} else {{
        statusEl.innerHTML = "Off — preview refreshes about every 30s. Press <strong>Start live preview</strong> to aim and focus (~5&nbsp;min).";
      }}
    }}
    restartPoll();
  }}
  async function refreshPreviewStatus() {{
    try {{
      var snap = await window.lanUi.fetchJson("/live-preview");
      setPreviewUi(snap);
    }} catch (e) {{
      /* keep last known UI */
    }}
  }}
  document.getElementById("live-preview-toggle").addEventListener("click", async function () {{
    var btn = this;
    var on = btn.dataset.enabled === "1";
    window.lanUi.clearBanner("cam-banner");
    window.lanUi.setBusy(btn, true, on ? "Stopping…" : "Starting…");
    try {{
      var snap = await window.lanUi.fetchJson(on ? "/live-preview/off" : "/live-preview/on", {{ method: "POST" }});
      setPreviewUi(snap);
      if (snap && snap.enabled) {{
        focusPeak = 0;
        focusSamples = 0;
        lastScore = null;
        setCue("");
        window.lanUi.showBanner("cam-banner", "info", "Live preview on", "Put the tower in the center. Turn the front ring until Center sharpness peaks.");
        tick();
      }} else {{
        window.lanUi.showBanner("cam-banner", "info", "Live preview off", "Normal capture schedule restored. Press Start again anytime.");
      }}
    }} catch (e) {{
      window.lanUi.showBanner("cam-banner", "bad", "Live preview failed", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
      if (window.__reloadCameraDebug) window.__reloadCameraDebug();
    }}
  }});
  document.getElementById("capture").addEventListener("click", async function () {{
    var btn = this;
    window.lanUi.clearBanner("cam-banner");
    window.lanUi.setBusy(btn, true, "Capturing…");
    try {{
      await window.lanUi.fetchRes("/capture", {{ method: "POST" }});
      window.lanUi.showBanner("cam-banner", "info", "Capture requested", "Preview and status will refresh shortly.");
    }} catch (e) {{
      window.lanUi.showBanner("cam-banner", "bad", "Capture failed", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
      if (window.__reloadCameraDebug) window.__reloadCameraDebug();
      refreshPreviewImg();
    }}
  }});
  document.addEventListener("visibilitychange", function () {{
    if (document.hidden) {{
      stopPoll();
      if (statusTimer) {{ clearInterval(statusTimer); statusTimer = null; }}
    }} else {{
      tick();
      restartPoll();
      refreshPreviewStatus();
      if (!statusTimer) statusTimer = setInterval(refreshPreviewStatus, 1000);
    }}
  }});
  bindFocusBox();
  refreshPreviewImg();
  refreshFocus();
  restartPoll();
  refreshPreviewStatus();
  statusTimer = setInterval(refreshPreviewStatus, 1000);
}})();
</script>
"""
    return lan_ui.page(
        "Camera home",
        body,
        active="camera",
        pipe_more=pipe_more,
        extra_head="<style>body.svc-cam main{max-width:min(80rem,calc(100vw - 2rem))}</style>",
    )


def _debug_ui(*, pipe_more: list[dict[str, str]] | None = None) -> str:
    toggle_card = f"""
  {lan_ui.status_placeholder("cam-connectivity-mini", "Loading camera status…")}
  {lan_ui.stale_hint("maint-updated")}
  {lan_ui.status_placeholder("status", "Loading status…")}
  <div class="actions">
    <button id="toggle" type="button" disabled>Please wait…</button>
  </div>
  <p class="muted stack-gap"><strong>What this does</strong></p>
  <ul class="muted">
    <li><strong>OFF (live)</strong> — <code>/feed.jpg</code> matches Raw. Public livestream shows the live camera when the schedule is online. Private LAN-only stays live.</li>
    <li><strong>ON (maintenance)</strong> — <code>/feed.jpg</code> serves the Wartungsbild. Public variants show Wartung; private LAN-only stays on the live Raw frame.</li>
  </ul>
  <p class="muted">To aim or focus the lens, use <a href="/">Camera home → Start live preview</a> (~5&nbsp;min auto-off). This page does not change capture rate.</p>
"""
    preview_card = f"""
  <p class="muted"><strong>Feed</strong> (<code>/feed.jpg</code>) — live camera or Wartungsbild, depending on the toggle above.</p>
  {lan_ui.preview_img("preview", alt="Feed JPEG (/feed.jpg) — live camera or maintenance placeholder", loading="eager")}
"""
    body = f"""
  {lan_ui.page_header("Maintenance image", "Temporarily replace the <strong>public</strong> livestream with a fixed placeholder. Capture keeps running. Private LAN-only images stay on the live frame.", kicker=":8080 · wartungsbild")}

  {lan_ui.card("Toggle", toggle_card, kind="cam")}
  {lan_ui.card("Current feed image", preview_card, kind="cam")}
<script>
(function () {{
  var previewQs = "{_UI_PREVIEW_QS}";
  function previewUrl() {{
    return "{_FEED_JPEG_PATH}?" + previewQs + "&t=" + Date.now();
  }}
  async function loadConnectivity() {{
    var el = document.getElementById("cam-connectivity-mini");
    if (!el) return;
    try {{
      var h = await window.lanUi.fetchJson("/health");
      var c = (h && typeof h.connectivity === "object" && h.connectivity) ? h.connectivity : {{}};
      var detail = "Capture backend: " + (h.backend || "?");
      if (h.image_age_seconds != null) detail += " · image age " + Math.round(Number(h.image_age_seconds)) + "s";
      if (h.last_capture_error) detail += " · last error: " + h.last_capture_error;
      window.lanUi.banner(el, c.level || (c.ok ? "ok" : "bad"), c.label || h.status || "Unknown status", detail);
    }} catch (e) {{
      window.lanUi.banner(el, "bad", "Health unreachable", e && e.message ? e.message : String(e));
    }}
  }}
  async function refresh() {{
    var statusEl = document.getElementById("status");
    var btn = document.getElementById("toggle");
    var stamp = document.getElementById("maint-updated");
    try {{
      var body = await window.lanUi.fetchJson("/maintenance");
      var on = !!(body && body.enabled);
      window.lanUi.banner(
        statusEl,
        on ? "warn" : "info",
        on ? "Maintenance ON" : "Maintenance OFF",
        on
          ? "Public livestream will show Wartungsbild. Private LAN-only stays on live Raw. Feed (/feed.jpg) shows the placeholder."
          : "Feed matches Raw — public livestream shows the live camera when the schedule is online."
      );
      btn.disabled = false;
      btn.textContent = on
        ? "Turn maintenance OFF (back to live camera)"
        : "Turn maintenance ON (show placeholder)";
      btn.className = on ? "primary" : "danger";
      btn.dataset.enabled = on ? "1" : "0";
      delete btn.dataset.lanLabel;
      window.lanUi.swapImg("preview", previewUrl(), {{ followNaturalAspect: true }});
      window.lanUi.stampUpdated(stamp, true);
    }} catch (err) {{
      window.lanUi.banner(
        statusEl,
        "bad",
        "Could not load status",
        (err && err.message ? err.message : String(err)) + " — reload or check /maintenance."
      );
      btn.disabled = true;
      btn.textContent = "Unavailable";
      btn.className = "err";
      window.lanUi.stampUpdated(stamp, false);
    }}
    await loadConnectivity();
  }}
  document.getElementById("toggle").addEventListener("click", async function () {{
    var btn = document.getElementById("toggle");
    var on = btn.dataset.enabled === "1";
    if (!on) {{
      var ok = window.lanUi.confirm(
        "Turn maintenance ON? Public livestream will show Wartungsbild (via pipeline). Private LAN-only stays on the live Raw frame. /feed.jpg also swaps for optional consumers."
      );
      if (!ok) return;
    }}
    window.lanUi.setBusy(btn, true, "Switching…");
    try {{
      await window.lanUi.fetchRes(on ? "/maintenance/off" : "/maintenance/on", {{ method: "POST" }});
    }} catch (err) {{
      window.lanUi.banner(
        document.getElementById("status"),
        "bad",
        "Toggle failed",
        err && err.message ? err.message : String(err)
      );
    }}
    await refresh();
  }});
  refresh();
}})();
</script>
"""
    return lan_ui.page("Maintenance", body, active="maintenance", pipe_more=pipe_more)


def _variant_menu() -> list[dict[str, str]] | None:
    """JPEG shortcuts for the configured camera."""
    try:
        root = find_repo_root(Path(__file__))
    except FileNotFoundError:
        return None
    camera_id, _brand = primary_site(root)
    return variant_menu_items(root, camera_id) or None


def make_handler(
    state: AppState,
    store: ImageStore,
    backend: CaptureBackend,
    cfg: dict[str, Any],
    maintenance: MaintenanceMode | None = None,
    live_preview: LivePreview | None = None,
) -> Type[BaseHTTPRequestHandler]:
    min_interval = float(cfg.get("http", {}).get("capture_min_interval_seconds", 2))
    pipe_more = _variant_menu()
    home_ui = _home_ui(pipe_more=pipe_more)
    debug_ui = _debug_ui(pipe_more=pipe_more)
    focus_regions = FocusRegionStore(store.image_path.parent / "focus-region.json")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            # Prefer application logging; keep access quiet for periodic polls.
            # parse_request can log_error before self.path exists.
            path = getattr(self, "path", "") or ""
            if (
                path.startswith("/health")
                or path.startswith("/raw")
                or path.startswith("/feed")
                or path.startswith("/live-preview")
                or path.startswith("/focus-score")
                or path.startswith("/focus-region")
                or path.startswith("/maintenance")
            ):
                return
            super().log_message(fmt, *args)

        def _send_json(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # UI shells are process-static; short private cache helps repeat navigations.
            self.send_header("Cache-Control", "private, max-age=30")
            self.end_headers()
            self.wfile.write(body)

        def _send_jpeg(
            self,
            data: bytes,
            *,
            etag: str | None = None,
            max_width: int | None = None,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            if max_width is not None and etag:
                etag = f'{etag[:-1]}-w{max_width}"' if etag.endswith('"') else f"{etag}-w{max_width}"
            inm = self.headers.get("If-None-Match")
            if etag and inm and inm == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "private, max-age=5")
                if extra_headers:
                    for k, v in extra_headers.items():
                        self.send_header(k, v)
                self.end_headers()
                return
            if max_width is not None:
                data = downscale_jpeg(data, max_width, quality=72)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "private, max-age=5")
            if etag:
                self.send_header("ETag", etag)
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _maintenance_payload(self) -> dict[str, Any]:
            if maintenance is None:
                return {
                    "enabled": False,
                    "available": False,
                    "auto": False,
                    "maintenance_auto": False,
                }
            snap = maintenance.snapshot()
            snap["available"] = True
            snap["ui"] = "GET /debug/ui"
            snap["home"] = "GET /"
            return snap

        def _live_preview_payload(self) -> dict[str, Any]:
            if live_preview is None:
                return {
                    "enabled": False,
                    "available": False,
                    "remaining_seconds": None,
                    "note": "live preview unavailable",
                }
            snap = live_preview.snapshot()
            snap["available"] = True
            return snap

        def _health_payload(self) -> dict[str, Any]:
            maint = self._maintenance_payload()
            payload = state.health(maintenance=maint if maint.get("available") else None)
            payload["maintenance"] = maint
            payload["live_preview"] = self._live_preview_payload()
            return payload

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            max_w = parse_max_width((qs.get("w") or [None])[0])
            if lan_ui.send_favicon(self, path):
                return
            if path == "/":
                self._send_html(home_ui)
                return
            if path == "/debug/ui":
                self._send_html(debug_ui)
                return
            if path == "/maintenance":
                self._send_json(200, self._maintenance_payload())
                return
            if path == "/live-preview":
                self._send_json(200, self._live_preview_payload())
                return
            if path == "/focus-score":
                region = focus_regions.get()
                jpeg = store.read_jpeg()
                score = sharpness_score(jpeg, region) if jpeg else None
                self._send_json(200, {"score": score, "region": region})
                return
            if path == "/health":
                self._send_json(200, self._health_payload())
                return
            if path == "/status":
                payload = state.status()
                enriched = self._health_payload()
                for key in ("connectivity", "fail_safe", "summary", "reasons", "next_steps"):
                    if key in enriched:
                        payload[key] = enriched[key]
                payload["maintenance"] = enriched["maintenance"]
                payload["live_preview"] = enriched["live_preview"]
                self._send_json(200, payload)
                return
            if path == "/debug":
                payload = state.debug()
                enriched = self._health_payload()
                for key in ("connectivity", "fail_safe", "summary", "reasons", "next_steps"):
                    if key in enriched:
                        payload[key] = enriched[key]
                payload["maintenance"] = enriched["maintenance"]
                payload["live_preview"] = enriched["live_preview"]
                self._send_json(200, payload)
                return
            if path in ("/raw.jpg", "/raw"):
                self._serve_live_jpeg(max_width=max_w)
                return
            if path in ("/feed.jpg", "/feed"):
                self._serve_feed_jpeg(max_width=max_w)
                return
            self._send_json(
                404,
                {
                    "error": "not found",
                    "endpoints": [
                        "GET /",
                        "/raw.jpg",
                        "/feed.jpg",
                        "/favicon.ico",
                        "/favicon.svg",
                        "/health",
                        "/status",
                        "/debug",
                        "GET /debug/ui",
                        "GET /maintenance",
                        "POST /maintenance/on",
                        "POST /maintenance/off",
                        "GET /live-preview",
                        "POST /live-preview/on",
                        "POST /live-preview/off",
                        "GET /focus-score",
                        "POST /focus-region",
                        "POST /capture",
                    ],
                },
            )

        def _serve_live_jpeg(self, *, max_width: int | None) -> None:
            """Always last-good live capture — never Wartungsbild (aim/focus path)."""
            data = store.read_jpeg()
            if data is None:
                self._send_json(
                    503,
                    {
                        "error": "no valid image available",
                        "fail_safe": "refusing to return an empty/fake image",
                        "next_steps": [
                            "Wait for the capture loop or POST /capture",
                            "GET /debug for checklist",
                            "journalctl -u webcam-camera -n 50 --no-pager",
                        ],
                    },
                )
                return

            # Strong-ish ETag from size+mtime so clients can 304
            etag = None
            if store.image_path.exists():
                st = store.image_path.stat()
                etag = f'W/"{st.st_mtime_ns}-{st.st_size}"'
            extra: dict[str, str] = {}
            if state.serving_stale_image:
                extra["X-Webcam-Fail-Safe"] = "serving-last-good"
            if live_preview is not None and live_preview.active():
                extra["X-Webcam-Live-Preview"] = "1"
            if state.last_success_at:
                extra["Last-Modified"] = time.strftime(
                    "%a, %d %b %Y %H:%M:%S GMT", time.gmtime(state.last_success_at)
                )
            self._send_jpeg(data, etag=etag, max_width=max_width, extra_headers=extra or None)

        def _serve_feed_jpeg(self, *, max_width: int | None) -> None:
            """Downstream feed: Wartungsbild when maintenance on, else same as raw."""
            if maintenance is not None and maintenance.enabled:
                self._send_jpeg(
                    maintenance.jpeg,
                    etag=maintenance.etag,
                    max_width=max_width,
                    extra_headers={"X-Webcam-Maintenance": "1"},
                )
                return
            self._serve_live_jpeg(max_width=max_width)

        def _set_maintenance(self, enabled: bool) -> None:
            if maintenance is None:
                self._send_json(503, {"error": "maintenance mode unavailable"})
                return
            maintenance.set_enabled(enabled, auto=False)
            if not enabled:
                # Fresh failure window before auto Wartungsbild re-engages
                with state._lock:
                    state.consecutive_failures = 0
            self._send_json(200, {"ok": True, **self._maintenance_payload()})

        def _set_live_preview(self, enabled: bool) -> None:
            if live_preview is None:
                self._send_json(503, {"error": "live preview unavailable"})
                return
            snap = live_preview.set_enabled(enabled)
            self._send_json(200, {"ok": True, **snap, "available": True})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/maintenance/on", "/maintenance/off"):
                self._set_maintenance(path.endswith("/on"))
                return
            if path == "/maintenance":
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                enabled = True
                if raw:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        self._send_json(400, {"error": "expected JSON {\"enabled\": true|false}"})
                        return
                    if "enabled" not in body:
                        self._send_json(400, {"error": "missing enabled"})
                        return
                    enabled = bool(body["enabled"])
                self._set_maintenance(enabled)
                return
            if path == "/focus-region":
                length = int(self.headers.get("Content-Length") or 0)
                max_body = int(cfg.get("http", {}).get("max_body_bytes", 65536))
                if length > max_body:
                    self._send_json(413, {"error": "body too large"})
                    return
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                    if not isinstance(body, dict):
                        raise ValueError("missing box")
                    region = {}
                    for key in ("left", "top", "width", "height"):
                        region[key] = float(body[key])
                        if not math.isfinite(region[key]):
                            raise ValueError("bad box")
                except (json.JSONDecodeError, UnicodeError, KeyError, TypeError, ValueError):
                    self._send_json(400, {"error": "expected JSON left, top, width, height"})
                    return
                try:
                    saved = focus_regions.save(region)
                except OSError as exc:
                    self._send_json(
                        503,
                        {
                            "ok": False,
                            "error": f"could not save focus region: {exc}",
                            "next_steps": [
                                "sudo /opt/home-webcam-pipeline/pi/scripts/fix-data-perms.sh",
                                "Retry after sync/deploy finishes (data/ must stay webcam:webcam)",
                            ],
                        },
                    )
                    return
                self._send_json(200, {"ok": True, "region": saved})
                return
            if path in ("/live-preview/on", "/live-preview/off"):
                self._set_live_preview(path.endswith("/on"))
                return
            if path == "/live-preview":
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                enabled = True
                if raw:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        self._send_json(400, {"error": "expected JSON {\"enabled\": true|false}"})
                        return
                    if "enabled" not in body:
                        self._send_json(400, {"error": "missing enabled"})
                        return
                    enabled = bool(body["enabled"])
                self._set_live_preview(enabled)
                return
            if path != "/capture":
                self._send_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            max_body = int(cfg.get("http", {}).get("max_body_bytes", 65536))
            if length > max_body:
                self._send_json(413, {"error": "body too large"})
                return
            if length:
                self.rfile.read(length)

            now = time.time()
            # During live preview, allow manual capture more often (UI may still use loop).
            effective_min = (
                min(min_interval, float(live_preview.interval_seconds))
                if live_preview is not None and live_preview.active()
                else min_interval
            )
            if now - state.last_manual_capture_at < effective_min:
                self._send_json(
                    429,
                    {
                        "error": "capture rate limited",
                        "retry_after_seconds": effective_min,
                        "next_steps": ["Wait a moment, then retry POST /capture"],
                    },
                )
                return
            state.last_manual_capture_at = now

            started = time.monotonic()
            try:
                data = backend.capture()
                path_out, meta = store.save_jpeg(data)
                duration = time.monotonic() - started
                state.record_success(path_out, meta, duration)
                if maintenance is not None and state.backend_name != "simulation":
                    maintenance.auto_clear()
                health = self._health_payload()
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "size_bytes": meta["size_bytes"],
                        "duration_seconds": round(duration, 3),
                        "path": str(path_out),
                        "health": health["status"],
                    },
                )
            except Exception as exc:  # noqa: BLE001
                state.record_failure(str(exc), time.monotonic() - started)
                health = self._health_payload()
                self._send_json(
                    500,
                    {
                        "ok": False,
                        "error": str(exc),
                        "fail_safe": health["fail_safe"],
                        "next_steps": health.get("next_steps"),
                    },
                )

    return Handler
