# 文書全体レビューの範囲と判断（2026-11-18）

Gemini（Agy）により、個別ファイルの添削ではなく、リポジトリ全体の読者導線・正本の分担・既存本文の編集を実施した。対象は基準commit `eb64a785a7bc1f8231ec1c47e7473373f251d9ec` の追跡Markdown全96件で、既存63件を編集し、33件を理由付きで保持した（加えて索引・復旧証拠・知見・本棚卸し記録を新設）。ここでの「編集」は全文書換えを意味せず、各行に変更内容を記す。

今後の編集基準は [writing-style.md](../writing-style.md)、目的別の入口は [ドキュメント案内](../README.md)、知見の追加先は [knowledge/README.md](../knowledge/README.md) を正本とする。この記録は2026-11-18の対象範囲と採用判断を確認するための証拠であり、生ログではない。また、コマンド検証・最終独立レビュー・PR作成は別工程であり、本記録単独で将来の本番状態や全検証完了を保証しない。

## 採用した構成と保持した境界

- 文書を「仕様」「運用・公開」「開発・検証」「再利用知見」「日付付き証拠」から探せる構成にした。既存ファイルの場所を保ち、リンク先と正本の役割を明確にした。
- 作業順の記録は、次回の判断を変える原因・条件・手順・限界と、その根拠へ整理した。安全条件や未確認事項は省略しない。
- [Worker復旧の証拠](issue-123/msm-worker-recovery-2026-11-18.md)と[次回に使う知見](../knowledge/entries/msm-trigger-worker-ops-drift.md)を分けた。`FRESH`観測を補完dispatchやMSM配信の復旧へ読み替えない。
- 公開済みCHANGELOG、UI生成入力、機械照合される証跡・データ、コード・設定・テストは変更しない。文書上の不一致は現コード（`scripts/static_ops/app_release.py`、`services/msm-trigger/ops.mjs`、`scripts/prepare_msm_feed.py`、`src/autonavlog/weather/real_msm_acceptance.py`）と照合して訂正した。

## 実行範囲と採用の確認

| 項目 | 記録 |
| --- | --- |
| ツール・指定モデル | `agy` / `gemini-4-hydrogen-high` |
| 会話ID | `060f9939-dbf6-4cef-9813-f9014366fcc0` |
| 初回全体編集の実行時刻（UTC） | `2026-11-18T04:54:15.831252+00:00` ～ `2026-11-18T05:05:26.516735+00:00`（後続の独立レビュー反映・コード照合修正を同会話で継続実施） |
| 入力文書の棚卸し | 基準commitの全96件についてpath・bytes・SHA-256を取得し、全96件の本文（`CHANGELOG.md` 全1,285行を含む）を通読 |
| 初回編集の依頼文SHA-256 | `42a0b56e22dd67675cd643f7dfe6a29a09082e184c765c8c7b91ab4dd8d7646c` |
| 初回編集の応答記録SHA-256 | `61ae583970923687e58793c25c9b12a15c0a2579d76bd8c8d015bde9de330957` |
| 最終内容確認の実行時刻（UTC） | `2026-11-18T05:14:15.639664+00:00` ～ `2026-11-18T05:16:50.576702+00:00` |
| 最終内容確認の依頼文 / 応答記録SHA-256 | `9eb9942084fdd1dfd02920a475248fd9035d42d2f34d63bd0a861db648425651` / `44cfef97393852f0a7a710c4552739583c0887ebdbb4d00a5c47672d10ee987d` |
| 最終2指摘の修正確認（同会話） | `2026-11-18T05:19:31.292735+00:00`。依頼文SHA-256 `4da458b60e0162bc43f653a1c15afbdde88d6556d1c3a748b9cbdda9fe63095d`、応答記録SHA-256 `efa5b78c1fd8789f862420fcc54c465194896b37803ebfdba008da04ca09b212` |
| 採用の確認 | 全96件の通読および独立レビュー指摘（安全条件復元・三重重複排除・リンク修正・再開条件復元・コード照合修正）の反映を確認済み。テスト・リンク検証・最終独立レビューの結果はPR本文に記録する |

モデル名は指定値であり、提供者側のモデル実体を独立に認証したものではない。生の対話ログ・認証情報・秘密設定値は公開せず、読者が必要とする判断と対象範囲だけを以下に残す。

