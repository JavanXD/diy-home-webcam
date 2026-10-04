"""Shared client JS for LAN pages (`window.lanUi`).

API (stable):
  lanUi.fetchJson(url, opts?)   → object; throws Error with .status on HTTP fail
  lanUi.fetchRes(url, opts?)    → Response; opts.timeoutMs (default 12000)
  lanUi.banner(el|id, kind, title, detailOrRows?)
    kind: ''|ok|warn|bad|info
    detailOrRows: plain string OR [[label, value], ...] for structured status
  lanUi.setBusy(btn, busy, busyLabel?)
  lanUi.confirm(message) → bool (window.confirm wrapper)
  lanUi.stampUpdated(el|id, ok)
  lanUi.formatDuration(seconds) → human string (e.g. "2h 15m")
  lanUi.escapeHtml(s)
  lanUi.showBanner / clearBanner — optional #id with [hidden]
  lanUi.swapImg(img|id, url, opts?) → Promise — keep previous frame until new loads
  lanUi.setPreviewAspect(img|id, width, height) — update .preview-frame aspect-ratio
"""

from __future__ import annotations

CLIENT_JS = """
window.lanUi = (function () {
  var DEFAULT_MS = 12000;

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function resolveEl(elOrId) {
    return typeof elOrId === "string" ? document.getElementById(elOrId) : elOrId;
  }

  function statusBadgeLabel(kind) {
    if (kind === "ok") return "OK";
    if (kind === "warn") return "WARN";
    if (kind === "bad") return "FAIL";
    if (kind === "info") return "INFO";
    return "—";
  }

  function banner(elOrId, kind, title, detailOrRows) {
    var el = resolveEl(elOrId);
    if (!el) return;
    var k = kind || "";
    el.hidden = false;
    el.className = "status-box banner " + k;
    el.removeAttribute("aria-busy");
    var badge = "<span class=\\"status-badge status-badge-" + escapeHtml(k || "info") + "\\">"
      + statusBadgeLabel(k) + "</span>";
    var body = "<div class=\\"status-body\\"><strong>" + escapeHtml(title || "Notice") + "</strong>";
    if (Array.isArray(detailOrRows) && detailOrRows.length) {
      body += "<dl class=\\"status-kv\\">";
      detailOrRows.forEach(function (row) {
        if (!row) return;
        var label = Array.isArray(row) ? row[0] : row.label;
        var value = Array.isArray(row) ? row[1] : row.value;
        if (label == null || value == null || value === "") return;
        body += "<div class=\\"status-kv-row\\"><dt>" + escapeHtml(String(label))
          + "</dt><dd>" + escapeHtml(String(value)) + "</dd></div>";
      });
      body += "</dl>";
    } else if (detailOrRows) {
      body += "<span class=\\"muted\\">" + escapeHtml(String(detailOrRows)) + "</span>";
    }
    body += "</div>";
    el.innerHTML = badge + body;
  }

  function showBanner(elOrId, kind, title, detail) {
    banner(elOrId, kind, title, detail);
  }

  function clearBanner(elOrId) {
    var el = resolveEl(elOrId);
    if (!el) return;
    el.hidden = true;
    el.removeAttribute("aria-busy");
    el.textContent = "";
    el.className = "banner";
  }

  function setBusy(btn, busy, busyLabel) {
    if (!btn) return;
    if (busy) {
      if (btn.dataset.lanLabel == null) btn.dataset.lanLabel = btn.textContent || "";
      btn.disabled = true;
      btn.setAttribute("aria-busy", "true");
      if (busyLabel) btn.textContent = busyLabel;
    } else {
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
      if (btn.dataset.lanLabel != null) {
        btn.textContent = btn.dataset.lanLabel;
        delete btn.dataset.lanLabel;
      }
    }
  }

  /** Confirm destructive / consequential actions. Returns true if the user accepts. */
  function confirmAction(message) {
    try {
      return window.confirm(String(message || "Are you sure?"));
    } catch (_) {
      return true;
    }
  }

  function stampUpdated(elOrId, ok) {
    var el = resolveEl(elOrId);
    if (!el) return;
    var t = new Date();
    var hh = String(t.getHours()).padStart(2, "0");
    var mm = String(t.getMinutes()).padStart(2, "0");
    var ss = String(t.getSeconds()).padStart(2, "0");
    var base = "Last updated " + hh + ":" + mm + ":" + ss;
    el.textContent = ok ? base : (base + " · refresh failed — data may be stale");
    el.className = "stale-hint" + (ok ? "" : " stale");
  }

  function formatDuration(seconds) {
    if (seconds == null || seconds === "" || isNaN(Number(seconds))) return "—";
    var s = Math.max(0, Math.floor(Number(seconds)));
    var days = Math.floor(s / 86400);
    s %= 86400;
    var hours = Math.floor(s / 3600);
    s %= 3600;
    var mins = Math.floor(s / 60);
    var secs = s % 60;
    if (days > 0) return days + "d " + hours + "h";
    if (hours > 0) return hours + "h " + mins + "m";
    if (mins > 0) return mins + "m " + secs + "s";
    return secs + "s";
  }

  async function fetchRes(url, opts) {
    opts = opts || {};
    var ms = opts.timeoutMs != null ? opts.timeoutMs : DEFAULT_MS;
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, ms);
    var init = {};
    for (var k in opts) {
      if (k === "timeoutMs") continue;
      init[k] = opts[k];
    }
    init.signal = ctrl.signal;
    if (!init.cache) init.cache = "no-store";
    try {
      var res = await fetch(url, init);
      if (!res.ok) {
        var body = "";
        try { body = (await res.text()).slice(0, 160); } catch (_) {}
        var err = new Error("HTTP " + res.status + (body ? ": " + body : ""));
        err.status = res.status;
        throw err;
      }
      return res;
    } catch (e) {
      if (e && e.name === "AbortError") {
        throw new Error("Request timed out after " + Math.round(ms / 1000) + "s");
      }
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  async function fetchJson(url, opts) {
    var res = await fetchRes(url, opts);
    var data;
    try {
      data = await res.json();
    } catch (e) {
      throw new Error("Invalid JSON response");
    }
    if (data == null || typeof data !== "object") {
      throw new Error("Unexpected response shape");
    }
    return data;
  }

  async function resolveCamera() {
    var q = new URLSearchParams(location.search).get("camera");
    if (q) return q;
    try {
      var health = await fetchJson("/health");
      var ids = (health && health.configured_cameras) || [];
      if (!ids.length && health && health.cameras) ids = Object.keys(health.cameras);
      if (ids.length) return String(ids[0]);
    } catch (e) {}
    return "";
  }

  function setPreviewAspect(imgOrId, width, height) {
    var img = resolveEl(imgOrId);
    if (!img || !img.closest) return;
    var frame = img.closest(".preview-frame");
    if (!frame) return;
    var w = Number(width);
    var h = Number(height);
    if (!(w > 0) || !(h > 0)) return;
    frame.style.aspectRatio = Math.round(w) + " / " + Math.round(h);
    img.setAttribute("width", String(Math.round(w)));
    img.setAttribute("height", String(Math.round(h)));
  }

  /**
   * Swap an <img> src only after the new URL has loaded (double-buffer).
   * Keeps the previous pixels visible; does not collapse .preview-frame height.
   * opts.objectUrl — blob URL to track on img._objUrl (revokes the previous one).
   */
  function swapImg(imgOrId, url, opts) {
    opts = opts || {};
    var img = resolveEl(imgOrId);
    if (!img || !url) return Promise.resolve(img);
    var prevBlob = img._objUrl;
    var frame = img.closest ? img.closest(".preview-frame") : null;
    if (frame) frame.classList.add("is-loading");
    return new Promise(function (resolve, reject) {
      var probe = new Image();
      probe.decoding = "async";
      var settled = false;
      function done(ok, err) {
        if (settled) return;
        settled = true;
        probe.onload = null;
        probe.onerror = null;
        if (frame) frame.classList.remove("is-loading");
        if (ok) resolve(img);
        else reject(err || new Error("Image failed to load"));
      }
      probe.onload = function () {
        try {
          if (opts.followNaturalAspect && probe.naturalWidth && probe.naturalHeight) {
            setPreviewAspect(img, probe.naturalWidth, probe.naturalHeight);
          }
          img.src = url;
          if (opts.objectUrl) {
            if (prevBlob && prevBlob !== opts.objectUrl) {
              try { URL.revokeObjectURL(prevBlob); } catch (_) {}
            }
            img._objUrl = opts.objectUrl;
          } else if (prevBlob) {
            try { URL.revokeObjectURL(prevBlob); } catch (_) {}
            delete img._objUrl;
          }
          done(true);
        } catch (e) {
          if (opts.objectUrl) {
            try { URL.revokeObjectURL(opts.objectUrl); } catch (_) {}
          }
          done(false, e);
        }
      };
      probe.onerror = function () {
        if (opts.objectUrl) {
          try { URL.revokeObjectURL(opts.objectUrl); } catch (_) {}
        }
        done(false, new Error("Image failed to load"));
      };
      probe.src = url;
    });
  }

  return {
    DEFAULT_MS: DEFAULT_MS,
    resolveCamera: resolveCamera,
    banner: banner,
    showBanner: showBanner,
    clearBanner: clearBanner,
    setBusy: setBusy,
    confirm: confirmAction,
    stampUpdated: stampUpdated,
    formatDuration: formatDuration,
    fetchRes: fetchRes,
    fetchJson: fetchJson,
    escapeHtml: escapeHtml,
    swapImg: swapImg,
    setPreviewAspect: setPreviewAspect,
  };
})();
""".strip()

