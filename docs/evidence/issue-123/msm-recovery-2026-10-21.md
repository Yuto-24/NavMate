# MSM recovery publication preparation — 2026-10-21 JST

> **日付付き復旧準備監査（2026-10-21 時点）**: 2026-10-15 失効後の単発復旧準備と #250 Pages 診断・#264 カタログ検証修正の事前検証記録です。当時の未反映・未マージ状態を現在の本番状態として扱わないでください（現行手順は [static_operations.md](../../static_operations.md)）。

**再利用可能な教訓と検証境界**:
- **#250 観測の `missing` vs 空マップ**: Pages API で non-env binding キーが `missing`（欠落）のとき、空マップと同一視せず `UNKNOWN` として記録する。また、GET 棚卸しは排他ロックではないため、公開直前に再取得する。
- **#264 公開後検証**: `release.json` の一致だけでなく、実取得した `catalog.json` 応答のバイト/SHA-256 と鮮度を同一応答で検証する必要がある（従来の 300/30/10 秒予算の根拠）。
- **独立レビューのモデル独立性**: 実装と同じモデルの別読み取りセッション（Astra → Astra）は同一モデル確認に留まり、相手モデル（GPT-6.1 Sol）での読み取り専用レビューを別途実施した。

## Canonical state (2026-10-21 09:34 JST)

Read at 09:34 JST, using the existing `static_request` HTTPS/no-cache/no-redirect
contract and existing GitHub access. Values of secrets were never retrieved.

- `https://navmate.yuto24.com/release.json` is clean v1.20.1 at the approved SHA.
- All six public connection settings match repository variables. All three
  static environments have zero variable overrides; complete inventories checked.
- `STATIC_AUTOMATION_ENABLED=false`; `STATIC_MONITOR_ENABLED` is unset. The
  publication workflow is active but scheduled jobs skip under the false switch.
- The catalog matches the release inventory: 555,017 bytes, SHA-256
  `5aa1cc614e01b871767024c6a11644576339f26b4fc6bd12100b94dcfbfc7384`, 22 assets.
  Generated `2026-10-15T07:35:46.791957Z`, expired
  `2026-10-15T13:35:46.791957Z` (October 15, 22:35 JST). It remains expired;
  successful build-only work does not restore production.
- Existing Pages-token names are present in `static-production` and
  `static-publication`, absent in `static-validation`. Presence does not prove
  current edit-token validity. `static-publication` requires reviewer `Yuto-24`
  and permits branch `main`; protection was not changed.

## #250 management observation

[GET-only diagnostic run 39521438591](https://github.com/Yuto-24/AutoNavLog/actions/runs/39521438591),
reviewed tooling SHA `ae606ff3dde9ad55d2fea7032369838207642de6`, observed
`2026-10-21T00:27:39.362990Z` (09:27 JST). Existing
`STATIC_CLOUDFLARE_READ_TOKEN` was used only inside the diagnostic step.

- Configured account path, project `navmate`, production branch `main` and
  canonical domain match. Project ID `79bb24b3-39de-4eb5-ab84-729b995c25e2`.
  The configured account path is not independent proof of account ownership.
- Current canonical production deployment:
  `9c4851d5-9dd2-4062-92f6-0f0421e72a0f`, successful `deploy`, approved application
  SHA above, created `2026-10-15T07:41:03.194692Z`. Project and deployment both
  report `uses_functions=false`.
- Pagination complete: 181 retained deployments, 18 FINISHED and 163 explicitly
  SKIPPED; zero ACTIVE, PENDING or UNKNOWN activities. No in-flight entries.
  Canonical deployment is present in the inventory; project reread is unchanged.
- Production configuration is present. `env_vars` is nonempty: the known TAF
  variable is plain text and there are two other names, whose names/values are
  not reproduced. Five known build variables are missing from Pages settings;
  the isolated build obtains its matching public settings from GitHub instead.
- All twelve inspected non-env binding keys are **missing**, not explicit empty
  maps. Their presence remains **UNKNOWN** in the report. Do not claim that this
  observation proved every binding absent. The existing publication gate and
  sealed static-artifact checks must still pass; resolve material UNKNOWN target
  facts through the existing authorized management view before publication.

This diagnostic intentionally exits 1 / reports BLOCKED even when the observation
succeeds; it never grants publication or quota acceptance. The hosted run is
therefore recorded as **failure with a completed observation**, not successful CI.
The old local-OAuth 401 no longer blocks this observation route. #250 remains open:
repeat the inventory immediately before publication, resolve unknown target facts,
and record that observation. A GET inventory is not a lock against another operator.

At 17:34 JST, [repeat diagnostic 39570276909](https://github.com/Yuto-24/AutoNavLog/actions/runs/39570276909)
observed the same canonical deployment, target/configuration and missing binding
states. Pagination covered 182 deployments (18 FINISHED, 164 explicitly SKIPPED),
with no ACTIVE/PENDING/UNKNOWN activities, no in-flight entries and an unchanged
project reread. At 17:28 JST, canonical catalog/configuration and disabled switches
also remained unchanged. These later reads still do not authorize publication.

## Build-only verification

[Run 39521789417](https://github.com/Yuto-24/AutoNavLog/actions/runs/39521789417)
completed **successfully** at 09:36 JST, on tooling `ae606ff`, with
`source_sha=a4de2a226dfa205b8be42fb62a710a1b06271ed8`, `publish=false`.

- Existing identity/configuration/source isolation gates passed.
- Nine recent immutable assets were restored; fresh real MSM was generated and
  decoded/validated by the existing producer and 24-hour coverage gate.
- Static build, release/data/schema checks and artifact tests passed. Candidate:
  151 files, 77,892,232 bytes; catalog expiry `2026-10-21T06:32:10.531989Z`.
- Production Browser E2E: **10 passed**, including real-MSM FORECAST and Local
  persistence scenarios. This is an isolated production-artifact test, not live
  canonical-origin Auth/Sync/TAF acceptance.
- Independent post-build artifact/feed validation and build identity recording
  passed. Upload CLI installation, staging, upload and post-upload verification
  were all **skipped**. This run does not exercise #264's post-upload check.
- The runner does not retain a reusable production artifact. A later approved
  publication generates fresh weather again; never reuse this expired evidence.

## PR #264 検証と 2026-10-21 時点の公開引き継ぎ境界

- **PR #264 のカタログ検証修正**: `release.json` の一致だけでなく実応答の `catalog.json` のバイト/SHA-256 と鮮度を同一応答で検証する回帰テストを追加し（300/30/10 秒予算維持）、GPT-6.1 Sol による読み取り専用独立レビュー（指摘なし）、Docker CI 1,904 テスト・Ruff・mypy・Web 型検査・隔離 Compose `autonavlog-wt-07e29e1c`（port 42376, v1.22.8）の起動を確認した。
- **2026-10-21 時点の残条件**: 上記 `Run 39521789417` は `publish=false` のため実際の公開後検査は未実施であり、当時の本番復旧には PR #264 マージ後の本番再読取・`static-production.yml` 実行・実オリジン受入（#123 定期更新 2 回）が残っていた。また Cloudflare Pages / Workers / GitHub public-runner の公式制限値は 2026-10-21 再確認時点の参照であり、アカウント全体の利用量・課金制御の証明ではない。
