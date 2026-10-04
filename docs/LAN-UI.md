# LAN UI design system

English operator UIs on the Pi LAN:

| Port | Service | Color | Pages |
|------|---------|-------|-------|
| `:8080` | Camera | green | `/` Camera home, `/debug/ui` Maintenance |
| `:8090` | Pipeline | red | `/` Pipeline home (incl. **System** card), `/schedule/ui` Schedule, `/variants/ui` Variants, `/setup/ui` Setup, `/timelapse/ui` Timelapse |

Import path stays `from shared import lan_ui` (package under `shared/lan_ui/`).

**Favicon:** original LAN appliance icon under `shared/lan_ui/assets/` (`favicon.svg`, `.ico`, 16/32 PNG, apple-touch). Every `lan_ui.page(...)` includes `<link rel="icon">`. Camera `:8080` and pipeline `:8090` both serve the same routes (`/favicon.svg`, `/favicon.ico`, …). nginx `:80`/`:443` only `301` to `:8080$request_uri`, so `/favicon.ico` on the hub follows to the camera service.

## Why Maintenance is on :8080 and Schedule / Variants on :8090

**Maintenance** lives on the camera because it owns the Wartungsbild flag (`GET|POST /maintenance`) and the optional `/feed.jpg` swap. The pipeline acquires **`/raw.jpg`** always and applies Wartung only to **public** variants when that flag is on. **Private LAN-only stays on the live raw frame.** The toggle belongs with the process that owns capture.

**Schedule** lives on the pipeline because it gates only the **public R2 livestream** (night/solar offline + placeholder upload). Private HA JPEG stays live. That decision sits on the publish path, not capture.

**Public live precedence** (fixed R2 / outbox live key only):

1. Schedule offline (`public_online == false`) → night/offline placeholder (wall-clock + temp overlays) — **even if** Wartungsbild / maintenance is on
2. Else maintenance on → Wartung frame (history skipped)
3. Else normal live variant

Pipeline acquires `/raw.jpg` always; public variants may render Wartung when maintenance is on. Private HA always stays on the live raw original. Only the **public live publish** prefers the schedule placeholder at night.

**Variants** also belong on the pipeline: crop, privacy masks, and output knobs are applied in `pi/pipeline/app/render.py` from `cameras/<id>/variants/*.yaml`. Capture on `:8080` stays the uncropped original. The LAN editor writes those YAML files on the Pi (write path A) and dry-runs `render_one` for preview.

The green/red navbar can jump across ports; page **bodies** stay service-scoped. There is no shared Overview hub that mixes both.

## Variants editor (`:8090`)

| Item | Detail |
|------|--------|
| UI | `http://home-webcam.local:8090/variants/ui` (primary red nav **Variants**) |
| Flow | Create → edit crop/masks/output/overlays → Preview → Save; mark one **public** variant as the **public livestream**. Gallery splits **Private (LAN-only)** (badge “LAN only”; home network only; not for the public website/livestream; e.g. Home Assistant) vs **Public variants**. |
| Create | `POST /variants` — name + template (`private` or `landscape-public`); JPEG filename auto `{name}.jpg`; atomic YAML under `cameras/<id>/variants/` |
| Editable | `description`, `crop` (drag cyan rectangle on **Edit crop** over the stored original, or mode/LTRB/width/height fracs/zoom/aspect_ratio fields), `privacy.masks` (drag rectangles on the large **Edit masks** canvas, or one line per mask; optional per-mask `label` / `note` — admin only, not drawn), `output.width` / `height` / `jpeg_quality`, `timestamp` (incl. `stroke_width`), `site_badge` (incl. `stroke_width`), `artistic` |
| Layout | Wide main (`min(80rem, …)` like camera focus). Full-width **Edit crop** (stored original via `GET /cameras/<id>/original.jpg` + cyan drag box) under Crop; full-width **Edit masks** (saved/live JPEG + yellow drag layer) under Privacy masks; compact **Preview (unsaved)** dry-run below Advanced overlays / sticky actions. Crop/mask layers sized to `object-fit: contain` content box so percent coords stay correct. Cover-fit output (no stretch). |
| Read-only | `name`, `visibility`, `output.filename` / R2 keys, `publish`, `watermark` |
| Help text | Each control has a short plain-English “what it’s for” note; API also returns `field_help` on `GET /variants/<name>` |
| Fit | Live + Preview scale the crop to fill output WxH without stretching. Optional `artistic.*` is the only intentional mild stretch. Prefer `crop.aspect_ratio` matching output AR. |
| Persistence | Atomic write to `cameras/<id>/variants/*.yaml` on the Pi |
| Preview | `POST /variants/<name>/preview` → JPEG (no disk / no R2); same `render_one` as production; UI runs preview **only on Preview click** (not on load/select) |
| Local JPEG URL | `http://<host>:8090/cameras/<id>/variants/{name}.jpg` (copyable; not the public edge path) |
| Public livestream | `GET\|POST /public-live?camera=` — selects which public variant’s bytes publish to the fixed R2 key from `camera.yaml` (`publish.public_live_key`). Runtime file: `data/<camera>/public-live.json`. Private variants are ineligible. |
| Gallery thumbs | Same live URL + `?w=240` (on-the-fly downscale); lazy-loaded |
| After save/create | Triggers render-only refresh for that camera; thumbs refresh via `jpeg_mtime_ns` cache key |
| Auth | Open on LAN on purpose. The home network is the trust boundary; there is no login. |

