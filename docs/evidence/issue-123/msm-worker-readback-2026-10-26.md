# PR #290: Worker軽量化と管理API read-back（2026-10-26 JST）

> **日付付き観測記録（2026-10-26 時点）**: PR #290 実装時点の 401 調査・管理 API read-back・ローカル検証記録です。その後の 2026-11-18 復旧再配置・自然 Cron 観測は [msm-worker-recovery-2026-11-18.md](msm-worker-recovery-2026-11-18.md)、再利用知見は [MSM-TRIGGER-OPS-DRIFT](../../knowledge/entries/msm-trigger-worker-ops-drift.md) を参照してください。

## 目的と範囲（2026-10-26 時点）

PR #290 における Worker 軽量化と管理 API read-back の記録である。厳密な DO 起動回数管理は後続へ分離し、共有無料枠・課金監視は #281 へ戻した。Worker CPU の provider 実測は実行可否の検証対象に残る。

## 401調査: 確認済みと原因の確度

- PRで未確認とされた直近の失敗は19:31 JSTの
  `GET /client/v4/accounts/<account>/workers/scripts/autonavlog-msm-trigger/settings`。
  この最初のGETでHTTP 401 Unauthorizedになり、続く`schedules`には到達していなかった。
- 認証方式はWrangler保存済みOAuth access tokenを直接読み、`Authorization: Bearer`で送る方式。
  `CLOUDFLARE_API_TOKEN`、Global API Key、Worker側GitHub Secretを使った失敗ではない。
- 失敗時はPython `urllib.error.HTTPError: HTTP Error 401: Unauthorized`のみ保存され、
  CloudflareのJSONエラー本文・エラーcode・request IDは保存されていない。
  当時のtokenの有効期限も保存されていないため、歴史的な401の期限切れ・失効を断定できない。
- 直接読み出すコードには有効期限検査・OAuth refreshがない。これはWranglerの通常認証経路と異なる。
  同日09:22 JSTにも同じ直接GETが401となり、`wrangler whoami`の通常refresh後の再GETでは成功した履歴がある。
  保存済みaccess tokenの期限切れ・未更新が有力だが、直近19:31の正確なprovider理由は未確認。
- 新規発行・登録・scope変更はせず、現在有効な同じWrangler OAuth認証で再取得した。
  今回使った保存済みaccess tokenの有効期限は20:49:17 JST、再取得は20:33 JST。
  期限・scopeのメタデータだけを確認し、token・refresh token・Secret値は出力していない。

## 復旧結果（20:33 JST）

| GET API末尾 | HTTP | 確認した内容 |
| --- | --- | --- |
| `/settings` | 200 / success=true / errors=[] | MODE=observe、STATEは既存namespaceと一致、DO bindingなし |
| `/schedules` | 200 / success=true / errors=[] | schedules=[] |
| `/deployments` | 200 / success=true / errors=[] | 18:15 JSTの停止version `62d08cdc-e151-4240-9b35-68e7dcc51109` が100% |
| `/secrets` | 200 / success=true / errors=[] | 名前はGITHUB_TOKENのみ。値は取得・表示していない |

API全体の恒常的な権限不足は今回のGET成功とは整合しない。管理APIのread-backは復旧したが、
新しい認証の作成で原因を回避したものではない。旧401のJSON詳細は復元できていない。
設定の`limits`は未指定で、これをCPU無制限とは扱わない。

今後の管理read-backでは有効期限を先に確認し、必要なら既存Wranglerの通常OAuth refreshを使う。
通常refreshに失敗する場合、新規login・token作成・Secret登録・権限変更を自動で行わず、
必要な操作と理由を示して止める。401/403は別credentialへの自動切替で隠さない。

## 今回の構成と後続

Workerは2,048 bytes以内の同一deploymentのhintで候補だけを判断し、catalog/release/hash/
全payload・上流Run探索・公開成功検査をActionsへ移す。DO実装・export・binding・migrationを外した。
KVへのPOST前の回数・時刻記録、8要求/UTC日・90分以上の抑制、失敗/不明の消費、
全active状態、Actions履歴、Actions側の同Run上限・再公開防止を維持する。
KVで同時tick・古いreadの厳密なadmissionは保証しない。この保証とrolling 24時間上限は後続設計。
詳細は[運用手順](../../msm_external_trigger.md)の後続節に記す。

アカウント全体の無料枠・課金監視は#281の後続。未確認を適合済みにせず、今回の公開前提に戻さない。
公式Workers制限はFreeのCronもCPU 10msであり、CPUは今回の検証対象に残る。
[Workers limits](https://developers.cloudflare.com/workers/platform/limits/)、
[KVの結果整合性](https://developers.cloudflare.com/kv/concepts/how-kv-works/)（今回再確認）。

## PR #290 時点の未確認事項と限定実測の計画（2026-10-26）

- 軽量版の Cloudflare 上の CPU は未測定（旧版 FRESH の 17 ms・旧 526 の接続先不明は解決済みとせず、ローカル `workerd`・bundle 縮小・dry-run を provider CPU 合格へ読み替えない）。限定 observe 実測の運用手順正本は [msm_external_trigger.md](../../msm_external_trigger.md) を参照。
- 2026-10-26 20:39 JST の read-only 確認：canonical の `freshness.json` は 404、`release.json` は 200 / 29,909 bytes、公開アプリ commit と GitHub `STATIC_APPROVED_SHA` はともに `a4de2a226dfa205b8be42fb62a710a1b06271ed8`、`STATIC_EXTERNAL_TRIGGER_ENABLED` 未設定、`STATIC_AUTOMATION_ENABLED=true`。

## 2026-10-26 時点の検証と concurrency-group 境界（PR #290）

- **ローカル検証・独立レビュー**: Worker/CLI/native `workerd` 45 件、TypeScript・Wrangler dry-run（9.14 KiB / gzip 3.37 KiB）、関連 Python 123 件、公開後検証 42 件、Ruff、Web 型検査成功（GPT-6 Astra 読み取り専用レビューで必須指摘なし。隔離 Compose `autonavlog-wt-6021b5fb` / 41503 healthy）。
- **Actions concurrency-group API の採用理由（`6c6e559b` 修正後）**: 作成順で待機 Run を推定する誤判定を防ぐため、`GET /repos/Yuto-24/NavMate/actions/concurrency_groups/static-production`（当時は移行前の `Yuto-24/AutoNavLog`）で現在 Run の workflow-level lease 保持と他 Run の `pending` を確認し、確認できた待機 Run のみを active 競合から除外する（API 失敗・欠落・job-level lease・別 holder は停止）。修正後 Python 187 件成功・GPT-6 Astra 再レビューで必須指摘なし。本番 `static-production` の lock 保持経路は当時 fixture 検証のみで未実証。
