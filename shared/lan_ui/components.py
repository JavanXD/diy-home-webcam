"""Reusable HTML fragments for LAN pages."""

from __future__ import annotations

from html import escape
from typing import Iterable


def pill(port_or_kind: str, label: str | None = None) -> str:
    """Port/service pill. ``port_or_kind``: ``8080``/``cam``, ``8090``/``pipe``, or ``brand``.

    Optional ``label`` overrides the visible text (e.g. ``pill("pipe", "JSON")``).
    """
    key = port_or_kind.lstrip(":").lower()
    if key in ("8080", "cam", "camera"):
        cls, default = "pill-cam", ":8080"
    elif key in ("8090", "pipe", "pipeline"):
        cls, default = "pill-pipe", ":8090"
    else:
        cls, default = "pill-brand", port_or_kind
    return f'<span class="pill {cls}">{escape(label or default)}</span>'


def page_header(title: str, lead: str = "", *, title_suffix: str = "", kicker: str = "") -> str:
    """Consistent page title + optional lead. ``title_suffix`` may include raw HTML (e.g. pill)."""
    kicker_html = f'\n  <span class="kicker">{escape(kicker)}</span>' if kicker else ""
    lead_html = f'\n  <p class="lead">{lead}</p>' if lead else ""
    return f"""<header class="page-header">{kicker_html}
  <h1>{escape(title)}{title_suffix}</h1>{lead_html}
</header>"""


def lan_link(
    label: str,
    *,
    port: int,
    path: str,
    link_class: str = "",
    strong: bool = False,
) -> str:
    """Cross-port ``<a data-lan-port>`` (rewritten by chrome nav JS)."""
    cls = f' class="{escape(link_class)}"' if link_class else ""
    text = f"<strong>{escape(label)}</strong>" if strong else escape(label)
    return (
        f'<a{cls} data-lan-port="{port}" data-lan-path="{escape(path, quote=True)}" '
        f'href="http://raspicam.local:{port}{escape(path, quote=True)}">{text}</a>'
    )


def card(
    title: str,
    body: str,
    *,
    kind: str | None = None,
    title_suffix: str = "",
    card_id: str = "",
) -> str:
    """Section panel. ``kind`` is ``cam`` / ``pipe`` / None. Empty ``title`` skips the head."""
    classes = ["card"]
    if kind == "cam":
        classes.append("card-cam")
    elif kind == "pipe":
        classes.append("card-pipe")
    id_attr = f' id="{escape(card_id)}"' if card_id else ""
    if title:
        return f"""<section class="{' '.join(classes)}"{id_attr}>
  <div class="panel-head"><h2>{escape(title)}{title_suffix}</h2></div>
  <div class="panel-body">
  {body}
  </div>
</section>"""
    return f"""<section class="{' '.join(classes)}"{id_attr}>
  <div class="panel-body">
  {body}
  </div>
</section>"""


def empty_state(message: str, *, el_id: str = "") -> str:
    """Muted empty/placeholder copy for galleries and panels."""
    id_attr = f' id="{escape(el_id)}"' if el_id else ""
    return f'<p class="empty-state"{id_attr}>{escape(message)}</p>'


def actions_bar(*buttons: str, sticky: bool = False, bar_id: str = "") -> str:
    """Action row. ``sticky`` pins primary actions while scrolling long forms."""
    classes = ["actions"]
    if sticky:
        classes.append("actions-sticky")
    id_attr = f' id="{escape(bar_id)}"' if bar_id else ""
    return f'<div class="{" ".join(classes)}"{id_attr}>\n  {"".join(buttons)}\n</div>'


def status_placeholder(el_id: str, loading: str = "Loading…") -> str:
    return (
        f'<div id="{escape(el_id)}" class="status-box is-loading" role="status" aria-busy="true">'
        f'<span class="status-badge">…</span>'
        f'<div class="status-body"><strong>{escape(loading)}</strong></div>'
        f"</div>"
    )


def banner_slot(el_id: str) -> str:
    return f'<div id="{escape(el_id)}" class="banner" hidden role="status"></div>'


def stale_hint(el_id: str) -> str:
    return f'<p id="{escape(el_id)}" class="stale-hint" aria-live="polite"></p>'


def preview_img(
    el_id: str,
    *,
    alt: str,
    width: int = 640,
    height: int = 480,
    css_class: str = "preview",
    loading: str = "lazy",
    framed: bool = True,
    overlay: str = "",
    frame_class: str = "",
) -> str:
    """Preview ``<img>``. Default ``loading=lazy``; use ``eager`` for above-the-fold live previews.

    When ``framed`` (default), wraps in ``.preview-frame`` with a fixed aspect-ratio box so
    reload / late decode does not collapse page layout.
    """
    load = loading if loading in ("lazy", "eager") else "lazy"
    w = max(1, int(width))
    h = max(1, int(height))
    img = (
        f'<img class="{escape(css_class)}" id="{escape(el_id)}" '
        f'alt="{escape(alt)}" width="{w}" height="{h}" '
        f'loading="{load}" decoding="async">'
    )
    if not framed:
        return img
    frame_cls = "preview-frame"
    extra = frame_class.strip()
    if extra:
        frame_cls += " " + escape(extra)
    return (
        f'<div class="{frame_cls}" style="aspect-ratio: {w} / {h}">'
        f"{img}{overlay}</div>"
    )


