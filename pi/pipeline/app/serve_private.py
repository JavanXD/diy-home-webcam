from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable, Type
from urllib.parse import parse_qs, urlparse

from shared import lan_ui
from shared.site_config import variant_menu_items
from shared.jpeg_util import downscale_jpeg, parse_max_width

from .camera_profile import load_camera_profile, public_site_label
from .public_live import PublicLiveSelection
from .schedule import PublicSchedule
from .setup_page import setup_ui
from .timelapse import TimelapseError, archive_for, job_error, request_build
from .timelapse_page import timelapse_ui
from .site_settings import create_camera, pipeline_config_paths, read_site, save_site
from .publish_settings import (
    default_env_path,
    probe_publish_connection,
    read_publish,
    save_publish,
)
from .path_safety import safe_camera_id, safe_jpeg_filename
from .wifi_nm import WifiError, network_glance, wifi_connect, wifi_scan, wifi_status
from .system_ops import (
    SystemOpsError,
    collect_system_status,
    collect_unit_logs,
    require_confirm,
    schedule_power,
    schedule_restart_services,
)
from .state import PipelineState
from .weather import DEFAULT_WEATHER_URL, get_weather_cache
from . import variants_editor as vedit
from shared.brand_overlay import format_site_badge

RefreshFn = Callable[..., dict[str, Any]]

# Gallery thumbs: narrow JPEG via ?w= (full live URL stays without w for HA/copy).
_GALLERY_THUMB_W = 240
# Large mask-edit canvas on Variants (wide main); still capped for LAN bandwidth.
_SERVED_PREVIEW_W = 1440


def _pipe_home_ui(*, pipe_more: list[dict[str, str]] | None = None) -> str:
    system_card = f"""
  {lan_ui.banner_slot("sys-msg")}
  <p class="muted">Home network only. Reboot and shut down affect the whole Pi. Restart webcam services leaves the OS running.</p>
  {lan_ui.actions_bar(
      '<button type="button" id="sys-restart" class="primary">Restart webcam services</button>',
      '<button type="button" id="sys-reboot" class="danger">Reboot Pi</button>',
      '<button type="button" id="sys-poweroff" class="danger">Shut down Pi</button>',
  )}
  <p class="field-help">Restart webcam services: <code>webcam-camera</code>, <code>webcam-pipeline</code>, and <code>nginx</code> when installed. Reboot / shut down use <code>systemctl reboot</code> / <code>poweroff</code>.</p>
<script>
(function () {{
  async function postSystem(path, confirmMsg, busyLabel) {{
    if (!window.lanUi.confirm(confirmMsg)) return;
    var btnRestart = document.getElementById("sys-restart");
    var btnReboot = document.getElementById("sys-reboot");
    var btnOff = document.getElementById("sys-poweroff");
    var buttons = [btnRestart, btnReboot, btnOff].filter(Boolean);
    buttons.forEach(function (b) {{ window.lanUi.setBusy(b, true, busyLabel); }});
    try {{
      var res = await window.lanUi.fetchJson(path, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ confirm: true }}),
        timeoutMs: 15000,
      }});
      window.lanUi.showBanner(
        "sys-msg",
        "warn",
        res.action === "restart-services" ? "Restarting services" : (res.action === "reboot" ? "Rebooting" : "Shutting down"),
        res.message || "Accepted"
      );
    }} catch (e) {{
      window.lanUi.showBanner(
        "sys-msg",
        "bad",
        "Request failed",
        String(e && e.message ? e.message : e)
      );
      buttons.forEach(function (b) {{ window.lanUi.setBusy(b, false); }});
    }}
  }}
  var restartBtn = document.getElementById("sys-restart");
  var rebootBtn = document.getElementById("sys-reboot");
  var powerBtn = document.getElementById("sys-poweroff");
  if (restartBtn) {{
    restartBtn.addEventListener("click", function () {{
      postSystem(
        "/system/restart-services",
        "Restart webcam services now?\\n\\nRestarts webcam-camera, webcam-pipeline, and nginx (if installed). The OS stays up. This page will disconnect for a few seconds.",
        "Restarting…"
      );
    }});
  }}
  if (rebootBtn) {{
    rebootBtn.addEventListener("click", function () {{
      postSystem(
        "/system/reboot",
        "Reboot this Raspberry Pi now?\\n\\nThe whole OS will restart. The webcam will be offline for about a minute.",
        "Rebooting…"
      );
    }});
  }}
  if (powerBtn) {{
    powerBtn.addEventListener("click", function () {{
      postSystem(
        "/system/poweroff",
        "Shut down this Raspberry Pi now?\\n\\nPower will turn off. You must reconnect power (or use the case power button) to bring the webcam back.",
        "Shutting down…"
      );
    }});
  }}
}})();
</script>
"""
    health_strip = f"""
  {lan_ui.status_placeholder("sys-health", "Loading host status…")}
  <dl class="debug-grid" id="sys-health-grid"></dl>
  {lan_ui.stale_hint("sys-health-updated")}
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
  function unitLine(units) {{
    if (!units || !units.length) return "";
    return units.map(function (u) {{
      var state = u.installed === false ? "not installed" : (u.active || "?");
      return (u.name || u.unit || "?") + "=" + state;
    }}).join(" · ");
  }}
  function diskLine(disks) {{
    if (!disks || !disks.length) return "";
    return disks.map(function (d) {{
      var pct = d.free_pct == null ? "?" : (d.free_pct + "% free");
      return (d.label || d.path || "disk") + " " + pct;
    }}).join(" · ");
  }}
  function publishLine(p) {{
    if (!p) return "";
    if (!p.enabled) return "publish off";
    if (p.last_success_age_seconds == null) return "no successful publish yet";
    return "last OK " + window.lanUi.formatDuration(p.last_success_age_seconds) + " ago";
  }}
  function clockLine(c) {{
    if (!c) return "";
    if (c.ntp_synchronized === true) return "NTP OK" + (c.timezone ? " · " + c.timezone : "");
    if (c.ntp_synchronized === false) return "NTP not synchronized";
    return "NTP unknown" + (c.timezone ? " · " + c.timezone : "");
  }}
  function healthKind(s) {{
    if (!s) return "warn";
    var units = s.units || [];
    var unitsBad = units.some(function (u) {{ return u.installed && !u.ok; }});
    var diskWarn = (s.disks || []).some(function (d) {{ return d.free_pct != null && d.free_pct < 15; }});
    var diskBad = (s.disks || []).some(function (d) {{ return d.free_pct != null && d.free_pct < 5; }});
    var temp = s.temperature_c;
    var tempWarn = temp != null && temp >= 70;
    var tempBad = temp != null && temp >= 80;
    var ntpBad = s.clock && s.clock.ntp_synchronized === false;
    if (unitsBad || diskBad || tempBad || ntpBad) return "bad";
    if (diskWarn || tempWarn) return "warn";
    return "ok";
  }}
  async function loadSystemHealth() {{
    var box = document.getElementById("sys-health");
    var dl = document.getElementById("sys-health-grid");
    var stamp = document.getElementById("sys-health-updated");
    if (!box || !dl) return;
    try {{
      var s = await window.lanUi.fetchJson("/system/status");
      var kind = healthKind(s);
      var title = kind === "ok" ? "Host OK" : (kind === "bad" ? "Host issues" : "Host warn");
      var detail = diskLine(s.disks);
      if (s.temperature_c != null) detail = (detail ? detail + " · " : "") + s.temperature_c + " °C";
      window.lanUi.banner(box, kind, title, detail || "");
      dl.innerHTML = "";
      row(dl, "Disk", diskLine(s.disks));
      row(dl, "SoC temp", s.temperature_c != null ? (s.temperature_c + " °C") : null);
      row(dl, "Units", unitLine(s.units));
      row(dl, "R2 publish", publishLine(s.publish));
      row(dl, "Clock", clockLine(s.clock));
      window.lanUi.stampUpdated(stamp, true);
    }} catch (e) {{
      window.lanUi.banner(box, "bad", "Host status unreachable", String(e && e.message ? e.message : e));
      window.lanUi.stampUpdated(stamp, false);
    }}
  }}
  var pollMs = 30000;
  var timer = null;
  function tick() {{
    if (document.hidden) return;
    loadSystemHealth();
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
  loadSystemHealth();
  startPoll();
}})();
</script>
"""
    network_card = f"""
  {lan_ui.status_placeholder("sys-net", "Loading network…")}
  <dl class="debug-grid" id="sys-net-grid"></dl>
  {lan_ui.stale_hint("sys-net-updated")}
  <p class="field-help">Join a different Wi‑Fi on <a data-lan-port="8090" data-lan-path="/setup/ui" href="/setup/ui">Setup</a>.</p>
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
  async function loadNet() {{
    var box = document.getElementById("sys-net");
    var dl = document.getElementById("sys-net-grid");
    var stamp = document.getElementById("sys-net-updated");
    if (!box || !dl) return;
    try {{
      var s = await window.lanUi.fetchJson("/system/status");
      var ifaces = (s.network || []);
      var up = ifaces.filter(function (i) {{ return i.up; }});
      var kind = up.length ? "ok" : "warn";
      var title = up.length ? ("Reachable · " + up.length + " link" + (up.length === 1 ? "" : "s")) : "No link up";
      var detail = up.map(function (i) {{
        return (i.type === "wifi" ? "wifi" : "eth") + " " + (i.ipv4 || i.device || "");
      }}).join(" · ");
      window.lanUi.banner(box, kind, title, detail || (s.message || ""));
      dl.innerHTML = "";
      if (!ifaces.length) {{
        row(dl, "Note", s.message || "No ethernet/wifi devices reported");
      }}
      ifaces.forEach(function (i) {{
        var label = (i.type === "wifi" ? "Wi‑Fi" : "Ethernet") + " (" + (i.device || "?") + ")";
        var bits = [];
        bits.push(i.up ? "up" : (i.state || "down"));
        if (i.ipv4) bits.push(i.ipv4);
        if (i.gateway) bits.push("gw " + i.gateway);
        if (i.type === "wifi" && i.ssid) bits.push(i.ssid);
        row(dl, label, bits.join(" · "));
      }});
      window.lanUi.stampUpdated(stamp, true);
    }} catch (e) {{
      window.lanUi.banner(box, "bad", "Network unreachable", String(e && e.message ? e.message : e));
      window.lanUi.stampUpdated(stamp, false);
    }}
  }}
  var pollMs = 30000;
  var timer = null;
  function tick() {{
    if (document.hidden) return;
    loadNet();
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
  loadNet();
  startPoll();
}})();
</script>
"""
    logs_card = f"""
  {lan_ui.banner_slot("sys-logs-msg")}
  {lan_ui.actions_bar('<button type="button" id="sys-logs-refresh" class="ghost">Refresh logs</button>')}
  <pre class="log-peek" id="sys-logs" aria-live="polite">Loading recent logs…</pre>
  <p class="field-help">Last ~40 lines from <code>webcam-camera</code> and <code>webcam-pipeline</code> only (read-only).</p>
<script>
(function () {{
  async function loadLogs() {{
    var pre = document.getElementById("sys-logs");
    var btn = document.getElementById("sys-logs-refresh");
    if (!pre) return;
    if (btn) window.lanUi.setBusy(btn, true, "Loading…");
    try {{
      var res = await window.lanUi.fetchJson("/system/logs?lines=40", {{ timeoutMs: 20000 }});
      if (res.ok === false) {{
        window.lanUi.showBanner("sys-logs-msg", "bad", "Logs unavailable", res.error || "journalctl failed");
        pre.textContent = res.error || "No log output";
      }} else {{
        window.lanUi.clearBanner("sys-logs-msg");
        pre.textContent = res.text || "(no recent journal lines)";
        pre.scrollTop = pre.scrollHeight;
      }}
    }} catch (e) {{
      window.lanUi.showBanner(
        "sys-logs-msg",
        "bad",
        "Logs unreachable",
        String(e && e.message ? e.message : e)
      );
      pre.textContent = "";
    }} finally {{
      if (btn) window.lanUi.setBusy(btn, false);
    }}
  }}
  var btn = document.getElementById("sys-logs-refresh");
  if (btn) btn.addEventListener("click", loadLogs);
  loadLogs();
}})();
</script>
"""
    status_card = f"""
  {lan_ui.status_placeholder("pipe-health", "Loading status…")}
  <dl class="debug-grid" id="pipe-debug"></dl>
  {lan_ui.stale_hint("pipe-updated")}
  <p class="muted stack-gap">Raw JSON endpoints are under <strong>More</strong> in the red nav.</p>
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
  async function loadPipeHealth() {{
    var box = document.getElementById("pipe-health");
    var dl = document.getElementById("pipe-debug");
    var stamp = document.getElementById("pipe-updated");
    if (!box || !dl) return;
    try {{
      var h = await window.lanUi.fetchJson("/health");
      var kind = "ok";
      if (h.status === "DEGRADED" || h.status === "STARTING") kind = "warn";
      if (h.status === "UNHEALTHY") kind = "bad";
      window.lanUi.banner(box, kind, h.status || "Unknown", h.summary || "");
      dl.innerHTML = "";
      row(dl, "Host uptime", window.lanUi.formatDuration(h.system_uptime_seconds));
      row(dl, "Service uptime", window.lanUi.formatDuration(h.uptime_seconds));
      row(dl, "Version", h.version);
      row(dl, "Cameras", h.camera_count);
      row(dl, "Last cycle", h.last_cycle_at);
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
    loadPipeHealth();
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
  loadPipeHealth();
  startPoll();
}})();
</script>
"""
    body = f"""
  {lan_ui.page_header("Pipeline", "Crops, privacy masks, private LAN-only images, and the public livestream schedule — pipeline service only.", title_suffix=" " + lan_ui.pill("8090"), kicker=":8090 · render · publish")}
  {lan_ui.card("Pipeline status", status_card, kind="pipe")}
  {lan_ui.card("System health", health_strip, kind="pipe")}
  {lan_ui.card("Network", network_card, kind="pipe")}
  {lan_ui.card("Recent logs", logs_card, kind="pipe")}
  {lan_ui.card("System", system_card, kind="pipe")}
"""
    return lan_ui.page("Pipeline", body, active="pipeline", pipe_more=pipe_more)


