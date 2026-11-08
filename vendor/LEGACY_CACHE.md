# Legacy native weather extension

The original `jma_gpv_weather-0.5.0-py3-none-any.whl` remains unchanged for Static
Web/portable assets and the weather-feed producer. Docker test/runtime installs
`jma_gpv_weather-0.5.0+legacycache.1-py3-none-any.whl` instead, a maintenance build
from the existing 0.5.0 source plus opt-in desktop cache recovery.

Source commit: `4ed0588` in `Yuto-24/jma-gpv-weather`.
Base: `585bca6a912a5f61b9d15271761374f2a7224389`.
SHA-256: `9b99d5e45b732a70f8dd1d649f8125b0176fda69ad2bf2033b5c80e834ed8626`.
Build: `uv build --wheel`; Python dependency requirements are unchanged.
The distribution local version identifies the patch; `__version__` retains the
base API contract 0.5.0. Legacy records both the API version and package build.

Only `LegacyMsmWeatherProvider` opts into `CachedMsmClient`. State is per session,
reset once per user calculation including its TAF iterations, and independently
reset on each prewarm cycle. Raw/normalized disk cache remains shared under the
existing library locks. This changes the previous process-wide provider sharing
only as needed to isolate each calculation's acquisition state.

After a listing refresh fails, saved listings identify only locally complete Runs.
A fixed Run remains fixed; an unpinned request selects the newest complete cached
Run. No date substitution, extrapolation or download occurs during recovery.
Missing/invalid data still fails and preserves Last Calculation. The same final
coverage check remains in force. Next action retries ordinary acquisition.

The warning was determined using Gemini via agy 1.5.3, model
`gemini-4-argon-high`, conversation `4641074a-c005-4fad-884d-7732361158c8`.
Its status and actual Run are saved with the calculation and shown through the
existing warning renderer; no frontend layout or Static Web change is required.
