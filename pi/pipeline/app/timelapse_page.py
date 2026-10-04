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
  </div>
"""
    storage_card = f"""
  <p id="tl-storage" class="muted">Loading storage…</p>
  <div class="tl-meter" aria-hidden="true">
    <div id="tl-meter-fill" class="tl-meter-fill" style="width:0%"></div>
  </div>
  <p id="tl-storage-pct" class="muted tl-storage-pct"></p>
  <p class="muted">Budget is <code>timelapse.max_gb</code> in <code>cameras/&lt;id&gt;/camera.yaml</code> (default {DEFAULT_MAX_GB:g} GB). Oldest days are deleted when the archive is full; also keep at most <code>retention_days</code>.</p>
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
      {lan_ui.card("Days", '''
  <p id="tl-empty" class="muted">Loading days…</p>
  <div id="tl-days" class="actions"></div>
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
    var busy = info.building === "mp4" || info.building === "gif";
    meta.textContent = info.frames
      ? (info.frames + " frames, " + info.first + "–" + info.last + (busy ? ". Making the " + info.building + "…" : "."))
      : "No frames for this day.";
    mp4.disabled = busy || info.frames < 2;
    gifBtn.disabled = busy || info.frames < 2;
    mp4.textContent = info.mp4 ? "Rebuild video" : "Make video";
    gifBtn.textContent = info.gif ? "Rebuild GIF" : "Make GIF";
    setMedia(info);
    if (busy) startPoll(); else stopPoll();
  }}
  async function loadDays(selectDay) {{
    var data = await window.lanUi.fetchJson("/timelapse" + camQuery());
    paintStorage(data.storage);
    var host = document.getElementById("tl-days");
    var empty = document.getElementById("tl-empty");
    host.innerHTML = "";
    var days = data.days || [];
    empty.hidden = days.length > 0;
    empty.textContent = days.length ? "" : "No days yet. Frames are saved about every 2 minutes while the public schedule is online.";
    days.forEach(function (info) {{
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = info.day === (selectDay || day) ? "" : "ghost";
      btn.textContent = info.day + " (" + info.frames + ")";
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
            "a.btn{display:inline-flex;align-items:center;justify-content:center;"
            "padding:0.45rem 0.85rem;border-radius:var(--radius-sm);text-decoration:none;"
            "border:1px solid var(--border-strong);background:var(--surface-2);color:inherit}"
            "a.btn.ghost{background:transparent}"
            "</style>"
        ),
    )