def _schedule_ui(*, pipe_more: list[dict[str, str]] | None = None) -> str:
    status_card = f"""
  {lan_ui.status_placeholder("status", "Loading schedule…")}
  {lan_ui.stale_hint("sched-updated")}
  {lan_ui.banner_slot("msg")}
"""
    when_card = f"""
  <label for="mode">Mode</label>
  <select id="mode">
    <option value="solar">Follow sunrise/sunset (with offset)</option>
    <option value="fixed">Fixed daily start and end times</option>
    <option value="always_on">Always online (ignore day/night)</option>
  </select>
  <p class="field-help">Solar uses the place from <a data-lan-port="8090" data-lan-path="/setup/ui" href="/setup/ui">Setup</a> (timezone + lat/lon) plus the offsets below. Fixed uses clock times. Always online never shows the night placeholder.</p>
  <label class="inline"><input type="checkbox" id="enabled"> Schedule enabled</label>
  <p class="field-help">When unchecked, the public stream stays online regardless of mode.</p>

  <div id="panel-solar" class="mode-panel">
    <fieldset>
      <legend>Sunrise / sunset window</legend>
      <p id="location-readonly" class="muted" role="status">Location: loading…</p>
      <p class="field-help">Edit latitude, longitude, and timezone on <a data-lan-port="8090" data-lan-path="/setup/ui" href="/setup/ui">Setup</a> — one place for the whole Pi.</p>
      <div class="row">
        <div>
          <label for="before">Minutes before sunrise (go online)</label>
          <input id="before" type="number" step="1" inputmode="numeric">
        </div>
        <div>
          <label for="after">Minutes after sunset (go offline)</label>
          <input id="after" type="number" step="1" inputmode="numeric">
        </div>
      </div>
    </fieldset>
  </div>

  <div id="panel-fixed" class="mode-panel" hidden>
    <fieldset>
      <legend>Fixed daily times</legend>
      <div class="row">
        <div>
          <label for="fixedStart">Go online at</label>
          <input id="fixedStart" type="time">
        </div>
        <div>
          <label for="fixedStop">Go offline at</label>
          <input id="fixedStop" type="time">
        </div>
      </div>
    </fieldset>
  </div>
"""
    placeholder_card = f"""
  <label class="inline"><input type="checkbox" id="overlay"> Show “Back at …” time on the placeholder</label>
  <p class="muted">A default night image is built in. Optionally upload your own JPEG for when the public stream is offline.</p>
  <label for="file">JPEG file</label>
  <input id="file" type="file" accept="image/jpeg,.jpg,.jpeg">
  <div class="actions">
    <button type="button" id="upload">Upload placeholder</button>
    <button type="button" id="resetPh" class="danger">Restore default image</button>
  </div>
  {lan_ui.preview_img("preview", alt="Placeholder preview", width=640, height=360)}
"""
    body = f"""
  {lan_ui.page_header("Public schedule", "Home network only. Controls when the <strong>public website</strong> shows the live camera vs a night/offline placeholder. Private LAN-only images always stay on the live frame.", kicker=":8090 · public online window")}

  {lan_ui.card("Current status", status_card, kind="pipe")}
  {lan_ui.card("When the public stream is online", when_card, kind="pipe")}
  {lan_ui.card("Offline / night placeholder", placeholder_card, kind="pipe")}

  <div class="actions actions-sticky">
    <button type="button" id="save" class="primary">Save schedule</button>
  </div>

<script>
(function () {{
  var cam = "";

  function syncModePanels() {{
    var mode = document.getElementById("mode").value || "solar";
    var solar = document.getElementById("panel-solar");
    var fixed = document.getElementById("panel-fixed");
    if (solar) solar.hidden = mode !== "solar";
    if (fixed) fixed.hidden = mode !== "fixed";
  }}

  async function load() {{
    var statusEl = document.getElementById("status");
    var stamp = document.getElementById("sched-updated");
    try {{
      var cfg = await window.lanUi.fetchJson("/schedule?camera=" + cam);
      var st = await window.lanUi.fetchJson("/schedule/status?camera=" + cam);
      document.getElementById("enabled").checked = !!(cfg && cfg.enabled);
      document.getElementById("mode").value = (cfg && cfg.mode) || "solar";
      var locEl = document.getElementById("location-readonly");
      if (locEl) {{
        if (cfg && cfg.location_set) {{
          locEl.textContent = "Location: " + Number(cfg.latitude).toFixed(4) + ", " +
            Number(cfg.longitude).toFixed(4) + " · " + (cfg.timezone || "local");
        }} else {{
          locEl.textContent = "Location: not set — open Setup to add latitude / longitude.";
        }}
      }}
      var solar = (cfg && typeof cfg.solar === "object" && cfg.solar) ? cfg.solar : {{}};
      var fixed = (cfg && typeof cfg.fixed === "object" && cfg.fixed) ? cfg.fixed : {{}};
      var ph = (cfg && typeof cfg.placeholder === "object" && cfg.placeholder) ? cfg.placeholder : {{}};
      document.getElementById("before").value =
        solar.start_offset_minutes_before_sunrise != null ? solar.start_offset_minutes_before_sunrise : 30;
      document.getElementById("after").value =
        solar.stop_offset_minutes_after_sunset != null ? solar.stop_offset_minutes_after_sunset : 30;
      document.getElementById("fixedStart").value = fixed.start || "07:00";
      document.getElementById("fixedStop").value = fixed.stop || "21:30";
      document.getElementById("overlay").checked = !!ph.overlay_back_at;
      syncModePanels();
      var online = !!(st && st.public_online);
      var kind = online ? "ok" : "warn";
      var title = online ? "ONLINE" : "OFFLINE";
      var rows = [];
      if (st) {{
        if (online && st.window && st.window.stop_local) {{
          rows.push(["Until", st.window.stop_local]);
        }} else if (!online && st.back_at_display) {{
          rows.push(["Back", st.back_at_display]);
        }}
        if (st.window && (st.window.start_local || st.window.stop_local)) {{
          rows.push(["Window", (st.window.start_local || "?") + " – " + (st.window.stop_local || "?")]);
        }}
        if (st.sun && (st.sun.sunrise_local || st.sun.sunset_local)) {{
          rows.push(["Sun", (st.sun.sunrise_local || "?") + " / " + (st.sun.sunset_local || "?")]);
        }}
        if (st.timezone) rows.push(["TZ", st.timezone]);
        if (st.mode) rows.push(["Mode", st.mode]);
      }}
      if (!rows.length && st && st.reason) {{
        window.lanUi.banner(statusEl, kind, title, st.reason);
      }} else {{
        window.lanUi.banner(statusEl, kind, title, rows);
      }}
      window.lanUi.swapImg(
        "preview",
        "/schedule/placeholder.jpg?camera=" + cam + "&t=" + Date.now(),
        {{ followNaturalAspect: true }}
      );
      window.lanUi.stampUpdated(stamp, true);
    }} catch (e) {{
      window.lanUi.banner(
        statusEl,
        "bad",
        "Could not load schedule",
        e && e.message ? e.message : String(e)
      );
      window.lanUi.stampUpdated(stamp, false);
    }}
  }}

  document.getElementById("mode").addEventListener("change", syncModePanels);

  document.getElementById("save").onclick = async function () {{
    var btn = this;
    window.lanUi.clearBanner("msg");
    window.lanUi.setBusy(btn, true, "Saving…");
    var body = {{
      enabled: document.getElementById("enabled").checked,
      mode: document.getElementById("mode").value,
      solar: {{
        start_offset_minutes_before_sunrise: Number(document.getElementById("before").value),
        stop_offset_minutes_after_sunset: Number(document.getElementById("after").value),
      }},
      fixed: {{
        start: document.getElementById("fixedStart").value,
        stop: document.getElementById("fixedStop").value,
      }},
      placeholder: {{ overlay_back_at: document.getElementById("overlay").checked }},
    }};
    try {{
      await window.lanUi.fetchRes("/schedule?camera=" + cam, {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify(body),
      }});
      window.lanUi.showBanner("msg", "info", "Saved", "Schedule updated.");
      await load();
    }} catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Save failed", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }};

  document.getElementById("upload").onclick = async function () {{
    var btn = this;
    window.lanUi.clearBanner("msg");
    var f = document.getElementById("file").files[0];
    if (!f) {{
      window.lanUi.showBanner("msg", "warn", "No file selected", "Please choose a JPEG first.");
      return;
    }}
    window.lanUi.setBusy(btn, true, "Uploading…");
    try {{
      var buf = await f.arrayBuffer();
      await window.lanUi.fetchRes("/schedule/placeholder?camera=" + cam, {{
        method: "POST",
        headers: {{"Content-Type": "image/jpeg"}},
        body: buf,
        timeoutMs: 30000,
      }});
      window.lanUi.showBanner("msg", "info", "Placeholder uploaded", "");
      await load();
    }} catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Upload failed", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }};

  document.getElementById("resetPh").onclick = async function () {{
    var btn = this;
    if (!window.lanUi.confirm("Restore the built-in night placeholder? Your uploaded JPEG will be removed.")) {{
      return;
    }}
    window.lanUi.clearBanner("msg");
    window.lanUi.setBusy(btn, true, "Restoring…");
    try {{
      await window.lanUi.fetchRes("/schedule/placeholder?camera=" + cam, {{ method: "DELETE" }});
      window.lanUi.showBanner("msg", "info", "Default placeholder active", "");
      await load();
    }} catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Restore failed", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }};

  window.lanUi.resolveCamera().then(function (id) {{
    cam = id || "";
    if (!cam) {{
      window.lanUi.showBanner("msg", "bad", "No camera", "Set cameras: in the pipeline config.");
      return;
    }}
    load();
  }});
}})();
</script>
"""
    return lan_ui.page("Schedule", body, active="schedule", pipe_more=pipe_more)