## PR #463 レビュー反映の追加編集（2026-11-18）

- **指定モデル・実行範囲**: `gemini-4-hydrogen-high`（会話ID `d7dd7011-8dcf-438c-a97b-f86e40d53c54`、基準 HEAD `4a7dddfd`）。主要編集の実行時刻（UTC）は `2026-11-18T05:42:39.377644+00:00` ～ `2026-11-18T05:44:54.116714+00:00`（依頼文 SHA-256 `91c92a8b5aa7fc08d7b22c1bae743ae6268d04a12f3eb9a2f22d2cf7474d2889`、応答記録 SHA-256 `93cc07a349732c6749b0f75237c16a0606346f3460d0a6796ad45092858ebd6a`）。後続の独立レビュー指摘反映を同会話で継続実施（その終了時刻や確定 commit hash 等の未確定値は記録しない）。
- **編集対象と採用理由（コード・既存本文と照合した最小修正）**:
  - [docs/account_deletion.md](../../docs/account_deletion.md): Rules による即時遮断対象を全端末からの Project 書込みへ明確化し、オフライン他端末の再接続前 Local 表示と区別するため。
  - [docs/account_sync.md](../../docs/account_sync.md): `src/autonavlog/web/legacy_migration.py`、`src/autonavlog/web/migration_remote.py` と [legacy_migration.md](../../docs/legacy_migration.md) に照合し、NavMate 先行配置の理由、Legacy 未更新期間に移行 plan 内 ID の読取で `gzip-v1:` 文書へ遭遇した場合にのみ移行失敗して `LINKED` へ戻る限定条件（無関係な新規 NavMate Project の圧縮だけでは失敗しない）、更新後の既存再試行手順、残存リスクを追記するため。
  - [docs/evidence/ci/account-sync-project-shards-20261101.md](ci/account-sync-project-shards-20261101.md): `.github/workflows/test.yml` に照合し、2 箇所の記述を「`account-sync` は `account-sync-tests` のみ検査し、分配検査は `web` が実行して失敗が `web` と `ci-required` へ伝播する」事実へ整合させるため。
  - [docs/evidence/issue-121/remote-production-2026-09-24.md](issue-121/remote-production-2026-09-24.md): [custom_domain_cutover.md](../../docs/custom_domain_cutover.md) と [custom-domain-2026-09-28.md](issue-123/custom-domain-2026-09-28.md) に照合し、`2026-09-27` を決定日として記載し完了日未確認を明示するため。
  - [docs/evidence/issue-123/msm-artifact-handoff-2026-10-27.md](issue-123/msm-artifact-handoff-2026-10-27.md): `tests/integration/check_static_artifact_handoff.py` が `os.getuid()` / `os.getgid()` を使用する実装に合わせて、再現条件を `1000:1000` 固定ではなく実行ホストの非 root UID/GID として記載するため。
  - [docs/evidence/issue-265-266/2026-10-16-target-serving.md](issue-265-266/2026-10-16-target-serving.md): 同文書 94 行と整合させ、Analytics 挿入と ETag 欠落を観測事実として分け、ETag 欠落原因を未確認として保つため。
  - [docs/forecast_refresh.md](../../docs/forecast_refresh.md): `src/autonavlog/web/facade.py` と同文書 35 行に照合し、weather mode 変更時のモデル/Run ピン解除を冒頭要約へ含めるため。
  - [docs/knowledge/entries/msm-trigger-worker-ops-drift.md](../../docs/knowledge/entries/msm-trigger-worker-ops-drift.md): `services/msm-trigger/ops.mjs` に照合し、元 `MODE=dispatch` かつ承認範囲内の復旧と元 `MODE=observe` 復旧（`enable-dispatch` / `enable-cron` 禁止・元 MODE/Cron 保持・`dispatch` 化の別途承認）を分離するため。
  - [docs/msm_external_trigger.md](../../docs/msm_external_trigger.md): read-back の設定差分確認前に `enable-cron` が実行されないよう、別コードブロックへ分離するため。
  - [docs/static_operations.md](../../docs/static_operations.md): `scripts/static_ops/app_release.py`（`Operator.verify()` / `verify_serving()`）と [app_publication_audit.md](../../docs/app_publication_audit.md) に照合し、本体再取得照合の対象が `index.html` と `local/manifest.json`（と欠損 404・Pages identity）であることを明記するため。
  - [docs/README.md](../../docs/README.md): 本 PR で新設した 4 つの表直前の空行不足（markdownlint MD058）を描画修正として空行のみ補正するため。
