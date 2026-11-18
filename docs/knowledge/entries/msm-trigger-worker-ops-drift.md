# msm-trigger 復旧時の ops.mjs 設定上書きと状態・認証復旧

- ID: MSM-TRIGGER-OPS-DRIFT
- Status: provisional
- Scope: `services/msm-trigger/`（`ops.mjs`、`wrangler.jsonc`、Wrangler 4.152.0 による Cloudflare Worker 運用・復旧）
- Trigger / search terms: `ops.mjs`、`.state/wrangler.json`、`observability` 差分、`.state/operator.json` 欠落、OAuth 401/403、`workerd` CA 不足、`FRESH` vs `DISPATCH_ACCEPTED`
- Last verified: 2026-11-18（Worker commit `810be0bbe24511f4da5fdf8b8f2b4a468fc6a97c` の再配置および自然 Cron 1 tick 観測まで。`DISPATCH_ACCEPTED`・provider CPU 集計は未実証）
- Evidence: [2026-11-18 Worker 復旧記録](../../evidence/issue-123/msm-worker-recovery-2026-11-18.md)、[2026-10-26 read-back 調査](../../evidence/issue-123/msm-worker-readback-2026-10-26.md)、[MSM 補完起動手順](../../msm_external_trigger.md)
- Supersedes / superseded by: 該当なし

## Observation and impact

1. `services/msm-trigger/ops.mjs` の `configuration()` を呼ぶ各コマンドは `wrangler.jsonc` を読んで `.state/wrangler.json` を毎回生成・上書きする。リポジトリの `wrangler.jsonc` には本番に元々設定されていた明示的 `observability` 設定が含まれないため、そのまま実行すると本番の `observability` 設定が欠落する（2026-11-18 の初回再配置で read-back 差分として検出）。
2. `.state/operator.json` がローカルに存在しない状態で安易に `ensure-kv` を再実行したり、保存済み OAuth access token をそのまま使って管理 API へ直接 GET（HTTP 403/401）して失敗したりすると、状態不整合や誤った認証変更を招く。
3. 隔離コンテナ内で `workerd` テストを実行した際、CA 証明書不足で起動失敗した。
4. 復旧後の自然 Cron が `FRESH`（`outcome=ok`）で終了しても、それは `canonical_freshness` の鮮度確認までであり、GitHub 照会・dispatch 送信・provider CPU 受入・MSM 配信回復までは検証されない。

## Cause and evidence

- `services/msm-trigger/ops.mjs` において `configuration()` を呼び出して `.state/wrangler.json` を書き出すコマンドは **`ensure-kv`、`abandon-pending`、`stage-secret`、`deploy-observe`、`observe-cron`、`enable-dispatch`、`enable-cron`、`stop`** である（`deploy-staged` は既存の `.state/wrangler.json` を再生成せずに使用し、`plan` は JSON を標準出力へ表示するだけでファイルを書かない）。`configuration()` は `...template`（`wrangler.jsonc` の内容）、`main`、`account_id`、`vars: { MODE }`、`triggers.crons`、`kv_namespaces` のみを組み立てる（2026-11-18 コード照合済み）。
- 保存済み OAuth token を直接読む GET は期限検査・自動 refresh を行わないため、期限切れ時に HTTP 401/403 で失敗する（2026-10-26 および 2026-11-18 の両方で `wrangler whoami` の通常 refresh 後に復旧。ただし初期 403/401 の provider エラー本文自体は未取得のため原因を断定しない）。

## Next-time action

1. **認証確認**: 管理 API で 401/403 が出た場合は新規 token や Secret を作らず、まず既存 `wrangler whoami` による通常 refresh を試す。
2. **ローカル状態の復元**: `.state/operator.json` が見当たらない場合、本番の読取専用 GET で account、既存 `STATE` KV の固定名・ID、`MODE`、Cron、デプロイ済み／未配置 version を確認してからローカル状態のみ復元する。`ensure-kv` や KV 作成・初期化・キー手動書換えは行わない。
3. **事前停止と段階配置（`observability`・元 MODE/opt-in/Cron の保持）**: 現行の `wrangler.jsonc` / `ops.mjs` を変更しない運用では、`.state/wrangler.json` を手修正しても次回上記コマンド実行で上書きされる。本番の元設定（`observability` 等）を保つには隔離テンプレートに元設定を明示したうえで、必ず **事前停止（外部 opt-in を `false` へ閉鎖 → `stop`・read-back・最大 15 分の停止伝播と進行中実行終了を確認）** を経て、ステップ 2 で確認した元状態と承認範囲に従って分岐する（具体コマンドと停止・KV 保持条件の正本は [docs/msm_external_trigger.md](../../msm_external_trigger.md#secret-管理と段階配置の安全制約)）。
   - **元 `MODE=dispatch` かつ承認範囲内の復旧のみ**: `enable-dispatch`（Cron 空）→ read-back 差分なし・承認確認 → 元 opt-in が有効だった場合だけ復元（元無効を勝手に有効化しない）→ 元 Cron 有効時だけ `enable-cron`（元停止なら再開しない）。
   - **元 `MODE=observe` の復旧**: `enable-dispatch` / `enable-cron`・opt-in 有効化は禁止（`ops.mjs` では `MODE` が `dispatch` へ変わるため）。元設定保持の隔離テンプレートで `MODE=observe`（元 Cron 有効時のみ read-back 後に再開）を復元し、`dispatch` 化は別途・個別の承認を得てから行う。
   - 停止は進行中公開を中断せず、KV 消去・初期化も行わない。
4. **コンテナ検証**: 隔離コンテナで `workerd` が起動しない場合は TLS 検証を無効化せず、ホストの既存 CA 証明書を read-only mount する。
5. **観測の切り分け**: 設定 read-back だけで経路受入としない。`FRESH` 判定と `DISPATCH_ACCEPTED`、Actions `msm-request/<request_id>` との一致、provider CPU 集計（10 ms 制限）、WSL 直接 GET と Worker GET の到達経路差を切り分けて記録する。

## Limits and counterexamples

- `ops.mjs` / `wrangler.jsonc` に `observability` 設定を取り込むコード修正を行えば上記テンプレート回避手順は変わるため、実行前に現行 `services/msm-trigger/ops.mjs` と `wrangler.jsonc` を確認すること。
- 2026-11-18 時点の観測は再配置と自然 Cron 1 tick（`FRESH`）までであり、実 dispatch 経路（`github_queued=200` / `DISPATCH_ACCEPTED` / Actions 一致）および provider CPU 集計の成立性は未確認である。

## Reuse feedback

- 2026-10-26 の OAuth refresh 知見（`msm-worker-readback-2026-10-26.md`）を 2026-11-18 の 403 調査で再利用し、新規認証・Secret 発行なしで管理 API read-back を復旧できた（ただし 2026-11-18 も元 403 の詳細本文は未取得）。