### Sync / pull

1. Tune on Pi via `/variants/ui` → YAML updates under `/opt/home-webcam-pipeline/cameras/`.
2. **Pull before sync:** `./pi/scripts/pull-cameras-from-pi.sh pi@home-webcam.local`
3. `sync-to-pi.sh` uses `--delete` on `cameras/` — without a pull, Mac YAML overwrites Pi edits (including newly created variants).

`webcam-pipeline` needs `ReadWritePaths=…/cameras` and `fix-data-perms.sh` ownership so the `webcam` user can write variant YAML.

## Navbar

Each port cluster has primary page links plus a collapsible **More** menu for that service’s JSON/debug endpoints only (camera More ≠ pipeline More). Cross-port jumps stay as the green/red page links (Camera home, Maintenance | Pipeline home, Schedule, Variants). On viewports ≤480px the bar collapses to green/red port chips + a **Menu** toggle that expands stacked full-width clusters (tap targets ≥44px; More menus open in-flow full width so they never clip off-screen).

| Cluster | Primary (UI pages) | More (JSON / JPEG only) |
|---------|---------------------|-------------------------|
| Green `:8080` | Camera home, Maintenance | Health/Status/Debug/Maintenance (JSON), Live image |
| Red `:8090` | Pipeline home, Schedule, Variants, Setup, Timelapse | Health/Status/Debug/System status/System logs/Schedule/Variants/Public livestream (JSON), plus that camera’s variant JPEGs when `cameras/<id>/variants/*.yaml` exists. The document title is always `Webcam`, not the camera `display_name`. Setup edits `camera.yaml` (name, place, weather URL), publish (R2 / custom S3 / local / off + test connection), and can join Wi-Fi. The password is not stored in the repo. Timelapse lists daylight days on the Pi (storage budget shown), builds MP4/GIF locally, and offers file downloads. |

More is keyboard-accessible (Arrow keys, Escape), closes on outside click, and works on touch. Endpoint lists live in `_MORE_CAM` / `_MORE_PIPE` in `chrome.py`.

## Package layout

| Module | Role |
|--------|------|
| `tokens.py` | CSS variables — cool technical neutrals + port identity |
| `styles.py` | Full stylesheet (tokens + components) |
| `chrome.py` | `page()`, `nav_html()`, `BRAND`, per-port More menus |
| `components.py` | `page_header`, `card` (panel-head / panel-body), `pill`, `lan_link`, `banner_slot`, `empty_state`, `actions_bar`, debug panel, … |
| `js_helpers.py` | `window.lanUi` client helpers + nav More dropdown + mobile Menu toggle JS |

## Design tokens (summary)

Technical ops dashboard (operator LAN pages; public landing stays separate):

- Surfaces: `--bg #e6e9ee`, `--card #f4f6f8`, `--fg #12161c`, `--muted #5a6470` (cool neutrals — not warm cream)
- Radii: near-square (`--radius` / `--radius-sm` ≈ 2px)
- Camera cluster: `--cam #1f6b42` / `--cam-bg #dde8e1` (ops green)
- Pipeline cluster: `--pipe #a8342a` / `--pipe-bg #eadfdd` (ops red)
- Status: left-border panels + monospace badges (`OK` / `WARN` / `FAIL` / `INFO`) — not big green success banners
- Also: spacing (`--space-*`), `--tap` (44px), focus ring (slate), monospace for paths / IDs / JSON hints

`body.svc-cam` / `body.svc-pipe` set `--accent` to the active service color (with readable `--on-accent`).

Panels use a uppercase `panel-head` + `panel-body`; page headers include an optional mono `kicker` and a bottom rule so operators can scan sections quickly.

## Client JS (`window.lanUi`)

