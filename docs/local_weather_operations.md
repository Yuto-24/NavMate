# Local Weather Feed, Forecast Selection, and Backup Server Operations

This document holds operator CLI commands, build/installer boundaries, Cloudflare Access / environment settings for the compute-only backup API, and verification/acceptance notes for Local Weather, Forecast Selection, and Forecast Backup.

For reader-facing specifications, see:
- [forecast_selection.md](forecast_selection.md)
- [forecast_refresh.md](forecast_refresh.md)
- [local_weather.md](local_weather.md)
- [forecast_backup.md](forecast_backup.md)

## 1. Static MSM / GSM feed generation CLI

Produce static weather feeds with the Python environment (including native dependencies such as `pygrib`) or the `weather-feed` Docker target:

```bash
# Local Python environment
python scripts/prepare_msm_feed.py --output /tmp/msm-feed --cache /tmp/msm-source-cache
AUTONAVLOG_MSM_FEED=/tmp/msm-feed npm --prefix web run build:local

# Reproducible producer container (bind-mount output and cache)
docker build --target weather-feed -t autonavlog-weather-feed .
```

- Default arguments produce 24 hours from the current UTC hour over library default bounds for the latest 2 compatible Runs (`--start`, `--hours`, `--bounds`, `--max-runs` override).
- Production updates use `--full-run` (retaining the latest Run meeting the 25-hour admission window and generating up to each Run's available horizon; normally up to 3 Runs).
  - **Code note**: `scripts/prepare_msm_feed.py`'s `full_run_requirements()` currently caps scanning at MSM's `MAX_FORECAST_HOURS` (`78` hours) and does not cover GSM's longer 132/264-hour horizons (see [wx_profile_feasibility.md](wx_profile_feasibility.md#現行コード文書の相違と後続)).
- If full-domain generation fails, preserve the existing catalog rather than publishing a shortened payload as complete.
- To enable full GSM fallback evaluation when the normal 2-Run MSM feed is insufficient to prove all MSM candidates are out of altitude coverage, publish candidate Runs with e.g. `--max-runs 32` rather than hiding unevaluated older Runs.
- **Manual GSM feed generation** (never added to the scheduled MSM workflow):

  ```bash
  python scripts/prepare_msm_feed.py --model GSM --output /tmp/gsm-feed --cache /tmp/gsm-cache \
    --start YYYY-MM-DDTHH:00:00+00:00 --hours 24 --bounds 29.7 35.2 128.5 134.8
  AUTONAVLOG_MSM_FEED=/tmp/msm-feed AUTONAVLOG_GSM_FEED=/tmp/gsm-feed npm --prefix web run build:local
  ```

- `prepare_local.py` removes stale generated feeds when feed env vars are omitted.

## 2. Weather library wheel and installer contract

- Tooling and the current application use the vendored `jma-gpv-weather==0.6.0` wheel (`vendor/README.md`).
- When rebuilding an older approved application for a forecast-only update, resolve that application's own single vendored weather wheel with its exact `pyproject.toml` pin; do not force a newer tooling pin onto an older approved checkout.
- Missing or ambiguous candidate wheels stop the build; `pip` rejects pin mismatches (`test_candidate_weather_dependency.py`).
- Upstream delivery record (2026-09-26 JST): [jma-gpv-weather PR #19](https://github.com/Yuto-24/jma-gpv-weather/pull/19) (`208f288fc95bcd1d1e951e7b62046b490d1b7958`, v0.6.0; 239 upstream tests + live RISH GSM 264h crop + Pyodide Node/Chromium round-trip); AutoNavLog integration tracked in [PR #217](https://github.com/Yuto-24/AutoNavLog/pull/217). Synthetic GSM policy fixtures are documented in [tests/fixtures/forecast-policy-README.md](../tests/fixtures/forecast-policy-README.md).
- **Library / cache / error-code technical contract**:
  - Model selection exceptions: `REQUIRES_HGT` proceeds to prepare; only `ALTITUDE_OUTSIDE_HGT_RANGE` from post-prepare API allows MSM→GSM altitude fallback; `SOURCE_VALUE_UNAVAILABLE` is a processing failure.
  - Project Schema 5 adds `selected_forecast_model` (migrating Schema 4 Run-only records to `MSM`), separated from `forecast_selection_fingerprint`.
  - Browser Cache Storage namespaces: `autonavlog.weather.msm.v1` / `autonavlog.weather.gsm.v1` (evicted together via `autonavlog.weather.*` callback on IndexedDB quota retry).
  - Fetch replay bounds: max 128 acquisition replays and 4 model-switch recalculations; `credentials: "omit"` on static feeds.
  - Error codes: `FORECAST_UNAVAILABLE`, `WEATHER_DISCOVERY_FAILED`, `WEATHER_COMMUNICATION_FAILED`, `WEATHER_SOURCE_UNAVAILABLE`, `WEATHER_TRANSPORT_FAILED`, `WEATHER_DOWNLOAD_FAILED`, `WEATHER_RUN_UNAVAILABLE`, `WEATHER_PREPARED_UNAVAILABLE`, `WEATHER_CATALOG_INVALID`, `WEATHER_CATALOG_EXPIRED`, `WEATHER_PAYLOAD_INTEGRITY_FAILED`, `WEATHER_CACHE_CORRUPT`, `WEATHER_PROCESSING_FAILED`.
  - CALM normalization records `CALM_WIND_DIRECTION_UNDEFINED` and `calm_normalization.original_values`.

## 3. Real MSM acceptance commands and merge gates

### Reproducible desktop vs. browser differential command

Generate a fresh feed and pass the same `--flight-date` and `--departure-time` to both the reference generator and browser verifier:

```bash
python scripts/local_reference.py --feed /tmp/msm-feed --native-cache /tmp/msm-source-cache \
  --flight-date YYYY-MM-DD --departure-time HH:MM > /tmp/reference.json
# Run on Windows Node; CDP targets a dedicated loopback Edge/Chromium profile
node --experimental-strip-types web/scripts/accept-local-weather.mjs \
  --cdp http://127.0.0.1:9227 --url http://localhost:4179 \
  --flight-date YYYY-MM-DD --departure-time HH:MM --reference /tmp/reference.json --output /tmp/acceptance.json
```

### Physical iPhone/iPad Safari gate and 2026-09-16 evidence

- **Merge / release gate**: Complete at least one fresh real-MSM `FORECAST` run on physical iPhone/iPad Safari with no OOM, unexpected reload, or crash, and confirm Project / Last Calculation retention on Weather failure. Windows or Playwright WebKit runs do not substitute for this gate.
- **2026-09-16 observations**:
  - Windows Edge `153.0.4234.32` (Win32) vs static production build (no fixtures, `/api/**` aborted): cold Weather body 5,629,561 bytes (warm 0 bytes), cold calc 1,744 ms (warm 424 ms), max process-tree RSS sample ~1,147–1,175 MB, 2-Run native decode 36.8 s / 308,048 KiB max RSS, parity within `1e-8` ([windows-acceptance.json](evidence/issue-144/windows-acceptance.json), [producer.json](evidence/issue-144/producer.json); CORS rejection evidence in [windows-source.json](evidence/issue-144/windows-source.json)). Single-host single-trial only; not a mobile memory guarantee.
  - Physical iPad Safari cold/warm fresh real-MSM completion and failure retention recorded in [ipad-safari-acceptance.md](evidence/issue-144/ipad-safari-acceptance.md).
- For offline live-MSM release validation, see [real_msm_acceptance.md](real_msm_acceptance.md).

## 4. Compute-only Forecast Backup Server configuration and verification

The compute-only backup API (`PUT/GET /api/forecast-backup/jobs/{UUID}`) is **disabled by default** and requires explicit approval and pre-production checks before activation.

### Environment configuration

- **Server**: `AUTONAVLOG_FORECAST_BACKUP_ORIGIN=https://navmate.yuto24.com` (if unset, backup routes are not registered).
- **Browser build**: `VITE_FORECAST_BACKUP_URL=https://navlog.yuto24.com/api/forecast-backup/jobs/` (if unset, normal weather failure shows backup-unconfigured status).
- **Trusted proxies**: `AUTONAVLOG_FORECAST_BACKUP_TRUSTED_PROXIES` (empty by default). Set CIDRs **only** when the gateway overwrites `CF-Connecting-IP` and direct origin connections are blocked; otherwise socket IP applies and proxied users share one client bucket.
- **Runtime parity**: Server must run the exact same revision, calculation engine, native MSM dependencies, and reference/performance data as the Static Web client; older `release/1.x` runtimes are not guaranteed compatible.

### Cloudflare Access exposure and rollback

- Only expose `/api/forecast-backup/jobs/*` on the existing host `navlog.yuto24.com` (allowed methods: `GET`, `PUT`, `OPTIONS`; allowed origin: `https://navmate.yuto24.com`; allowed headers: `Content-Type`, `X-AutoNavLog-Request`).
- **Never** widen Cloudflare Access exceptions to old UI, `/api/session`, editing, saving, or `/api/navmate-migration/*` routes.
- Verify host/runtime parity, Access exception scope, origin defense, trusted proxy headers, edge rate limits, live MSM fetch & post-prepare coverage, normal recovery, and continued outage monitoring before enabling.
- **Rollback**: Close the `/api/forecast-backup/jobs/*` Access exception, unset `AUTONAVLOG_FORECAST_BACKUP_ORIGIN` and `VITE_FORECAST_BACKUP_URL`, and revert to normal Local-only behavior without deleting saved data or `autonavlog-data` volumes.

### Backup verification tests

- `tests/integration/serve_forecast_backup_fixture.py`: loopback fixture server using historical portable MSM (does not prove live MSM fetch).
- `tests/unit/test_forecast_backup.py`: isolation, size/rate/concurrency/deadline limits, compatibility checks, corrupt results.
- `web/e2e/forecast-backup.spec.ts` / `web/e2e/forecast-backup-unit.spec.ts`: browser adapter, Pyodide, Local save/reload, normal recovery, and input/account change cancellation.