def camera_debug_panel_html(*, health_url: str = "/health") -> str:
    """Camera connectivity card + JS that fills from GET /health."""
    url = escape(health_url, quote=True)
    return f"""
<section class="card card-cam" id="camera-status-card">
  <div class="panel-head"><h2>Camera status {pill("8080")}</h2></div>
  <div class="panel-body">
  {status_placeholder("cam-connectivity", "Loading status…")}
  <dl class="debug-grid" id="cam-debug"></dl>
  {stale_hint("cam-updated")}
  <p class="muted stack-gap">Raw JSON endpoints are under <strong>More</strong> in the green nav.</p>
  </div>
</section>
<script>
(function () {{
  function row(dl, k, v) {{
    if (v === undefined || v === null || v === "") return;
    var dt = document.createElement("dt");
    dt.textContent = k;
    var dd = document.createElement("dd");
    dd.textContent = String(v);
    dl.appendChild(dt);
    dl.appendChild(dd);
  }}
  async function loadCameraDebug() {{
    var box = document.getElementById("cam-connectivity");
    var dl = document.getElementById("cam-debug");
    var stamp = document.getElementById("cam-updated");
    if (!box || !dl) return;
    try {{
      var h = await window.lanUi.fetchJson("{url}");
      var c = (h && typeof h.connectivity === "object" && h.connectivity) ? h.connectivity : {{}};
      var kind = c.level || (c.ok ? "ok" : "bad");
      var title = c.label || h.status || "Unknown status";
      var detail = c.detail || h.summary || "";
      window.lanUi.banner(box, kind, title, detail);
      dl.innerHTML = "";
      row(dl, "Health", h.status);
      row(dl, "Host uptime", window.lanUi.formatDuration(h.system_uptime_seconds));
      row(dl, "Service uptime", window.lanUi.formatDuration(h.uptime_seconds));
      var backendName = h.backend || c.backend;
      if (backendName === "picamera2" || backendName === "rpicam") row(dl, "Backend", backendName);
      row(dl, "Camera detected", h.camera_detected === true ? "yes" : (h.camera_detected === false ? "no" : "?"));
      row(dl, "Model", h.camera_model);
      var maint = (h.maintenance && typeof h.maintenance === "object") ? h.maintenance : null;
      if (c.maintenance_auto || (maint && maint.auto)) {{
        row(dl, "Mode", "Auto maintenance image");
        row(dl, "Auto reason", (c.maintenance_reason || (maint && maint.reason) || "—"));
      }}
      row(dl, "Image age", h.image_age_seconds != null ? Math.round(Number(h.image_age_seconds)) + " s" : "—");
      row(dl, "Valid JPEG", h.has_valid_image ? "yes" : "no");
      row(dl, "Consecutive failures", h.consecutive_failure_count);
      row(dl, "Last error", h.last_capture_error);
      row(dl, "Last event", h.last_event);
      row(dl, "Maintenance", maint && maint.enabled ? (maint.auto ? "ON (auto)" : "ON (manual)") : "OFF");
      var vids = Array.isArray(c.video_devices) ? c.video_devices
        : (Array.isArray(h.video_devices) ? h.video_devices : []);
      var vidCount = (c.video_devices_count != null) ? Number(c.video_devices_count)
        : ((h.video_devices_count != null) ? Number(h.video_devices_count) : vids.length);
      var vidTrunc = !!(c.video_devices_truncated || h.video_devices_truncated);
      if (vids.length) {{
        var vidLabel = vids.join(", ");
        if (vidTrunc && vidCount > vids.length) {{
          vidLabel += " (+" + (vidCount - vids.length) + " more)";
        }}
        row(dl, "/dev/video* (" + vidCount + ")", vidLabel);
      }} else if (vidCount > 0) {{
        row(dl, "/dev/video*", vidCount + " nodes (libcamera)");
      }} else if (c.video_devices_checked) {{
        row(dl, "/dev/video*", "none");
      }}
      if (c.picamera2 != null) row(dl, "picamera2", c.picamera2 ? "importable" : "not available");
      window.lanUi.stampUpdated(stamp, true);
    }} catch (e) {{
      window.lanUi.banner(box, "bad", "Health unreachable", String(e && e.message ? e.message : e));
      window.lanUi.stampUpdated(stamp, false);
    }}
  }}
  var pollMs = 30000;
  var timer = null;
  function tick() {{
    if (document.hidden) return;
    loadCameraDebug();
  }}
  function startPoll() {{
    if (timer) return;
    timer = setInterval(tick, pollMs);
  }}
  function stopPoll() {{
    if (!timer) return;
    clearInterval(timer);
    timer = null;
  }}
  document.addEventListener("visibilitychange", function () {{
    if (document.hidden) stopPoll();
    else {{ tick(); startPoll(); }}
  }});
  loadCameraDebug();
  startPoll();
  window.__reloadCameraDebug = loadCameraDebug;
}})();
</script>
""".strip()


def rewrite_host_links_js(element_ids: Iterable[str]) -> str:
    """Optional helper: rewrite hardcoded raspicam.local host in given element ids."""
    ids = ",".join(f'"{escape(i, quote=True)}"' for i in element_ids)
    return f"""
(function () {{
  var h = location.hostname || "raspicam.local";
  [{ids}].forEach(function (id) {{
    var el = document.getElementById(id);
    if (!el || !el.href) return;
    el.href = el.href.replace("raspicam.local", h);
  }});
}})();
""".strip()
