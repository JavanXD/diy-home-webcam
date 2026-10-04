/**
 * Public webcam Worker — live JPEG + 404 for private prefixes.
 * Static landing/favicons/branding are asset-first (`site/` + `_headers`).
 * SEO files (`/robots.txt`, `/sitemap.xml`) run Worker-first and are served from
 * ASSETS so a cross_version_cache HIT of a pre-upload 404 cannot stick.
 * Public responses must stay visitor-safe: no storage, pipeline, or debug details.
 *
 * Workers Caching (`cache.enabled` in wrangler) honors Cache-Control on this
 * Worker's responses so edge HITs skip both Worker CPU and R2 Class B.
 */

export interface Env {
  WEBCAM_BUCKET: R2Bucket;
  ASSETS: Fetcher;
}

const LIVE_MAP: Record<string, string> = {
  "/example-live-webcam.jpg": "live/example-live-webcam.jpg",
};

/**
 * Align with pipeline placeholder / live overwrite cadence:
 * camera poll_interval_seconds (typically 60). Wartung/Nacht frames
 * republish at least every minute with a fresh Uhrzeit overlay; weather
 * badge still TTL 300s. Landing REFRESH_MS uses 60s + small skew.
 */
const LIVE_CACHE_SECONDS = 60;
/** Serve stale while one edge refresh runs (request collapsing / soft TTL). */
const LIVE_SWR_SECONDS = 30;

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    // Worker-first (see wrangler run_worker_first) — serve from assets with their
    // Cache-Control so SEO discovery is not a sticky empty 404.
    if (path === "/robots.txt" || path === "/sitemap.xml") {
      return env.ASSETS.fetch(request);
    }

    const objectKey = LIVE_MAP[path];
    if (objectKey) {
      // Query strings are part of the Workers Caching key — collapse busting.
      if (url.search) {
        url.search = "";
        return Response.redirect(url.toString(), 302);
      }
      return serveLiveJpeg(env.WEBCAM_BUCKET, objectKey, request);
    }

    if (path.startsWith("/history/") || path.startsWith("/original/")) {
      return new Response("Not Found", { status: 404 });
    }

    // Asset-first serves site/; this is a fallback if the Worker still runs.
    return env.ASSETS.fetch(request);
  },
} satisfies ExportedHandler<Env>;

async function serveLiveJpeg(
  bucket: R2Bucket,
  key: string,
  request: Request,
): Promise<Response> {
  const object = await bucket.get(key);
  if (!object) {
    // Visitor-facing only — never expose keys, storage, or ops hints.
    // no-store: do not cache "missing" at the edge while publish catches up.
    return new Response("Image temporarily unavailable\n", {
      status: 503,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-store",
      },
    });
  }

  // Always return a full 200 on Worker miss so Workers Caching can store the
  // body. Conditional 304 for matching ETags is handled at the edge / browser.
  const headers = new Headers();
  headers.set("Content-Type", "image/jpeg");
  headers.set(
    "Cache-Control",
    `public, max-age=${LIVE_CACHE_SECONDS}, stale-while-revalidate=${LIVE_SWR_SECONDS}`,
  );
  if (object.httpEtag) headers.set("ETag", object.httpEtag);
  if (object.uploaded) {
    headers.set("Last-Modified", object.uploaded.toUTCString());
  }

  if (request.method === "HEAD") {
    return new Response(null, { status: 200, headers });
  }
  return new Response(object.body, { status: 200, headers });
}
