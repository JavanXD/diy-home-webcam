# Free-plan public branding

**Decision:** Brand on the public **landing page** with an HTML/CSS chip (site name + optional link). Do **not** composite a logo watermark onto the live JPEG on the Free plan (no Cloudflare Images).

## JPEG burn-in

Public variants may enable a small **site badge** (hostname · outdoor °C) via `site_badge` in the variant YAML. Keep `watermark.enabled: false` on public variants unless you host your own logo assets.

## Landing

Replace `site/index.html` with your own chip, favicons, and copy. Do not ship someone else’s logo.
