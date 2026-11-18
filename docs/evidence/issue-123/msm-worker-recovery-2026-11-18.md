# MSM 補完起動 Worker の復旧記録（2026-11-18 JST）

> **日付付き観測記録です（2026-11-18 時点）。** 本記録はその後の本番状態、継続的な MSM 更新、および未実施の dispatch 経路まで保証するものではありません。運用仕様の正本は [msm_external_trigger.md](../../msm_external_trigger.md)、得られた再利用知見は [MSM-TRIGGER-OPS-DRIFT](../../knowledge/entries/msm-trigger-worker-ops-drift.md) を参照してください。

## 結論と現在地（2026-11-18 時点）

2026-11-18 に `autonavlog-msm-trigger` Worker を `Yuto-24/NavMate` 参照の修正済み版（`810be0bbe24511f4da5fdf8b8f2b4a468fc6a97c`）へ復旧再配置し、`MODE=dispatch`・15 分 Cron（`*/15 * * * *`）で自然 Cron 1 回の `FRESH` 判定まで確認した。

ただし、**確認できたのは「301 原因コードの修正反映」と「自然 Cron の `FRESH` 判定」まで**であり、補完 `DISPATCH_ACCEPTED` の実証と本番 MSM 配信の復旧・継続更新は別の未検証領域として残る。

## 復旧前調査と原因

- 旧 repository 名での実行一覧 GET が HTTP 301、新 repository `Yuto-24/NavMate` で HTTP 200 を返すとの調査を受け、稼働中の本番 Worker（version `d14cb159-a0e0-4e4c-9590-33dbe8ffc0df`）を確認した。
- 本番版には旧 `Yuto-24/AutoNavLog` 参照が残り、`Yuto-24/NavMate` 参照が含まれていなかったため、リネーム修正が本番 Worker へ未反映であることを確定した。
- 修正済みコードは commit `810be0bbe24511f4da5fdf8b8f2b4a468fc6a97c`。新配布物の source map 内の `worker.ts`（SHA-256 `e132f26b60e1ff3d5cca44d384cc6c19aae9fea9aef4955377abdf34fab4242a`）は同 commit と完全一致した。

## 認証・状態復元と再配置で判明した制約

1. **既存 OAuth 認証の refresh 再利用**:
   - 保存済み OAuth access token を使った直接 GET は HTTP 403 を返した（保存済み access token は期限切れ）。
   - 2026-10-26 の同様の記録（[msm-worker-readback-2026-10-26.md](msm-worker-readback-2026-10-26.md)）と同様に、既存 `wrangler whoami` の通常 refresh 実行後に GET が復旧した。新規 token・Secret・権限は作成していない。
   - 期限切れが有力原因だが、初回 403 応答の provider 詳細本文は未取得のため原因を断定しない。
2. **ローカル `.state/operator.json` の復元**:
   - 元のローカル `.state/operator.json` が探索範囲で見つからなかったため、本番 GET により account、既存 `STATE` binding の KV namespace 再利用、`MODE`、Cron、最新 version、未配置 version 不在を確認し、ローカル状態だけを再構成した。
   - `ensure-kv`、KV の新規作成・初期化、手動の KV キー更新は一切行わず、既存 KV の内容と `GITHUB_TOKEN` Secret をそのまま維持した。
3. **隔離コンテナでの事前検証と CA 証明書**:
   - 固定 Wrangler `4.152.0` と Node 22 隔離コンテナで `typecheck`、dry-run（`check`）、70 テストが成功した。
   - 初回実行時はコンテナ内の CA 証明書不足により `workerd` が起動せず 1 件失敗した。既存の CA 証明書を read-only mount して再実行し成功した。TLS 検証の無効化は行っていない。
4. **`ops.mjs` による `observability` 設定上書きの検出と回避**:
   - 既定の `services/msm-trigger/ops.mjs` は、`configuration()` を呼ぶコマンド（`enable-dispatch`、`enable-cron` 等）実行時に `wrangler.jsonc` を読んで `.state/wrangler.json` を上書き生成し、本番に元々あった明示的 `observability` 設定を省略する。
   - 段階配置（`enable-dispatch`（Cron なし）→ read-back → `enable-cron`）の初回 Cron なし版（`248913e4-bd16-42d8-8dec-2cce08c34531`）で read-back 差分としてこれを検出し、Cron 再開を停止した。
   - 隔離配置用のテンプレートに元の `observability` 設定を明示して再配置した（リポジトリの `wrangler.jsonc` と `ops.mjs` 自体は未修正）。保存した `.state/wrangler.json` だけを手直ししても次の該当 `ops.mjs` 実行で上書きされる点に注意が必要である。

## 配置 version と最終観測設定（2026-11-18）

| 段階 / 項目 | 観測値・結果 |
| --- | --- |
| 初回 Cron なし配置 | version `248913e4-bd16-42d8-8dec-2cce08c34531`（read-back で `observability` 差分を検出し Cron 再開を停止） |
| 修正再配置（Cron なし最終版） | version `3ea62654-a965-4adf-bfba-d141f8f85ea2`（JS / source map hash 一致） |
| Cron 再開版（100% 配置） | version `e72845b1-826b-4393-8d1d-9bd1d6de0b05`（JS / source map hash 一致） |
| 維持した構成 | account / Worker 名 `autonavlog-msm-trigger` / 既存 `STATE` KV / 既存 `GITHUB_TOKEN` Secret 名と値 / `MODE=dispatch` / Cron `*/15 * * * *` / `compatibility_date=2026-10-19` / `workers_dev=false` / `preview_urls=false` / `observability` 無効および元の詳細設定 |
| GitHub 側変数（前後不変） | `STATIC_EXTERNAL_TRIGGER_ENABLED=true`、`STATIC_AUTOMATION_ENABLED=true`、`STATIC_APPROVED_SHA` 不変。手動 dispatch・フラグ変更・アプリ再リリース・RISH 一覧 404 修正は未実施 |

## 自然 Cron 観測と未実証の境界

- **2026-11-18 10:00:38 JST の自然 Cron**:
  - version: `e72845b1-826b-4393-8d1d-9bd1d6de0b05`
  - `outcome=ok`、`canonical_freshness=200`（188 bytes）、`status=FRESH`、`hint_run=20261117210000`、`publication=NOT_VERIFIED`
  - 残り鮮度が基準超のため、GitHub 照会・dispatch POST は実行されていない。
  - tail 観測は CPU 1 ms / wall 272 ms を記録したが、provider の CPU 集計は未取得のため 10 ms CPU 受入の証拠とはしない。
- **到達経路の差異**:
  - 同じ `canonical_freshness` URL に対し、WSL からの直接 GET は HTTP 403、稼働中の同 Worker からは HTTP 200 が返った。到達経路を区別して評価する必要がある。
- **未実証の範囲（この作業で完了としないもの）**:
  - `github_queued=200`、および `DISPATCH_ACCEPTED` の実行 ID と Actions `msm-request/<request_id>` の一致は未実証。
  - 本番 MSM の全 payload 整合性と継続更新はこの作業では検証していない。
  - **「301 原因コードの修正反映」「自然 Cron の鮮度判定（`FRESH`）」「補完 dispatch の実証」「本番 MSM 配信の復旧」は別の証拠であり、`FRESH` を dispatch 成功へ読み替えない。**
