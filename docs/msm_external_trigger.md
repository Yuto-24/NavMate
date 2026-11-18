# MSM 補完起動: 軽量 Worker (`autonavlog-msm-trigger`) と Actions 検証

`autonavlog-msm-trigger` は、`https://navmate.yuto24.com/weather/msm/freshness.json` の鮮度ヒントを 15 分 Cron で監視し、更新候補時に限って `Yuto-24/NavMate` の `static-production.yml` へ `workflow_dispatch` を送る軽量 Cloudflare Worker です。公開可否・予報 Run 発見・全 payload 検証・公開後確認はすべて Actions 側が担い、Worker 自身は公開成功を判定しません。

> **現在の運用位置づけと関連記録**:
> - **2026-11-18 復旧状態（観測記録）**: `Yuto-24/NavMate` 参照修正版（commit `810be0bbe24511f4da5fdf8b8f2b4a468fc6a97c`）を再配置し、`MODE=dispatch` / 15 分 Cron で自然 Cron 1 回の `FRESH` 判定まで確認済み（[2026-11-18 復旧記録](evidence/issue-123/msm-worker-recovery-2026-11-18.md)）。**`DISPATCH_ACCEPTED` 経路の実証、provider CPU 集計（10 ms 受入）、および本番 MSM の全 payload 整合性・継続更新は未確認**であり、その後の本番状態も本記録からは断定しない。
> - **設計上の設定上書き制約**: `services/msm-trigger/ops.mjs` の `configuration()` を使う経路は、毎回 `wrangler.jsonc` から `.state/wrangler.json` を上書き生成するため、本番の明示的 `observability` 設定等を省略し得る。手順と回避策は [CLI（設定上書き制約と段階操作）](#cli設定上書き制約と段階操作) および知見 [MSM-TRIGGER-OPS-DRIFT](knowledge/entries/msm-trigger-worker-ops-drift.md) を参照。

## 鮮度ファイルと起動判断

公開 tooling は承認済みアプリの build/test 後、`weather/msm/freshness.json` を追加し、`release.json` の inventory へ実 bytes/hash を登録して catalog と同じ Pages deployment に載せます。

- schema 1 は `run`（catalog assets 中の実在する最新 Run）、`generated_at`、`expires_at`、`app_commit` を持つ。生成・期限は catalog から転記し、6 時間の TTL を更新・延長しない。2,048 bytes 以内とし、架空の Run や「次に来るはずの Run」を記録しない。
- Worker はこの 1 ファイルを `no-store`、HTTPS、redirect 拒否、10 秒、2,048 bytes 上限で取得し、schema、UTC 3 時間境界 Run、生成日時、6 時間期限、40 桁 commit 形式を検証する。
- **残り 3 時間超**: `FRESH` として終了し、GitHub 照会・POST は行わない（`upstream: "NOT_CHECKED"`、`publication: "NOT_VERIFIED"`）。
- **残り 3 時間以下（有効な古い/期限切れ hint を含む）**: KV の要求回数・90 分 cooldown と、GitHub `Yuto-24/NavMate` の active 5 状態（`queued` / `in_progress` / `waiting` / `pending` / `requested`）・直近 24 時間履歴で要求を抑制する。8 要求/UTC 日の上限を維持し、空振り・失敗・受付不明も枠を消費する。
- POST 前に KV（キー `trigger-v1`）へ要求数と時刻を記録し、書込失敗時は送信しない。POST は自動 retry しない。旧 `msm-fallback/` と新 `msm-request/` の両方の prefix を会計する。
- 欠落 404、SPA HTML、JSON 不正、schema 不正、過大、取得失敗は `UNKNOWN` で停止する。欠落を期限切れへ読み替えて起動しない。
- `request_id` は起動要求の ID（現在時刻ミリ秒文字列）であり予報 Run ではない。`DISPATCH_ACCEPTED` は受付のみを示し、`publication: "NOT_VERIFIED"` のまま Actions 側で公開可否と公開後検査を完結させる。
- [GitHub API 版 `2026-03-10` の dispatch 成功](https://docs.github.com/en/rest/actions/workflows?apiVersion=2026-03-10#create-a-workflow-dispatch-event)は HTTP 200 を返す。1 MiB 上限内で JSON を読み、正の整数 `workflow_run_id` と `Yuto-24/NavMate` を指す `run_url` / `html_url` を検証して受付結果へ記録する。
- KV は結果整合性であり分散 lock ではない。古い read や同時 tick による厳密な 8 件上限・rolling 24 時間上限はこの構成で保証しない（Actions 側の concurrency・履歴・同 Run 上限で補う）。厳密な予約を行う Durable Object (`RequestGate`) は後続分離のまま本構成に含めない。

## CPU と実行の観測

- `scheduled` handler は結果と全 HTTP stage の `diagnostics` 配列を 1 件の JSON ログへまとめる（URL 本文・header・Secret 値は出力しない）。
- `scripts/static_ops/msm_observation.py` は副作用なしで受付・CPU 観測を照合する。enqueue から実行終了までを含む対象 1 件の provider CPU 値で 10 ms 制限を評価し、tail の単発値だけを合格証拠にしない。API 失敗・欠測・曖昧な集計は `UNKNOWN` とする。

## Actions 側の境界

workflow concurrency `static-production` / `cancel-in-progress: false` を共有する。承認済みアプリ SHA 固定を維持し、2026-10-28 の明示承認に基づき予報のみの公開は手動を含め承認待ちにしない（preflight / producer は無人実行用 `static-production` environment、build-only は `static-validation` を使用）。

1. bounded な完全履歴と全 active 状態を照合し、自 Run 以外の実行中・承認待ち、日次 8、90 分間隔、重複 request ID、rerun、任意 SHA 指定を拒否する。GitHub concurrency API で現在 Run が `static-production` lock を保持することを確認し、同 group で pending と確認できた Run だけを active 競合から除外する。
2. canonical release・catalog の実 bytes/hash、全 asset inventory と全 payload bytes/hash を検証し、hint と catalog の一致を確認する（hint 非搭載の旧 deployment からの欠落起動は認めない）。
3. 既存 `preflight_feed.py` で 25 時間を満たす新しい完全な予報 Run を発見する（新 Run なしは健康な既存 catalog・完全予報時のみ `NO_NEW_RUN`）。
4. 検出した実 Run を job 名 `msm-detected/<Run>` として記録し、先行する同 Run 検出履歴が 2 件以上なら停止する。
5. restore・生成・全 payload decode/coverage・独立 build/E2E・upload 直前比較・upload 後検査（全 payload 照合を含む）を通過して公開する。

## CLI（設定上書き制約と段階操作）

リポジトリルートから実行する。Wrangler（`4.152.0`）と lockfile は `services/msm-trigger/package.json` で固定し、template（`wrangler.jsonc`）は常に `observe`・Cron 空・ダミー KV で管理し本番へ直接使用しない。

> **重要（`ops.mjs` の `.state/wrangler.json` 上書き仕様）**:
> 現在の `services/msm-trigger/ops.mjs` は、`configuration()` を呼ぶコマンド（`ensure-kv`、`abandon-pending`、`stage-secret`、`deploy-observe`、`observe-cron`、`enable-dispatch`、`enable-cron`、`stop`）の実行時にリポジトリの `wrangler.jsonc` を読み込み、`.state/wrangler.json` を上書き生成する（`deploy-staged` は既存の `.state/wrangler.json` を再生成せずに使用し、`plan` は JSON を表示するだけでファイルを書かない）。`wrangler.jsonc` には明示的 `observability` 設定がないため、本番に元からある `observability` 詳細設定を保つには、隔離配置用テンプレートへ元設定を明示したうえで **事前停止（外部 opt-in 閉鎖 → `stop`・read-back・伝播/進行中終了確認）→ Cron なし配置 → read-back 差分確認 → 条件一致時のみ opt-in・Cron 再開** の順に進めること（具体順序は [Secret 管理と段階配置の安全制約](#secret-管理と段階配置の安全制約) を参照）。`.state/wrangler.json` だけを手修正しても次回上記 `configuration()` 呼び出しコマンドの実行で上書きされる。

認証不要の開発・検証:

```sh
npm --prefix services/msm-trigger ci
npm --prefix services/msm-trigger run typecheck
npm --prefix services/msm-trigger run check
npm --prefix services/msm-trigger test
npm --prefix services/msm-trigger run ops -- plan
```

隔離コンテナ等で `workerd` テストが CA 証明書不足により失敗する場合は、TLS 検証を無効化せず、ホストの既存 CA 証明書を read-only mount して再実行する。

管理 API / CLI 操作（**個別承認後のみ**。`set -x`・token 引数・ログ出力は禁止）:

- **認証 refresh**: 保存済み OAuth access token を使う直接 GET が HTTP 401/403 で失敗する場合、まず既存 `wrangler whoami` の通常 refresh 後に再読込を試す。新規 token・Secret・権限を無断で作成しない（[2026-10-26 調査](evidence/issue-123/msm-worker-readback-2026-10-26.md)）。
- **`.state/operator.json` 喪失時**: 安易に `ensure-kv` や KV 初期化へ進まず、まず本番 GET で account、既存 `STATE` KV（固定名 `autonavlog-msm-trigger-state`）、`MODE`、Cron、最新/未配置 version を確認してローカル状態だけ復元し、既存 KV 内容と `GITHUB_TOKEN` Secret を保持する。

```sh
# 初回構築時（既存環境復旧時は本番 GET で状態確認後にローカル復元を優先）
npm --prefix services/msm-trigger run ops -- ensure-kv
npm --prefix services/msm-trigger run ops -- deploy-observe
npm --prefix services/msm-trigger run ops -- stage-secret GITHUB_TOKEN
npm --prefix services/msm-trigger run ops -- deploy-staged
npm --prefix services/msm-trigger run ops -- observe-cron
```

### Secret 管理と段階配置の安全制約

- **Secret の段階登録**: `wrangler secret put/delete` は新 version を即時 deploy するため使わず、`stage-secret`（`wrangler versions secret put`）→ `deploy-staged` の 2 段階を維持する。`stage-secret` は **`MODE=observe` かつ Cron 停止中のみ** 実行し、次の Secret を stage する前に必ず `pending version` を `deploy-staged` で配置する。同時管理者による version 変更が検出された場合は停止し、`versions list` で確認する。同じ名前の Secret 更新・期限前更新も同じ手順で上書きし、追加リソースを作らない。
- **復旧版の事前停止と段階復帰・本番 `dispatch` 有効化**:
  - 新規・復旧版の配置や変更を行う前に、まず GitHub 側外部 opt-in を `STATIC_EXTERNAL_TRIGGER_ENABLED=false` へ閉じる（元々無効だった場合は無効維持。停止操作は進行中の公開を中断せず、KV も消去・初期化しない）。

```sh
# 既存の GitHub 認証を使用。新規 credential 作成を兼ねない
gh variable set STATIC_EXTERNAL_TRIGGER_ENABLED --repo Yuto-24/NavMate --body false
```

  - 続いて `stop` 実行前に、ローカル（`.state/operator.json` 等）およびリモートに **未配置の `staged_version`（配置待ち Secret version）が残っていないか** を read-only で確認する（`ops.mjs` は `staged_version` が残存している間 `stop` 等のコマンドを拒否するため）。
    - **配置待ち（`staged_version`）がない場合**: `deploy-staged` は実行せず、そのまま下の `stop` へ進む。
    - **`staged_version` が残存している場合**: `deploy-staged` はその version を **100% 即時配置** するため、次の 4 条件をすべて read-only で確認できた場合のみ先に `deploy-staged` を実行する。
      1. 既存の承認対象 version および承認済み Secret 更新の範囲内であること。
      2. ローカル状態とリモート Worker の双方が `MODE=observe` かつ Cron 停止中であること。
      3. Cron 停止伝播（最大 15 分）および進行中実行が終了していること。
      4. 対象 version・設定・現在の配置状態に不整合がないこと。
      - いずれかを確認できない／不一致／承認範囲外の場合は、**外部 opt-in 閉鎖（`false`）を維持したまま `deploy-staged` を実行せず停止**する（`staged_version` の手動削除やガード迂回は禁止）。

      ```sh
      # staged_version 残存かつ上記 4 条件をすべて確認できた場合のみ実行
      npm --prefix services/msm-trigger run ops -- deploy-staged
      ```

      - `deploy-staged` 実行後は **read-back で配置状態を確認し、かつ `staged_version` が解消されたこと** を確認してから下の `stop` へ進む（未解消・不整合時はここで停止する）。

  - **事前停止（`stop` 実行）**: 配置待ちがないことを確認した場合、または上記 `deploy-staged` 後の read-back と `staged_version` 解消を確認した後に、本番の元設定（`observability` 等）を明示した隔離テンプレートで `stop`（`MODE=observe`、Cron 空）を実行する。

    ```sh
    npm --prefix services/msm-trigger run ops -- stop
    ```

  - `stop` 後は read-back で `MODE=observe`・Cron 空・元設定保持を確認し、**Cron 停止伝播（最大 15 分）および進行中実行の終了**を確認してから、復旧前に記録した元の MODE・外部 opt-in・Cron 状態と承認範囲に従って段階復帰する。なお、新規有効化時やコード変更時は有効化前確認および下節の限定 observe 実測を行ったうえで別途・個別の承認を得て進む。
  - **元 `MODE=dispatch` かつ承認範囲内の復旧（または別途承認済みの本番 `dispatch` 有効化）**:
    1. 元設定を保持した隔離テンプレートで `enable-dispatch`（`MODE=dispatch`、Cron 空）を配置する。

       ```sh
       npm --prefix services/msm-trigger run ops -- enable-dispatch
       ```

    2. read-back で設定差分（`observability` 等）がないことおよび承認内容との一致を確認する（差分または不整合がある場合はここで停止し、以降へ進まない）。
    3. **復旧前に記録した元の外部 opt-in が有効だった場合だけ**（または個別承認された新規有効化時だけ）GitHub 側の `STATIC_EXTERNAL_TRIGGER_ENABLED` を `true` へ復元する（元 opt-in 無効を勝手に有効化しない）。

       ```sh
       # 元 opt-in が有効（または新規有効化が個別承認済み）の場合のみ実行
       gh variable set STATIC_EXTERNAL_TRIGGER_ENABLED --repo Yuto-24/NavMate --body true
       ```

    4. **復旧前に記録した元の Cron が有効だった場合だけ**（または個別承認された新規有効化時だけ）`enable-cron` を実行する（元 Cron 停止なら再開しない）。

       ```sh
       # 元 Cron が有効（または新規有効化が個別承認済み）の場合のみ実行
       npm --prefix services/msm-trigger run ops -- enable-cron
       ```

  - **元 `MODE=observe` の復旧**: `enable-dispatch` と `enable-cron` は実行しない（`ops.mjs` では両コマンドとも `MODE` を `dispatch` へ変更するため）。元設定保持の隔離テンプレートで `deploy-observe`（元 Cron が有効だった場合のみ read-back 確認後に `observe-cron`、元 Cron 停止なら再開しない）により元の `MODE`・Cron を復元し、`observe` から `dispatch` への切替および外部 opt-in 有効化は別途・個別の承認を得てから行う。
- **停止と `pending` 整理**:
  - Cron の追加・変更・削除は反映伝播に **最大 15 分** かかり得る。また、停止操作は **進行中の公開を中断しない**（緊急時は上記のとおり GitHub 側 `STATIC_EXTERNAL_TRIGGER_ENABLED=false` を先に閉じる）。
  - 停止後も **KV を削除・初期化して試行枠や失敗上限をリセットしない**。同じ Run で 2 回失敗した場合は上流／GitHub／公開ログを調べ、通常は次の新 Run を待つ。
  - 旧 `pending` を整理する必要がある場合だけ、**別途承認のうえ Cron 停止伝播（最大 15 分）および進行中実行終了を確認して** `abandon-pending` を実行する（日次・同 Run カウンタと cooldown は保持）。

## 有効化前・コード変更時の限定 observe 実測（別途承認後のみ）

新規導入、コードや実行基盤の変更後、あるいは未確認経路の受入を行う際は、**設定 read-back のみで完了とせず** 別途承認を得て限定 observe 実測を実施する（2026-11-18 のコード修正再配置では `MODE=dispatch` 復旧後に自然 Cron 1 tick の `FRESH` のみ観測しており、CPU 集計と `DISPATCH_ACCEPTED` 経路は依然未受入）。

1. 対象を既存 Worker・既存 KV・固定 commit に限定し、`observe` 配置（外部 opt-in 無効・実 dispatch なし）→ **Cron 反映待ち最大 15 分** → **観測最大 30 分・最大 2 tick** → 停止と read-back までを一組にする。
2. 先に hint 付き公開の証拠と設定・承認済みアプリ SHA を read-only で確認する（hint 欠落なら欠落経路の確認のみとし、更新候補経路の受入とはしない）。
3. Cloudflare tail と **provider CPU 集計** で各 tick の CPU / wall / outcome を取得する（固定 stage / hostname / status / read bytes のみ記録し、token / header / 本文 / Secret URL は出さない）。
4. 最初の **`UNKNOWN`、HTTP / IO / `BODY_LIMIT`、`exceededCpu`、CPU 10 ms 超過、想定外設定、期限到達、または 2 tick 到達** で停止し、`MODE=observe`・Cron 空を read-back する。停止伝播と遅着ログも確認する。
5. `FRESH`・期限切れ・GitHub 到達・欠落は別経路として記録し、少数サンプルだけで未測定経路を含めた CPU 10 ms 以内や dispatch 成功を宣言しない。

## 権限・Secret と無料枠境界

| 対象 | 最小権限と制約 |
| --- | --- |
| Worker `GITHUB_TOKEN` | fine-grained PAT を `Yuto-24/NavMate` のみへ限定（Actions: write、必須 Metadata: read、期限あり）。**workflow 単体への権限限定ではないため、他 workflow 起動・Actions 操作も可能な権限であることを承認する。** 401/403 で別 token へ自動切替せず停止する |
| 既存 Pages token | GitHub の既存公開 environment のみに保持。**Worker へ渡さず、新規発行もしない** |
| Cloudflare 管理 CLI | 既存 account 限定の Workers Scripts: Edit、Workers KV Storage: Edit（inventory/作成）、必要な Account Settings: Read。Worker runtime には渡さない |
| `HEARTBEAT_URL` | 任意、Healthchecks ping URL（`https://hc-ping.com/<uuid>`）。閲覧 URL や token をログへ出さず、**別サービス登録・Secret 登録は別途承認** を要する |

- **無料枠境界**: 通常 `FRESH` 経路は鮮度ファイル 1 取得、更新候補経路は最大 9 HTTP 取得（KV は tick ごと 1 read、予約時 1 write）。既存 TAF・他 Worker と account 日次枠を共有する。Actions 側は最大 8 要求/日で保守的上界 440 runner 分/日。アカウント全体の共有クオータ・課金監視は #281 に分離済み。
- **Free CPU 10 ms 境界**: ローカルテスト・bundle サイズ・HTTP 回数・tail の単発値からは合格宣言せず、実 dispatch を含む provider CPU 集計で確認する。

## 運用観測の履歴（詳細根拠は各証跡を参照）

- **2026-11-18 復旧再配置と自然 Cron 観測**: [2026-11-18 復旧記録](evidence/issue-123/msm-worker-recovery-2026-11-18.md) および知見 [MSM-TRIGGER-OPS-DRIFT](knowledge/entries/msm-trigger-worker-ops-drift.md)。301 原因コード修正反映と自然 Cron 1 tick の `FRESH` 判定まで確認済みだが、`DISPATCH_ACCEPTED` 実証（`github_queued=200` と `msm-request/<request_id>` 一致）・provider CPU 集計・本番 MSM 継続更新は未実証（`FRESH` を dispatch 成功へ読み替えない）。また WSL 直接 GET（403）と Worker GET（200）の経路差を確認。
- **2026-10-26 以前の観測**: 旧版 `17daa313` の observe 測定は `FRESH` で CPU 17 ms（provider 集計 17.232 ms）/ wall 348 ms。2026-10-26 20:33 JST の read-back では `MODE=observe`・Cron 空・停止 version `62d08cdc-e151-4240-9b35-68e7dcc51109` を確認（[msm-worker-readback-2026-10-26.md](evidence/issue-123/msm-worker-readback-2026-10-26.md)）。

## 公式資料・別件メモ

- [GitHub workflow jobs metadata](https://docs.github.com/en/rest/actions/workflow-jobs) / [dispatch 権限](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event) / [実行状態 API](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs) / [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [Cloudflare Workers limits](https://developers.cloudflare.com/workers/platform/limits/) / [Cron 管理・伝播](https://developers.cloudflare.com/workers/configuration/cron-triggers/) / [KV pricing](https://developers.cloudflare.com/kv/platform/pricing/) / [KV 整合性](https://developers.cloudflare.com/kv/concepts/how-kv-works/) / [Secret 登録の副作用](https://developers.cloudflare.com/workers/configuration/secrets/)
- [Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits/) / [Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/)
- **取得元 timeout の別件提案**: 外部 Cron は GitHub schedule 欠落を補うだけで、京都大学 listing / GRIB 通信の timeout（現行 `acquire_listings` 60 秒 socket timeout）は解決しない。調査時は失敗 phase・Run・ファイル種別・HTTP status・経過時間・試行数を秘密情報なしで記録し、401/403・不正データ・hash 不一致では retry せず、dispatch POST の自動 retry とも混ぜない。
