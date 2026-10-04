# Public web hosting

Template Worker + minimal `site/` for a public live JPEG.

1. Set `LIVE_MAP` in `worker/src/index.ts` to match `publish.public_live_key`.
2. Edit `wrangler.jsonc` (see `examples/webhosting/`).
3. Replace `site/` with your landing copy.
4. `npx wrangler deploy`

Local: `npx wrangler dev` → http://127.0.0.1:8787/