def _variants_ui(*, pipe_more: list[dict[str, str]] | None = None) -> str:
    status_body = (
        lan_ui.status_placeholder("status", "Loading variants…")
        + lan_ui.stale_hint("var-updated")
        + lan_ui.banner_slot("msg")
    )
    body = f"""
  {lan_ui.page_header("Variants", "Each variant is a crop and privacy layout of the same camera. Drag the cyan crop on the full frame, yellow masks on the output, then <strong>Preview</strong> or <strong>Save</strong>. <strong>Private</strong> is LAN-only (not for the public website). Pick one public variant as the livestream — the website URL stays the same.", kicker=":8090 · crop · masks · livestream")}
  {lan_ui.card("Status", status_body, kind="pipe")}

  {lan_ui.card("Public livestream", '''
  <p class="muted" id="publicLiveSummary">Loading…</p>
  <p class="muted stack-gap">The public website uses one fixed live URL from the camera config. Choosing a different variant only changes <em>which crop</em> is published there — the URL stays the same. Private (LAN-only) variants cannot be selected.</p>
  ''', kind="pipe")}

  {lan_ui.card("Private (LAN-only)", '''
  <p class="muted">Private / LAN-only image — reachable on the home network only (e.g. Home Assistant). Not for the public website or livestream. Click a row to edit crop or privacy masks.</p>
  <div id="privateGallery" class="variant-gallery" role="list"></div>
  ''', kind="pipe")}

  {lan_ui.card("Public variants", '''
  <p class="muted">Crops meant for the public livestream (and extra public templates). Use <strong>Use for public livestream</strong> on exactly one of these.</p>
  <div id="publicGallery" class="variant-gallery" role="list"></div>
  <p class="muted stack-gap">Thumbnails are small previews. Click a row to edit. <strong>Preview</strong> runs only when you click the button (not automatically).</p>
  ''', kind="pipe")}

  {lan_ui.card("New variant", '''
  <div class="row">
    <div>
      <label for="newName">Name</label>
      <input id="newName" type="text" autocomplete="off" placeholder="courtyard" spellcheck="false">
    </div>
    <div>
      <label for="newTemplate">Start from template</label>
      <select id="newTemplate">
        <option value="private">Private — LAN-only full view</option>
        <option value="landscape-public">Public — cropped view with privacy masks</option>
      </select>
    </div>
  </div>
  <p class="muted">Creates a settings file under <code>cameras/&lt;id&gt;/variants/</code>. Image filename is <code>{{name}}.jpg</code>. A private template stays LAN-only. New public variants stay unpublished until publish is enabled.</p>
  <div class="actions">
    <button type="button" id="createBtn" class="primary">Create variant</button>
  </div>
  ''', kind="pipe")}

  <fieldset id="variant-editor">
    <legend>Edit selected variant</legend>
    <p class="fieldset-help">Adjust crop, size, and overlays, then <strong>Preview</strong> or <strong>Save</strong>. The image fills the output size without stretching.</p>
    <label for="variant">Variant</label>
    <select id="variant"></select>
    <p class="muted" id="meta">—</p>
    <label for="description">Description</label>
    <input id="description" type="text" autocomplete="off" placeholder="Optional note">
    <p class="field-help">Optional note — saved in the settings file only.</p>
    <label for="variantUrl">Image URL (LAN)</label>
    <div class="row">
      <div>
        <input id="variantUrl" type="text" readonly autocomplete="off" spellcheck="false">
      </div>
      <div style="flex:0 0 auto">
        <button type="button" id="copyUrl" class="ghost">Copy URL</button>
      </div>
    </div>
  </fieldset>

  <fieldset>
    <legend>Crop</legend>
    <p class="fieldset-help">Which part of the full camera frame to keep. Drag the cyan rectangle on the raw frame below. Set <strong>aspect ratio</strong> to match the output size for a clean cover-fit (no stretch).</p>
    <div class="crop-tools">
      <div>
        <label for="cropMode">Mode</label>
        <select id="cropMode">
          <option value="">(auto from file)</option>
          <option value="full">full — entire camera frame</option>
          <option value="centered">centered — width/height fractions + zoom</option>
          <option value="arbitrary">arbitrary — custom left / top / right / bottom</option>
        </select>
      </div>
      <div>
        <label for="aspect">Aspect ratio</label>
        <input id="aspect" type="text" placeholder="16:9" autocomplete="off">
      </div>
      <button type="button" id="cropFull" class="ghost">Full frame</button>
      <button type="button" id="cropMatchOut" class="ghost">Match output AR</button>
    </div>
    <p class="field-help" id="cropHint">Drag the cyan box to move; pull the corner to resize. Aspect locks when set. Preview, then Save.</p>
    <div class="crop-edit-stage">
      <h2 class="h-inline">Edit crop</h2>
      <p class="muted">Full camera frame (stored original) — drag the cyan rectangle. Output still cover-fits without stretching.</p>
      {lan_ui.preview_img("cropSrc", alt="Full camera original — crop edit surface", width=1280, height=720, loading="lazy", overlay='<div class="crop-layer" id="cropLayer"><div class="crop-box" id="cropBox"><span class="crop-tag">crop</span><span class="crop-handle" aria-hidden="true"></span></div></div>', frame_class="is-sharp")}
    </div>
    <details>
      <summary>Coordinates</summary>
      <div class="row">
        <div>
          <label for="cropLeft">Left</label>
          <input id="cropLeft" type="number" step="0.01" min="0" max="1" inputmode="decimal" placeholder="0–1">
        </div>
        <div>
          <label for="cropTop">Top</label>
          <input id="cropTop" type="number" step="0.01" min="0" max="1" inputmode="decimal" placeholder="0–1">
        </div>
        <div>
          <label for="cropRight">Right</label>
          <input id="cropRight" type="number" step="0.01" min="0" max="1" inputmode="decimal" placeholder="0–1">
        </div>
        <div>
          <label for="cropBottom">Bottom</label>
          <input id="cropBottom" type="number" step="0.01" min="0" max="1" inputmode="decimal" placeholder="0–1">
        </div>
      </div>
      <p class="field-help">Custom crop edges as fractions of the full frame (0 = left/top, 1 = right/bottom). Used in arbitrary mode.</p>
      <div class="row">
        <div>
          <label for="widthFrac">Width fraction</label>
          <input id="widthFrac" type="number" step="0.01" min="0.05" max="1" inputmode="decimal" placeholder="centered">
          <p class="field-help">Centered mode: how much of the frame width to keep (before zoom).</p>
        </div>
        <div>
          <label for="heightFrac">Height fraction</label>
          <input id="heightFrac" type="number" step="0.01" min="0.05" max="1" inputmode="decimal" placeholder="centered">
          <p class="field-help">Centered mode: how much of the frame height to keep (before zoom).</p>
        </div>
        <div>
          <label for="zoom">Zoom</label>
          <input id="zoom" type="number" step="0.05" min="1" max="8" inputmode="decimal" placeholder="≥1">
          <p class="field-help">1 = no zoom. Higher values zoom into the crop center (no stretch). Dragging the box resets zoom to 1.</p>
        </div>
      </div>
    </details>
  </fieldset>

  <fieldset>
    <legend>Output size &amp; quality</legend>
    <p class="fieldset-help">Final image size in pixels. The crop is scaled to fill width × height without stretching. Filename and cloud keys stay locked.</p>
    <div class="row">
      <div>
        <label for="outWidth">Width</label>
        <input id="outWidth" type="number" step="1" min="64" max="7680" inputmode="numeric" placeholder="1600">
        <p class="field-help">Final image width in pixels.</p>
      </div>
      <div>
        <label for="outHeight">Height</label>
        <input id="outHeight" type="number" step="1" min="64" max="7680" inputmode="numeric" placeholder="900">
        <p class="field-help">Final image height in pixels.</p>
      </div>
      <div>
        <label for="jpegQuality">JPEG quality</label>
        <input id="jpegQuality" type="number" step="1" min="1" max="95" inputmode="numeric" placeholder="80">
        <p class="field-help">1 (small file) to 95 (large). Public frames are usually 78–85.</p>
      </div>
    </div>
  </fieldset>

  <fieldset>
    <legend>Privacy masks</legend>
    <p class="fieldset-help">Drag a yellow rectangle on the large image to cover a window. Pull the corner to resize. Labels stay in the settings file — they are not drawn on the public image.</p>
    <div class="mask-tools">
      <button type="button" id="maskAdd">Add mask</button>
      <div>
        <label for="maskMode">Mode</label>
        <select id="maskMode">
          <option value="blur">blur</option>
          <option value="pixelate">pixelate</option>
          <option value="black">black</option>
        </select>
      </div>
      <div>
        <label for="maskStrength">Strength</label>
        <input id="maskStrength" type="number" min="1" max="64" step="1" value="18" inputmode="numeric">
      </div>
      <div class="mask-label-field">
        <label for="maskLabel">Label</label>
        <input id="maskLabel" type="text" maxlength="80" autocomplete="off" placeholder="left dormer">
      </div>
      <button type="button" id="maskDelete" class="ghost">Delete</button>
    </div>
    <p class="field-help" id="maskHint">Click a box to edit it. Click Preview to see the blur, then Save.</p>
    <div class="mask-edit-stage">
      <h2 class="h-inline">Edit masks</h2>
      <p class="muted">Saved / live image — drag boxes here.</p>
      {lan_ui.preview_img("served", alt="Currently served variant JPEG — mask edit surface", width=1280, height=720, loading="lazy", overlay='<div class="mask-layer" id="servedMasks"></div>', frame_class="is-sharp")}
    </div>
    <details>
      <summary>Coordinates</summary>
      <label for="masks">Masks</label>
      <textarea id="masks" rows="6" spellcheck="false" placeholder="0.0,0.45,0.25,0.85,blur,18 # left dormer"></textarea>
      <p class="field-help">One rectangle per line: left,top,right,bottom,mode,strength — optional <code># label</code></p>
    </details>
  </fieldset>

  <details class="advanced-panel" id="variant-advanced">
    <summary>Advanced overlays <span class="muted">(timestamp, site badge, artistic stretch)</span></summary>
    <p class="fieldset-help">Optional timestamp, site badge, and panoramic stretch.</p>

    <fieldset>
      <legend>Timestamp on image</legend>
      <p class="fieldset-help">Capture time in the camera timezone. Cream text with a dark outline.</p>
      <label class="inline"><input id="tsEnabled" type="checkbox"> Enable timestamp</label>
      <div class="row">
        <div>
          <label for="tsPosition">Position</label>
          <select id="tsPosition">
            <option value="bottom-left">bottom-left</option>
            <option value="bottom-right">bottom-right</option>
            <option value="top-left">top-left</option>
            <option value="top-right">top-right</option>
          </select>
        </div>
        <div>
          <label for="tsOpacity">Opacity</label>
          <input id="tsOpacity" type="number" step="0.05" min="0" max="1" inputmode="decimal" placeholder="0.85">
        </div>
        <div>
          <label for="tsFont">Font size</label>
          <input id="tsFont" type="number" step="1" min="8" max="96" inputmode="numeric" placeholder="24">
        </div>
        <div>
          <label for="tsStroke">Stroke</label>
          <input id="tsStroke" type="number" step="1" min="0" max="8" inputmode="numeric" placeholder="2">
          <p class="field-help">Outline width (0 = none).</p>
        </div>
        <div>
          <label for="tsMargin">Margin</label>
          <input id="tsMargin" type="number" step="1" min="0" max="128" inputmode="numeric" placeholder="28">
        </div>
      </div>
    </fieldset>

    <fieldset>
      <legend>Site / temperature badge</legend>
      <p class="fieldset-help">Top-left site name and optional outdoor temperature. Cream text with a dark outline, same as the timestamp.</p>
      <label class="inline"><input id="badgeEnabled" type="checkbox"> Enable site badge</label>
      <div class="row">
        <div>
          <label for="badgeSite">Site name</label>
          <input id="badgeSite" type="text" autocomplete="off" placeholder="example.com">
          <p class="field-help">Hostname shown in the badge.</p>
        </div>
        <div>
          <label class="inline"><input id="badgeTemp" type="checkbox"> Include temperature</label>
          <p class="field-help">Append outdoor °C from the camera weather feed when available.</p>
        </div>
        <div>
          <label for="badgeFont">Font size</label>
          <input id="badgeFont" type="number" step="1" min="10" max="64" inputmode="numeric" placeholder="26">
        </div>
        <div>
          <label for="badgeStroke">Stroke</label>
          <input id="badgeStroke" type="number" step="1" min="0" max="8" inputmode="numeric" placeholder="2">
          <p class="field-help">Outline width (0 = none).</p>
        </div>
        <div>
          <label for="badgeMargin">Margin</label>
          <input id="badgeMargin" type="number" step="1" min="0" max="64" inputmode="numeric" placeholder="28">
        </div>
      </div>
    </fieldset>

    <fieldset>
      <legend>Artistic stretch (optional)</legend>
      <p class="fieldset-help">Optional panoramic look. Leave empty or 1.0 for a normal image.</p>
      <div class="row">
        <div>
          <label for="artStretch">Horizontal stretch</label>
          <input id="artStretch" type="number" step="0.01" min="0.85" max="1.25" inputmode="decimal" placeholder="1.0">
          <p class="field-help">0.85–1.25 (e.g. 1.06 for a mild wide feel).</p>
        </div>
        <div>
          <label for="artCompress">Vertical compress</label>
          <input id="artCompress" type="number" step="0.01" min="0.85" max="1.0" inputmode="decimal" placeholder="1.0">
          <p class="field-help">0.85–1.0 (e.g. 0.96).</p>
        </div>
      </div>
    </fieldset>
  </details>

  <p class="muted preview-hint" id="previewHint">Click <strong>Preview</strong> to try edits without saving. Preview is not automatic — result shows in the compact frame below.</p>
  <div class="preview-secondary">
    <h2 class="h-inline">Preview (unsaved)</h2>
    <p class="muted">Unsaved preview after you click Preview. Edit crop and masks on the large images above.</p>
    {lan_ui.preview_img("preview", alt="Unsaved preview of selected variant", width=640, height=360, loading="lazy")}
  </div>

  <div class="actions actions-sticky">
    <button type="button" id="previewBtn">Preview</button>
    <button type="button" id="save" class="primary">Save</button>
    <button type="button" id="reload" class="ghost">Reload</button>
  </div>

<script>
(function () {{
  var cam = "";
  var currentName = "";
  var currentServedPath = "";
  var currentJpegMtime = "";
  var thumbW = {_GALLERY_THUMB_W};
  var servedW = {_SERVED_PREVIEW_W};
  var cropPreviewW = {_SERVED_PREVIEW_W};
  var maskList = [];
  var maskSelected = -1;
  var writingMasks = false;
  var writingCrop = false;
  var cropBox = {{ left: 0, top: 0, right: 1, bottom: 1 }};
  var cropBound = false;

  function absoluteUrl(path) {{
    var p = path || "";
    if (!p) return "";
    if (p.indexOf("http") === 0) return p;
    var host = location.hostname || "home-webcam.local";
    var port = location.port || "8090";
    return "http://" + host + ":" + port + p;
  }}

  function withQuery(path, params) {{
    if (!path) return "";
    var bits = [];
    Object.keys(params).forEach(function (k) {{
      if (params[k] == null || params[k] === "") return;
      bits.push(encodeURIComponent(k) + "=" + encodeURIComponent(String(params[k])));
    }});
    if (!bits.length) return path;
    return path + (path.indexOf("?") >= 0 ? "&" : "?") + bits.join("&");
  }}

  function numOrNull(id) {{
    var el = document.getElementById(id);
    var v = (el && el.value != null) ? String(el.value).trim() : "";
    if (!v) return null;
    var n = Number(v);
    return Number.isFinite(n) ? n : null;
  }}

  function parseMasks(text) {{
    var lines = String(text || "").split(/\\n+/);
    var out = [];
    for (var i = 0; i < lines.length; i++) {{
      var line = lines[i].trim();
      if (!line || line.charAt(0) === "#") continue;
      var label = "";
      var hash = line.indexOf("#");
      if (hash >= 0) {{
        label = line.slice(hash + 1).trim();
        line = line.slice(0, hash).trim();
      }}
      var parts = line.split(/[,\\s]+/).filter(Boolean);
      if (parts.length < 4) throw new Error("mask line " + (i + 1) + ": need left,top,right,bottom[,mode[,strength]][# label]");
      var item = {{
        type: "rect",
        left: Number(parts[0]),
        top: Number(parts[1]),
        right: Number(parts[2]),
        bottom: Number(parts[3]),
        mode: (parts[4] || "blur").toLowerCase(),
      }};
      if (parts[5] != null) item.strength = Number(parts[5]);
      if (label) item.label = label;
      out.push(item);
    }}
    return out;
  }}

  function formatMasks(masks) {{
    if (!masks || !masks.length) return "";
    return masks.map(function (m) {{
      var bits = [m.left, m.top, m.right, m.bottom, m.mode || "blur"];
      if (m.strength != null) bits.push(m.strength);
      var line = bits.join(",");
      var note = (m.label != null && String(m.label).trim()) ? String(m.label).trim()
        : ((m.note != null && String(m.note).trim()) ? String(m.note).trim() : "");
      if (note) line += " # " + note;
      return line;
    }}).join("\\n");
  }}

  function round4(n) {{
    return Math.round(n * 10000) / 10000;
  }}

  function writeMasks() {{
    writingMasks = true;
    var el = document.getElementById("masks");
    if (el) el.value = formatMasks(maskList);
    writingMasks = false;
  }}

  function syncMaskFields() {{
    var mode = document.getElementById("maskMode");
    var strength = document.getElementById("maskStrength");
    var label = document.getElementById("maskLabel");
    var del = document.getElementById("maskDelete");
    var hint = document.getElementById("maskHint");
    var none = maskSelected < 0 || !maskList[maskSelected];
    if (mode) mode.disabled = none;
    if (strength) strength.disabled = none;
    if (label) label.disabled = none;
    if (del) del.disabled = none;
    if (none) {{
      if (hint) hint.textContent = maskList.length
        ? "Click a box to edit it. Click Preview to see the blur, then Save."
        : "Add a mask, then drag it onto a window. Click Preview to see the blur, then Save.";
      return;
    }}
    var m = maskList[maskSelected];
    if (mode) mode.value = m.mode || "blur";
    if (strength) strength.value = m.strength != null ? m.strength : 18;
    if (label) label.value = m.label || "";
    if (hint) hint.textContent = "Box " + (maskSelected + 1) + " of " + maskList.length + ". Drag to move, corner to resize.";
  }}

  function syncMaskLayerToImage() {{
    /* Size the mask layer to the object-fit:contain content box so % coords match pixels. */
    var img = document.getElementById("served");
    var layer = document.getElementById("servedMasks");
    if (!img || !layer) return;
    var frame = img.closest(".preview-frame");
    if (!frame) return;
    var fw = frame.clientWidth || 0;
    var fh = frame.clientHeight || 0;
    var nw = img.naturalWidth || 0;
    var nh = img.naturalHeight || 0;
    if (fw < 1 || fh < 1) return;
    if (nw < 1 || nh < 1) {{
      layer.style.left = "0";
      layer.style.top = "0";
      layer.style.width = "100%";
      layer.style.height = "100%";
      return;
    }}
    var scale = Math.min(fw / nw, fh / nh);
    var w = nw * scale;
    var h = nh * scale;
    var left = (fw - w) / 2;
    var top = (fh - h) / 2;
    layer.style.left = left + "px";
    layer.style.top = top + "px";
    layer.style.width = w + "px";
    layer.style.height = h + "px";
  }}

  function paintMaskBoxes() {{
    syncMaskLayerToImage();
    document.querySelectorAll(".mask-box").forEach(function (el) {{
      var i = Number(el.getAttribute("data-i"));
      var m = maskList[i];
      if (!m) return;
      el.style.left = (m.left * 100) + "%";
      el.style.top = (m.top * 100) + "%";
      el.style.width = ((m.right - m.left) * 100) + "%";
      el.style.height = ((m.bottom - m.top) * 100) + "%";
      el.classList.toggle("is-selected", i === maskSelected);
      var tag = el.querySelector(".mask-tag");
      if (tag) tag.textContent = (m.label && String(m.label).trim()) ? String(m.label).trim() : ("mask " + (i + 1));
    }});
  }}

  function bindMaskBox(el) {{
    el.addEventListener("pointerdown", function (ev) {{
      if (ev.button != null && ev.button !== 0) return;
      ev.preventDefault();
      ev.stopPropagation();
      var resize = ev.target && ev.target.classList && ev.target.classList.contains("mask-handle");
      var i = Number(el.getAttribute("data-i"));
      maskSelected = i;
      syncMaskFields();
      paintMaskBoxes();
      var frame = el.parentElement.getBoundingClientRect();
      var origin = maskList[i];
      var start = {{
        x: ev.clientX,
        y: ev.clientY,
        left: origin.left,
        top: origin.top,
        right: origin.right,
        bottom: origin.bottom,
      }};
      try {{ el.setPointerCapture(ev.pointerId); }} catch (err) {{}}
      function onMove(e) {{
        var dx = (e.clientX - start.x) / Math.max(frame.width, 1);
        var dy = (e.clientY - start.y) / Math.max(frame.height, 1);
        var next;
        if (resize) {{
          var right = Math.min(1, Math.max(start.left + 0.02, start.right + dx));
          var bottom = Math.min(1, Math.max(start.top + 0.02, start.bottom + dy));
          next = {{ left: start.left, top: start.top, right: right, bottom: bottom }};
        }} else {{
          var w = start.right - start.left;
          var h = start.bottom - start.top;
          var left = start.left + dx;
          var top = start.top + dy;
          if (left < 0) left = 0;
          if (top < 0) top = 0;
          if (left + w > 1) left = 1 - w;
          if (top + h > 1) top = 1 - h;
          next = {{ left: left, top: top, right: left + w, bottom: top + h }};
        }}
        var m = maskList[i];
        m.left = round4(next.left);
        m.top = round4(next.top);
        m.right = round4(next.right);
        m.bottom = round4(next.bottom);
        paintMaskBoxes();
        writeMasks();
      }}
      function onUp() {{
        el.removeEventListener("pointermove", onMove);
        el.removeEventListener("pointerup", onUp);
        el.removeEventListener("pointercancel", onUp);
        writeMasks();
      }}
      el.addEventListener("pointermove", onMove);
      el.addEventListener("pointerup", onUp);
      el.addEventListener("pointercancel", onUp);
    }});
  }}

  function renderMaskLayers() {{
    var layer = document.getElementById("servedMasks");
    if (!layer) return;
    layer.textContent = "";
    syncMaskLayerToImage();
    maskList.forEach(function (m, i) {{
      var box = document.createElement("div");
      box.className = "mask-box" + (i === maskSelected ? " is-selected" : "");
      box.setAttribute("data-i", String(i));
      box.style.left = (m.left * 100) + "%";
      box.style.top = (m.top * 100) + "%";
      box.style.width = ((m.right - m.left) * 100) + "%";
      box.style.height = ((m.bottom - m.top) * 100) + "%";
      var tag = document.createElement("span");
      tag.className = "mask-tag";
      tag.textContent = (m.label && String(m.label).trim()) ? String(m.label).trim() : ("mask " + (i + 1));
      var handle = document.createElement("span");
      handle.className = "mask-handle";
      handle.setAttribute("aria-hidden", "true");
      box.appendChild(tag);
      box.appendChild(handle);
      bindMaskBox(box);
      layer.appendChild(box);
    }});
    syncMaskFields();
  }}

  function loadMaskEditor() {{
    try {{
      maskList = parseMasks(document.getElementById("masks").value);
    }} catch (err) {{
      return;
    }}
    if (maskSelected >= maskList.length) maskSelected = maskList.length ? 0 : -1;
    renderMaskLayers();
  }}

  function applyMaskField(key, value) {{
    if (maskSelected < 0 || !maskList[maskSelected]) return;
    maskList[maskSelected][key] = value;
    writeMasks();
    paintMaskBoxes();
  }}

  function parseAspectRatio(text) {{
    var s = String(text || "").trim();
    if (!s) return null;
    if (/^\\d+(\\.\\d+)?$/.test(s)) {{
      var n = Number(s);
      return n > 0 ? n : null;
    }}
    var parts = s.replace("/", ":").split(":");
    if (parts.length !== 2) return null;
    var a = Number(parts[0]), b = Number(parts[1]);
    if (!Number.isFinite(a) || !Number.isFinite(b) || a <= 0 || b <= 0) return null;
    return a / b;
  }}

  function applyAspectToBox(box, ratio) {{
    if (!ratio || ratio <= 0) return box;
    var left = box.left, top = box.top, right = box.right, bottom = box.bottom;
    var bw = Math.max(0.02, right - left);
    var bh = Math.max(0.02, bottom - top);
    var cur = bw / bh;
    if (cur > ratio) {{
      var nw = bh * ratio;
      left = left + (bw - nw) / 2;
      right = left + nw;
    }} else if (cur < ratio) {{
      var nh = bw / ratio;
      top = top + (bh - nh) / 2;
      bottom = top + nh;
    }}
    if (left < 0) {{ right -= left; left = 0; }}
    if (top < 0) {{ bottom -= top; top = 0; }}
    if (right > 1) {{ left -= (right - 1); right = 1; }}
    if (bottom > 1) {{ top -= (bottom - 1); bottom = 1; }}
    left = Math.max(0, Math.min(left, 0.98));
    top = Math.max(0, Math.min(top, 0.98));
    right = Math.max(left + 0.02, Math.min(right, 1));
    bottom = Math.max(top + 0.02, Math.min(bottom, 1));
    return {{ left: left, top: top, right: right, bottom: bottom }};
  }}

  function computeCropBoxFromForm() {{
    var mode = (document.getElementById("cropMode").value || "").toLowerCase();
    var left = numOrNull("cropLeft");
    var top = numOrNull("cropTop");
    var right = numOrNull("cropRight");
    var bottom = numOrNull("cropBottom");
    var wf = numOrNull("widthFrac");
    var hf = numOrNull("heightFrac");
    var z = numOrNull("zoom") || 1;
    if (z < 1) z = 1;
    if (!mode) {{
      if (left != null || top != null || right != null || bottom != null) mode = "arbitrary";
      else if (wf != null || hf != null || z > 1) mode = "centered";
      else mode = "full";
    }}
    var box;
    if (mode === "full") {{
      box = {{ left: 0, top: 0, right: 1, bottom: 1 }};
    }} else if (mode === "centered") {{
      var w = Math.min(1, Math.max(0.05, (wf != null ? wf : 1) / z));
      var h = Math.min(1, Math.max(0.05, (hf != null ? hf : 1) / z));
      box = {{
        left: (1 - w) / 2,
        top: (1 - h) / 2,
        right: (1 + w) / 2,
        bottom: (1 + h) / 2,
      }};
    }} else {{
      box = {{
        left: left != null ? left : 0,
        top: top != null ? top : 0,
        right: right != null ? right : 1,
        bottom: bottom != null ? bottom : 1,
      }};
      if (z > 1) {{
        var bw = box.right - box.left;
        var bh = box.bottom - box.top;
        var nw = bw / z;
        var nh = bh / z;
        var cx = (box.left + box.right) / 2;
        var cy = (box.top + box.bottom) / 2;
        box = {{ left: cx - nw / 2, top: cy - nh / 2, right: cx + nw / 2, bottom: cy + nh / 2 }};
      }}
    }}
    var ar = parseAspectRatio(document.getElementById("aspect").value);
    box = applyAspectToBox(box, ar);
    box.left = round4(Math.max(0, Math.min(box.left, 0.98)));
    box.top = round4(Math.max(0, Math.min(box.top, 0.98)));
    box.right = round4(Math.max(box.left + 0.02, Math.min(box.right, 1)));
    box.bottom = round4(Math.max(box.top + 0.02, Math.min(box.bottom, 1)));
    return box;
  }}

  function syncCropLayerToImage() {{
    var img = document.getElementById("cropSrc");
    var layer = document.getElementById("cropLayer");
    if (!img || !layer) return;
    var frame = img.closest(".preview-frame");
    if (!frame) return;
    var fw = frame.clientWidth || 0;
    var fh = frame.clientHeight || 0;
    var nw = img.naturalWidth || 0;
    var nh = img.naturalHeight || 0;
    if (fw < 1 || fh < 1) return;
    if (nw < 1 || nh < 1) {{
      layer.style.left = "0";
      layer.style.top = "0";
      layer.style.width = "100%";
      layer.style.height = "100%";
      return;
    }}
    var scale = Math.min(fw / nw, fh / nh);
    var w = nw * scale;
    var h = nh * scale;
    var left = (fw - w) / 2;
    var top = (fh - h) / 2;
    layer.style.left = left + "px";
    layer.style.top = top + "px";
    layer.style.width = w + "px";
    layer.style.height = h + "px";
  }}

  function paintCropBox() {{
    syncCropLayerToImage();
    var el = document.getElementById("cropBox");
    if (!el) return;
    el.style.left = (cropBox.left * 100) + "%";
    el.style.top = (cropBox.top * 100) + "%";
    el.style.width = ((cropBox.right - cropBox.left) * 100) + "%";
    el.style.height = ((cropBox.bottom - cropBox.top) * 100) + "%";
    var hint = document.getElementById("cropHint");
    if (hint) {{
      hint.textContent =
        "Crop " + cropBox.left.toFixed(2) + "," + cropBox.top.toFixed(2) +
        " → " + cropBox.right.toFixed(2) + "," + cropBox.bottom.toFixed(2) +
        ". Drag to move, corner to resize. Preview, then Save.";
    }}
  }}

  function writeCropFieldsFromBox(box, opts) {{
    opts = opts || {{}};
    writingCrop = true;
    var modeEl = document.getElementById("cropMode");
    if (modeEl) modeEl.value = "arbitrary";
    document.getElementById("cropLeft").value = String(round4(box.left));
    document.getElementById("cropTop").value = String(round4(box.top));
    document.getElementById("cropRight").value = String(round4(box.right));
    document.getElementById("cropBottom").value = String(round4(box.bottom));
    if (opts.resetZoom !== false) {{
      var zEl = document.getElementById("zoom");
      if (zEl) zEl.value = "1";
    }}
    writingCrop = false;
  }}

  function refreshCropFromForm() {{
    if (writingCrop) return;
    cropBox = computeCropBoxFromForm();
    paintCropBox();
  }}

  function bindCropBox() {{
    if (cropBound) return;
    var el = document.getElementById("cropBox");
    if (!el) return;
    cropBound = true;
    el.addEventListener("pointerdown", function (ev) {{
      if (ev.button != null && ev.button !== 0) return;
      ev.preventDefault();
      ev.stopPropagation();
      var resize = ev.target && ev.target.classList && ev.target.classList.contains("crop-handle");
      var frame = el.parentElement.getBoundingClientRect();
      var start = {{
        x: ev.clientX,
        y: ev.clientY,
        left: cropBox.left,
        top: cropBox.top,
        right: cropBox.right,
        bottom: cropBox.bottom,
      }};
      var ar = parseAspectRatio(document.getElementById("aspect").value);
      try {{ el.setPointerCapture(ev.pointerId); }} catch (err) {{}}
      function onMove(e) {{
        var dx = (e.clientX - start.x) / Math.max(frame.width, 1);
        var dy = (e.clientY - start.y) / Math.max(frame.height, 1);
        var next;
        if (resize) {{
          var right = Math.min(1, Math.max(start.left + 0.02, start.right + dx));
          var bottom = Math.min(1, Math.max(start.top + 0.02, start.bottom + dy));
          next = {{ left: start.left, top: start.top, right: right, bottom: bottom }};
          if (ar) {{
            var bw = next.right - next.left;
            var bh = next.bottom - next.top;
            if (bw / bh > ar) next.right = next.left + bh * ar;
            else next.bottom = next.top + bw / ar;
            if (next.right > 1) {{
              next.right = 1;
              next.bottom = next.top + (next.right - next.left) / ar;
            }}
            if (next.bottom > 1) {{
              next.bottom = 1;
              next.right = next.left + (next.bottom - next.top) * ar;
            }}
            if (next.right - next.left < 0.02) next.right = next.left + 0.02;
            if (next.bottom - next.top < 0.02) next.bottom = next.top + 0.02;
          }}
        }} else {{
          var w = start.right - start.left;
          var h = start.bottom - start.top;
          var left = start.left + dx;
          var top = start.top + dy;
          if (left < 0) left = 0;
          if (top < 0) top = 0;
          if (left + w > 1) left = 1 - w;
          if (top + h > 1) top = 1 - h;
          next = {{ left: left, top: top, right: left + w, bottom: top + h }};
        }}
        cropBox = {{
          left: round4(next.left),
          top: round4(next.top),
          right: round4(next.right),
          bottom: round4(next.bottom),
        }};
        writeCropFieldsFromBox(cropBox);
        paintCropBox();
      }}
      function onUp() {{
        el.removeEventListener("pointermove", onMove);
        el.removeEventListener("pointerup", onUp);
        el.removeEventListener("pointercancel", onUp);
        writeCropFieldsFromBox(cropBox);
        paintCropBox();
      }}
      el.addEventListener("pointermove", onMove);
      el.addEventListener("pointerup", onUp);
      el.addEventListener("pointercancel", onUp);
    }});
  }}

  function setCropSrcImg() {{
    if (!cam) return;
    var path = "/cameras/" + encodeURIComponent(cam) + "/original.jpg";
    window.lanUi.swapImg(
      "cropSrc",
      withQuery(path, {{ w: cropPreviewW, v: String(Date.now()) }})
    ).then(function () {{
      var img = document.getElementById("cropSrc");
      if (img && img.naturalWidth && img.naturalHeight) {{
        window.lanUi.setPreviewAspect("cropSrc", img.naturalWidth, img.naturalHeight);
      }}
      paintCropBox();
    }}).catch(function () {{
      paintCropBox();
    }});
  }}

  function buildCrop() {{
    var crop = {{}};
    var mode = document.getElementById("cropMode").value;
    if (mode) crop.mode = mode;
    crop.left = numOrNull("cropLeft");
    crop.top = numOrNull("cropTop");
    crop.right = numOrNull("cropRight");
    crop.bottom = numOrNull("cropBottom");
    var wf = numOrNull("widthFrac"), hf = numOrNull("heightFrac"), z = numOrNull("zoom");
    if (wf != null) crop.width_frac = wf;
    if (hf != null) crop.height_frac = hf;
    if (z != null) crop.zoom = z;
    var ar = document.getElementById("aspect").value.trim();
    if (ar) crop.aspect_ratio = ar;
    return crop;
  }}

  function buildOutput() {{
    var out = {{}};
    var w = numOrNull("outWidth"), h = numOrNull("outHeight"), q = numOrNull("jpegQuality");
    if (w != null) out.width = Math.round(w);
    if (h != null) out.height = Math.round(h);
    if (q != null) out.jpeg_quality = Math.round(q);
    return out;
  }}

  function buildTimestamp() {{
    var ts = {{
      enabled: !!(document.getElementById("tsEnabled") && document.getElementById("tsEnabled").checked),
      position: document.getElementById("tsPosition").value || "bottom-left",
    }};
    var op = numOrNull("tsOpacity"), fs = numOrNull("tsFont"), m = numOrNull("tsMargin");
    var sw = numOrNull("tsStroke");
    if (op != null) ts.opacity = op;
    if (fs != null) ts.font_size = Math.round(fs);
    if (m != null) ts.margin = Math.round(m);
    if (sw != null) ts.stroke_width = Math.round(sw);
    return ts;
  }}

  function buildSiteBadge() {{
    var badge = {{
      enabled: !!(document.getElementById("badgeEnabled") && document.getElementById("badgeEnabled").checked),
      site: (document.getElementById("badgeSite").value || "").trim(),
      temperature: !!(document.getElementById("badgeTemp") && document.getElementById("badgeTemp").checked),
    }};
    var fs = numOrNull("badgeFont"), m = numOrNull("badgeMargin");
    var sw = numOrNull("badgeStroke");
    if (fs != null) badge.font_size = Math.round(fs);
    if (m != null) badge.margin = Math.round(m);
    if (sw != null) badge.stroke_width = Math.round(sw);
    return badge;
  }}

  function buildArtistic() {{
    var art = {{}};
    var hs = numOrNull("artStretch"), vc = numOrNull("artCompress");
    if (hs != null) art.horizontal_stretch = hs;
    if (vc != null) art.vertical_compress = vc;
    return art;
  }}

  function buildBody() {{
    var body = {{
      description: (document.getElementById("description").value || "").trim(),
      crop: buildCrop(),
      privacy: {{ masks: parseMasks(document.getElementById("masks").value) }},
      output: buildOutput(),
      timestamp: buildTimestamp(),
      site_badge: buildSiteBadge(),
    }};
    var art = buildArtistic();
    if (Object.keys(art).length) body.artistic = art;
    else body.artistic = {{}};
    return body;
  }}

  function setUrlField(servedPath) {{
    currentServedPath = servedPath || "";
    var url = absoluteUrl(currentServedPath);
    var el = document.getElementById("variantUrl");
    if (el) el.value = url;
  }}

  function setServedImg(path, mtimeNs) {{
    if (!path) return;
    window.lanUi.swapImg(
      "served",
      withQuery(path, {{ w: servedW, v: mtimeNs || "" }})
    ).then(function () {{
      paintMaskBoxes();
    }}).catch(function () {{
      paintMaskBoxes();
    }});
  }}

  function syncPreviewAspectFromForm() {{
    var w = numOrNull("outWidth") || 640;
    var h = numOrNull("outHeight") || 360;
    window.lanUi.setPreviewAspect("served", w, h);
    window.lanUi.setPreviewAspect("preview", w, h);
    paintMaskBoxes();
    paintCropBox();
  }}

  function setPreviewHintVisible(show) {{
    var hint = document.getElementById("previewHint");
    if (!hint) return;
    hint.classList.toggle("is-quiet", !show);
  }}

  function fillForm(payload) {{
    var cfg = payload.config || {{}};
    var meta = payload.meta || {{}};
    var crop = cfg.crop || {{}};
    var out = cfg.output || {{}};
    var ts = cfg.timestamp || {{}};
    var badge = cfg.site_badge || {{}};
    var art = cfg.artistic || {{}};
    document.getElementById("description").value = cfg.description != null ? cfg.description : "";
    document.getElementById("cropMode").value = crop.mode || "";
    document.getElementById("cropLeft").value = crop.left != null ? crop.left : "";
    document.getElementById("cropTop").value = crop.top != null ? crop.top : "";
    document.getElementById("cropRight").value = crop.right != null ? crop.right : "";
    document.getElementById("cropBottom").value = crop.bottom != null ? crop.bottom : "";
    document.getElementById("widthFrac").value = crop.width_frac != null ? crop.width_frac : "";
    document.getElementById("heightFrac").value = crop.height_frac != null ? crop.height_frac : "";
    document.getElementById("zoom").value = crop.zoom != null ? crop.zoom : "";
    document.getElementById("aspect").value = crop.aspect_ratio != null ? crop.aspect_ratio : "";
    document.getElementById("outWidth").value = out.width != null ? out.width : "";
    document.getElementById("outHeight").value = out.height != null ? out.height : "";
    document.getElementById("jpegQuality").value = out.jpeg_quality != null ? out.jpeg_quality : "";
    var masks = (cfg.privacy && cfg.privacy.masks) ? cfg.privacy.masks : [];
    document.getElementById("masks").value = formatMasks(masks);
    maskSelected = -1;
    loadMaskEditor();
    document.getElementById("tsEnabled").checked = !!ts.enabled;
    document.getElementById("tsPosition").value = ts.position || "bottom-left";
    document.getElementById("tsOpacity").value = ts.opacity != null ? ts.opacity : "";
    document.getElementById("tsFont").value = ts.font_size != null ? ts.font_size : "";
    document.getElementById("tsStroke").value = ts.stroke_width != null ? ts.stroke_width : "";
    document.getElementById("tsMargin").value = ts.margin != null ? ts.margin : "";
    document.getElementById("badgeEnabled").checked = !!badge.enabled;
    document.getElementById("badgeSite").value = badge.site != null ? badge.site : "";
    document.getElementById("badgeTemp").checked = badge.temperature !== false;
    document.getElementById("badgeFont").value = badge.font_size != null ? badge.font_size : "";
    document.getElementById("badgeStroke").value = badge.stroke_width != null ? badge.stroke_width : "";
    document.getElementById("badgeMargin").value = badge.margin != null ? badge.margin : "";
    document.getElementById("artStretch").value =
      art.horizontal_stretch != null ? art.horizontal_stretch : "";
    document.getElementById("artCompress").value =
      art.vertical_compress != null ? art.vertical_compress : "";
    var bits = [];
    bits.push((meta.name || "?") + " (" + (meta.visibility || "?") + ")");
    if (meta.filename) bits.push("file " + meta.filename);
    bits.push(meta.publish ? "publish on" : "publish off");
    if (meta.yaml_file) bits.push("settings " + meta.yaml_file);
    if (out.width && out.height) bits.push(out.width + "×" + out.height);
    if (meta.is_public_live) bits.push("public livestream");
    document.getElementById("meta").textContent = bits.join(" · ");
    currentJpegMtime = meta.jpeg_mtime_ns != null ? String(meta.jpeg_mtime_ns) : "";
    syncPreviewAspectFromForm();
    setUrlField(meta.served_url || "");
    setServedImg(meta.served_url || "", currentJpegMtime);
    refreshCropFromForm();
    bindCropBox();
    setCropSrcImg();
  }}

  function updatePublicLiveSummary(pl) {{
    var el = document.getElementById("publicLiveSummary");
    if (!el) return;
    if (!pl) {{
      el.textContent = "No public livestream variant selected yet.";
      return;
    }}
    el.innerHTML =
      "Currently publishing: <strong>" + (pl.variant || "?") + "</strong> → cloud key <code>" +
      (pl.live_key || "?") + "</code> · public path <code>" +
      (pl.public_url_path || "?") + "</code>";
  }}

  async function setPublicLive(name) {{
    if (!window.lanUi.confirm(
      "Use \\"" + name + "\\" for the public livestream? The website URL stays the same; only which crop is published changes."
    )) {{
      return;
    }}
    window.lanUi.clearBanner("msg");
    try {{
      var res = await window.lanUi.fetchJson("/public-live?camera=" + cam, {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{ variant: name, republish: true }}),
        timeoutMs: 60000,
      }});
      updatePublicLiveSummary(res.public_live || res);
      var detail = "Fixed cloud key " + ((res.public_live || res).live_key || "");
      if (res.refresh && res.refresh.ok === false) {{
        window.lanUi.showBanner(
          "msg",
          "ok",
          "Public livestream set to " + name,
          detail + " — republish deferred (next cycle or check publish credentials)."
        );
      }} else {{
        window.lanUi.showBanner(
          "msg",
          "ok",
          "Public livestream set to " + name,
          detail + (res.refresh ? " — republish started." : " — takes effect on the next publish.")
        );
      }}
      await loadList(name);
    }} catch (e) {{
      window.lanUi.showBanner(
        "msg",
        "bad",
        "Could not set public livestream",
        e && e.message ? e.message : String(e)
      );
    }}
  }}

  function isPrivateVariant(v) {{
    return String((v && v.visibility) || "").toLowerCase() === "private";
  }}

  function selectVariant(name) {{
    var sel = document.getElementById("variant");
    if (sel) sel.value = name;
    loadOne(name).catch(function (e) {{
      window.lanUi.showBanner("msg", "bad", "Load failed", e && e.message ? e.message : String(e));
    }});
  }}

  function appendVariantRow(root, v) {{
    var privateFeed = isPrivateVariant(v);
    var row = document.createElement("div");
    row.className =
      "variant-row" +
      (v.name === currentName ? " is-active" : "") +
      (v.is_public_live ? " is-public-live" : "") +
      (privateFeed ? " is-private" : "");
    row.setAttribute("data-name", v.name);
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.setAttribute("aria-pressed", v.name === currentName ? "true" : "false");
    var img = document.createElement("img");
    img.className = "variant-thumb";
    img.alt = "";
    img.width = 120;
    img.height = 68;
    img.loading = "lazy";
    img.decoding = "async";
    if (v.served_url) {{
      img.src = withQuery(v.served_url, {{
        w: thumbW,
        v: v.jpeg_mtime_ns != null ? v.jpeg_mtime_ns : "",
      }});
    }}
    var info = document.createElement("div");
    info.className = "variant-info";
    var titleRow = document.createElement("div");
    titleRow.className = "variant-title-row";
    var title = document.createElement("strong");
    title.textContent = v.name;
    titleRow.appendChild(title);
    if (privateFeed) {{
      var privateBadge = document.createElement("span");
      privateBadge.className = "private-badge";
      privateBadge.textContent = "LAN only";
      titleRow.appendChild(privateBadge);
    }}
    if (v.is_public_live) {{
      var badge = document.createElement("span");
      badge.className = "live-badge";
      badge.textContent = "Public livestream";
      titleRow.appendChild(badge);
    }}
    var meta = document.createElement("p");
    meta.className = "muted";
    if (privateFeed) {{
      meta.textContent =
        "Private · LAN-only · " + (v.filename || "?") + " · not for public website";
    }} else {{
      meta.textContent = "Public · " + (v.filename || "?");
    }}
    var urlLine = document.createElement("code");
    urlLine.textContent = absoluteUrl(v.served_url);
    info.appendChild(titleRow);
    info.appendChild(meta);
    info.appendChild(urlLine);
    // Private never gets "Use for public livestream" (can_be_public_live is false server-side).
    if (!privateFeed && v.can_be_public_live && !v.is_public_live) {{
      var actions = document.createElement("div");
      actions.className = "variant-live-actions";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "primary";
      btn.textContent = "Use for public livestream";
      btn.onclick = function (ev) {{
        ev.stopPropagation();
        setPublicLive(v.name);
      }};
      actions.appendChild(btn);
      info.appendChild(actions);
    }}
    row.appendChild(img);
    row.appendChild(info);
    row.onclick = function () {{ selectVariant(v.name); }};
    row.onkeydown = function (ev) {{
      if (ev.key === "Enter" || ev.key === " ") {{
        ev.preventDefault();
        selectVariant(v.name);
      }}
    }};
    root.appendChild(row);
  }}

  function renderGallery(items) {{
    var privateRoot = document.getElementById("privateGallery");
    var publicRoot = document.getElementById("publicGallery");
    if (!privateRoot || !publicRoot) return;
    privateRoot.innerHTML = "";
    publicRoot.innerHTML = "";
    var list = items || [];
    var privateItems = list.filter(isPrivateVariant);
    var publicItems = list.filter(function (v) {{ return !isPrivateVariant(v); }});
    if (!privateItems.length) {{
      privateRoot.innerHTML =
        '<p class="empty-state">No private LAN-only variants yet.</p>';
    }} else {{
      privateItems.forEach(function (v) {{ appendVariantRow(privateRoot, v); }});
    }}
    if (!publicItems.length) {{
      publicRoot.innerHTML =
        '<p class="empty-state">No public variants yet — create one below from a public template.</p>';
    }} else {{
      publicItems.forEach(function (v) {{ appendVariantRow(publicRoot, v); }});
    }}
  }}

  async function runPreview(opts) {{
    opts = opts || {{}};
    if (!currentName) return;
    var btn = document.getElementById("previewBtn");
    if (!opts.silent) window.lanUi.clearBanner("msg");
    if (btn && !opts.silent) window.lanUi.setBusy(btn, true, "Preview…");
    try {{
      syncPreviewAspectFromForm();
      var body = buildBody();
      var res = await window.lanUi.fetchRes(
        "/variants/" + encodeURIComponent(currentName) + "/preview?camera=" + cam,
        {{
          method: "POST",
          headers: {{"Content-Type": "application/json"}},
          body: JSON.stringify(body),
          timeoutMs: 30000,
        }}
      );
      var blob = await res.blob();
      var objUrl = URL.createObjectURL(blob);
      await window.lanUi.swapImg("preview", objUrl, {{ objectUrl: objUrl }});
      setPreviewHintVisible(false);
      if (!opts.silent) {{
        window.lanUi.showBanner("msg", "info", "Preview ready", "Not saved — click Save to keep these edits.");
      }}
    }} catch (e) {{
      if (!opts.silent) {{
        window.lanUi.showBanner("msg", "bad", "Preview failed", e && e.message ? e.message : String(e));
      }}
    }} finally {{
      if (btn && !opts.silent) window.lanUi.setBusy(btn, false);
    }}
  }}

  async function loadList(prefer) {{
    var statusEl = document.getElementById("status");
    var stamp = document.getElementById("var-updated");
    try {{
      var list = await window.lanUi.fetchJson("/variants?camera=" + cam);
      var sel = document.getElementById("variant");
      var items = list.variants || [];
      var names = items.map(function (v) {{ return v.name; }});
      sel.innerHTML = "";
      names.forEach(function (n) {{
        var opt = document.createElement("option");
        opt.value = n;
        opt.textContent = n;
        sel.appendChild(opt);
      }});
      var pick = prefer || currentName || names[0] || "";
      if (pick && names.indexOf(pick) >= 0) sel.value = pick;
      currentName = sel.value;
      updatePublicLiveSummary(list.public_live);
      renderGallery(items);
      window.lanUi.banner(
        statusEl,
        "ok",
        (list.count || 0) + " variant(s)",
        ""
      );
      window.lanUi.stampUpdated(stamp, true);
      if (currentName) await loadOne(currentName);
    }} catch (e) {{
      window.lanUi.banner(
        statusEl,
        "bad",
        "Could not load variants",
        e && e.message ? e.message : String(e)
      );
      window.lanUi.stampUpdated(stamp, false);
    }}
  }}

  async function loadOne(name) {{
    currentName = name;
    var payload = await window.lanUi.fetchJson("/variants/" + encodeURIComponent(name) + "?camera=" + cam);
    fillForm(payload);
    var rows = document.querySelectorAll(
      "#privateGallery .variant-row, #publicGallery .variant-row"
    );
    for (var i = 0; i < rows.length; i++) {{
      var active = rows[i].getAttribute("data-name") === name;
      rows[i].classList.toggle("is-active", active);
      rows[i].setAttribute("aria-pressed", active ? "true" : "false");
    }}
    // Intentionally no auto dry-run preview — Preview button only (saves Pi CPU).
    setPreviewHintVisible(true);
  }}

  document.getElementById("variant").onchange = async function () {{
    window.lanUi.clearBanner("msg");
    try {{
      await loadOne(this.value);
    }} catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Load failed", e && e.message ? e.message : String(e));
    }}
  }};

  document.getElementById("reload").onclick = async function () {{
    window.lanUi.clearBanner("msg");
    await loadList(currentName);
  }};

  document.getElementById("copyUrl").onclick = async function () {{
    var el = document.getElementById("variantUrl");
    var url = el ? el.value : "";
    if (!url) return;
    try {{
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        await navigator.clipboard.writeText(url);
      }} else {{
        el.focus();
        el.select();
        document.execCommand("copy");
      }}
      window.lanUi.showBanner("msg", "info", "URL copied", url);
    }} catch (e) {{
      window.lanUi.showBanner("msg", "warn", "Copy manually", url);
    }}
  }};

  document.getElementById("createBtn").onclick = async function () {{
    var btn = this;
    window.lanUi.clearBanner("msg");
    var name = (document.getElementById("newName").value || "").trim();
    var template = document.getElementById("newTemplate").value || "private";
    if (!name) {{
      window.lanUi.showBanner("msg", "bad", "Name required", "Use lowercase letters, digits, hyphens.");
      return;
    }}
    window.lanUi.setBusy(btn, true, "Creating…");
    try {{
      var res = await window.lanUi.fetchJson("/variants?camera=" + cam, {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{ name: name, template: template }}),
        timeoutMs: 60000,
      }});
      var created = (res.variant && res.variant.meta && res.variant.meta.name) || name;
      document.getElementById("newName").value = "";
      window.lanUi.showBanner(
        "msg",
        "ok",
        "Created " + created,
        absoluteUrl((res.variant && res.variant.meta && res.variant.meta.served_url) || "")
      );
      await loadList(created);
    }} catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Create failed", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }};

  document.getElementById("previewBtn").onclick = function () {{
    runPreview({{ silent: false }});
  }};

  document.getElementById("maskAdd").onclick = function () {{
    if (maskList.length >= 32) {{
      window.lanUi.showBanner("msg", "bad", "Too many masks", "At most 32 rectangles.");
      return;
    }}
    maskList.push({{
      type: "rect",
      left: 0.35,
      top: 0.35,
      right: 0.65,
      bottom: 0.65,
      mode: "blur",
      strength: 18,
    }});
    maskSelected = maskList.length - 1;
    writeMasks();
    renderMaskLayers();
  }};
  document.getElementById("maskDelete").onclick = function () {{
    if (maskSelected < 0) return;
    maskList.splice(maskSelected, 1);
    if (maskSelected >= maskList.length) maskSelected = maskList.length - 1;
    writeMasks();
    renderMaskLayers();
  }};
  document.getElementById("maskMode").onchange = function () {{
    applyMaskField("mode", this.value || "blur");
  }};
  document.getElementById("maskStrength").onchange = function () {{
    var n = Number(this.value);
    if (!Number.isFinite(n)) return;
    n = Math.max(1, Math.min(64, Math.round(n)));
    this.value = String(n);
    applyMaskField("strength", n);
  }};
  document.getElementById("maskLabel").oninput = function () {{
    applyMaskField("label", this.value);
  }};
  document.getElementById("masks").addEventListener("input", function () {{
    if (writingMasks) return;
    loadMaskEditor();
  }});

  ["cropMode", "cropLeft", "cropTop", "cropRight", "cropBottom", "widthFrac", "heightFrac", "zoom", "aspect"].forEach(function (id) {{
    var el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("change", refreshCropFromForm);
    el.addEventListener("input", refreshCropFromForm);
  }});
  document.getElementById("cropFull").onclick = function () {{
    cropBox = {{ left: 0, top: 0, right: 1, bottom: 1 }};
    var ar = parseAspectRatio(document.getElementById("aspect").value);
    if (ar) cropBox = applyAspectToBox(cropBox, ar);
    writeCropFieldsFromBox(cropBox);
    paintCropBox();
  }};
  document.getElementById("cropMatchOut").onclick = function () {{
    var w = numOrNull("outWidth");
    var h = numOrNull("outHeight");
    if (w && h && w > 0 && h > 0) {{
      document.getElementById("aspect").value = String(Math.round(w)) + ":" + String(Math.round(h));
    }}
    cropBox = applyAspectToBox(cropBox, parseAspectRatio(document.getElementById("aspect").value));
    writeCropFieldsFromBox(cropBox);
    paintCropBox();
  }};

  document.getElementById("save").onclick = async function () {{
    var btn = this;
    window.lanUi.clearBanner("msg");
    if (!currentName) return;
    window.lanUi.setBusy(btn, true, "Saving…");
    try {{
      var body = buildBody();
      await window.lanUi.fetchRes(
        "/variants/" + encodeURIComponent(currentName) + "?camera=" + cam,
        {{
          method: "PUT",
          headers: {{"Content-Type": "application/json"}},
          body: JSON.stringify(body),
          timeoutMs: 60000,
        }}
      );
      window.lanUi.showBanner("msg", "info", "Saved", "Settings written on the Pi · image refresh started.");
      await loadList(currentName);
    }} catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Save failed", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }};

  window.addEventListener("resize", function () {{
    paintMaskBoxes();
    paintCropBox();
  }});

  window.lanUi.resolveCamera().then(function (id) {{
    cam = id || "";
    if (!cam) {{
      window.lanUi.showBanner("msg", "bad", "No camera", "Set cameras: in the pipeline config.");
      return;
    }}
    bindCropBox();
    loadList();
  }});
}})();
</script>
"""
    return lan_ui.page(
        "Variants",
        body,
        active="variants",
        pipe_more=pipe_more,
        # Wide like camera focus — large crop + mask canvases need room.
        extra_head="<style>body.svc-pipe main{max-width:min(80rem,calc(100vw - 2rem))}</style>",
    )