| API | Purpose |
|-----|---------|
| `fetchJson(url, opts?)` | JSON GET/POST; throws on non-OK / bad JSON |
| `fetchRes(url, opts?)` | Raw `Response`; `opts.timeoutMs` (default 12s) |
| `banner(el\|id, kind, title, detail?)` | Fill `.status-box` / `.banner` (`ok`/`warn`/`bad`/`info`) with monospace status badge + body; clears `[hidden]` |
| `showBanner` / `clearBanner` | Same fill / empty + `[hidden]` toggle (CSS forces `[hidden]`/`:empty` to `display: none` so flex banners take no space) |
| `setBusy(btn, busy, label?)` | Disable + busy label + `aria-busy` |
| `confirm(message)` | `window.confirm` wrapper for destructive / consequential actions |
| `stampUpdated(el\|id, ok)` | “Last updated …” / stale hint |
| `swapImg(img\|id, url, opts?)` | Double-buffer image swap — keep previous pixels until the new URL loads; optional `objectUrl` / `followNaturalAspect` |
| `setPreviewAspect(img\|id, w, h)` | Update wrapping `.preview-frame` aspect-ratio without collapsing height |

## UX conventions (operator pages)

- **One purpose per page** — header (`page_header`) states it; bodies stay service-scoped.
- **Primary vs secondary** — `.primary` for Save / Capture / Create; `.danger` for consequential (maintenance ON, restore placeholder); `.ghost` for Reload / Copy.
- **Confirm** before maintenance ON, restore default placeholder, switching the public livestream variant, and System reboot / shut down / restart webcam services.
- **System** (Pipeline home): `POST /system/reboot`, `/system/poweroff`, `/system/restart-services` with JSON `{"confirm":true}`; polkit `50-webcam-system.rules` (logind + restart of webcam-camera / webcam-pipeline / nginx only). Delayed ~1s so the 202 response can flush.
- **System health / Network / Recent logs** (Pipeline home, above System power): `GET /system/status` (disk free %, SoC temp, unit active state, last R2 publish age, NTP/clock, eth+wifi glance) and `GET /system/logs?lines=40` (fixed units `webcam-camera` + `webcam-pipeline` only). Journal read needs user `webcam` in group `systemd-journal` (provision/deploy). No unbound root shell.
- **Sticky actions** (`.actions-sticky`) on long forms (Schedule Save, Variants Preview/Save).
- **Stable preview boxes** (`.preview-frame`) — fixed aspect-ratio; Reload/Preview use `lanUi.swapImg` so the page does not jump while a new JPEG decodes. Variants: large `.mask-edit-stage` canvas for drag; compact `.preview-secondary` dry-run; hint (`.preview-hint`) sits above the dry-run only.
- **Mode panels** — Schedule shows solar *or* fixed fields based on mode (not both).
- **Empty states** — dashed `.empty-state` in galleries when no variants.
- **Gallery rows** — keyboard-focusable (`tabindex`, Enter/Space); livestream action is a nested button with `stopPropagation`.

Open LAN UI work items: [TODO.md](../TODO.md).

## Performance (Pi LAN)

Operator pages are small HTML shells (~23–40 KB) with inline CSS/JS from `shared/lan_ui`. The slow part is **JPEG + dry-run render**, not the shell.

| Lever | Behaviour |
|-------|-----------|
| Camera / health poll | **30 s** idle; **~750 ms** while **Live preview** is on (Camera home); pauses when the tab is hidden (`visibilitychange`) |
| Camera UI preview | `/raw.jpg?w=720` (always live; full `/raw.jpg` for aiming). **Start live preview** on Camera home: temporary high-rate capture (~0.75s, auto-off ~5 min / 300s) with countdown bar. Pipeline acquires `/raw.jpg`; private LAN-only is always raw-based. |
| Variants gallery | `/cameras/.../jpg?w=240` + `loading=lazy`; cache key = `jpeg_mtime_ns` (no `Date.now` bust) |
| Variants dry-run | **Preview button only** — no auto-preview on load/select (avoids PIL render every click) |
| Variant JPEG Cache-Control | Full-size / `?t=` (HA): `no-store`, never 304. Gallery `?w=` thumbs: `private, max-age=15` + ETag/304. Optional `?w=` downscale via `shared/jpeg_util.py` |
| HTML shells | `private, max-age=30` (process-static until service restart) |
| nginx `:80` | 301 → `:8080` only (no proxy weight) |

Do **not** lower capture/pipeline poll intervals for snappier LAN UI — that burns Pi CPU/R2; see [COST-PERF.md](COST-PERF.md).

## Add a new LAN page

1. Build the body with shared helpers (`card`, `status_placeholder`, …) — prefer classes over inline styles.
2. Wrap with `lan_ui.page("Title", body, active="<nav-id>")`.
3. If it belongs in the global nav, add an entry to `_NAV_CAM` or `_NAV_PIPE` in `chrome.py` and map `active` in `_body_svc_class`. For a new JSON/debug URL, add it to that port’s `_MORE_CAM` or `_MORE_PIPE` — not the other port’s list.
4. Keep copy English; use `lan_link(...)` for cross-port links (`data-lan-port`). Prefer nav More over body link spam for raw endpoints.
5. Extend camera/pipeline tests with key English strings + `nav-cam` / `nav-pipe` + `nav-more`.

Do **not** merge camera and pipeline processes — UI sharing only.