- **結果の確認方法**: 各編集箇所と参照先ソースコード・既存文書の突合せ、および編集後の `git diff --check` による差分・空白検査を実施。

## 全96件の判定

| 文書 | 判定 | 理由・変更内容 |
| --- | --- | --- |
| [.github/pull_request_template.md](../../.github/pull_request_template.md) | 保持 | PRテンプレートはdocs/writing-style.md参照・UI文言確認欄・Release契約とPending release notes形式を簡潔に維持しており変更不要。 |
| [AGENTS.md](../../AGENTS.md) | 保持 | エージェント共通制約・レビュー要件・安全境界の正本として簡潔かつdocs/writing-style.md等へ正しく委譲しており、重複規則を追加しないため現状維持。 |
| [CHANGELOG.md](../../CHANGELOG.md) | 保持 | 全1,285行を通読し、公開済みリリースノート改変禁止の境界に従いUIお知らせ生成入力かつバージョン履歴正本として現状維持。 |
| [CLAUDE.md](../../CLAUDE.md) | 保持 | AGENTS.md・docs/knowledge・docs/writing-style.mdへの5行の簡潔な誘導であり重複がないため現状維持。 |
| [DESIGN.md](../../DESIGN.md) | 保持 | 旧設計メモを廃止し現行正本4文書へ誘導する14行の互換スタブとして明確に機能しているため現状維持。 |
| [KNOWN_ISSUES.md](../../KNOWN_ISSUES.md) | 保持 | UIお知らせ生成入力であり実文言変更に別途UI確認が必要なため現状維持し、docs/README.mdとREADME.mdから役割を明示した。 |
| [README.md](../../README.md) | 編集 | docs/README.mdとdocs/knowledge/INDEX.mdへの入口導線およびCHANGELOG/KNOWN_ISSUESの役割案内を追加（test_supported_runtime_contract.pyとtest_version.pyの必須文言・禁止文言は保持）。 |
| [data/reference/aip/20261029/sources/README.md](../../data/reference/aip/20261029/sources/README.md) | 保持 | SWIM 2026-10-29原本ZIP3点のSHA-256と来歴・表示境界を簡潔に記録しており現状維持。 |
| [docs/account_deletion.md](../../docs/account_deletion.md) | 編集 | 冒頭に結論・対象範囲（#181状態遷移・世代分離・#393文言確認）の要約を追加し、目的から読み始められるよう整理。 |
| [docs/account_sync.md](../../docs/account_sync.md) | 編集 | 冒頭にAccount Syncと大容量圧縮の要約を追加し、rollout節のPR時代表現（「this PR does not deploy...」）を運用手順表現へ整理（既存アンカー保持）。 |
| [docs/agent_workflow.md](../../docs/agent_workflow.md) | 編集 | 参照先と確認範囲にdocs/README.md・docs/writing-style.md・docs/knowledge/INDEX.mdへの入口導線を追加。 |
| [docs/airport-vor-departure.md](../../docs/airport-vor-departure.md) | 保持 | VOR Tracking Modeの仕様・対応局根拠・vor_stations.json正本境界が簡潔明瞭に整理されているため現状維持。 |
| [docs/app_publication_audit.md](../../docs/app_publication_audit.md) | 編集 | 後続単位節のPR時代表現を#339提案と#440/#454実装済みの区別へ整理し、Journal.finish()のstdout全出力指摘がf0de81a8および現行scripts/static_ops/app_release.pyで非公開化済みである旨を注記（既存アンカー保持）。 |
| [docs/application_contract.md](../../docs/application_contract.md) | 編集 | 冒頭にAutoNavLogApplication契約・Session復元・エラー正規化の要約を追加（#119アンカー保持）。 |
| [docs/architecture.md](../../docs/architecture.md) | 編集 | 冒頭でStatic Web本番経路（React+Pyodide+IndexedDB）とLegacy FastAPI検証経路の位置づけを明確化。 |
| [docs/authentication.md](../../docs/authentication.md) | 編集 | 冒頭にFirebase Auth・account_v1_境界の要約を追加し、実装時のFirebase不在表現を自動テスト検証境界の明確な記述へ整理。 |
| [docs/automatic_app_releases.md](../../docs/automatic_app_releases.md) | 編集 | 冒頭に自動公開の適用条件要約を追加し、現行scripts/static_ops/app_release.py:271-299に合わせてJournal.finish()がstatus/review_sha256/plan_sha256のみstdout出力しfull journalを非公開保持する事実を明記。 |
| [docs/calculation_rules.md](../../docs/calculation_rules.md) | 保持 | 計算・表示・燃料・RJFM Policy・30° CUTの正本として構造・根拠ともに一貫しているため現状維持。 |
| [docs/cloudflare_tunnel.md](../../docs/cloudflare_tunnel.md) | 編集 | 冒頭で本手順がLegacy FastAPI/Docker版専用でありStatic Web本番には不要であることを明確化。 |
| [docs/custom_domain_cutover.md](../../docs/custom_domain_cutover.md) | 編集 | 冒頭にnavmate.yuto24.com切替の正本範囲と日付付き証跡（2026-09-28）へのリンクを追加。 |
| [docs/data_provenance.md](../../docs/data_provenance.md) | 編集 | AIP 2026-10-29取込準備節の現在地と未完了事項（#149）の時制・日付表現を整理。 |
| [docs/development_worktrees.md](../../docs/development_worktrees.md) | 編集 | 冒頭にWorktree分離とprewarm抑止の結論要約を追加し、重複した前置きを整理（既存アンカー保持）。 |
| [docs/evidence/alt-responsive-copy-review.md](../../docs/evidence/alt-responsive-copy-review.md) | 保持 | Gemini CLIの1回確認記録・会話ID・対象境界が23行で簡潔に完結しているため現状維持。 |
| [docs/evidence/ci/account-sync-project-shards-20261101.md](../../docs/evidence/ci/account-sync-project-shards-20261101.md) | 編集 | PRスタック時のマージ前提記述を整理し、結論・適用条件・現行testing.md正本への誘導を冒頭に構造化。 |
| [docs/evidence/ci/account-sync-workers-20261101.md](../../docs/evidence/ci/account-sync-workers-20261101.md) | 保持 | 結論・測定結果・固定条件と限界・再現手順・変更範囲が明確に構造化されているため現状維持。 |
| [docs/evidence/ci/arita-calculation-wait-20261109.md](../../docs/evidence/ci/arita-calculation-wait-20261109.md) | 保持 | 失敗根拠・待機条件・CPU競合再現・修正境界が明確に構造化されているため現状維持。 |
| [docs/evidence/ci/impact-selection-20261110.md](../../docs/evidence/ci/impact-selection-20261110.md) | 編集 | 2026-11-17のRuleset登録完了・PR #448/#449実測を冒頭結論へ反映し、途中の旧「未確認だった」記述削除と末尾PR作業ログ文言の圧縮を実施。 |
| [docs/evidence/ci/independent-shards-20261101.md](../../docs/evidence/ci/independent-shards-20261101.md) | 編集 | PR相対表現を除去し、Pythonファイル分割のクリティカルパス制約・現行拡張先への誘導を冒頭に追加。 |
| [docs/evidence/header-218/README.md](../../docs/evidence/header-218/README.md) | 保持 | 結論・画面リンク・検証範囲・独立レビュー・限界が簡潔に整理されているため現状維持。 |
| [docs/evidence/issue-121/remote-production-2026-09-24.md](../../docs/evidence/issue-121/remote-production-2026-09-24.md) | 編集 | 旧navmate.pages.dev/v1.20.1の歴史的監査記録であり現行オリジンや異なるschema互換の証拠ではない旨を冒頭に明記。 |
| [docs/evidence/issue-123/activation-2026-09-26.md](../../docs/evidence/issue-123/activation-2026-09-26.md) | 編集 | 2026-09-26初期構築監査であることを明示し、skipped履歴とOAuth 401の再利用教訓を冒頭へ抽出。 |
| [docs/evidence/issue-123/custom-domain-2026-09-28.md](../../docs/evidence/issue-123/custom-domain-2026-09-28.md) | 編集 | 2026-09-28切替前観測であることを明示し、ALLOWED_ORIGINS文字列仕様・urllib 403差・CORS限界の教訓を冒頭へ抽出。 |
| [docs/evidence/issue-123/local-operations.md](../../docs/evidence/issue-123/local-operations.md) | 編集 | PR実装時表現を2026-09-24初期実装検証記録へ改め、no-new-Run拒否やTAF独立性等の再利用境界を構造化・末尾作業ログを整理。 |
| [docs/evidence/issue-123/msm-artifact-handoff-2026-10-27.md](../../docs/evidence/issue-123/msm-artifact-handoff-2026-10-27.md) | 編集 | Docker root出力とnonroot間のPermissionError原因・限定chown対処・限界を冒頭へ構造化し、PR状態・レビュー作業ログを圧縮。 |
| [docs/evidence/issue-123/msm-recovery-2026-10-08.md](../../docs/evidence/issue-123/msm-recovery-2026-10-08.md) | 編集 | 2026-10-08の日付付き監査へ整理し、7日超失効時の保持0件・コンテナ隔離・OAuth 401限界を冒頭抽出して末尾PR作業ログを削減。 |
| [docs/evidence/issue-123/msm-recovery-2026-10-21.md](../../docs/evidence/issue-123/msm-recovery-2026-10-21.md) | 編集 | 2026-10-21の準備監査へ整理し、#250 missing表現・#264 catalog同一応答検証・モデル独立レビュー教訓を冒頭抽出・末尾PR境界を削減。 |
| [docs/evidence/issue-123/msm-worker-readback-2026-10-26.md](../../docs/evidence/issue-123/msm-worker-readback-2026-10-26.md) | 編集 | 2026-10-26の日付付き観測へ整理し、2026-11-18復旧記録およびMSM-TRIGGER-OPS-DRIFTへ相互リンク、末尾レビュー作業文言を圧縮。 |
| [docs/evidence/issue-123/unattended-readiness-2026-10-22.md](../../docs/evidence/issue-123/unattended-readiness-2026-10-22.md) | 編集 | 2026-10-22監査から再利用技術知見（cache-storage-limit 402、verify_limits HTMLパーサー、WIF課金境界）を冒頭抽出し末尾PR作業メモを削減。 |
| [docs/evidence/issue-144/ipad-safari-acceptance.md](../../docs/evidence/issue-144/ipad-safari-acceptance.md) | 保持 | 2026-09-16実機iPad Safari確認結果と未記録項目を26行で誠実かつ簡潔に記録しているため現状維持。 |
| [docs/evidence/issue-235-inbound-umk-local.md](../../docs/evidence/issue-235-inbound-umk-local.md) | 編集 | 最新V3正本（rjfm_inbound_guidance.md）との関係を明示し、PR取り込み前の引き継ぎ文言をb515afc7ベースライン・検証限界・参照commit一覧へ整理。 |
| [docs/evidence/issue-257-worktree-cache.md](../../docs/evidence/issue-257-worktree-cache.md) | 編集 | 冒頭で原因（48h prewarm・旧イメージ・WSL VHDX非自動縮小）と正本development_worktrees.mdへの導線を構造化し、末尾PR配信表現を整理。 |
| [docs/evidence/issue-265-266/2026-10-16-target-serving.md](../../docs/evidence/issue-265-266/2026-10-16-target-serving.md) | 編集 | Draft PR依存・未マージbranch指定を2026-10-16時点境界へ書き換え、#265のA/B/Bドリフトと#266のError 1010知見を冒頭へ抽出。 |
| [docs/evidence/issue-265-266/2026-10-17-root-analytics.md](../../docs/evidence/issue-265-266/2026-10-17-root-analytics.md) | 編集 | 2026-10-17単一版失敗が2026-10-18の2版許可リストへ置換された歴史的記録であることを明記し、旧未マージPR指示を2026-10-17時点記録へ整理。 |
| [docs/evidence/issue-265-266/2026-10-18-two-analytics-versions.md](../../docs/evidence/issue-265-266/2026-10-18-two-analytics-versions.md) | 編集 | 旧Draft PRスタックの現在形表現を除去し、2版リテラル許可の根拠と公開時原本不在の限界を冒頭へ整理。 |
| [docs/evidence/issue-354-msm-discovery-2026-11-04.md](../../docs/evidence/issue-354-msm-discovery-2026-11-04.md) | 保持 | 原因未確定の事実・再現条件・run_discovery診断仕様が60行で明確に構造化されているため現状維持。 |
| [docs/evidence/issue-374/README.md](../../docs/evidence/issue-374/README.md) | 保持 | 正本wx_profile_feasibility.mdへの誘導と検証再現コマンド・限界を簡潔にまとめているため現状維持。 |
| [docs/evidence/ui/416-443-local-validation.md](../../docs/evidence/ui/416-443-local-validation.md) | 編集 | 3回のレビュー往復時系列節を「主な検証対象と修正境界」「ベースライン検証と再現確認」「残るゲート・UI文言照合の記録」へ統合再編し、全SHA/件数/レビュー根拠を保持。 |
| [docs/forecast_backup.md](../../docs/forecast_backup.md) | 編集 | 冒頭に既定無効の予備計算API境界要約を追加し、末尾のPR時代表現（「本PRは...」）を運用境界表現へ修正。 |
| [docs/forecast_refresh.md](../../docs/forecast_refresh.md) | 編集 | 冒頭にDATE/ETDによるピン解除とfingerprint比較による更新規則の要約を追加。 |
| [docs/forecast_schema_transition.md](../../docs/forecast_schema_transition.md) | 編集 | v2.3.2移行が2026-11-15に完了した現在地を冒頭・候補表・本文へ反映し、本番受入と承認済みSHA引継ぎ完了後の自動運用再開条件を復元して矛盾を解消。 |
| [docs/forecast_selection.md](../../docs/forecast_selection.md) | 編集 | 冒頭にMSM→GSM優先順位・jma-gpv-weather 0.6.0境界・Schema 5契約の要約を追加。 |
| [docs/knowledge/INDEX.md](../../docs/knowledge/INDEX.md) | 編集 | docs/README.mdへの誘導を追加し、MSM Worker知見エントリMSM-TRIGGER-OPS-DRIFT・docs/msm_external_trigger.md・2026-11-18復旧記録を索引へ統合。 |
| [docs/knowledge/README.md](../../docs/knowledge/README.md) | 編集 | 全体目次docs/README.mdおよび文書統制正本docs/writing-style.mdへの相互参照を追加。 |
| [docs/knowledge/TEMPLATE.md](../../docs/knowledge/TEMPLATE.md) | 保持 | 再利用可能知見の構造化テンプレートとして過不足なく機能しているため現状維持。 |
| [docs/knowledge/entries/msm-verification-budget.md](../../docs/knowledge/entries/msm-verification-budget.md) | 保持 | TEMPLATE.mdおよびwriting-style.mdに準拠した構造化済み知見エントリであるため現状維持。 |
| [docs/legacy_migration.md](../../docs/legacy_migration.md) | 編集 | 冒頭にLegacyアカウント連携とNAVMATE_ACTIVE移行契約の要約を追加（既存アンカー保持）。 |
| [docs/local_calculation_core.md](../../docs/local_calculation_core.md) | 編集 | 冒頭で#125固定fixture回帰と本番運用正本への導線を明確化し、末尾の実装チェック経過文を2026-09-14時点検証要約へ圧縮。 |
| [docs/local_calculation_poc.md](../../docs/local_calculation_poc.md) | 編集 | 2026-09-13のPython/Pyodide正式採用決定を冒頭へ明示し、PR #162チェックポイント作業ログを1段落へ統合整理（既存アンカー保持）。 |
| [docs/local_persistence.md](../../docs/local_persistence.md) | 編集 | 冒頭にIndexedDB v2 / Latest / CAS / 気象キャッシュ退避の契約要約を追加。 |
| [docs/local_static_docker.md](../../docs/local_static_docker.md) | 編集 | 冒頭にcompose.local.yamlの用途（ローカル開発自動更新）と本番Pages/Legacy Composeとの分離を明記（既存アンカー保持）。 |
| [docs/local_weather.md](../../docs/local_weather.md) | 編集 | scripts/prepare_msm_feed.pyのfull_run_requirements()がMAX_FORECAST_HOURS=78を走査上限とするコード実装と一致するよう本文を訂正。 |
| [docs/map_background.md](../../docs/map_background.md) | 保持 | 地理院タイル仕様・欠損処理・出典常時表示の根拠が簡潔明瞭に整理されているため現状維持。 |
| [docs/map_route_builder.md](../../docs/map_route_builder.md) | 編集 | 冒頭に#174/#175/#176とKML/KMZ連結規則の要約を追加し、各節の「Verification adds / Release owned by integration」調記述を中立なテスト範囲記述へ整理。 |
| [docs/msm_external_trigger.md](../../docs/msm_external_trigger.md) | 編集 | PR #290実装前の旧記述を現行仕様へ全面更新し、ops.mjsのconfiguration()呼出しコマンド一覧とdeploy-staged/planの違い、有効化前限定observe実測・停止条件、15分Cron伝播・KV削除禁止・pending承認整理、Secret権限境界（PAT/Pages/Heartbeat・stage制約）、2026-11-18復旧結果と未実証境界（証跡/知見へ分離委譲し三重重複排除）を統合。 |
| [docs/navmate_branding.md](../../docs/navmate_branding.md) | 編集 | 冒頭にブランド統合・互換境界の要約を置き、2026-10-24マージや2026-11-08確認を日付付き観測へ整理してWorker再配置注記を補完。 |
| [docs/platform_capabilities.md](../../docs/platform_capabilities.md) | 編集 | 冒頭にBrowser Platform境界とDomain分離の要約を追加。 |
| [docs/primary_source_audit.md](../../docs/primary_source_audit.md) | 保持 | 一次資料の公開範囲・POH版数・VERIFIED状態の意味を42行で明瞭に記述しているため現状維持。 |
| [docs/real_msm_acceptance.md](../../docs/real_msm_acceptance.md) | 編集 | src/autonavlog/weather/real_msm_acceptance.pyのコード実装に合わせて依存記述をjma-msm-wind==0.2.1からjma-gpv-weather==0.6.0へ訂正。 |
| [docs/reference/aip_map_geodata_20261029.md](../../docs/reference/aip_map_geodata_20261029.md) | 保持 | SWIM 2026-10-29データ構成・KS4境界との責務分離・#149未完了条件が簡潔に整理されているため現状維持。 |
| [docs/reference/vrep-169-confirmed-source.md](../../docs/reference/vrep-169-confirmed-source.md) | 保持 | build_vrep_catalog.pyの入力元となる17空港・115点の不変原典データ記録であり現状維持。 |
| [docs/reference/vrep.md](../../docs/reference/vrep.md) | 編集 | 「mainは新規MAP経路のみで再編集未対応」という旧記述を初期#169時点の履歴注記へ改め、現行map_route_builder.mdへ誘導。 |
| [docs/release_lines.md](../../docs/release_lines.md) | 編集 | release/1.x初期化節のPR時点表現（「At preparation time...」）を条件付きの一般手順表現へ整理。 |
| [docs/rjfm_arrival_vrep_altitudes.md](../../docs/rjfm_arrival_vrep_altitudes.md) | 保持 | ARITA/SHIRAHAMAの1,500 ft自動計画規則を23行で過不足なく記述しているため現状維持。 |
| [docs/rjfm_inbound_guidance.md](../../docs/rjfm_inbound_guidance.md) | 編集 | 冒頭に最新のInbound Policy V3と西側延長案内カードの位置づけ要約を追加。 |
| [docs/rounding_mode_helpers.md](../../docs/rounding_mode_helpers.md) | 編集 | 冒頭を結論先出し（現在地・UI配置根拠・calculation_rules.md正本誘導）へ整理し、他branch担当等の作業メモ的表現を除去。 |
| [docs/schema431_actions_prepare.md](../../docs/schema431_actions_prepare.md) | 編集 | v2.3.2移行の2026-11-15完了状態を冒頭に明示し、末尾の#440未実装表現を実装済み（app_publication_audit.md参照）へ整合（既存アンカー保持）。 |
| [docs/schema_transition.md](../../docs/schema_transition.md) | 編集 | 1.x DB v1→v2 writer fence移行とv2系Schema 4→5移行（forecast_schema_transition.md）の区別を冒頭で明確化。 |
| [docs/schema_transition_validation.md](../../docs/schema_transition_validation.md) | 編集 | 冒頭にローカル実装検証の位置づけと2つの再利用知見（環境メタデータ分離・resolve時のstale除去）を明記。 |
| [docs/server_retirement.md](../../docs/server_retirement.md) | 編集 | 「現時点では停止不可」「本準備では未実施」表現を承認条件明示・2026-10-23歴史的ベースラインへ整理（既存アンカー保持）。 |
| [docs/source_policy.md](../../docs/source_policy.md) | 保持 | 内部資料非公開方針と実装Policy分離を27行で明瞭に定めているため現状維持。 |
| [docs/static_operations.md](../../docs/static_operations.md) | 編集 | 冒頭に運用責務一覧・正本リンク・Operator.verify()と--verify-payloadsの範囲差を明示し、PR #211前置き・v1.22.7履歴文脈・#281認証プローブ・PR #232 static-provider-probe手順の作業ログ重複を圧縮（既存アンカー全保持）。 |
| [docs/static_production.md](../../docs/static_production.md) | 編集 | 冒頭をnavmate.yuto24.com正式本番経路・関連正本リンク・承認境界・旧pages.dev位置づけの簡潔な要約へ整理（既存アンカー保持）。 |
| [docs/static_web_browser_acceptance.md](../../docs/static_web_browser_acceptance.md) | 編集 | 冒頭に受入3区分と2026-09-27/28実機ゲート完了サマリーを追加（既存アンカー保持）。 |
| [docs/taf_proxy.md](../../docs/taf_proxy.md) | 編集 | 冒頭からPRスコープ列挙を削り、TAF Proxy契約・障害分離の簡潔な概要へ整理。 |
| [docs/terrain_inputs.md](../../docs/terrain_inputs.md) | 保持 | GSI DEM10B仕様・取得境界・地形点KML検証・AREA1除外・検証範囲が明確に整理されているため現状維持。 |
| [docs/testing.md](../../docs/testing.md) | 編集 | 冒頭にCIルーティング・#458境界・Browser検証入口の要約を追加し、#142/#154棚卸し見出しを歴史的記録として明記（既存アンカー全保持）。 |
| [docs/ui_copy_review.md](../../docs/ui_copy_review.md) | 保持 | scripts/ui_copy_review.pyの機械照合契約と完全に整合した簡潔な正本であるため現状維持。 |
| [docs/web-design/README.md](../../docs/web-design/README.md) | 編集 | 冒頭に#416の1マップ・1操作ペイン契約を明記し、切れていた../../README.md#開発リンクを../release_lines.mdへ修正、末尾のPRゲート文言を除去。 |
| [docs/writing-style.md](../../docs/writing-style.md) | 編集 | 正本と証跡の分離・現在地と日付付き観測の区別・入口目次同期・証跡秘匿のドキュメント統制基準を統合。 |
| [docs/wx_profile_feasibility.md](../../docs/wx_profile_feasibility.md) | 保持 | 結論先出し・1次資料比較・実データ限界・容量予算・コード相違まで網羅的に構造化されているため現状維持。 |
| [tests/fixtures/forecast-policy-README.md](../../tests/fixtures/forecast-policy-README.md) | 保持 | 合成acceptance fixtureの生成条件と限界を28行で明確に記録しているため現状維持（ci_changes.py上も非docs扱い）。 |
| [tests/fixtures/msm-portable/README.md](../../tests/fixtures/msm-portable/README.md) | 保持 | オフラインMSMスナップショットの固定条件を9行で正確に記録しているため現状維持。 |
| [tests/fixtures/schema4/README.md](../../tests/fixtures/schema4/README.md) | 保持 | v2.2.2合成レコードの再生成手順と境界を23行で正確に記録しているため現状維持。 |
| [tests/fixtures/static-root-analytics/README.md](../../tests/fixtures/static-root-analytics/README.md) | 保持 | Issue #266捕捉HTMLフィクスチャのハッシュ・オフセット・来歴記録であり現状維持。 |
| [vendor/README.md](../../vendor/README.md) | 保持 | jma_gpv_weather-0.6.0 wheelのソースcommitとSHA-256を14行で正確に記録しているため現状維持。 |
| [web/e2e/no-legacy.md](../../web/e2e/no-legacy.md) | 保持 | #146 No-Legacy検証の独立スイート実行手順・環境記録であり、docs外ファイルで変更不要のため現状維持。 |
