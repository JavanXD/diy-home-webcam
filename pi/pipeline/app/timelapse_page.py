"""LAN page for days stored on the Pi. Nothing here is uploaded."""

from __future__ import annotations

from shared import lan_ui

from .timelapse import DEFAULT_MAX_GB, GIF_FPS, GIF_WIDTH, MP4_FPS, MP4_WIDTH


def timelapse_ui(*, pipe_more: list[dict[str, str]] | None = None) -> str:
    day_card = f"""
  <p id="tl-meta" class="muted">Pick a day. Frames are saved about every 2 minutes while the public schedule is online, then played at {MP4_FPS} frames per second — a full day is about half a minute.</p>
  <div id="tl-stage" class="tl-stage" hidden>
    <div id="tl-thumb-frame" class="preview-frame tl-media" style="aspect-ratio: 16 / 9" hidden>
      <img id="tl-thumb" class="preview" alt="Last frame for this day" hidden>
    </div>
    <div id="tl-video-frame" class="preview-frame tl-media" style="aspect-ratio: 16 / 9" hidden>
      <video id="tl-video" controls playsinline muted hidden></video>
    </div>
  </div>
  <div class="actions">
    <button type="button" id="tl-mp4" disabled>Make video</button>
    <a id="tl-dl-mp4" class="btn ghost" hidden download>Download video</a>
    <button type="button" id="tl-gif-btn" class="ghost" disabled>Make GIF</button>
    <a id="tl-dl-gif" class="btn ghost" hidden download>Download GIF</a>
    <button type="button" id="tl-delete" class="danger" disabled>Delete day…</button>
  </div>
"""
    storage_card = f"""
  <p id="tl-storage" class="muted">Loading storage…</p>
  <div class="tl-meter" aria-hidden="true">
    <div id="tl-meter-fill" class="tl-meter-fill" style="width:0%"></div>
  </div>
  <p id="tl-storage-pct" class="muted tl-storage-pct"></p>
  <label class="inline"><input type="checkbox" id="tl-enabled" checked> Save daylight frames</label>
  <p class="field-help">When off, no new frames are stored. Existing days stay until pruned.</p>
  <div class="row">
    <div>
      <label for="tl-max-gb">Budget (GB)</label>
      <input id="tl-max-gb" type="number" min="1" max="2000" step="1" inputmode="decimal" value="{DEFAULT_MAX_GB:g}">
    </div>
    <div>
      <label for="tl-retention">Keep days</label>
      <input id="tl-retention" type="number" min="7" max="5000" step="1" inputmode="numeric" value="400">
    </div>
  </div>
  <label for="tl-interval">Frame interval (seconds)</label>
  <input id="tl-interval" type="number" min="30" max="3600" step="1" inputmode="numeric" value="120">
  <p class="field-help">How often a new daylight frame is kept while the public schedule is online (default 120). Oldest days are deleted when the archive is over budget or past keep-days. Also in <code>camera.yaml</code> under <code>timelapse</code>.</p>
  <div class="actions">
    <button type="button" id="tl-save-settings" class="primary">Save archive settings</button>
  </div>
  <p class="muted">The video ({MP4_WIDTH} px, H.264, muted) is best for watching. The GIF is a smaller {GIF_WIDTH} px copy at {GIF_FPS} fps. Neither file is uploaded.</p>
"""
    body = f"""
  {lan_ui.page_header(
      "Timelapse",
      "Daylight frames stay on this Pi. The public site still gets only the current live picture.",
      kicker=":8090 · local",
  )}
  {lan_ui.banner_slot("tl-banner")}
  {lan_ui.card("Storage on this Pi", storage_card, kind="pipe")}
  <div class="row">
    <div>
      {lan_ui.card("History", '''
  <p class="muted tl-history-hint">Newest first. Pick a day to preview or export.</p>
  <p id="tl-empty" class="muted">Loading days…</p>
  <div id="tl-days" class="tl-day-list" role="listbox" aria-label="Timelapse history"></div>
''', kind="pipe")}
    </div>
    <div>
      {lan_ui.card("This day", day_card, kind="pipe")}
    </div>
  </div>
<script>
(function () {{
  var day = "";
  var poll = null;
  function camQuery() {{
    var q = new URLSearchParams(location.search).get("camera");
    return q ? ("?camera=" + encodeURIComponent(q)) : "";
  }}
  function withCam(extra) {{
    var base = camQuery();
    if (!extra) return base;
    return base ? (base + "&" + extra) : ("?" + extra);
  }}
  function show(kind, title, detail) {{
    window.lanUi.showBanner("tl-banner", kind, title, detail || "");
  }}
  function paintStorage(storage) {{
    var el = document.getElementById("tl-storage");
    var fill = document.getElementById("tl-meter-fill");
    var pctEl = document.getElementById("tl-storage-pct");
    if (!storage) {{
      el.textContent = "Storage: unknown";
      fill.style.width = "0%";
      pctEl.textContent = "";
      return;
    }}
    var used = storage.used_human || "?";
    var limit = storage.max_human || null;
    var pct = typeof storage.used_pct === "number" ? storage.used_pct : null;
    if (limit && pct != null) {{
      el.textContent = used + " of " + limit + " archive budget";
      var w = Math.max(0, Math.min(100, pct));
      fill.style.width = w + "%";
      fill.classList.toggle("is-high", w >= 85);
      pctEl.textContent = (w < 0.1 && w > 0 ? "<0.1" : String(Math.round(w * 10) / 10)) + "% used";
    }} else if (limit) {{
      el.textContent = used + " of " + limit + " archive budget";
      fill.style.width = "0%";
      pctEl.textContent = "";
    }} else {{
      el.textContent = "Using " + used + " (no size budget set)";
      fill.style.width = "0%";
      pctEl.textContent = "";
    }}
  }}
  function paintSettings(settings) {{
    if (!settings) return;
    var en = document.getElementById("tl-enabled");
    if (en) en.checked = settings.enabled !== false;
    var maxGb = document.getElementById("tl-max-gb");
    if (maxGb && settings.max_gb != null) maxGb.value = settings.max_gb;
    var ret = document.getElementById("tl-retention");
    if (ret && settings.retention_days != null) ret.value = settings.retention_days;
    var iv = document.getElementById("tl-interval");
    if (iv && settings.min_interval_seconds != null) iv.value = settings.min_interval_seconds;
  }}
  function setMedia(info) {{
    var video = document.getElementById("tl-video");
    var thumb = document.getElementById("tl-thumb");
    var thumbFrame = document.getElementById("tl-thumb-frame");
    var videoFrame = document.getElementById("tl-video-frame");
    var stage = document.getElementById("tl-stage");
    var dlMp4 = document.getElementById("tl-dl-mp4");
    var dlGif = document.getElementById("tl-dl-gif");
    var bust = "t=" + Date.now();
    var showVideo = !!info.mp4;
    var showThumb = !!info.frames && !showVideo;
    stage.hidden = !(showVideo || showThumb);
    thumbFrame.hidden = !showThumb;
    thumb.hidden = !showThumb;
    if (showThumb) {{
      thumb.src = "/timelapse/" + info.day + "/thumb" + withCam(bust);
      thumb.onload = function () {{
        if (thumb.naturalWidth && thumb.naturalHeight) {{
          window.lanUi.setPreviewAspect(thumb, thumb.naturalWidth, thumb.naturalHeight);
          videoFrame.style.aspectRatio = thumb.naturalWidth + " / " + thumb.naturalHeight;
        }}
      }};
    }}
    videoFrame.hidden = !showVideo;
    video.hidden = !showVideo;
    if (showVideo) {{
      var src = "/timelapse/" + info.day + "/mp4" + withCam(bust);
      if (video.getAttribute("data-src") !== src) {{
        video.setAttribute("data-src", src);
        video.src = src;
      }}
      video.onloadedmetadata = function () {{
        if (video.videoWidth && video.videoHeight) {{
          videoFrame.style.aspectRatio = video.videoWidth + " / " + video.videoHeight;
        }}
      }};
    }}
    dlMp4.hidden = !info.mp4;
    dlGif.hidden = !info.gif;
    if (info.mp4) {{
      dlMp4.href = "/timelapse/" + info.day + "/mp4" + withCam("download=1");
      dlMp4.setAttribute("download", "timelapse-" + info.day + ".mp4");
    }}
    if (info.gif) {{
      dlGif.href = "/timelapse/" + info.day + "/gif" + withCam("download=1");
      dlGif.setAttribute("download", "timelapse-" + info.day + ".gif");
    }}
  }}
  function paint(info) {{
    day = info.day;
    var meta = document.getElementById("tl-meta");
    var mp4 = document.getElementById("tl-mp4");
    var gifBtn = document.getElementById("tl-gif-btn");
    var delBtn = document.getElementById("tl-delete");
    var busy = info.building === "mp4" || info.building === "gif";
    meta.textContent = info.frames
      ? (info.frames + " frames, " + info.first + "–" + info.last + (busy ? ". Making the " + info.building + "…" : "."))
      : "No frames for this day.";
    mp4.disabled = busy || info.frames < 2;
    gifBtn.disabled = busy || info.frames < 2;
    delBtn.disabled = busy || !info.day || !(info.frames > 0 || info.mp4 || info.gif);
    mp4.textContent = info.mp4 ? "Rebuild video" : "Make video";
    gifBtn.textContent = info.gif ? "Rebuild GIF" : "Make GIF";
    setMedia(info);
    if (busy) startPoll(); else stopPoll();
  }}
  function clearDayView() {{
    day = "";
    stopPoll();
    document.getElementById("tl-meta").textContent = "Pick a day. Frames are saved about every 2 minutes while the public schedule is online, then played at {MP4_FPS} frames per second — a full day is about half a minute.";
    document.getElementById("tl-mp4").disabled = true;
    document.getElementById("tl-gif-btn").disabled = true;
    document.getElementById("tl-delete").disabled = true;
    document.getElementById("tl-mp4").textContent = "Make video";
    document.getElementById("tl-gif-btn").textContent = "Make GIF";
    document.getElementById("tl-stage").hidden = true;
    document.getElementById("tl-dl-mp4").hidden = true;
    document.getElementById("tl-dl-gif").hidden = true;
    var video = document.getElementById("tl-video");
    video.removeAttribute("data-src");
    video.removeAttribute("src");
  }}
  function formatDayLabel(iso) {{
    var parts = String(iso || "").split("-");
    if (parts.length !== 3) return iso;
    var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("en-GB", {{
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric"
    }});
  }}
  function formatPlayback(frames, fps) {{
    var n = Number(frames) || 0;
    var rate = Number(fps) || {MP4_FPS};
    if (n < 2 || rate <= 0) return "";
    var secs = Math.round(n / rate);
    if (secs < 60) return "~" + secs + "s playback";
    var m = Math.floor(secs / 60);
    var s = secs % 60;
    return s ? "~" + m + "m " + s + "s playback" : "~" + m + "m playback";
  }}
  function dayMeta(info) {{
    var bits = [];
    var n = Number(info.frames) || 0;
    bits.push(n === 1 ? "1 frame" : n + " frames");
    var play = formatPlayback(n, info.mp4_fps);
    if (play) bits.push(play);
    else if (info.first && info.last && info.first !== info.last) {{
      bits.push(info.first.slice(0, 5) + "–" + info.last.slice(0, 5));
    }}
    if (info.mp4) bits.push("video ready");
    else if (info.gif) bits.push("GIF ready");
    return bits.join(" · ");
  }}
  async function loadDays(selectDay) {{
    var data = await window.lanUi.fetchJson("/timelapse" + camQuery());
    paintStorage(data.storage);
    paintSettings(data.settings);
    var host = document.getElementById("tl-days");
    var empty = document.getElementById("tl-empty");
    var hint = document.querySelector(".tl-history-hint");
    host.innerHTML = "";
    var days = data.days || [];
    empty.hidden = days.length > 0;
    if (hint) hint.hidden = days.length === 0;
    empty.textContent = days.length ? "" : "No days yet. Frames are saved about every 2 minutes while the public schedule is online.";
    var active = selectDay || day;
    days.forEach(function (info) {{
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tl-day-row" + (info.day === active ? " is-selected" : "");
      btn.setAttribute("role", "option");
      btn.setAttribute("aria-selected", info.day === active ? "true" : "false");
      var label = document.createElement("span");
      label.className = "tl-day-label";
      label.textContent = formatDayLabel(info.day);
      var meta = document.createElement("span");
      meta.className = "tl-day-meta";
      meta.textContent = dayMeta(info);
      btn.appendChild(label);
      btn.appendChild(meta);
      btn.addEventListener("click", function () {{ loadDay(info.day); }});
      host.appendChild(btn);
    }});
    if (selectDay) return loadDay(selectDay);
    if (!day && days.length) return loadDay(days[0].day);
  }}
  async function loadDay(name, opts) {{
    day = name;
    var info = await window.lanUi.fetchJson("/timelapse/" + name + camQuery());
    paint(info);
    if (info.error) show("bad", "Could not make the timelapse", info.error);
    if (!(opts && opts.skipList)) await loadDays();
  }}
  async function build(kind) {{
    if (!day) return;
    window.lanUi.clearBanner("tl-banner");
    var btn = document.getElementById(kind === "gif" ? "tl-gif-btn" : "tl-mp4");
    window.lanUi.setBusy(btn, true, "Starting…");
    try {{
      var info = await window.lanUi.fetchJson("/timelapse/" + day + "/build" + camQuery(), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ format: kind }})
      }});
      paint(info);
    }} catch (e) {{
      show("bad", "Could not start", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }}
  function startPoll() {{
    if (poll) return;
    poll = setInterval(function () {{
      if (day) loadDay(day, {{ skipList: true }}).catch(function () {{}});
    }}, 1500);
  }}
  function stopPoll() {{
    if (!poll) return;
    clearInterval(poll);
    poll = null;
  }}
  document.getElementById("tl-mp4").addEventListener("click", function () {{ build("mp4"); }});
  document.getElementById("tl-gif-btn").addEventListener("click", function () {{ build("gif"); }});
  document.getElementById("tl-delete").addEventListener("click", async function () {{
    if (!day) return;
    var label = formatDayLabel(day);
    if (!window.lanUi.confirm(
      "Delete day " + label + "? All frames and rendered videos for this day will be removed. Other days are kept. This cannot be undone."
    )) return;
    var btn = document.getElementById("tl-delete");
    window.lanUi.clearBanner("tl-banner");
    window.lanUi.setBusy(btn, true, "Deleting…");
    try {{
      var result = await window.lanUi.fetchJson("/timelapse/" + day + "/delete" + camQuery(), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ confirm: true }})
      }});
      paintStorage(result.storage);
      clearDayView();
      show("ok", "Day deleted", label + " removed from this Pi");
      var next = (result.days && result.days[0] && result.days[0].day) || undefined;
      await loadDays(next);
      if (!next) clearDayView();
    }} catch (e) {{
      show("bad", "Could not delete day", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }});
  document.getElementById("tl-save-settings").addEventListener("click", async function () {{
    var btn = document.getElementById("tl-save-settings");
    window.lanUi.clearBanner("tl-banner");
    window.lanUi.setBusy(btn, true, "Saving…");
    try {{
      var saved = await window.lanUi.fetchJson("/timelapse/settings" + camQuery(), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          timelapse_enabled: document.getElementById("tl-enabled").checked,
          timelapse_max_gb: Number(document.getElementById("tl-max-gb").value),
          timelapse_retention_days: Number(document.getElementById("tl-retention").value),
          timelapse_min_interval_seconds: Number(document.getElementById("tl-interval").value)
        }})
      }});
      paintSettings(saved.settings || saved);
      show("ok", "Archive settings saved", "camera.yaml timelapse updated");
      await loadDays(day || undefined);
    }} catch (e) {{
      show("bad", "Could not save settings", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }});
  loadDays().catch(function (e) {{
    show("bad", "Could not load days", e && e.message ? e.message : String(e));
  }});
}})();
</script>
"""
    return lan_ui.page(
        "Timelapse",
        body,
        active="timelapse",
        pipe_more=pipe_more,
        extra_head=(
            "<style>"
            "#tl-thumb[hidden],#tl-video[hidden],#tl-thumb-frame[hidden],#tl-video-frame[hidden],"
            "#tl-stage[hidden],#tl-dl-mp4[hidden],#tl-dl-gif[hidden]{display:none !important}"
            ".tl-stage{margin-top:0.55rem}"
            ".tl-stage .preview-frame{margin-top:0;max-width:var(--preview-max)}"
            ".tl-stage .preview-frame video{"
            "position:absolute;inset:0;width:100%;height:100%;object-fit:contain;"
            "background:#0e1116;border:0;display:block}"
            ".tl-meter{height:0.55rem;margin:0.55rem 0 0.25rem;background:var(--surface-2);"
            "border:1px solid var(--border-strong);border-radius:999px;overflow:hidden}"
            ".tl-meter-fill{height:100%;width:0;background:#5b7cfa;transition:width .25s ease}"
            ".tl-meter-fill.is-high{background:#c45c26}"
            ".tl-storage-pct{margin:0 0 0.35rem;font-variant-numeric:tabular-nums}"
            ".tl-history-hint{margin:0 0 0.55rem}"
            ".tl-day-list{display:flex;flex-direction:column;gap:0.35rem;"
            "max-height:min(28rem,60vh);overflow:auto;margin:0;padding:0.1rem}"
            "button.tl-day-row{display:flex;flex-direction:column;align-items:flex-start;"
            "gap:0.15rem;width:100%;margin:0;padding:0.65rem 0.8rem;text-align:left;"
            "border:1px solid var(--border-strong);border-radius:var(--radius-sm);"
            "background:var(--surface);color:inherit;cursor:pointer;"
            "font:inherit;line-height:1.25;transition:border-color .15s ease,background .15s ease,"
            "box-shadow .15s ease}"
            "button.tl-day-row:hover{border-color:var(--accent);background:var(--surface-2)}"
            "button.tl-day-row:focus-visible{outline:2px solid var(--accent);outline-offset:2px}"
            "button.tl-day-row.is-selected{border-color:var(--accent);"
            "background:color-mix(in srgb,var(--accent) 10%,var(--surface));"
            "box-shadow:inset 3px 0 0 var(--accent)}"
            ".tl-day-label{font-weight:650;font-variant-numeric:tabular-nums}"
            ".tl-day-meta{font-size:var(--fs-sm);color:var(--muted);"
            "font-variant-numeric:tabular-nums}"
            "a.btn{display:inline-flex;align-items:center;justify-content:center;"
            "padding:0.45rem 0.85rem;border-radius:var(--radius-sm);text-decoration:none;"
            "border:1px solid var(--border-strong);background:var(--surface-2);color:inherit}"
            "a.btn.ghost{background:transparent}"
            "</style>"
        ),
    )
