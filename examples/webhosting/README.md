# Public site template

`webhosting/` holds the Worker + landing for *your* public site. Template notes:

1. Copy [`wrangler.jsonc`](wrangler.jsonc) over `webhosting/wrangler.jsonc` and set your account, zone, and bucket. After the custom domain works, keep `workers_dev` and `preview_urls` false.
2. In `webhosting/worker/src/index.ts`, change `LIVE_MAP` so the public path matches `publish.public_live_key` in the camera file. Example:

```ts
const LIVE_MAP: Record<string, string> = {
  "/example-live-webcam.jpg": "live/example-live-webcam.jpg",
};
```

3. Replace `webhosting/site/` (HTML, icons, `sitemap.xml`, `robots.txt`) with your own pages. Do not publish someone else's logo or photo.
4. Local preview: `cd webhosting && npx wrangler dev` → http://127.0.0.1:8787/
