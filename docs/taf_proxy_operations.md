# Destination TAF Proxy: Operations, Deployment, and Verification

This document holds operator deployment, Cloudflare Workers Free capacity estimates, release checks, and verification records for the Destination TAF Serverless Proxy (`services/taf-proxy`). For the reader-facing specification and failure/abuse-control boundaries, see [taf_proxy.md](taf_proxy.md).

## Workers Free estimate and zero-cost boundary (checked 2026-09-16)

Cloudflare Workers Free was selected (single ES module using standard Fetch, Cache API, and native rate limiting binding; no framework, KV, D1, Durable Objects, custom auth, or secrets; `workers.dev` removes the need for a custom domain).

Official limits observed on **2026-09-16** (re-verify at release time; do not treat as permanent):

| Item | Workers Free limit | Proxy budget |
| --- | --- | --- |
| Account daily requests | 100,000 / day (00:00 UTC reset) | 1 request per TAF fetch (cache hits and rejections also count) |
| CPU | 10 ms / invocation (I/O wait excluded) | Small JSON validation and header addition only; check metrics after deploy |
| Memory | 128 MB | 64 KiB / body, 4 concurrent upstream / isolate |
| External subrequests | 50 / invocation | Max 1, no redirects or retries |
| Concurrent external connections | 6 / request | Max 1 |
| Quota exceeded | Error 1027 | Browser marks TAF `UNAVAILABLE`; calculation and save continue |