NAV_REWRITE_JS = """
(function () {
  var h = location.hostname || "home-webcam.local";
  var here = String(location.port || "");
  document.querySelectorAll("a[data-lan-port]").forEach(function (a) {
    var port = a.getAttribute("data-lan-port");
    var path = a.getAttribute("data-lan-path") || "/";
    if (port && port !== here) {
      a.href = "http://" + h + ":" + port + path;
    } else {
      a.href = path;
    }
  });
})();
""".strip()

NAV_MORE_JS = """
(function () {
  function menuOf(btn) {
    var id = btn.getAttribute("aria-controls");
    return id ? document.getElementById(id) : null;
  }

  function closeOne(btn) {
    var menu = menuOf(btn);
    btn.setAttribute("aria-expanded", "false");
    if (menu) menu.hidden = true;
  }

  function closeAll(exceptBtn) {
    document.querySelectorAll(".nav-more-btn[aria-expanded='true']").forEach(function (btn) {
      if (btn !== exceptBtn) closeOne(btn);
    });
  }

  function openOne(btn) {
    var menu = menuOf(btn);
    if (!menu) return;
    closeAll(btn);
    btn.setAttribute("aria-expanded", "true");
    menu.hidden = false;
    var first = menu.querySelector("a");
    if (first) first.focus();
  }

  function toggle(btn) {
    if (btn.getAttribute("aria-expanded") === "true") closeOne(btn);
    else openOne(btn);
  }

  document.querySelectorAll(".nav-more").forEach(function (wrap) {
    var btn = wrap.querySelector(".nav-more-btn");
    var menu = wrap.querySelector(".nav-more-menu");
    if (!btn || !menu) return;

    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      toggle(btn);
    });

    btn.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openOne(btn);
      } else if (e.key === "Escape") {
        closeOne(btn);
      }
    });

    menu.addEventListener("keydown", function (e) {
      var items = Array.prototype.slice.call(menu.querySelectorAll("a"));
      if (!items.length) return;
      var i = items.indexOf(document.activeElement);
      if (e.key === "Escape") {
        e.preventDefault();
        closeOne(btn);
        btn.focus();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        items[(i + 1) % items.length].focus();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        items[(i - 1 + items.length) % items.length].focus();
      } else if (e.key === "Home") {
        e.preventDefault();
        items[0].focus();
      } else if (e.key === "End") {
        e.preventDefault();
        items[items.length - 1].focus();
      } else if (e.key === "Tab") {
        closeOne(btn);
      }
    });
  });

  document.addEventListener("click", function (e) {
    var t = e.target;
    if (t && t.closest && t.closest(".nav-more")) return;
    closeAll();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeAll();
  });

  window.lanNavMoreCloseAll = closeAll;
})();
""".strip()

