# Cost & performance (Free-first)

Target stack: **Workers Free + R2 Free + no Cloudflare Images**. Optimizations below are already reflected in defaults.

## Knobs that matter most

| Lever | Default now | Effect |
|-------|-------------|--------|
| Pipeline `poll_interval_seconds` | **60** | LAN acquire/render cycle; skips R2 when bytes unchanged |
| Weather / site-badge `ttl_seconds` | **300** (5 min) | Temp on badge; placeholder **Uhrzeit** still refreshes every minute |
| History upload | **off** | Live JPEG still publishes. Day frames stay on the Pi (`timelapse` in camera.yaml) |
| History `retention_days` | **90** | Cap Class B list + storage; `scripts/prune-history.py` |
| Wide variant `publish: false` | on | Only landscape hits R2 |
| Public JPEG size/quality | 1600×900 @ q80 | Smaller objects, faster uploads/downloads |
| Pi capture interval | **30s** | Less Pi CPU/SD; still fresh for 60s poll |
| Conditional GET (ETag) | on | Skip download when Pi image unchanged; still re-render public badge/clock |
| Worker live JPEG `Cache-Control` | **max-age=60, stale-while-revalidate=30** | Matches placeholder Uhrzeit republish (~1 min) |
| Workers Caching (`cache.enabled`) | **on** | Edge HIT skips Worker invoke + R2 Class B |
| Landing refresh JS | **next minute + random 15–45s**, stable URL | Per-tab jitter avoids :05 stampede; usually after irregular publish (~:10–:15); no `?t=` bust; `If-None-Match` |
| Static HTML | max-age=60, s-w-r=600 | `_headers`; asset-first (no Worker) |
| Favicons / OG / branding PNG | **7d immutable** | `_headers`; cheap static hits |

## Public edge caching (intentional tradeoffs)

1. **Freshness ≈ live overwrite** — Wartung / night placeholders republish at least every **minute** with a fresh wall-clock `YYYY-MM-DD HH:MM` (+ site/temp badge). Edge `max-age=60`; landing JS refreshes at **next minute + random 15–45s** (per tab) so clients spread and usually land after upload. Live camera frames still skip R2 when bytes are identical.
2. **No cache-busting query** — Unique `?t=` keys defeat Workers Caching (path+query is the cache key). The landing uses the bare `/example-live-webcam.jpg` URL; any query is **302**’d away.
3. **503 is `no-store`** — Missing live object must not be cached while publish is catching up.
4. **Worker miss returns 200 + body** — So the edge can store a full entry; browsers/CDN still do ETag/304 on subsequent revalidations without a Class B each time.
5. **`cross_version_cache: true`** — Live bytes come from R2, not Worker code; keep warm cache across deploys (max ~1 min stale after a cache-affecting change is acceptable).
6. **Static vs Worker** — HTML/icons are asset-first + `_headers`. Only live JPEG (and blocked `/history` `/original`) hit the Worker script.

## Approximate R2 write load (one camera, landscape only)

- Live overwrite (Wartungsbild / night placeholder): ~1 Class A / min via Uhrzeit → ~43k/month; live camera with changing frames similar; static live frame + steady temp → far fewer
- History: ~1 Class A / 5 min → ~8.6k/month
- If you tighten history to 15 min: ~3k/month

### Live Class B / Worker requests (order of magnitude)

| Scenario | Before (bust + no-store) | After (stable URL + edge cache) |
|----------|--------------------------|----------------------------------|
| One open tab | ~1 Worker + 1 Class B / 60s | ~1 network revalidate / 60s; edge HIT → **0** Class B most ticks |
| Many viewers, same POP | N × Class B / 60s | ~1 Class B / 60s per POP (tiered cache + collapsing) |
| Hotlink / embed | Same as above if they use the clean URL | Same; `?t=` embeds get 302 then share the clean key |

Watch the R2 Free dashboard if you add cameras or lower intervals.

## Pipeline behaviour (perf)

1. `If-None-Match` / `If-Modified-Since` → Pi may return **304** → reuse original; still refresh public site-badge / Wartung Uhrzeit when those change.
2. SHA unchanged → render cache hit unless maintenance clock minute or site-badge text changed → no R2 put.
3. `publish: false` or missing `r2_live_key` → local only (HA can still use wide/private).
4. Wartung / night placeholders burn **wall-clock date+time** (`YYYY-MM-DD HH:MM`, same as live burn-in) + station temp (not a frozen capture timestamp); republish when the minute or temp label changes.

## Pi behaviour (perf)

- Capture every 30s; pipeline polls every 60s (always a recent frame without capturing every second).
- JPEG quality 88 on full sensor; public downscale happens on the LAN host.
- Quiet success logs (INFO every N captures).
- **LAN UI:** do not auto dry-run variant previews; gallery/camera previews use `?w=` thumbs; poll ~30s and pause when the tab is hidden — see [LAN-UI.md](LAN-UI.md) § Performance.

## What not to do on Free

- Cloudflare Images overlay on every live frame (5k unique transforms/month).
- Publishing every variant to R2.
- History every poll (use `min_interval_seconds`).
- Sub-minute client poll “for smoothness” — browser cache + ~1 min placeholder Uhrzeit is enough for a village sky.
- Client `?t=` / `cache: "no-store"` refresh loops — burns Worker + Class B with no freshness gain over max-age=60.

## Tuning later

```yaml
# cameras/example/camera.yaml
poll_interval_seconds: 120          # slower live
publish:
  history:
    min_interval_seconds: 900       # 15 min timelapse frames
```

```yaml
# wide-public.yaml — enable R2 only if you need it
publish: true
output:
  r2_live_key: live/example-wide-webcam.jpg
```
