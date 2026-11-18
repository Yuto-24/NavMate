# Custom-domain cutover pre-check — 2026-09-28

> **日付付き切替前観測（2026-09-28）**: `https://navmate.yuto24.com` 切替作業中の読み取り確認記録であり、現在の本番設定（TAF 許可オリジンや `pages.dev` リダイレクト状態）を示すものではありません。現行の切替・運用手順は [custom_domain_cutover.md](../../custom_domain_cutover.md) を参照してください。

**再利用可能な教訓と検証境界**:
- `services/taf-proxy` の `ALLOWED_ORIGINS` は `.split(",")` で読むため JSON 配列ではなくカンマ区切り文字列を設定する（チェックイン済みテンプレートは空文字の fail-closed を維持）。
- Python `urllib` による直接 GET が一律 403 になっても、curl（Honest 識別子等）の結果と切り分けて判定し、403 の推測で仕様を変更しない。
- Legacy `/api/navmate-migration/status` の CORS `OPTIONS` 200 は公開 CORS 境界のみを検証し、実 Google トークン認証や 303 リダイレクトの代替証拠にならない。

## Read-only production observations (2026-09-28 10:34–10:37 UTC)

Checked with curl without following redirects at approximately 10:34–10:37 UTC:

| Probe | Result |
| --- | --- |
| `https://navmate.yuto24.com/release.json` | HTTP 200, clean v1.20.1, SHA `a4de2a226dfa205b8be42fb62a710a1b06271ed8` |
| `https://navmate.pages.dev/` | HTTP 200; old entry is still served, not redirected |
| Legacy `/api/navmate-migration/status`, OPTIONS with canonical Origin | HTTP 200, matching allow-origin, Authorization / Content-Type, GET / POST / OPTIONS, `Vary: Origin` |
| Same Legacy preflight with pages.dev Origin | HTTP 403, no allow-origin |
| Existing production TAF endpoint, GET `?icao=RJFM` with canonical Origin | HTTP 403, no allow-origin |
| Same TAF GET with pages.dev Origin | HTTP 200, allow-origin is pages.dev |
| Canonical `/weather/msm/catalog.json` | Generated `2026-09-24T11:53:06.314558Z`, expired `2026-09-24T17:53:06.314558Z` |

The Legacy result verifies the public CORS boundary only; it does not prove the selected
host env file, live Google identity, completed-account redirect or data restoration.
The Auth/Sync/Last Calculation acceptance reported by the operator on September 27 is
in [#123](https://github.com/Yuto-24/AutoNavLog/issues/123#issuecomment-5852546355), not
a new browser acceptance run here. GitHub variable values and current provider plans /
quota were not verified in this task. An initial Python urllib probe received uniform
403 responses, including for the release file; the curl observations above supersede
that inconclusive probe and must not be confused with it.

## 2026-09-28 時点の残ゲートと境界

- **matsu / Legacy**: `AUTONAVLOG_NAVMATE_URL=https://navmate.yuto24.com/`・loopback・Access 境界の確認、および完了済みアカウント 303 と新規ブラウザ移行/Sync の実機確認。
- **TAF / Cloudflare / Firebase**: `services/taf-proxy` の ignored `wrangler.local.jsonc` へ CSV 許可オリジンを反映（チェックイン済みテンプレートは空文字のまま維持し、作業コピーの配列形式編集に注意）。切替受入後に旧 `navmate.pages.dev` Bulk Redirect と旧 Auth ドメイン整理へ進む。
- **GitHub / MSM**: `STATIC_ORIGIN` 整合確認、承認済み SHA の分離、および 2026-09-24 失効カタログに対する承認済み新規フィード公開・2 回以上の定期更新・ロールバック確認（いずれも本調査時点では未完了）。

当時の PR レビュー（GPT-6 Sol）では初期再作成手順の明示的 loopback bind 欠落が指摘され、runbook 側で `AUTONAVLOG_BIND_ADDRESS=127.0.0.1` と事前 `config` 検証を必須化した。
