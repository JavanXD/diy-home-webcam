"""System Info LAN page — gauges, metrics history, network, logs, power."""

from __future__ import annotations

from shared import lan_ui


def system_info_ui(*, pipe_more: list[dict[str, str]] | None = None) -> str:
    """Full System Info page (nav tab). Host gauges + history charts + ops cards."""
    system_card = f"""
  {lan_ui.banner_slot("sys-msg")}
  <p class="muted">Home network only. Reboot and shut down affect the whole Pi. Restart webcam services leaves the OS running.</p>
  {lan_ui.actions_bar(
      '<button type="button" id="sys-restart" class="primary">Restart webcam services</button>',
      '<button type="button" id="sys-reboot" class="danger">Reboot Pi</button>',
      '<button type="button" id="sys-poweroff" class="danger">Shut down Pi</button>',
  )}
  <p class="field-help">Restart webcam services: <code>webcam-camera</code>, <code>webcam-pipeline</code>, <code>webcam-stream</code>, and <code>nginx</code> when installed. Reboot / shut down use <code>systemctl reboot</code> / <code>poweroff</code>.</p>
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
        "Restart webcam services now?\\n\\nRestarts webcam-camera, webcam-pipeline, webcam-stream, and nginx (if installed). The OS stays up. This page will disconnect for a few seconds.",
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

    health_card = f"""
  {lan_ui.status_placeholder("sys-health", "Loading host status…")}
  <div class="gauge-grid" id="sys-gauge-grid" aria-label="Host and timing gauges"></div>
  <dl class="debug-grid" id="sys-health-grid"></dl>
  <div class="metrics-panel" id="sys-metrics">
    <div class="metrics-toolbar">
      <label class="metrics-field">Refresh
        <select id="sys-metrics-refresh" aria-label="Metrics refresh interval">
          <option value="5000">5 s</option>
          <option value="15000" selected>15 s</option>
          <option value="30000">30 s</option>
        </select>
      </label>
      <label class="metrics-field">Window
        <select id="sys-metrics-window" aria-label="Metrics history window">
          <option value="120">2 min</option>
          <option value="300" selected>5 min</option>
          <option value="600">10 min</option>
        </select>
      </label>
    </div>
    <p class="metrics-subtitle">Host history</p>
    <div class="metrics-toolbar metrics-series">
      <label class="inline metrics-check"><input type="checkbox" id="sys-show-cpu" checked> CPU %</label>
      <label class="inline metrics-check"><input type="checkbox" id="sys-show-temp" checked> Temp °C</label>
      <label class="inline metrics-check"><input type="checkbox" id="sys-show-load"> Load</label>
      <label class="inline metrics-check"><input type="checkbox" id="sys-show-mem"> Memory %</label>
      <label class="inline metrics-check"><input type="checkbox" id="sys-show-swap"> Swap %</label>
      <label class="inline metrics-check"><input type="checkbox" id="sys-show-disk"> Disk write</label>
    </div>
    <svg class="metrics-chart" id="sys-metrics-host" viewBox="0 0 320 120" role="img" aria-label="Host metrics history"></svg>
    <p class="field-help" id="sys-metrics-host-legend">CPU · temp · optional load / memory / swap / disk write</p>
    <p class="metrics-subtitle">Timing history</p>
    <div class="metrics-toolbar metrics-series">
      <label class="inline metrics-check"><input type="checkbox" id="sys-show-age" checked> Frame age</label>
      <label class="inline metrics-check"><input type="checkbox" id="sys-show-capture" checked> Capture</label>
      <label class="inline metrics-check"><input type="checkbox" id="sys-show-cycle"> Pipeline cycle</label>
      <label class="inline metrics-check"><input type="checkbox" id="sys-show-stream"> Stream lag</label>
    </div>
    <svg class="metrics-chart" id="sys-metrics-timing" viewBox="0 0 320 120" role="img" aria-label="Timing metrics history"></svg>
    <p class="field-help" id="sys-metrics-timing-legend">Frame age · capture duration · pipeline cycle · stream Extra lag</p>
  </div>
  {lan_ui.stale_hint("sys-health-updated")}
