# MSM renewal recovery audit — 2026-10-08 JST

> **日付付き復旧準備監査（2026-10-08 時点）**: 2026-09-28 に失効していた本番 MSM カタログの再生成準備とコンテナ隔離検証を記録したものです。現在の運用手順は [static_operations.md](../../static_operations.md) を参照し、当時のカタログ時刻や未設定状態を現在の本番状態として扱わないでください。

**再利用可能な教訓と検証境界**:
- 本番カタログが 7 日以上前に失効していた場合、7 日保持復元（retention restore）は 0 件となり、完全な新規取得による再構築が必要になる。
- 候補ビルドコンテナ（Docker）とホスト側検証・アップロード基盤の境界分離（tooling マウントなし、Docker socket なし、トークンなし、feed は read-only）を実コンテナ検証で確認した。
- ローカル Wrangler OAuth の期限切れによる Pages 管理 GET 401 が残っていても、公開 `release.json` の一致だけでは Pages 管理状態（進行中デプロイ・Functions 有無等）を代替できない。

## Production reads at 2026-10-08 01:16 JST (2026-10-07 16:16 UTC)

Observed at 2026-10-08 01:16 JST (2026-10-07 16:16 UTC), using existing GitHub
authentication and canonical HTTPS reads. Secret endpoints were used for **names only**;
no secret value was retrieved or printed. Public configuration was compared internally.

- Repository is public. PR #239 remote HEAD was exactly
  `7e3d44101212439cf5346f01509cd3d7d0b2e175`; no advance from the supplied HEAD.
- Origin is `https://navmate.yuto24.com`; expected Pages project is `navmate`.
- Production is clean version `1.20.1`, commit
  `a4de2a226dfa205b8be42fb62a710a1b06271ed8`, matching `STATIC_APPROVED_SHA`.
- All six public `VITE_*` configuration entries match repository variables. The three
  publication/validation environments have no variable overrides. Existing Pages-token
  metadata is present in production/publication, absent from validation.
- Served `release.json` SHA-256:
  `518bc7cf5d8e18775597d1a757ff238cbe85bfb4e2afb8fad196a8d7ace42782`.
- Catalog matches its release inventory, but is **expired**: generated
  `2026-09-28T14:55:46.203544Z`, expires `2026-09-28T20:55:46.203544Z`, six assets.
  These dates were obtained in this audit; their old freshness is not a current pass.
- `STATIC_AUTOMATION_ENABLED` / `STATIC_MONITOR_ENABLED` are unset.
- Pages management GET with the existing local OAuth returned **HTTP 401**. Actual
  project/deployment ID/production branch/runtime settings/in-flight work are UNKNOWN.
  Public release identity is not a substitute for this management evidence. No token
  renewal, new auth, permission or billing change was attempted.

## Local real-MSM build-only evidence

The trusted existing producer obtained Runs `20261007060000` and `20261007090000`.
The expired production catalog had no assets within the seven-day retention window;
restoration retained zero assets for this run. Rolling retention remains implemented
and covered by isolated tests; this particular live sample does not prove retained reuse.

- Newly generated catalog: `2026-10-07T16:26:36.310554Z`, six-hour expiry
  `2026-10-07T22:26:36.310554Z`. These are **time-bound local evidence**, not production.
- Hash/byte checks and native payload decoding pass for both Runs. The native library
  verifies wind, aloft temperature and surface temperature coverage from
  `2026-10-07T16:00:00Z` through the next 24 hours.
- A clean checkout of the currently approved application SHA and the matching public
  settings built successfully inside the candidate sandbox (Python 3.12 / Node 24).
  Production Browser E2E passed **10 tests**, including served real-MSM calculation,
  weather-failure retention, saved NAV LOG/reload and browser-process restart.
- Independent host inventory/configuration/private-material validation and isolated
  upload staging pass. The candidate has 142 files; `release.json` SHA-256 is
  `dc33cfe2f0c3c220a2cab201b79181fa7823e0b57874e6809af08476f272eda9`.
- Real Docker boundary checks confirm no tooling mount, Docker socket, provider token or
  runner output-command files; the mounted feed rejects writes. Candidate pip/npm/build
  code runs in that container, while validators/upload tooling stay on the host.
- Scoped operations/collection/retention/verification tests: **358 passed**. Independent
  model review confirmed runtime/private-material rejection and resolved the initial
  candidate-can-replace-validator finding by container isolation and stdlib validation.
- Full local Docker CI: **1,491 passed / 1 warning**, Ruff, mypy (77 files), release,
  performance/runtime data, schema and sdist/wheel checks pass. Web Application tests
  **89 passed**, static artifact/release-notes tests, typecheck and build pass. Six
  additional sealed-Worker/secret/expired-artifact regressions pass after that full run.
- Isolated Compose runtime `autonavlog-wt-84b51acb` is healthy at
  `http://127.0.0.1:45174`, version `1.22.5`. Its generated named volume is retained;
  the primary working directory, `.codex/` and primary runtime/volume were untouched.

## 2026-10-08 時点の残ゲートと限界

- Pages project / 現行デプロイ / 進行中状態は 401 のため未確認であり、公開前に管理 API の再取得が必要と判定した。
- 本ローカルビルドとブラウザ E2E（10 件）は時間制限付きのローカル証拠であり、定期実行・本番配信・クオータ取得（#281）の受入を代替しない。失効したローカルカタログの再利用は禁止とし、公開承認後に新規生成する条件とした。