References: [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/), [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [Rate Limiting binding](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/), [Cache API](https://developers.cloudflare.com/workers/runtime-apis/cache/). (The old `workers.dev` Cache API restriction was removed in [cloudflare-docs commit 935b0366c6ca](https://github.com/cloudflare/cloudflare-docs/commit/935b0366c6ca).)

Capacity assumption (illustrative planning example, not live user counts): **100 users × 20/day = 2,000 requests/day** (2% of daily free tier; 20,000/day at 1,000 users). Combine all Workers sharing the Cloudflare account. Continuous queries for one airport with an active edge cache produce roughly 12 upstream requests/hour/edge location, increasing with eviction, multiple locations, or multiple airports.

Operate strictly on the **Free plan**. Do not treat rate limiters or CPU settings as billing caps; use a Free account and accept `UNAVAILABLE` until daily reset if quota is exhausted. Never require paid upgrades or automatic billing.

## Configuration and deployment

1. Confirm in the Cloudflare dashboard that the target account is on **Workers Free** and check other Workers' quota usage.
2. Run `npm --prefix services/taf-proxy ci` and `npm --prefix services/taf-proxy run check` using the pinned Wrangler.
3. Copy `services/taf-proxy/wrangler.jsonc` to ignored `services/taf-proxy/wrangler.local.jsonc` and set `ALLOWED_ORIGINS` to the production Static Web origin (scheme + host + optional port, no trailing slash).
   - **Value must be a string** (comma-separated for multiple origins, never a JSON array, because the Worker calls `.split(",")`).
   - Do not include wildcards or `localhost` in production. Keep the tracked template empty (fail closed). If `wrangler.local.jsonc` already exists, edit only the target key rather than overwriting.
   - Ensure the Rate Limiting namespace ID does not collide with other Workers in the account.
4. Operator logs in with Wrangler, verifies the target account, and runs:
   `npm --prefix services/taf-proxy run deploy -- --config wrangler.local.jsonc`
   Production deployment requires explicit approval. No secret is needed for TAF execution itself.
5. Set `VITE_TAF_PROXY_URL` to the deployed `https://autonavlog-taf.<subdomain>.workers.dev/taf` URL when running `npm --prefix web run build:local` (or `build:static`). This URL is public, not a secret.
6. Verify GET and destination TAF display from the Static Web origin. Keep the `workers.dev` endpoint independent; do not add fail-open routes on NavMate or AviationWeather origins.

For the #123 canonical origin (`https://navmate.yuto24.com`), the final value in ignored `wrangler.local.jsonc` is `"ALLOWED_ORIGINS": "https://navmate.yuto24.com"`. During cutover validation only, a temporary dual-origin CSV `"https://navmate.pages.dev,https://navmate.yuto24.com"` may be used (this is temporary TAF compatibility only, not multi-origin Legacy migration). Remove the old origin after redirect and verify canonical success and old-origin rejection; see [custom_domain_cutover.md](custom_domain_cutover.md).

## Local verification commands

```bash
npm --prefix services/taf-proxy run dev -- --ip 127.0.0.1 --port 8787 --var ALLOWED_ORIGINS:http://127.0.0.1:4145
VITE_TAF_PROXY_URL=http://127.0.0.1:8787/taf npm --prefix web run build:local
python3 -m http.server 4145 --bind 127.0.0.1 --directory web/dist-local
AUTONAVLOG_LOCAL_URL=http://127.0.0.1:4145 npm --prefix web run test:taf
```

Note: `test:taf` uses controlled fixtures for responses, quota, timeouts, and outages; it is distinct from live upstream smoke checks. Fixed #125 MSM fixtures may legitimately report `TAF_TIME_OUT_OF_RANGE` against live TAF validity windows.

## Release checklist

- [ ] Re-verify Cloudflare pricing/limits, native rate binding, and AviationWeather.gov limits; record date and changes.
- [ ] Confirm account is on Workers Free with no paid-plan auto-billing enabled.
- [ ] Confirm combined daily request headroom across all Workers (accounting for cache hits, rejections, and abuse).
- [ ] Verify origin allowlist, public TAF URL, namespace ID, and independent endpoint.
- [ ] Run Proxy unit / `workerd` tests, Application tests, Python selection/invariance tests, and Static Browser tests.
- [ ] On the live deployment, verify CPU time stays within Free limits and live TAF/CORS responses succeed.
- [ ] Fetch the same ICAO with an allowed `Origin` twice from a non-browser client (e.g., `curl`) a few seconds apart: the second request must return HTTP 200, a shorter `max-age`, and the same TAF. A `429` within 1 minute indicates edge caching is not working and blocks release. Also confirm re-fetch after TTL expiry.
- [ ] Verify upstream errors, timeouts, 429 / Error 1027 equivalents, and proxy outage leave only TAF `UNAVAILABLE` while calculation, save, reload/reopen, Project, and Last Calculation remain intact.
- [ ] Test quota exhaustion using fixtures rather than load-testing live free quota.

## Implementation verification notes (2026-09-16)

- Official `workerd` tests verified fixed upstream, CORS, cache hits, native rate binding, and redirect rejection; Node unit tests verified size, header/body timeouts, concurrency limits, and invalid queries.
- Live AviationWeather.gov fetch from local Worker for RJFM returned HTTP 200 (1 record, 1,935 bytes); Chromium on static origin `http://127.0.0.1:4145` read the record via CORS with 300 s TTL.
- Real Pyodide / IndexedDB verified TAF success → simulated 1027 (503) → 7 s timeout → network cut → reload → recovery with invariant NAV LOG navigation/fuel and retained checkpoint/Last Calculation.
- Dry-run bundle size: ~5.12 KiB (gzip ~1.88 KiB).
- **Note**: Production Cloudflare account deployment, live origin connection, and Cloudflare-side CPU metrics require separate release approval and remain production release gates.
- **Endpoint / error-code contract**: `GET /taf?icao=<ICAO>` (`VITE_TAF_PROXY_URL`); client maps missing/invalid config to `TAF_PROXY_NOT_CONFIGURED`, 7 s deadline to `TAF_FETCH_TIMEOUT`, and network/HTTP/CORS/quota/invalid payload to `TAF_FETCH_FAILED` (each maps to destination TAF `UNAVAILABLE` without blocking calculation).
- `crowd.test.mjs` simulates 100-user school-IP warm/cold cache, 8 airports, 4 isolated proxy instances, cache-write coalescing, absolute TTL transition, TAF AMD, empty 200/204, 429, timeout, and malformed/mismatched responses without hitting live AviationWeather.gov. (Chronest uses a separate direct path and is unaffected.)