NAV_MOBILE_JS = """
(function () {
  var nav = document.querySelector("nav.nav");
  var btn = document.getElementById("nav-toggle");
  var panels = document.getElementById("nav-panels");
  if (!nav || !btn || !panels) return;

  var MQ = window.matchMedia("(max-width: 480px)");

  function setOpen(open) {
    nav.classList.toggle("is-open", open);
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    btn.textContent = open ? "Close" : "Menu";
    if (!open && typeof window.lanNavMoreCloseAll === "function") {
      window.lanNavMoreCloseAll();
    }
  }

  function syncDesktop() {
    if (!MQ.matches) setOpen(false);
  }

  btn.addEventListener("click", function (e) {
    e.preventDefault();
    e.stopPropagation();
    setOpen(btn.getAttribute("aria-expanded") !== "true");
  });

  document.addEventListener("click", function (e) {
    if (!MQ.matches || !nav.classList.contains("is-open")) return;
    var t = e.target;
    if (t && t.closest && t.closest("nav.nav")) return;
    setOpen(false);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && nav.classList.contains("is-open")) {
      setOpen(false);
      btn.focus();
    }
  });

  if (MQ.addEventListener) MQ.addEventListener("change", syncDesktop);
  else if (MQ.addListener) MQ.addListener(syncDesktop);
  syncDesktop();
})();
""".strip()


def client_js() -> str:
    return CLIENT_JS


def nav_rewrite_js() -> str:
    return NAV_REWRITE_JS


def nav_more_js() -> str:
    return NAV_MORE_JS


def nav_mobile_js() -> str:
    return NAV_MOBILE_JS