def make_handler(
    state: PipelineState,
    repo_root: Path,
    *,
    refresh_fn: RefreshFn | None = None,
    refresh_min_interval: float = 5.0,
) -> Type[BaseHTTPRequestHandler]:
    lock = threading.Lock()
    last_refresh_at = 0.0
    configured = [str(item) for item in ((state.config or {}).get("cameras") or []) if item]
    camera_id = configured[0] if configured else ""
    pipe_more = variant_menu_items(repo_root, camera_id) or None
    pipe_home_ui = _pipe_home_ui(pipe_more=pipe_more)
    schedule_ui = _schedule_ui(pipe_more=pipe_more)
    variants_ui = _variants_ui(pipe_more=pipe_more)
    setup_page = setup_ui(pipe_more=pipe_more)
    timelapse_page = timelapse_ui(pipe_more=pipe_more)

    def _schedule(camera_id: str) -> PublicSchedule:
        return PublicSchedule(repo_root, camera_id or _primary_camera())

    def _configured_cameras() -> list[str]:
        raw = list((state.config or {}).get("cameras") or [])
        return [str(item) for item in raw if item]

    def _primary_camera() -> str:
        """First configured camera. Used when a request omits ?camera=."""
        ids = _configured_cameras() or list(state.cameras)
        return ids[0] if ids else ""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            # parse_request can call log_error before self.path is set.
            path = getattr(self, "path", "") or ""
            if (
                path.startswith("/health")
                or path.startswith("/system/")
                or path.startswith("/schedule/status")
                or path.startswith("/setup/wifi")
                or "/variants/" in path
                or path.startswith("/timelapse/")
            ):
                return
            super().log_message(fmt, *args)

        def _security_headers(self) -> None:
            # LAN appliance: no CORS (browsers stay same-origin). Light MIME sniffing guard.
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("Referrer-Policy", "no-referrer")

        def _json(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._security_headers()
            self.end_headers()
            self.wfile.write(body)

        def _html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=30")
            self._security_headers()
            self.end_headers()
            self.wfile.write(body)

        def _send_variant_jpeg(self, path: Path, *, max_width: int | None = None) -> None:
            st = path.stat()
            etag = f'W/"{st.st_mtime_ns}-{st.st_size}"'
            if max_width is not None:
                etag = f'W/"{st.st_mtime_ns}-{st.st_size}-w{max_width}"'
            # Gallery thumbs (?w=): short cache + conditional GET.
            # Full-size / HA (?t= cache-bust in package): always send the body.
            # A 304 with empty body fights HA template image refresh.
            qs = parse_qs(urlparse(self.path).query)
            cache_bust = bool(qs.get("t") or qs.get("v"))
            allow_304 = max_width is not None and not cache_bust
            inm = self.headers.get("If-None-Match")
            if allow_304 and inm and inm == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "private, max-age=15")
                self.end_headers()
                return
            data = path.read_bytes()
            if max_width is not None:
                data = downscale_jpeg(data, max_width, quality=70)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            if max_width is not None and not cache_bust:
                self.send_header("Cache-Control", "private, max-age=15")
            else:
                self.send_header("Cache-Control", "no-store")
            self.send_header("ETag", etag)
            self._security_headers()
            self.end_headers()
            self.wfile.write(data)

        def _camera_from_qs(self, parsed) -> str:
            qs = parse_qs(parsed.query)
            return (qs.get("camera") or [_primary_camera()])[0]

        def _read_json_body(self, length: int, *, max_bytes: int = 65536) -> dict[str, Any]:
            if length > max_bytes:
                raise ValueError(f"body too large (max {max_bytes})")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON: {exc}") from exc
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            return body

        def _variants_write_error(self, exc: BaseException) -> bool:
            """Map write failures to JSON responses. Returns True if handled."""
            if isinstance(exc, KeyError):
                self._json(404, {"error": str(exc)})
                return True
            if isinstance(exc, FileNotFoundError):
                self._json(404, {"error": str(exc)})
                return True
            if isinstance(exc, ValueError):
                self._json(400, {"error": str(exc)})
                return True
            if isinstance(exc, OSError):
                self._json(
                    500,
                    {
                        "error": f"could not write YAML: {exc}",
                        "hint": "Ensure webcam can write cameras/ (fix-data-perms + ReadWritePaths)",
                    },
                )
                return True
            return False

        def _variants_refresh(self, cam: str) -> dict[str, Any] | None:
            if refresh_fn is None:
                return None
            try:
                return refresh_fn(cam, force=True, skip_acquire=True)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}

        def _variants_save(self, cam: str, name: str, body: dict[str, Any]) -> None:
            try:
                payload = vedit.save_variant(repo_root, cam, name, body)
            except (KeyError, FileNotFoundError, ValueError, OSError) as exc:
                if self._variants_write_error(exc):
                    return
                raise
            self._json(
                200,
                {
                    "ok": True,
                    "saved": True,
                    "variant": payload,
                    "refresh": self._variants_refresh(cam),
                },
            )

        def _variants_create(self, cam: str, body: dict[str, Any]) -> None:
            try:
                payload = vedit.create_variant(repo_root, cam, body)
            except (KeyError, FileNotFoundError, ValueError, OSError) as exc:
                if self._variants_write_error(exc):
                    return
                raise
            self._json(
                201,
                {
                    "ok": True,
                    "created": True,
                    "variant": payload,
                    "refresh": self._variants_refresh(cam),
                },
            )

        def _timelapse_archive(self, camera_id: str):
            try:
                profile = load_camera_profile(repo_root, camera_id)
            except (FileNotFoundError, ValueError) as exc:
                raise TimelapseError(str(exc)) from exc
            return archive_for(repo_root, camera_id, profile)

        def _timelapse_settings_from_profile(self, profile: Any) -> dict[str, Any]:
            cfg = getattr(profile, "timelapse", None) or {}
            max_gb = cfg.get("max_gb")
            if max_gb is None and cfg.get("max_bytes") is not None:
                max_gb = round(float(cfg["max_bytes"]) / 1024**3, 3)
            if max_gb is None:
                from .timelapse import DEFAULT_MAX_GB as _default_gb

                max_gb = _default_gb
            return {
                "enabled": bool(cfg.get("enabled", True)),
                "max_gb": float(max_gb),
                "retention_days": int(cfg.get("retention_days") or 400),
                "min_interval_seconds": int(cfg.get("min_interval_seconds") or 120),
            }

        def _timelapse_get(self, parsed) -> None:
            cam = self._camera_from_qs(parsed)
            parts = [part for part in parsed.path.split("/") if part]
            qs = parse_qs(parsed.query)
            # ["timelapse"] or ["timelapse", day] or ["timelapse", day, thumb|mp4|gif]
            try:
                profile = load_camera_profile(repo_root, cam)
                archive = archive_for(repo_root, cam, profile)
                if len(parts) == 1:
                    self._json(
                        200,
                        {
                            "camera": cam,
                            "days": archive.list_days(),
                            "storage": archive.storage_info(),
                            "settings": self._timelapse_settings_from_profile(profile),
                            "local_only": True,
                        },
                    )
                    return
                day = parts[1]
                info = archive.describe(day)
                info["error"] = job_error(archive.root, day)
                if len(parts) == 2:
                    self._json(200, info)
                    return
                kind = parts[2]
                if kind == "thumb":
                    thumb = archive.thumb_path(day)
                    if thumb is None:
                        self._json(404, {"error": "no frames"})
                        return
                    self._send_variant_jpeg(thumb, max_width=480)
                    return
                if kind in ("mp4", "gif"):
                    path = archive.export_path(day, kind)
                    if not path.is_file():
                        self._json(404, {"error": "not built yet"})
                        return
                    download = (qs.get("download") or ["0"])[0] in ("1", "true", "yes")
                    filename = f"timelapse-{day}.{kind}"
                    ctype = "video/mp4" if kind == "mp4" else "image/gif"
                    self._send_ranged(
                        path,
                        ctype,
                        download=download,
                        filename=filename if download else None,
                    )
                    return
                self._json(404, {"error": "not found"})
            except (TimelapseError, FileNotFoundError, ValueError) as exc:
                self._json(400, {"error": str(exc)})

        def _send_ranged(
            self,
            path: Path,
            content_type: str,
            *,
            download: bool = False,
            filename: str | None = None,
        ) -> None:
            size = path.stat().st_size
            start, end = 0, size - 1
            status = 200
            header = self.headers.get("Range")
            if header and header.startswith("bytes=") and size:
                spec = header[6:].split(",", 1)[0].strip()
                left, _, right = spec.partition("-")
                try:
                    if left == "":
                        length = int(right)
                        start = max(0, size - length)
                    else:
                        start = int(left)
                        end = int(right) if right else size - 1
                except ValueError:
                    start, end = 0, size - 1
                else:
                    end = min(end, size - 1)
                    if start > end or start >= size:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    status = 206
            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "private, max-age=60")
            if download and filename:
                safe = filename.replace('"', "")
                self.send_header("Content-Disposition", f'attachment; filename="{safe}"')
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                with path.open("rb") as fh:
                    fh.seek(start)
                    remaining = length
                    while remaining:
                        chunk = fh.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path

            if lan_ui.send_favicon(self, path):
                return
            if path == "/":
                self._html(pipe_home_ui)
                return
            if path == "/schedule/ui":
                self._html(schedule_ui)
                return
            if path == "/variants/ui":
                self._html(variants_ui)
                return
            if path == "/setup/ui":
                self._html(setup_page)
                return
            if path == "/timelapse/ui":
                self._html(timelapse_page)
                return
            if path == "/timelapse" or path.startswith("/timelapse/"):
                self._timelapse_get(parsed)
                return
            if path == "/setup":
                cam = self._camera_from_qs(parsed)
                try:
                    self._json(200, read_site(repo_root, cam))
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return
            if path == "/setup/wifi":
                self._json(200, wifi_status())
                return
            if path == "/setup/publish":
                self._json(200, read_publish(state.config or {}, default_env_path()))
                return
            if path == "/setup/wifi/scan":
                try:
                    self._json(200, wifi_scan())
                except WifiError as exc:
                    self._json(400, {"error": str(exc)})
                return
            if path == "/schedule":
                cam = self._camera_from_qs(parsed)
                self._json(200, _schedule(cam).get_config())
                return
            if path == "/schedule/status":
                cam = self._camera_from_qs(parsed)
                self._json(200, _schedule(cam).evaluate().as_dict())
                return
            if path == "/schedule/placeholder.jpg":
                cam = self._camera_from_qs(parsed)
                sched = _schedule(cam)
                status = sched.evaluate()
                badge = None
                brand_name = "Webcam"
                try:
                    profile = load_camera_profile(repo_root, cam)
                    brand_name = profile.display_name or brand_name
                    wx = profile.weather or {}
                    snap = get_weather_cache(
                        url=str(wx.get("url") or DEFAULT_WEATHER_URL),
                        ttl_seconds=float(wx.get("ttl_seconds", 300)),
                        timeout_seconds=float(wx.get("timeout_seconds", 4)),
                    ).get()
                    site = public_site_label(profile)
                    badge = format_site_badge(site, snap.temp_c) if site else None
                except Exception:  # noqa: BLE001
                    badge = None
                data = sched.render_public_placeholder(
                    status, site_badge=badge, brand=brand_name
                ).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return

            if path == "/variants":
                cam = self._camera_from_qs(parsed)
                try:
                    self._json(200, vedit.list_variants(repo_root, cam))
                except FileNotFoundError as exc:
                    self._json(404, {"error": str(exc)})
                return

            if path == "/public-live":
                cam = self._camera_from_qs(parsed)
                try:
                    self._json(200, PublicLiveSelection(repo_root, cam).status())
                except FileNotFoundError as exc:
                    self._json(404, {"error": str(exc)})
                return

            parts = path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "variants" and parts[1] not in ("ui",):
                cam = self._camera_from_qs(parsed)
                name = parts[1]
                try:
                    self._json(200, vedit.get_variant(repo_root, cam, name))
                except KeyError as exc:
                    self._json(404, {"error": str(exc)})
                except FileNotFoundError as exc:
                    self._json(404, {"error": str(exc)})
                return

            if path == "/health":
                payload = state.health()
                payload["schedule"] = _schedule(_primary_camera()).evaluate().as_dict()
                self._json(200, payload)
                return
            if path == "/system/status":
                data_root = Path(state.repo_root) / "data"
                net = network_glance()
                payload = collect_system_status(
                    data_path=data_root if data_root.exists() else None,
                    publish=dict(state.publish_info),
                    network=list(net.get("interfaces") or []),
                )
                if net.get("message"):
                    payload["message"] = net.get("message")
                self._json(200, payload)
                return
            if path == "/system/logs":
                qs = parse_qs(parsed.query)
                raw_lines = (qs.get("lines") or ["40"])[0]
                try:
                    n = int(raw_lines)
                except (TypeError, ValueError):
                    n = 40
                self._json(200, collect_unit_logs(lines=n))
                return
            if path == "/status":
                payload = state.status()
                payload["schedule"] = _schedule(_primary_camera()).evaluate().as_dict()
                self._json(200, payload)
                return
            if path == "/debug":
                payload = state.debug()
                payload["schedule"] = _schedule(_primary_camera()).evaluate().as_dict()
                payload["schedule_ui"] = "GET /schedule/ui (LAN)"
                payload["variants_ui"] = "GET /variants/ui (LAN)"
                payload["public_live_ui"] = "GET /variants/ui (set public live there)"
                try:
                    payload["public_live"] = PublicLiveSelection(
                        repo_root, _primary_camera()
                    ).status()
                except Exception as exc:  # noqa: BLE001
                    payload["public_live"] = {"error": str(exc)}
                self._json(200, payload)
                return

            if (
                len(parts) == 3
                and parts[0] == "cameras"
                and parts[2] == "original.jpg"
            ):
                camera_id = safe_camera_id(parts[1])
                if camera_id is None:
                    self._json(400, {"error": "invalid camera id"})
                    return
                src: Path | None = None
                try:
                    candidate = vedit.original_path(repo_root, camera_id)
                    if candidate.is_file():
                        src = candidate
                except Exception:  # noqa: BLE001
                    src = None
                if src is None:
                    for guess in (
                        repo_root / "data" / camera_id / "original" / "latest.jpg",
                        repo_root / "data" / camera_id / "originals" / "latest.jpg",
                    ):
                        if guess.is_file():
                            src = guess
                            break
                if src is None or not src.is_file():
                    self._json(
                        404,
                        {
                            "error": "original not found",
                            "camera": camera_id,
                            "hint": "Run the pipeline once or POST /refresh to store latest.jpg",
                        },
                    )
                    return
                qs = parse_qs(parsed.query)
                max_w = parse_max_width((qs.get("w") or [None])[0])
                self._send_variant_jpeg(src, max_width=max_w)
                return

            if len(parts) == 4 and parts[0] == "cameras" and parts[2] == "variants":
                camera_id = safe_camera_id(parts[1])
                filename = safe_jpeg_filename(parts[3])
                if camera_id is None or filename is None:
                    self._json(400, {"error": "invalid camera or variant path"})
                    return
                name = filename.rsplit(".", 1)[0]
                variant_path = state.resolve_variant_path(camera_id, name)
                disk_lookup_error: str | None = None
                if variant_path is None:
                    # In-memory map empty/stale — still serve if JPEG exists on disk.
                    try:
                        profile = load_camera_profile(repo_root, camera_id)
                        variants_dir = repo_root / profile.storage["variants_dir"]
                        candidate = variants_dir / filename
                        if candidate.is_file():
                            variant_path = candidate
                        else:
                            for v in profile.variants:
                                out = (v.get("output") or {}).get("filename")
                                if v.get("name") == name and out:
                                    alt = variants_dir / out
                                    if alt.is_file():
                                        variant_path = alt
                                        break
                    except Exception as exc:  # noqa: BLE001
                        disk_lookup_error = str(exc)
                    if variant_path is None:
                        # Conventional layout fallback (profile load may have failed).
                        for guess in (
                            repo_root / "data" / camera_id / "variants" / filename,
                            repo_root / "cameras" / camera_id / "variants" / filename,
                        ):
                            if guess.is_file():
                                variant_path = guess
                                break
                if variant_path is None or not variant_path.is_file():
                    payload: dict[str, Any] = {
                        "error": "variant not found",
                        "camera": camera_id,
                        "requested": filename,
                        "fail_safe": "refusing to invent an image",
                        "next_steps": [
                            "POST /refresh",
                            "GET /debug",
                            "Confirm cameras/<id>/variants/*.yaml output.filename",
                        ],
                    }
                    if disk_lookup_error:
                        payload["detail"] = disk_lookup_error
                    self._json(404, payload)
                    return
                qs = parse_qs(parsed.query)
                max_w = parse_max_width((qs.get("w") or [None])[0])
                self._send_variant_jpeg(variant_path, max_width=max_w)
                return

            private_alias = path.removeprefix("/private/")
            if (
                path.startswith("/private/")
                and private_alias.endswith(".jpg")
                and "/" not in private_alias
            ):
                camera_id = safe_camera_id(private_alias[: -len(".jpg")])
                if camera_id is None:
                    self._json(400, {"error": "invalid camera id"})
                    return
                self.path = f"/cameras/{camera_id}/variants/private.jpg"
                return self.do_GET()

            self._json(
                404,
                {
                    "error": "not found",
                    "endpoints": [
                        "/health",
                        "/status",
                        "/debug",
                        "/favicon.ico",
                        "/favicon.svg",
                        "GET /schedule/ui",
                        "GET|POST /schedule",
                        "GET /variants/ui",
                        "GET /variants",
                        "POST /variants",
                        "GET|PUT /variants/<name>",
                        "POST /variants/<name>/preview",
                        "GET|POST /public-live",
                        "POST /refresh",
                        "POST /system/reboot",
                        "POST /system/poweroff",
                        "POST /system/restart-services",
                        "GET /system/status",
                        "GET /system/logs",
                        "/cameras/<id>/original.jpg",
                        "/cameras/<id>/variants/<file>.jpg",
                        "/private/<id>.jpg",
                    ],
                },
            )

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/schedule/placeholder":
                cam = self._camera_from_qs(parsed)
                _schedule(cam).clear_custom_placeholder()
                self._json(200, {"ok": True, "placeholder": "default"})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            nonlocal last_refresh_at
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            cam = (qs.get("camera") or [_primary_camera()])[0]

            length = int(self.headers.get("Content-Length") or 0)
            parts = path.strip("/").split("/")

            if path.startswith("/timelapse/") and path.endswith("/build"):
                parts = [part for part in path.split("/") if part]
                try:
                    if len(parts) != 3:
                        raise TimelapseError("not found")
                    body = self._read_json_body(length)
                    kind = str(body.get("format") or "mp4")
                    archive = self._timelapse_archive(cam)
                    info = request_build(archive, parts[1], kind)
                    info["error"] = job_error(archive.root, parts[1])
                    self._json(200, info)
                except TimelapseError as exc:
                    self._json(400, {"error": str(exc)})
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return

            if path == "/timelapse/settings":
                try:
                    body = self._read_json_body(length) if length else {}
                    saved = save_site(repo_root, cam, body)
                    self._json(
                        200,
                        {
                            "ok": True,
                            "camera": cam,
                            "settings": {
                                "enabled": saved["timelapse_enabled"],
                                "max_gb": saved["timelapse_max_gb"],
                                "retention_days": saved["timelapse_retention_days"],
                                "min_interval_seconds": saved[
                                    "timelapse_min_interval_seconds"
                                ],
                            },
                        },
                    )
                except ValueError as exc:
                    code = 413 if "too large" in str(exc) else 400
                    self._json(code, {"error": str(exc)})
                return

            if path == "/schedule/placeholder":
                if length > 2_000_000:
                    self._json(413, {"error": "placeholder too large (max 2MB)"})
                    return
                raw = self.rfile.read(length) if length else b""
                try:
                    saved = _schedule(cam).save_placeholder_jpeg(raw)
                    self._json(200, {"ok": True, "path": str(saved)})
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return

            if path == "/setup":
                try:
                    body = self._read_json_body(length)
                    saved = save_site(repo_root, cam, body)
                    # Location lives only in camera.yaml; schedule reads it live — no copy.
                    self._json(200, {"ok": True, **saved})
                except ValueError as exc:
                    code = 413 if "too large" in str(exc) else 400
                    self._json(code, {"error": str(exc)})
                return

            if path == "/setup/cameras":
                try:
                    body = self._read_json_body(length)
                    created = create_camera(
                        repo_root,
                        str(body.get("id") or ""),
                        str(body.get("display_name") or ""),
                    )
                    cams = [str(item) for item in (state.config.get("cameras") or []) if item]
                    if created["camera_id"] not in cams:
                        cams.append(created["camera_id"])
                        state.config["cameras"] = cams
                    self._json(200, {"ok": True, **created})
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return

            if path == "/setup/publish":
                try:
                    body = self._read_json_body(length) if length else {}
                    saved = save_publish(
                        state.config,
                        default_env_path(),
                        body,
                        yaml_paths=pipeline_config_paths(repo_root),
                    )
                    self._json(200, {"ok": True, **saved})
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                except OSError as exc:
                    self._json(400, {"error": f"could not write publish settings: {exc}"})
                return

            if path == "/setup/publish/test":
                try:
                    body = self._read_json_body(length) if length else {}
                    result = probe_publish_connection(
                        state.config,
                        default_env_path(),
                        body,
                    )
                    self._json(200, result)
                except ValueError as exc:
                    self._json(200, {"ok": False, "detail": str(exc)})
                return

            if path == "/setup/wifi":
                try:
                    body = self._read_json_body(length) if length else {}
                    require_confirm(body)
                    # Never log the password; clear local ref after connect.
                    secret = str(body.get("password") or "")
                    result = wifi_connect(str(body.get("ssid") or ""), secret)
                    secret = ""
                    self._json(200, result)
                except SystemOpsError as exc:
                    self._json(400, {"error": str(exc)})
                except WifiError as exc:
                    self._json(400, {"error": str(exc)})
                except ValueError as exc:
                    code = 413 if "too large" in str(exc) else 400
                    self._json(code, {"error": str(exc)})
                return

            if path in ("/system/reboot", "/system/poweroff", "/system/restart-services"):
                try:
                    body = self._read_json_body(length) if length else {}
                    require_confirm(body)
                    if path == "/system/restart-services":
                        result = schedule_restart_services()
                    else:
                        result = schedule_power("reboot" if path.endswith("/reboot") else "poweroff")
                    self._json(202, result)
                except SystemOpsError as exc:
                    self._json(400, {"error": str(exc)})
                except ValueError as exc:
                    code = 413 if "too large" in str(exc) else 400
                    self._json(code, {"error": str(exc)})
                return

            if path == "/schedule":
                try:
                    body = self._read_json_body(length)
                    cfg = _schedule(cam).update_config(body)
                    status = _schedule(cam).evaluate().as_dict()
                    self._json(200, {"ok": True, "config": cfg, "status": status})
                except ValueError as exc:
                    code = 413 if "too large" in str(exc) else 400
                    self._json(code, {"error": str(exc)})
                return

            if path == "/public-live":
                try:
                    body = self._read_json_body(length) if length else {}
                    variant = str(body.get("variant") or "").strip()
                    if not variant:
                        self._json(400, {"error": "variant is required"})
                        return
                    republish = body.get("republish", True)
                    if isinstance(republish, str):
                        republish = republish.strip().lower() in ("1", "true", "yes")
                    pl = PublicLiveSelection(repo_root, cam).set_variant(
                        variant, force_publish=bool(republish)
                    )
                    refresh = None
                    if republish and refresh_fn is not None:
                        try:
                            refresh = refresh_fn(cam, force=True, skip_acquire=True)
                        except Exception as exc:  # noqa: BLE001
                            refresh = {"ok": False, "error": str(exc)}
                    self._json(
                        200,
                        {
                            "ok": True,
                            "public_live": pl,
                            "refresh": refresh,
                        },
                    )
                except KeyError as exc:
                    self._json(404, {"error": str(exc)})
                except ValueError as exc:
                    code = 413 if "too large" in str(exc) else 400
                    self._json(code, {"error": str(exc)})
                except FileNotFoundError as exc:
                    self._json(404, {"error": str(exc)})
                return

            # POST /variants — create from template
            if path == "/variants":
                try:
                    body = self._read_json_body(length)
                except ValueError as exc:
                    code = 413 if "too large" in str(exc) else 400
                    self._json(code, {"error": str(exc)})
                    return
                self._variants_create(cam, body)
                return

            # POST /variants/<name>/preview — dry-run JPEG
            if len(parts) == 3 and parts[0] == "variants" and parts[2] == "preview":
                name = parts[1]
                try:
                    body = self._read_json_body(length) if length else {}
                    data = vedit.preview_jpeg(repo_root, cam, name, body or None)
                except KeyError as exc:
                    self._json(404, {"error": str(exc)})
                    return
                except FileNotFoundError as exc:
                    self._json(404, {"error": str(exc)})
                    return
                except ValueError as exc:
                    code = 413 if "too large" in str(exc) else 400
                    self._json(code, {"error": str(exc)})
                    return
                except Exception as exc:  # noqa: BLE001
                    self._json(500, {"error": str(exc)})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return

            # POST /variants/<name> — same as PUT (save YAML)
            if len(parts) == 2 and parts[0] == "variants" and parts[1] not in ("ui",):
                name = parts[1]
                try:
                    body = self._read_json_body(length)
                except ValueError as exc:
                    code = 413 if "too large" in str(exc) else 400
                    self._json(code, {"error": str(exc)})
                    return
                self._variants_save(cam, name, body)
                return

            if length > 65536:
                self._json(413, {"error": "body too large"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            body: dict[str, Any] = {}
            if raw.strip():
                try:
                    body = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    body = {}

            camera_id = body.get("camera") or (qs.get("camera") or [None])[0]
            if path in ("/refresh", "/regenerate"):
                camera_id = camera_id or _primary_camera()
            elif len(parts) == 3 and parts[0] == "cameras" and parts[2] == "refresh":
                camera_id = parts[1]
            else:
                self._json(404, {"error": "not found", "hint": "POST /refresh, /schedule, or /variants/<name>"})
                return

            if refresh_fn is None:
                self._json(503, {"error": "refresh not available in this mode"})
                return

            now = time.time()
            with lock:
                if now - last_refresh_at < refresh_min_interval:
                    self._json(
                        429,
                        {
                            "error": "refresh rate limited",
                            "retry_after_seconds": refresh_min_interval,
                        },
                    )
                    return
                last_refresh_at = now

            render_only = bool(body.get("render_only")) or (qs.get("render_only") or ["0"])[0] in (
                "1",
                "true",
                "yes",
            )
            force = True
            try:
                result = refresh_fn(
                    camera_id,
                    force=force,
                    skip_acquire=render_only,
                )
                self._json(
                    200 if result.get("ok") else 502,
                    {
                        "ok": bool(result.get("ok")),
                        "camera": camera_id,
                        "mode": "render_only" if render_only else "acquire_and_render",
                        "summary": result.get("summary"),
                        "health": state.health(),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})

        def do_PUT(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            cam = self._camera_from_qs(parsed)
            length = int(self.headers.get("Content-Length") or 0)
            parts = path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "variants" and parts[1] not in ("ui",):
                name = parts[1]
                try:
                    body = self._read_json_body(length)
                except ValueError as exc:
                    code = 413 if "too large" in str(exc) else 400
                    self._json(code, {"error": str(exc)})
                    return
                self._variants_save(cam, name, body)
                return
            self._json(404, {"error": "not found", "hint": "PUT /variants/<name>"})

    return Handler
