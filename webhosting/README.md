# Public webhosting (Cloudflare Worker + R2)

## Live

- https://webcam.ferienpark-schellbronn.de/
- https://webcam.ferienpark-schellbronn.de/schellbronn-live-webcam.jpg
- https://webcam.ferienpark-schellbronn.de/sitemap.xml (landing URL for Google)
- https://webcam.ferienpark-schellbronn.de/robots.txt (`Allow: /` + Sitemap)

Worker serves `/robots.txt` and `/sitemap.xml` via `run_worker_first` (assets body) so they are not stuck behind a Workers Caching HIT of an old 404 when `cross_version_cache` is on.

## Local

```bash
cd webhosting
npm install
npx wrangler dev
```

- Local: http://127.0.0.1:8787/

## Deploy

Uses Bollenhut account (`account_id` in `wrangler.jsonc`).

**GitHub Actions:** push to `main` under `webhosting/` (or run **Deploy Worker** → workflow_dispatch). Needs repo secrets `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` (from `~/Projects/.secrets/bollenhuthaus.env`).

```bash
# Create bucket once (if missing) — also: ./scripts/setup-r2.sh
npx wrangler r2 bucket create schellbronn-webcam

# Manual deploy
npx wrangler deploy
```

`workers_dev` and `preview_urls` are disabled — public entry is the custom domain only.

**Caching (Free quota):** Workers Caching is on for live JPEG (`Cache-Control: public, max-age=60, stale-while-revalidate=30`). Landing JS refreshes at **next minute + random 15–45s** (per tab) on the **stable** image URL (no `?t=` bust) — spreads clients; usually after irregular publish (~:10–:15). Static HTML/icons: `site/_headers`. Details: [../docs/COST-PERF.md](../docs/COST-PERF.md).

**Cutover steps:** [docs/CUTOVER.md](../docs/CUTOVER.md)  
**Smoke after deploy:** `./scripts/smoke-public.sh`

**R2 history prune:** weekly workflow `Prune R2 history` (needs `AWS_*` + `R2_BUCKET` secrets from `schellbronn-webcam-r2.env`).

## Branding (Free)

**HTML landing only** — see [docs/FREE-BRANDING.md](docs/FREE-BRANDING.md).  
Cost/perf: [../docs/COST-PERF.md](../docs/COST-PERF.md).


| Key | Purpose |
|-----|---------|
| `live/schellbronn-live-webcam.jpg` | Latest public landscape |
| `live/schellbronn-wide-webcam.jpg` | Latest public wide |
| `history/schellbronn/<variant>/YYYY/MM/DD/HHMMSS.jpg` | Timelapse source frames (not publicly listed) |

Pipeline uploads with S3-compatible credentials (see `pi/pipeline/config/pipeline.example.yaml`).