<script>
(function () {{
  var PREF_KEY = "webcam.sysMetrics";
  var prefs = {{
    refreshMs: 15000, windowSec: 300,
    showCpu: true, showTemp: true, showLoad: false, showMem: false, showSwap: false, showDisk: false,
    showAge: true, showCapture: true, showCycle: false, showStream: false
  }};
  try {{
    var saved = JSON.parse(localStorage.getItem(PREF_KEY) || "{{}}");
    if (saved && typeof saved === "object") Object.keys(prefs).forEach(function (k) {{
      if (saved[k] != null) prefs[k] = saved[k];
    }});
  }} catch (e) {{}}
  function savePrefs() {{
    try {{ localStorage.setItem(PREF_KEY, JSON.stringify(prefs)); }} catch (e) {{}}
  }}
  var DEFAULT_THRESH = {{
    cpu_percent: {{ max: 100, warn: 70, bad: 90, higher_is_bad: true, unit: "%", label: "CPU" }},
    temperature_c: {{ max: 90, warn: 65, bad: 75, higher_is_bad: true, unit: "°C", label: "SoC temp" }},
    mem_used_pct: {{ max: 100, warn: 75, bad: 90, higher_is_bad: true, unit: "%", label: "Memory" }},
    swap_used_pct: {{ max: 100, warn: 10, bad: 40, higher_is_bad: true, unit: "%", label: "Swap" }},
    load_pct: {{ max: 150, warn: 70, bad: 100, higher_is_bad: true, unit: "%", label: "Load" }},
    disk_free_pct: {{ max: 100, warn: 20, bad: 10, higher_is_bad: false, unit: "%", label: "Disk free" }},
    disk_write_mib_s: {{ max: 40, warn: 8, bad: 20, higher_is_bad: true, unit: "MiB/s", label: "Disk write" }},
    frame_age_seconds: {{ max: 10, warn: 2, bad: 5, higher_is_bad: true, unit: "s", label: "Frame age" }},
    capture_duration_seconds: {{ max: 2, warn: 0.8, bad: 1.0, higher_is_bad: true, unit: "s", label: "Capture" }},
    pipeline_cycle_seconds: {{ max: 60, warn: 15, bad: 40, higher_is_bad: true, unit: "s", label: "Pipeline cycle" }},
    stream_lag_seconds: {{ max: 5, warn: 1.0, bad: 3.0, higher_is_bad: true, unit: "s", label: "Stream lag" }}
  }};
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
  function bandKind(value, th) {{
    if (value == null || !th) return "neutral";
    var v = Number(value);
    if (th.higher_is_bad === false) {{
      if (v <= th.bad) return "bad";
      if (v <= th.warn) return "warn";
      return "ok";
    }}
    if (v >= th.bad) return "bad";
    if (v >= th.warn) return "warn";
    return "ok";
  }}
  function healthKind(s) {{
    if (!s) return "warn";
    var m = s.metrics || s.cpu || {{}};
    var th = s.thresholds || m.thresholds || DEFAULT_THRESH;
    var unitsBad = (s.units || []).some(function (u) {{ return u.installed && !u.ok; }});
    var ntpBad = s.clock && s.clock.ntp_synchronized === false;
    var throttleBad = m.throttled === true;
    var bad = unitsBad || ntpBad || throttleBad;
    var warn = false;
    ["cpu_percent", "temperature_c", "mem_used_pct", "swap_used_pct", "load_pct",
     "disk_free_pct", "frame_age_seconds", "capture_duration_seconds"].forEach(function (k) {{
      var val = k === "cpu_percent" ? m.percent : m[k];
      var kind = bandKind(val, th[k]);
      if (kind === "bad") bad = true;
      if (kind === "warn") warn = true;
    }});
    if (bad) return "bad";
    if (warn) return "warn";
    return "ok";
  }}
  function svgEl(name, attrs) {{
    var el = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.keys(attrs || {{}}).forEach(function (k) {{ el.setAttribute(k, attrs[k]); }});
    return el;
  }}
  function polar(cx, cy, r, angleDeg) {{
    var a = (angleDeg - 180) * Math.PI / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  }}
  function arcPath(cx, cy, r, a0, a1) {{
    var p0 = polar(cx, cy, r, a0);
    var p1 = polar(cx, cy, r, a1);
    var large = (a1 - a0) > 180 ? 1 : 0;
    return "M " + p0[0].toFixed(2) + " " + p0[1].toFixed(2) +
      " A " + r + " " + r + " 0 " + large + " 1 " + p1[0].toFixed(2) + " " + p1[1].toFixed(2);
  }}
  function renderGauge(host, key, value, th, fmt) {{
    var card = document.createElement("div");
    card.className = "gauge-card";
    var kind = bandKind(value, th);
    card.classList.add("gauge-" + kind);
    var svg = svgEl("svg", {{ class: "gauge-svg", viewBox: "0 0 120 78", role: "img" }});
    var cx = 60, cy = 62, r = 46;
    var max = Number(th.max) || 100;
    var warn = Number(th.warn);
    var bad = Number(th.bad);
    function toAngle(v) {{
      var n = Math.max(0, Math.min(max, Number(v) || 0));
      return (n / max) * 180;
    }}
    if (th.higher_is_bad === false) {{
      // low is bad: red near 0, green near max
      svg.appendChild(svgEl("path", {{ d: arcPath(cx, cy, r, 0, toAngle(bad)), class: "gauge-zone-bad", fill: "none" }}));
      svg.appendChild(svgEl("path", {{ d: arcPath(cx, cy, r, toAngle(bad), toAngle(warn)), class: "gauge-zone-warn", fill: "none" }}));
      svg.appendChild(svgEl("path", {{ d: arcPath(cx, cy, r, toAngle(warn), 180), class: "gauge-zone-ok", fill: "none" }}));
    }} else {{
      svg.appendChild(svgEl("path", {{ d: arcPath(cx, cy, r, 0, toAngle(warn)), class: "gauge-zone-ok", fill: "none" }}));
      svg.appendChild(svgEl("path", {{ d: arcPath(cx, cy, r, toAngle(warn), toAngle(bad)), class: "gauge-zone-warn", fill: "none" }}));
      svg.appendChild(svgEl("path", {{ d: arcPath(cx, cy, r, toAngle(bad), 180), class: "gauge-zone-bad", fill: "none" }}));
    }}
    svg.appendChild(svgEl("path", {{ d: arcPath(cx, cy, r, 0, 180), class: "gauge-track", fill: "none" }}));
    if (value != null && !isNaN(Number(value))) {{
      var ang = toAngle(value);
      var tip = polar(cx, cy, r - 8, ang);
      svg.appendChild(svgEl("line", {{
        x1: cx, y1: cy, x2: tip[0], y2: tip[1], class: "gauge-needle"
      }}));
      svg.appendChild(svgEl("circle", {{ cx: cx, cy: cy, r: 3.5, class: "gauge-hub" }}));
    }}
    card.appendChild(svg);
    var label = document.createElement("div");
    label.className = "gauge-label";
    label.textContent = th.label || key;
    card.appendChild(label);
    var valEl = document.createElement("div");
    valEl.className = "gauge-value";
    valEl.textContent = value == null || value === "" ? "—" : (fmt ? fmt(value) : (String(value) + (th.unit || "")));
    card.appendChild(valEl);
    host.appendChild(card);
  }}
  function renderThrottleGauge(host, throttled, flags) {{
    var card = document.createElement("div");
    card.className = "gauge-card " + (throttled === true ? "gauge-bad" : (throttled === false ? "gauge-ok" : "gauge-neutral"));
    var svg = svgEl("svg", {{ class: "gauge-svg", viewBox: "0 0 120 78", role: "img" }});
    var cx = 60, cy = 62, r = 46;
    svg.appendChild(svgEl("path", {{
      d: arcPath(cx, cy, r, 0, 180),
      class: throttled === true ? "gauge-zone-bad" : (throttled === false ? "gauge-zone-ok" : "gauge-track"),
      fill: "none"
    }}));
    var ang = throttled === true ? 165 : (throttled === false ? 15 : 90);
    var tip = polar(cx, cy, r - 8, ang);
    svg.appendChild(svgEl("line", {{ x1: cx, y1: cy, x2: tip[0], y2: tip[1], class: "gauge-needle" }}));
    svg.appendChild(svgEl("circle", {{ cx: cx, cy: cy, r: 3.5, class: "gauge-hub" }}));
    card.appendChild(svg);
    var label = document.createElement("div");
    label.className = "gauge-label";
    label.textContent = "Throttle";
    card.appendChild(label);
    var valEl = document.createElement("div");
    valEl.className = "gauge-value";
    if (throttled === true) valEl.textContent = "ACTIVE";
    else if (throttled === false) valEl.textContent = "OK";
    else valEl.textContent = "—";
    card.appendChild(valEl);
    if (flags && flags.length) {{
      var hint = document.createElement("div");
      hint.className = "gauge-hint";
      hint.textContent = flags.slice(0, 2).join(", ");
      card.appendChild(hint);
    }}
    host.appendChild(card);
  }}
  function drawGauges(s) {{
    var host = document.getElementById("sys-gauge-grid");
    if (!host) return;
    host.innerHTML = "";
    var m = s.metrics || s.cpu || {{}};
    var th = s.thresholds || m.thresholds || DEFAULT_THRESH;
    function fmtPct(v) {{ return Number(v).toFixed(v >= 10 ? 0 : 1) + "%"; }}
    function fmtTemp(v) {{ return Number(v).toFixed(1) + " °C"; }}
    function fmtSec(v) {{ return Number(v).toFixed(v >= 10 ? 1 : 2) + " s"; }}
    function fmtMib(v) {{ return Number(v).toFixed(2) + " MiB/s"; }}
    renderGauge(host, "cpu_percent", m.percent, th.cpu_percent || DEFAULT_THRESH.cpu_percent, fmtPct);
    renderGauge(host, "temperature_c", m.temperature_c != null ? m.temperature_c : s.temperature_c, th.temperature_c || DEFAULT_THRESH.temperature_c, fmtTemp);
    renderGauge(host, "load_pct", m.load_pct, th.load_pct || DEFAULT_THRESH.load_pct, fmtPct);
    renderGauge(host, "mem_used_pct", m.mem_used_pct, th.mem_used_pct || DEFAULT_THRESH.mem_used_pct, fmtPct);
    renderGauge(host, "swap_used_pct", m.swap_used_pct, th.swap_used_pct || DEFAULT_THRESH.swap_used_pct, fmtPct);
    renderGauge(host, "disk_free_pct", m.disk_free_pct, th.disk_free_pct || DEFAULT_THRESH.disk_free_pct, fmtPct);
    renderGauge(host, "disk_write_mib_s", m.disk_write_mib_s, th.disk_write_mib_s || DEFAULT_THRESH.disk_write_mib_s, fmtMib);
    renderGauge(host, "frame_age_seconds", m.frame_age_seconds, th.frame_age_seconds || DEFAULT_THRESH.frame_age_seconds, fmtSec);
    renderGauge(host, "capture_duration_seconds", m.capture_duration_seconds, th.capture_duration_seconds || DEFAULT_THRESH.capture_duration_seconds, fmtSec);
    renderGauge(host, "pipeline_cycle_seconds", m.pipeline_cycle_seconds, th.pipeline_cycle_seconds || DEFAULT_THRESH.pipeline_cycle_seconds, fmtSec);
    renderGauge(host, "stream_lag_seconds", m.stream_lag_seconds, th.stream_lag_seconds || DEFAULT_THRESH.stream_lag_seconds, fmtSec);
    renderThrottleGauge(host, m.throttled, m.throttle_flags);
  }}
  function drawChart(svgId, legendId, hist, series, sampleSec) {{
    var svg = document.getElementById(svgId);
    var legend = document.getElementById(legendId);
    if (!svg) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var W = 320, H = 120, padL = 28, padR = 8, padT = 10, padB = 18;
    var plotW = W - padL - padR, plotH = H - padT - padB;
    var now = Date.now() / 1000;
    var win = prefs.windowSec || 300;
    var points = (hist || []).filter(function (p) {{ return p && p.t != null && (now - p.t) <= win; }});
    svg.appendChild(svgEl("rect", {{ x: 0, y: 0, width: W, height: H, class: "metrics-bg" }}));
    var yMax = 100;
    series.forEach(function (s) {{
      if (!s.on) return;
      points.forEach(function (p) {{
        var v = s.get(p);
        if (v != null && v > yMax) yMax = v;
      }});
      if (s.fixedMax) yMax = Math.max(yMax, s.fixedMax);
    }});
    yMax = Math.max(1, Math.ceil(yMax * 1.1));
    var ticks = 4;
    for (var i = 0; i <= ticks; i++) {{
      var frac = i / ticks;
      var y = padT + plotH * (1 - frac);
      var val = Math.round(yMax * frac * 10) / 10;
      svg.appendChild(svgEl("line", {{ x1: padL, y1: y, x2: padL + plotW, y2: y, class: "metrics-grid" }}));
      var lab = svgEl("text", {{ x: padL - 4, y: y + 3, class: "metrics-axis", "text-anchor": "end" }});
      lab.textContent = String(val);
      svg.appendChild(lab);
    }}
    if (!points.length) {{
      var empty = svgEl("text", {{ x: padL + plotW / 2, y: padT + plotH / 2, class: "metrics-empty", "text-anchor": "middle" }});
      empty.textContent = "Collecting samples…";
      svg.appendChild(empty);
      if (legend) legend.textContent = "Samples every ~" + (sampleSec || 5) + " s; chart fills as history arrives.";
      return;
    }}
    var t0 = now - win, t1 = now;
    function xFor(t) {{ return padL + ((t - t0) / (t1 - t0)) * plotW; }}
    function yFor(v) {{
      var n = Math.max(0, Math.min(yMax, Number(v) || 0));
      return padT + plotH * (1 - n / yMax);
    }}
    function polyline(pts, cls) {{
      if (pts.length < 2) return;
      var d = pts.map(function (pt, i) {{ return (i ? "L" : "M") + pt[0].toFixed(1) + " " + pt[1].toFixed(1); }}).join(" ");
      svg.appendChild(svgEl("path", {{ d: d, class: cls, fill: "none" }}));
    }}
    var bits = [];
    series.forEach(function (s) {{
      if (!s.on) return;
      var pts = points.filter(function (p) {{ return s.get(p) != null; }}).map(function (p) {{
        return [xFor(p.t), yFor(s.get(p))];
      }});
      polyline(pts, s.cls);
      bits.push(s.name);
    }});
    var xLab0 = svgEl("text", {{ x: padL, y: H - 4, class: "metrics-axis" }});
    xLab0.textContent = "-" + (win >= 60 ? Math.round(win / 60) + "m" : win + "s");
    svg.appendChild(xLab0);
    var xLab1 = svgEl("text", {{ x: padL + plotW, y: H - 4, class: "metrics-axis", "text-anchor": "end" }});
    xLab1.textContent = "now";
    svg.appendChild(xLab1);
    if (legend) legend.textContent = (bits.join(" · ") || "No series selected") + " · sample ~" + (sampleSec || 5) + "s";
  }}
  function drawCharts(m) {{
    var hist = (m && m.history) || [];
    var cores = (m && m.cpu_count) || 4;
    drawChart("sys-metrics-host", "sys-metrics-host-legend", hist, [
      {{ name: "CPU %", on: prefs.showCpu, cls: "metrics-line-cpu", get: function (p) {{ return p.cpu; }}, fixedMax: 100 }},
      {{ name: "Temp °C", on: prefs.showTemp, cls: "metrics-line-temp", get: function (p) {{ return p.temp; }}, fixedMax: 90 }},
      {{ name: "Load", on: prefs.showLoad, cls: "metrics-line-load", get: function (p) {{
        return p.load1 == null ? null : Math.min(150, (p.load1 / cores) * 100);
      }} }},
      {{ name: "Memory %", on: prefs.showMem, cls: "metrics-line-mem", get: function (p) {{ return p.mem_pct; }}, fixedMax: 100 }},
      {{ name: "Swap %", on: prefs.showSwap, cls: "metrics-line-swap", get: function (p) {{ return p.swap_pct; }}, fixedMax: 100 }},
      {{ name: "Disk write MiB/s", on: prefs.showDisk, cls: "metrics-line-disk", get: function (p) {{
        return p.disk_write_bps == null ? null : p.disk_write_bps / (1024 * 1024);
      }} }}
    ], m && m.sample_interval_seconds);
    drawChart("sys-metrics-timing", "sys-metrics-timing-legend", hist, [
      {{ name: "Frame age s", on: prefs.showAge, cls: "metrics-line-age", get: function (p) {{ return p.frame_age; }} }},
      {{ name: "Capture s", on: prefs.showCapture, cls: "metrics-line-capture", get: function (p) {{ return p.capture_s; }} }},
      {{ name: "Cycle s", on: prefs.showCycle, cls: "metrics-line-cycle", get: function (p) {{ return p.cycle_s; }} }},
      {{ name: "Stream lag s", on: prefs.showStream, cls: "metrics-line-stream", get: function (p) {{ return p.stream_lag; }} }}
    ], m && m.sample_interval_seconds);
  }}
  async function loadSystemHealth() {{
    var box = document.getElementById("sys-health");
    var dl = document.getElementById("sys-health-grid");
    var stamp = document.getElementById("sys-health-updated");
    if (!box || !dl) return;
    try {{
      var s = await window.lanUi.fetchJson("/system/status");
      var m = s.metrics || s.cpu || {{}};
      var kind = healthKind(s);
      var title = kind === "ok" ? "Host OK" : (kind === "bad" ? "Host issues" : "Host warn");
      var detail = diskLine(s.disks);
      if (s.temperature_c != null) detail = (detail ? detail + " · " : "") + s.temperature_c + " °C";
      if (m.percent != null) detail = (detail ? detail + " · " : "") + m.percent + "% CPU";
      if (m.frame_age_seconds != null) detail = (detail ? detail + " · " : "") + "age " + Number(m.frame_age_seconds).toFixed(2) + "s";
      window.lanUi.banner(box, kind, title, detail || "");
      dl.innerHTML = "";
      row(dl, "Disk", diskLine(s.disks));
      row(dl, "SoC temp", s.temperature_c != null ? (s.temperature_c + " °C") : null);
      row(dl, "CPU", m.percent != null ? (m.percent + "%") : null);
      row(dl, "Load", m.load_1 != null
        ? (m.load_1 + " / " + (m.load_5 != null ? m.load_5 : "–") + " / " + (m.load_15 != null ? m.load_15 : "–") +
          (m.cpu_count ? (" (" + m.cpu_count + " cores)") : ""))
        : null);
      row(dl, "Memory", m.mem_used_pct != null ? (m.mem_used_pct + "% used") : null);
      row(dl, "Swap", m.swap_used_pct != null ? (m.swap_used_pct + "% used") : null);
      row(dl, "Disk write", m.disk_write_mib_s != null ? (m.disk_write_mib_s + " MiB/s") : null);
      row(dl, "Frame age", m.frame_age_seconds != null ? (Number(m.frame_age_seconds).toFixed(2) + " s") : null);
      row(dl, "Capture", m.capture_duration_seconds != null ? (Number(m.capture_duration_seconds).toFixed(2) + " s") : null);
      row(dl, "Pipeline cycle", m.pipeline_cycle_seconds != null ? (Number(m.pipeline_cycle_seconds).toFixed(2) + " s") : null);
      row(dl, "Stream lag", m.stream_lag_seconds != null ? (Number(m.stream_lag_seconds).toFixed(2) + " s") : null);
      row(dl, "Failed captures", m.failed_captures != null ? m.failed_captures : null);
      if (m.service_cpu) {{
        var svc = m.service_cpu;
        var svcBits = ["webcam-camera", "webcam-pipeline", "webcam-stream"].map(function (n) {{
          return svc[n] != null ? (n.replace("webcam-", "") + " " + svc[n] + "%") : null;
        }}).filter(Boolean);
        row(dl, "Service CPU", svcBits.length ? svcBits.join(" · ") : null);
      }}
      row(dl, "Throttle", m.throttled === true
        ? ("ACTIVE" + (m.throttle_hex ? " " + m.throttle_hex : ""))
        : (m.throttled === false ? "OK" : null));
      row(dl, "Units", unitLine(s.units));
      row(dl, "R2 publish", publishLine(s.publish));
      row(dl, "Clock", clockLine(s.clock));
      drawGauges(s);
      drawCharts(m);
      window.lanUi.stampUpdated(stamp, true);
    }} catch (e) {{
      window.lanUi.banner(box, "bad", "Host status unreachable", String(e && e.message ? e.message : e));
      window.lanUi.stampUpdated(stamp, false);
    }}
  }}
  var timer = null;
  function pollMs() {{ return prefs.refreshMs || 15000; }}
  function tick() {{ if (!document.hidden) loadSystemHealth(); }}
  function startPoll() {{ stopPoll(); timer = setInterval(tick, pollMs()); }}
  function stopPoll() {{ if (timer) {{ clearInterval(timer); timer = null; }} }}
  function bindControls() {{
    var refresh = document.getElementById("sys-metrics-refresh");
    var win = document.getElementById("sys-metrics-window");
    if (refresh) {{
      refresh.value = String(prefs.refreshMs);
      refresh.addEventListener("change", function () {{
        prefs.refreshMs = Number(refresh.value) || 15000;
        savePrefs(); startPoll(); tick();
      }});
    }}
    if (win) {{
      win.value = String(prefs.windowSec);
      win.addEventListener("change", function () {{
        prefs.windowSec = Number(win.value) || 300;
        savePrefs(); tick();
      }});
    }}
    function wire(id, key) {{
      var el = document.getElementById(id);
      if (!el) return;
      el.checked = !!prefs[key];
      el.addEventListener("change", function () {{ prefs[key] = !!el.checked; savePrefs(); tick(); }});
    }}
    wire("sys-show-cpu", "showCpu");
    wire("sys-show-temp", "showTemp");
    wire("sys-show-load", "showLoad");
    wire("sys-show-mem", "showMem");
    wire("sys-show-swap", "showSwap");
    wire("sys-show-disk", "showDisk");
    wire("sys-show-age", "showAge");
    wire("sys-show-capture", "showCapture");
    wire("sys-show-cycle", "showCycle");
    wire("sys-show-stream", "showStream");
  }}
  document.addEventListener("visibilitychange", function () {{
    if (document.hidden) stopPoll();
    else {{ tick(); startPoll(); }}
  }});
  bindControls();
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
  function tick() {{ if (!document.hidden) loadNet(); }}
  function startPoll() {{ if (!timer) timer = setInterval(tick, pollMs); }}
  function stopPoll() {{ if (timer) {{ clearInterval(timer); timer = null; }} }}
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
  <p class="field-help">Last ~40 lines from <code>webcam-camera</code>, <code>webcam-pipeline</code>, and <code>webcam-stream</code> only (read-only).</p>
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

    units_card = f"""
  {lan_ui.status_placeholder("sys-units", "Loading services…")}
  <div class="unit-pills" id="sys-unit-pills"></div>
  <dl class="debug-grid" id="sys-units-grid"></dl>
<script>
(function () {{
  async function loadUnits() {{
    var box = document.getElementById("sys-units");
    var pills = document.getElementById("sys-unit-pills");
    var dl = document.getElementById("sys-units-grid");
    if (!box || !pills || !dl) return;
    try {{
      var s = await window.lanUi.fetchJson("/system/status");
      var units = s.units || [];
      var bad = units.some(function (u) {{ return u.installed && !u.ok; }});
      var kind = bad ? "bad" : "ok";
      window.lanUi.banner(box, kind, bad ? "Service issues" : "Services", units.length + " units");
      pills.innerHTML = "";
      dl.innerHTML = "";
      units.forEach(function (u) {{
        var pill = document.createElement("span");
        var state = u.installed === false ? "missing" : (u.ok ? "active" : (u.active || "down"));
        pill.className = "unit-pill unit-" + (u.ok ? "ok" : (u.installed ? "bad" : "neutral"));
        pill.textContent = (u.name || "?") + " · " + state;
        pills.appendChild(pill);
        var dt = document.createElement("dt");
        dt.textContent = u.name || u.unit;
        var dd = document.createElement("dd");
        dd.textContent = u.installed === false ? "not installed" : ((u.active || "?") + (u.sub_state ? (" / " + u.sub_state) : ""));
        dl.appendChild(dt);
        dl.appendChild(dd);
      }});
    }} catch (e) {{
      window.lanUi.banner(box, "bad", "Services unreachable", String(e && e.message ? e.message : e));
    }}
  }}
  loadUnits();
  setInterval(function () {{ if (!document.hidden) loadUnits(); }}, 30000);
}})();
</script>
"""

    body = f"""
  {lan_ui.page_header("System Info", "Host gauges, performance history, network, logs, and power — pipeline service on :8090.", title_suffix=" " + lan_ui.pill("8090"), kicker=":8090 · health · metrics")}
  {lan_ui.card("Host & timing", health_card, kind="pipe")}
  {lan_ui.card("Services", units_card, kind="pipe")}
  {lan_ui.card("Network", network_card, kind="pipe")}
  {lan_ui.card("Recent logs", logs_card, kind="pipe")}
  {lan_ui.card("Power", system_card, kind="pipe")}
"""
    return lan_ui.page("System Info", body, active="system-info", pipe_more=pipe_more)
