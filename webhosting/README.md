# Public site (Cloudflare Worker + assets)

1. Copy [`examples/webhosting/wrangler.jsonc`](../examples/webhosting/wrangler.jsonc) values into `wrangler.jsonc` (account, route, bucket). Keep `workers_dev` and `preview_urls` false once the custom domain works.
2. Set `LIVE_MAP` in `worker/src/index.ts` to match `publish.public_live_key` in your camera YAML.
3. Replace `site/` with your landing page, icons, `robots.txt`, and `sitemap.xml`.

Local preview: `cd webhosting && npx wrangler dev` → http://127.0.0.1:8787/
