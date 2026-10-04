"""LAN Setup page: project YAML + Wi-Fi join. Password is not stored."""

from __future__ import annotations

from shared import lan_ui


def setup_ui(*, pipe_more: list[dict[str, str]] | None = None) -> str:
    site = """
  <p class="field-help">Saved into <code>cameras/&lt;id&gt;/camera.yaml</code>. Saving rewrites that file (comments are dropped; other keys are kept).</p>
  <label for="cameraPick">Camera</label>
  <select id="cameraPick"></select>
  <label for="displayName">Display name</label>
  <input id="displayName" type="text" maxlength="80" autocomplete="off">
  <p class="field-help">Public JPEG overlay and LAN label (e.g. Home Assistant). Example: Example Webcam.</p>
  <label for="timezone">Timezone</label>
  <input id="timezone" type="text" autocomplete="off" placeholder="Europe/Berlin">
  <div class="row">
    <div>
      <label for="lat">Latitude</label>
      <input id="lat" type="number" step="0.0001" inputmode="decimal" autocomplete="off">
    </div>
    <div>
      <label for="lon">Longitude</label>
      <input id="lon" type="number" step="0.0001" inputmode="decimal" autocomplete="off">
    </div>
  </div>
  <p class="field-help">Latitude, longitude, and timezone for the public schedule. Schedule only edits the online window offsets.</p>
  <label for="siteLabel">Site label</label>
  <input id="siteLabel" type="text" maxlength="80" autocomplete="off" placeholder="example.com">
  <p class="field-help">Text drawn in the corner of public JPEGs. Saved on each public variant.</p>
  <label for="liveKey">Public JPEG key</label>
  <input id="liveKey" type="text" maxlength="120" autocomplete="off" placeholder="live/example-live-webcam.jpg">
  <p class="field-help">Object key in the publish bucket. The public website must use this same path. Switching the live crop does not rename it.</p>
  <label for="weatherUrl">Weather URL</label>
  <input id="weatherUrl" type="url" inputmode="url" autocomplete="off" placeholder="https://example.com/api/weather">
  <p class="field-help">JSON with <code>current.temp_c</code>. Leave empty to skip temperature on the public JPEG.</p>
  <div class="row">
    <div>
      <label for="weatherTtl">Cache seconds</label>
      <input id="weatherTtl" type="number" min="30" max="86400" step="1" inputmode="numeric">
    </div>
    <div>
      <label for="weatherTimeout">Request timeout (seconds)</label>
      <input id="weatherTimeout" type="number" min="1" max="30" step="1" inputmode="numeric">
    </div>
  </div>
"""
    create = """
  <p class="field-help">Copies <code>examples/cameras/example</code> and adds the id to the pipeline camera list. The existing camera stays.</p>
  <div class="row">
    <div>
      <label for="newId">Camera id</label>
      <input id="newId" type="text" maxlength="41" autocomplete="off" placeholder="shed">
    </div>
    <div>
      <label for="newDisplay">Display name</label>
      <input id="newDisplay" type="text" maxlength="80" autocomplete="off" placeholder="Shed webcam">
    </div>
  </div>
  <div class="actions">
    <button type="button" id="createCam" class="primary">Create camera</button>
  </div>
"""
    publish = """
  <p class="field-help">
    Upload the public JPEG to any S3-compatible store (Cloudflare R2, AWS S3, MinIO, Wasabi, Backblaze B2 S3 API),
    write to a local outbox, or turn publish off. A Cloudflare Worker landing page is optional — you can make the
    object publicly readable and hotlink / <code>&lt;img&gt;</code> / iframe the object URL. Keys go to
    <code>/etc/webcam-pipeline/env</code> on this Pi (not into git). Leave the secret blank to keep the current one.
    Restart the pipeline service before the next upload uses a new key.
  </p>
  <label for="publishProvider">Provider</label>
  <select id="publishProvider">
    <option value="off">Off — do not upload</option>
    <option value="r2">Cloudflare R2</option>
    <option value="s3">Custom S3-compatible</option>
    <option value="local">Local outbox only</option>
  </select>
  <p class="field-help" id="providerHelp"></p>
  <div id="publishRemote">
    <label for="accountId">Cloudflare account id</label>
    <input id="accountId" type="text" maxlength="64" autocomplete="off" placeholder="optional for R2 — fills the endpoint">
    <p class="field-help">R2 only. Used to build <code>https://&lt;account&gt;.r2.cloudflarestorage.com</code> when the endpoint field is empty.</p>
    <label for="endpoint">Endpoint URL</label>
    <input id="endpoint" type="url" inputmode="url" autocomplete="off" placeholder="https://s3.example.com">
    <p class="field-help">S3 API endpoint. Examples: R2 <code>https://&lt;account&gt;.r2.cloudflarestorage.com</code>, MinIO <code>http://192.168.1.10:9000</code>, AWS leave regional or use the S3 URL your console shows.</p>
    <label for="bucket">Bucket</label>
    <input id="bucket" type="text" maxlength="80" autocomplete="off">
    <div class="row">
      <div>
        <label for="region">Region</label>
        <input id="region" type="text" maxlength="64" autocomplete="off" placeholder="auto">
      </div>
      <div>
        <label class="inline" style="margin-top:1.6rem"><input type="checkbox" id="pathStyle"> Path-style addressing</label>
        <p class="field-help">Often needed for MinIO. Leave off for R2 and AWS virtual-hosted style.</p>
      </div>
    </div>
    <label for="accessKey">Access key id</label>
    <input id="accessKey" type="text" autocomplete="off">
    <label for="secretKey">Secret access key</label>
    <input id="secretKey" type="password" autocomplete="new-password">
  </div>
  <p class="muted" id="publishHint"></p>
  <div class="actions">
    <button type="button" id="testPublish" class="ghost">Test connection</button>
    <button type="button" id="savePublish" class="primary">Save publish settings</button>
  </div>
"""
    find_pi = """
  <div id="find-pi" class="status-box" role="status">Loading address…</div>
  <p class="field-help">
    After you leave <strong>Webcam-Setup</strong>, switch your phone back to home Wi-Fi and open Camera with the
    IPv4 or <code>*.local</code> name below. Many Android phones do not resolve <code>*.local</code> — use the IPv4
    or your router’s Wi-Fi / DHCP client list (hostname often <code>home-webcam</code>).
  </p>
  <dl class="debug-grid" id="find-pi-kv"></dl>
  <p class="muted" id="find-pi-urls"></p>
"""
    wifi = """
  <div id="wifi-now" class="status-box" role="status">Loading Wi-Fi…</div>
  <div id="ap-help" class="field-help" hidden>
    You are on the temporary <strong>Webcam-Setup</strong> access point.
    Note the <strong>Find this Pi</strong> card (IPv4 / hostname) before you join home Wi-Fi.
    Scan, pick your home Wi-Fi, enter its password, then tap <strong>Join Wi-Fi</strong>.
    The Pi leaves Webcam-Setup and joins home; your phone must switch back to home Wi-Fi afterward.
    Temporary AP password (printed in the DIY build doc): <code>webcam-setup</code>.
  </div>
  <p class="field-help">The password is sent once to NetworkManager and is not written into this project. Joining a different network can drop this page.</p>
  <div class="actions">
    <button type="button" id="scan" class="ghost">Scan networks</button>
  </div>
  <label for="ssid">Network</label>
  <select id="ssid"></select>
  <label for="psk">Password</label>
  <input id="psk" type="password" autocomplete="new-password">
  <p class="field-help">Leave the password empty for an open network. DHCP stays on; set a fixed address on the router if you want one.</p>
"""
    body = f"""
  {lan_ui.page_header("Setup", "Name, place, weather feed, and Wi-Fi for this Pi. Home network only.", kicker=":8090 · site · network")}
  {lan_ui.banner_slot("msg")}
  {lan_ui.card("Find this Pi", find_pi, kind="pipe")}
  {lan_ui.card("Project", site, kind="pipe")}
  {lan_ui.card("New camera", create, kind="pipe")}
  {lan_ui.card("Publish", publish, kind="pipe")}
  {lan_ui.card("Wi-Fi", wifi, kind="pipe")}
  {lan_ui.actions_bar(
      '<button type="button" id="save" class="primary">Save project</button>',
      '<button type="button" id="connect" class="primary">Join Wi-Fi</button>',
      sticky=True,
  )}
<script>
(function () {{
  var cam = "";

  function val(id) {{ return document.getElementById(id).value; }}
  function set(id, v) {{
    var el = document.getElementById(id);
    if (el && v != null) el.value = v;
  }}

  function row(dl, label, value) {{
    if (!value) return;
    var dt = document.createElement("dt");
    dt.textContent = label;
    var dd = document.createElement("dd");
    dd.textContent = value;
    dl.appendChild(dt);
    dl.appendChild(dd);
  }}

  async function loadSite() {{
    var site = await window.lanUi.fetchJson("/setup?camera=" + encodeURIComponent(cam));
    set("displayName", site.display_name || "");
    set("timezone", site.timezone || "");
    set("lat", site.latitude != null ? site.latitude : "");
    set("lon", site.longitude != null ? site.longitude : "");
    set("weatherUrl", site.weather_url || "");
    set("weatherTtl", site.weather_ttl_seconds != null ? site.weather_ttl_seconds : 300);
    set("weatherTimeout", site.weather_timeout_seconds != null ? site.weather_timeout_seconds : 4);
    set("siteLabel", site.site_label || "");
    set("liveKey", site.public_live_key || "");
  }}

  function fillCameras(ids, current) {{
    var sel = document.getElementById("cameraPick");
    sel.innerHTML = "";
    (ids || []).forEach(function (id) {{
      var opt = document.createElement("option");
      opt.value = id;
      opt.textContent = id;
      sel.appendChild(opt);
    }});
    if (current) sel.value = current;
  }}

  function fillFindPi(status) {{
    var box = document.getElementById("find-pi");
    var dl = document.getElementById("find-pi-kv");
    var urlsEl = document.getElementById("find-pi-urls");
    if (!box || !dl) return;
    dl.innerHTML = "";
    if (urlsEl) urlsEl.textContent = "";
    if (!status) {{
      window.lanUi.banner(box, "warn", "Address unknown", "");
      return;
    }}
    var hostname = status.hostname || "";
    var mdns = status.mdns || (hostname ? hostname + ".local" : "");
    var currentIp = "";
    if (status.setup_ap) {{
      currentIp = status.setup_ap_gateway || "10.42.0.1";
    }} else if (status.ipv4) {{
      currentIp = status.ipv4;
    }}
    var addrs = (status.addresses || []).map(function (a) {{
      return (a.type || a.device || "?") + " " + (a.ipv4 || "");
    }}).filter(Boolean);
    var title = status.setup_ap ? "On Webcam-Setup AP" : (status.ssid ? "On home Wi-Fi" : "Network");
    var detail = [mdns, currentIp].filter(Boolean).join(" · ");
    window.lanUi.banner(box, status.setup_ap ? "warn" : "ok", title, detail);
    row(dl, "Hostname", hostname);
    row(dl, "mDNS", mdns);
    row(dl, "Current IPv4", currentIp);
    if (status.last_lan_ipv4 && status.last_lan_ipv4 !== currentIp) {{
      row(dl, "Last home IPv4", status.last_lan_ipv4);
    }}
    if (addrs.length) row(dl, "Interfaces", addrs.join(", "));
    var urls = status.lan_urls || {{}};
    var linkBits = [];
    if (urls.ipv4_camera) linkBits.push("Camera " + urls.ipv4_camera);
    else if (urls.mdns_camera) linkBits.push("Camera " + urls.mdns_camera);
    if (urls.mdns_camera && urls.ipv4_camera) linkBits.push("or " + urls.mdns_camera);
    if (status.setup_ap) {{
      linkBits.push("After Join: use Last home IPv4 or router client list if mDNS fails (common on Android).");
    }}
    if (urlsEl) urlsEl.textContent = linkBits.join(" · ");
  }}

  function fillWifi(status) {{
    var box = document.getElementById("wifi-now");
    var apHelp = document.getElementById("ap-help");
    fillFindPi(status);
    if (!status || status.available === false) {{
      window.lanUi.banner(box, "warn", "Wi-Fi unavailable", (status && status.message) || "");
      if (apHelp) apHelp.hidden = true;
      return;
    }}
    if (apHelp) apHelp.hidden = !status.setup_ap;
    if (status.setup_ap) {{
      var apDetail = [
        "temporary setup AP",
        status.setup_ap_url || ("http://" + (status.setup_ap_gateway || "10.42.0.1") + ":8090/setup/ui"),
        status.device
      ].filter(Boolean).join(" · ");
      window.lanUi.banner(box, "warn", status.setup_ap_ssid || "Webcam-Setup", apDetail);
      return;
    }}
    var ssid = status.ssid || "not connected";
    var detail = [status.device, status.ipv4, status.state].filter(Boolean).join(" · ");
    window.lanUi.banner(box, status.ssid ? "ok" : "warn", ssid, detail);
  }}

  function fillNetworks(list, current) {{
    var sel = document.getElementById("ssid");
    var names = (list && list.networks) || [];
    sel.innerHTML = "";
    names.forEach(function (n) {{
      var opt = document.createElement("option");
      opt.value = n.ssid;
      var mark = n.in_use ? " · connected" : "";
      opt.textContent = n.ssid + " (" + (n.signal || 0) + "%)" + mark;
      sel.appendChild(opt);
    }});
    if (current && current.ssid) sel.value = current.ssid;
  }}

  async function loadWifi() {{
    var status = await window.lanUi.fetchJson("/setup/wifi");
    fillWifi(status);
    return status;
  }}

  document.getElementById("save").addEventListener("click", async function () {{
    var btn = document.getElementById("save");
    window.lanUi.setBusy(btn, true, "Saving…");
    try {{
      await window.lanUi.fetchJson("/setup?camera=" + encodeURIComponent(cam), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          display_name: val("displayName"),
          timezone: val("timezone"),
          latitude: val("lat"),
          longitude: val("lon"),
          weather_url: val("weatherUrl"),
          weather_ttl_seconds: Number(val("weatherTtl")),
          weather_timeout_seconds: Number(val("weatherTimeout")),
          site_label: val("siteLabel"),
          public_live_key: val("liveKey")
        }})
      }});
      window.lanUi.showBanner("msg", "info", "Saved", "camera.yaml updated");
    }} catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Save failed", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }});

  document.getElementById("scan").addEventListener("click", async function () {{
    var btn = document.getElementById("scan");
    window.lanUi.setBusy(btn, true, "Scanning…");
    try {{
      var status = await loadWifi();
      var list = await window.lanUi.fetchJson("/setup/wifi/scan");
      fillNetworks(list, status);
      window.lanUi.showBanner("msg", "info", "Scan finished", (list.networks || []).length + " networks");
    }} catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Scan failed", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }});

  document.getElementById("connect").addEventListener("click", async function () {{
    var ssid = val("ssid");
    if (!ssid) {{
      window.lanUi.showBanner("msg", "warn", "No network", "Scan, then pick a network.");
      return;
    }}
    if (!window.lanUi.confirm("Join “" + ssid + "”? This Pi may leave the current Wi-Fi.")) return;
    var btn = document.getElementById("connect");
    window.lanUi.setBusy(btn, true, "Joining…");
    try {{
      var res = await window.lanUi.fetchJson("/setup/wifi", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ ssid: ssid, password: val("psk") }})
      }});
      document.getElementById("psk").value = "";
      var joinedBits = [];
      if (res.ipv4) joinedBits.push(res.ipv4);
      if (res.mdns) joinedBits.push(res.mdns);
      if (res.message) joinedBits.push(res.message);
      window.lanUi.showBanner("msg", "info", "Joined " + (res.ssid || ssid), joinedBits.join(" — "));
      fillFindPi(res);
      await loadWifi();
    }} catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Could not join", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }});

  document.getElementById("cameraPick").addEventListener("change", async function () {{
    cam = document.getElementById("cameraPick").value || "";
    try {{ await loadSite(); }}
    catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Could not load camera", e && e.message ? e.message : String(e));
    }}
  }});

  document.getElementById("createCam").addEventListener("click", async function () {{
    var btn = document.getElementById("createCam");
    window.lanUi.setBusy(btn, true, "Creating…");
    try {{
      var created = await window.lanUi.fetchJson("/setup/cameras", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ id: val("newId"), display_name: val("newDisplay") }})
      }});
      cam = created.camera_id;
      var health = await window.lanUi.fetchJson("/health");
      fillCameras((health && health.configured_cameras) || [cam], cam);
      await loadSite();
      window.lanUi.showBanner("msg", "ok", "Camera created", cam);
    }} catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Create failed", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }});

  function providerHelp(provider) {{
    var map = {{
      off: "Public variants stay on this Pi only. No upload.",
      r2: "Cloudflare R2 preset. Paste the account id (optional) or the full R2 S3 endpoint, bucket, and R2 API token keys. Make the live object publicly readable to hotlink it — a Worker page is optional.",
      s3: "Any S3-compatible API: AWS S3, MinIO, Wasabi, Backblaze B2 (S3), etc. Set endpoint, bucket, region, and keys. Public object URL / hotlink is enough; a Worker is optional.",
      local: "Writes the same key layout under data/outbox/ on this Pi. Serve or copy that file yourself — no cloud bucket."
    }};
    return map[provider] || "";
  }}

  function syncPublishForm() {{
    var provider = val("publishProvider") || "off";
    var help = document.getElementById("providerHelp");
    if (help) help.textContent = providerHelp(provider);
    var remote = document.getElementById("publishRemote");
    if (remote) remote.hidden = !(provider === "r2" || provider === "s3");
    var accountRow = document.getElementById("accountId");
    if (accountRow) {{
      var wrap = accountRow.closest("label") || accountRow;
      // account field + its help stay visible mainly for R2
      accountRow.disabled = provider !== "r2";
    }}
  }}

  function publishPayload() {{
    return {{
      provider: val("publishProvider"),
      account_id: val("accountId"),
      bucket: val("bucket"),
      endpoint_url: val("endpoint"),
      region: val("region") || "auto",
      force_path_style: document.getElementById("pathStyle").checked,
      access_key_id: val("accessKey"),
      secret_access_key: val("secretKey")
    }};
  }}

  async function loadPublish() {{
    var pub = await window.lanUi.fetchJson("/setup/publish");
    set("publishProvider", pub.provider || (pub.enabled ? "s3" : "off"));
    set("bucket", pub.bucket || "");
    set("endpoint", pub.endpoint_url || "");
    set("region", pub.region || "auto");
    set("accountId", pub.account_id || "");
    document.getElementById("pathStyle").checked = !!pub.force_path_style;
    var hint = [];
    if (pub.access_key_set) hint.push("access key is set");
    if (pub.secret_set) hint.push("secret is set");
    if (pub.env_path) hint.push("env " + pub.env_path);
    if (pub.restart_required) hint.push("restart the pipeline after a new key");
    document.getElementById("publishHint").textContent = hint.join(" · ");
    syncPublishForm();
  }}

  document.getElementById("publishProvider").addEventListener("change", syncPublishForm);

  document.getElementById("accountId").addEventListener("change", function () {{
    var account = val("accountId");
    if (val("publishProvider") === "r2" && account && !val("endpoint")) {{
      set("endpoint", "https://" + account + ".r2.cloudflarestorage.com");
    }}
  }});

  document.getElementById("testPublish").addEventListener("click", async function () {{
    var btn = document.getElementById("testPublish");
    window.lanUi.setBusy(btn, true, "Testing…");
    try {{
      var res = await window.lanUi.fetchJson("/setup/publish/test", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(publishPayload())
      }});
      if (res && res.ok) {{
        window.lanUi.showBanner("msg", "ok", "Connection OK", res.detail || "");
      }} else {{
        window.lanUi.showBanner("msg", "bad", "Connection failed", (res && res.detail) || "unknown error");
      }}
    }} catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Connection failed", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }});

  document.getElementById("savePublish").addEventListener("click", async function () {{
    var btn = document.getElementById("savePublish");
    window.lanUi.setBusy(btn, true, "Saving…");
    try {{
      await window.lanUi.fetchJson("/setup/publish", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(publishPayload())
      }});
      document.getElementById("secretKey").value = "";
      document.getElementById("accessKey").value = "";
      await loadPublish();
      window.lanUi.showBanner("msg", "ok", "Publish settings saved", "Restart the pipeline service before the next upload.");
    }} catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Publish save failed", e && e.message ? e.message : String(e));
    }} finally {{
      window.lanUi.setBusy(btn, false);
    }}
  }});

  window.lanUi.resolveCamera().then(async function (id) {{
    cam = id || "";
    try {{
      var health = await window.lanUi.fetchJson("/health");
      fillCameras((health && health.configured_cameras) || (cam ? [cam] : []), cam);
      if (cam) await loadSite();
      await loadPublish();
      await loadWifi();
    }} catch (e) {{
      window.lanUi.showBanner("msg", "bad", "Could not load setup", e && e.message ? e.message : String(e));
    }}
  }});
}})();
</script>
"""
    return lan_ui.page("Setup", body, active="setup", pipe_more=pipe_more)
