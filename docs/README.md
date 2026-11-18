# NavMate ドキュメント案内

このリポジトリの文書は **目的別（仕様の正本／運用・リリース／開発・検証／知見／証跡）** に整理しています。知りたいテーマの正本から参照してください。

- **製品と操作の概要**: [README](../README.md)（本番経路・保存の注意・基本検証コマンド）
- **利用者向け公開記録（UI 生成入力）**: [変更履歴 (CHANGELOG)](../CHANGELOG.md)、[既知の不具合 (KNOWN_ISSUES)](../KNOWN_ISSUES.md)
  - Information ダイアログの生成入力です。公開済みリリースノートは改変せず、UI 文言の変更時は [UI 文言確認手順](ui_copy_review.md) に従います。
- **過去の個別検証・障害調査**: [証跡アーカイブ](evidence/) は実施時点の観測と再利用可能な判断材料を保持します。現在の本番状態や最新仕様の根拠にはしません。

## 1. 仕様の正本（設計・計算・データ・UI）

### 航法計算・経路・地図・地形
| テーマ | 正本 | ここで分かること |
| --- | --- | --- |
| NAV LOG 計算・表示 | [calculation_rules.md](calculation_rules.md) | 丸め、VAR/VOR、各 Flight Phase、燃料計画、RJFM Policy、参考表示の規則 |
| 四捨五入モード | [rounding_mode_helpers.md](rounding_mode_helpers.md) | 計算・表示への丸め適用、UI 配置根拠、一時設定のライフサイクル |
| 出発 VOR 基準 | [airport-vor-departure.md](airport-vor-departure.md) | 出発位置 VOR Tracking Mode、対応局、第 1 Leg 磁気基準、原本 JSON の管理 |
| RJFM 到着高度 | [rjfm_arrival_vrep_altitudes.md](rjfm_arrival_vrep_altitudes.md) | RJFM 向け特定 VREP の自動計画高度と手動入力優先規則 |
| RJFM 帰路・延長案内 | [rjfm_inbound_guidance.md](rjfm_inbound_guidance.md) | RJFM 帰路補完、KS4-3 回避境界と安全余裕、参考案内カードの扱い |
| MAP 経路作成・KML/KMZ | [map_route_builder.md](map_route_builder.md) | MAP 経路作成、確定済み経路の再編集、KML/KMZ 取込・連結規則 |
| 背景地図・出典 | [map_background.md](map_background.md) | 背景地図タイルの配信元・表示範囲、欠損時処理、出典表示要件 |
| 地形入力（DEM / KML） | [terrain_inputs.md](terrain_inputs.md) | GSI DEM 復号・被覆判定、地形点 KML の標高基準・障害物除外境界 |

### 出典・参照データ来歴
| テーマ | 正本 | ここで分かること |
| --- | --- | --- |
| 出典公開方針 | [source_policy.md](source_policy.md) | 内部運用資料の非公開境界と公開資料の出典管理方針 |
| 一次資料の確認状況 | [primary_source_audit.md](primary_source_audit.md) | SR22 AFM/POH・公開航空資料・内部参照の確認粒度と確認状態の定義 |
| データ来歴 | [data_provenance.md](data_provenance.md) | 同梱性能データ、空港・RJFM 参照、VOR/DME 局、気象、AIP データの来歴 |
| VREP 登録カタログ | [reference/vrep.md](reference/vrep.md) | 登録 VREP カタログの選択・永続化と [承認済み原典表](reference/vrep-169-confirmed-source.md) |
| AIP 地図表示用データ | [reference/aip_map_geodata_20261029.md](reference/aip_map_geodata_20261029.md) | SWIM 配布 ZIP（[ソース記録](../data/reference/aip/20261029/sources/README.md)）の採用範囲と取込条件 |
| 旧設計メモ互換入口 | [DESIGN.md](../DESIGN.md) | 旧メモ廃止・現行正本への誘導スタブ |

### 気象・選択・予備経路
| テーマ | 正本 | ここで分かること |
| --- | --- | --- |
| モデル選択（MSM→GSM） | [forecast_selection.md](forecast_selection.md) | モデル優先順位、互換性・天気ライブラリ境界、Schema 拡張の契約 |
| 再計算・Run 更新 | [forecast_refresh.md](forecast_refresh.md) | 入力変更時の Run 固定／更新規則と旧 Run 注意表示 |
| Local Static 気象運用 | [local_weather.md](local_weather.md) | 静的 MSM/GSM 配信、ブラウザキャッシュ契約、取得障害の分類と切替 |
| 目的地 TAF Proxy | [taf_proxy.md](taf_proxy.md) | 目的地 TAF 用 Serverless Proxy の契約、制限、配備・確認手順 |
| 計算専用予備サーバー | [forecast_backup.md](forecast_backup.md) | 既定無効の予備計算 API 境界、実行・レート制限、有効化前条件 |
| WX 雲・湿度検証 | [wx_profile_feasibility.md](wx_profile_feasibility.md) | 雲・湿度プロファイルの技術検証結論、容量概算、上流 API 提案 |

### アプリケーション・永続化・アカウント・UI
| テーマ | 正本 | ここで分かること |
| --- | --- | --- |
| 全体アーキテクチャ | [architecture.md](architecture.md) | Static / Legacy 境界、保存層構造、表示投影、気象 Provider 接続 |
| Application 境界・Session | [application_contract.md](application_contract.md) | `AutoNavLogApplication` 契約、エラー正規化、同一タブ reload 復元 |
| Browser Platform 境界 | [platform_capabilities.md](platform_capabilities.md) | ファイル入出力・Clipboard・KML 出力・外部リンク・接続ヒントの分離 |
| IndexedDB 永続化 | [local_persistence.md](local_persistence.md) | ブラウザ内 Project 永続化、CAS・マイグレーション・容量退避境界 |
| Google ログイン | [authentication.md](authentication.md) | Firebase Auth、決定論的アカウント識別、名前空間分離、失効時遮断 |
| Account Sync | [account_sync.md](account_sync.md) | Firestore 同期、大容量ペイロード圧縮、競合解決、削除 Undo |
| アカウント削除 | [account_deletion.md](account_deletion.md) | アカウント削除の状態遷移、他端末遮断、再登録時の世代分離 |
| Legacy アカウント連携・移行 | [legacy_migration.md](legacy_migration.md) | Legacy 所有者連携、一括移行の状態遷移、Access 例外境界 |
| UI デザイン・レイアウト | [web-design/README.md](web-design/README.md) | 画面構成、レスポンシブ配置規則、トークン、文言ロック方針 |
| NavMate ブランド統合 | [navmate_branding.md](navmate_branding.md) | ブランド名・リポジトリ名と既存識別子の互換境界、アイコン再生成 |

## 2. 運用・配信・リリース手順

| テーマ | 正本 | ここで分かること |
| --- | --- | --- |
| Static Web 本番ビルド・公開 | [static_production.md](static_production.md) | 本番ビルド・検査、Pages 手動配備、ロールバック、無料枠条件 |
| 定常運用・アプリ手動公開 | [static_operations.md](static_operations.md) | 毎時 MSM 更新、監視、WSL `prepare` / `publish`、Rules 移行、クオータ確認 |
| MSM 補完起動 Worker | [msm_external_trigger.md](msm_external_trigger.md) | 補完起動 Worker の契約、CLI 注意点、限定 observe 確認、停止境界 |
| カスタムドメイン切替 | [custom_domain_cutover.md](custom_domain_cutover.md) | 本番ドメイン切替の順序、TAF/Legacy 設定整合、ロールバック方針 |
| 安定版 Release 自動公開 | [automatic_app_releases.md](automatic_app_releases.md) | 安定版 Release からの自動公開橋渡し、単調更新と停止条件 |
| バージョンライン・Release 契約 | [release_lines.md](release_lines.md) | 開発・保守ブランチ運用、VERSION/CHANGELOG と PR Release 契約 |
| Schema 4→5 手動移行 | [forecast_schema_transition.md](forecast_schema_transition.md) | Schema 4→5 移行の互換条件、完了記録、再適用 helper 手順 |
| Schema 4→5 Actions 手順 | [schema431_actions_prepare.md](schema431_actions_prepare.md) | Actions による暗号化受け渡し手順、期限境界、実公開知見 |
| 1.x 一方通行ストレージ移行 | [schema_transition.md](schema_transition.md) | 1.x DB アクセス境界移行手順と [実装検証記録](schema_transition_validation.md) |
| 旧サーバ廃止準備・救済 | [server_retirement.md](server_retirement.md) | 旧環境停止の前提条件、移行 URL 除去、オフライン救済と Volume 整理 |
| Local 版 Docker 自動更新 | [local_static_docker.md](local_static_docker.md) | ローカル Docker 自動更新、共有開発モード、MSM キャッシュ整理 |
| Legacy Tunnel / Access | [cloudflare_tunnel.md](cloudflare_tunnel.md) | Legacy Docker 版のローカルバインド・Cloudflare Tunnel / Access 設定 |

## 3. 開発・テスト・統制・知見

| テーマ | 正本 | ここで分かること |
| --- | --- | --- |
| エージェント共通制約 | [AGENTS.md](../AGENTS.md) / [CLAUDE.md](../CLAUDE.md) | スコープ制限、モデル独立レビュー、安全境界、Worktree 原則 |
| モデル選択・作業手順 | [agent_workflow.md](agent_workflow.md) | 独立レビュー引き継ぎ、段階的調査・検証、CI 監視停止ルール |
| 文章規範・ドキュメント統制 | [writing-style.md](writing-style.md) | 読者向け文章ルール、正本・証跡・知見の維持基準、提出前チェック |
| UI 文言確認手順 | [ui_copy_review.md](ui_copy_review.md) | Gemini CLI 確認・採用理由記録・ソース照合の手順 |
| Codex Worktree 開発環境 | [development_worktrees.md](development_worktrees.md) | 隔離 Compose・開発バックアップ保持・終了時整理・prewarm 抑止 |
| テスト・CI 分割 | [testing.md](testing.md) | PR 影響判定、CI 分割構成、Browser 検証入口、テスト配置規則 |
| Static ブラウザ受入 | [static_web_browser_acceptance.md](static_web_browser_acceptance.md) | ブラウザ・端末別受入マトリクスと実機チェックリスト |
| 実 MSM 受入検査 | [real_msm_acceptance.md](real_msm_acceptance.md) | 実 MSM パッケージとライブ気象取得の受入検査手順 |
| アプリ公開工程の監査 | [app_publication_audit.md](app_publication_audit.md) | 公開工程の重複・排他評価、Pages 履歴通信上限、工程計測境界 |
| 再利用可能な知見 | [knowledge/INDEX.md](knowledge/INDEX.md) | 知見索引（[運用ルール](knowledge/README.md) / [テンプレート](knowledge/TEMPLATE.md)） |

## 4. 過去のPoC・証跡・フィクスチャ記録

- **文書全体統制の棚卸し（2026-11-18）**: [documentation-governance-20261118.md](evidence/documentation-governance-20261118.md)（全 96 件の判定・構成設計・コード照合記録）
- **Pyodide 採用判断と初期基準**: [local_calculation_poc.md](local_calculation_poc.md)（採用決定と PoC 記録）、[local_calculation_core.md](local_calculation_core.md)（固定 fixture 回帰基準）
- **公開・運用証跡（Issue #121 / #123 / #265-#266 / #354）**:
  - #121 初期本番監査（旧オリジン）: [remote-production-2026-09-24.md](evidence/issue-121/remote-production-2026-09-24.md)
  - #123 構築・切替・復旧: [local-operations.md](evidence/issue-123/local-operations.md)、[activation-2026-09-26.md](evidence/issue-123/activation-2026-09-26.md)、[custom-domain-2026-09-28.md](evidence/issue-123/custom-domain-2026-09-28.md)、[msm-recovery-2026-10-08.md](evidence/issue-123/msm-recovery-2026-10-08.md)、[msm-recovery-2026-10-21.md](evidence/issue-123/msm-recovery-2026-10-21.md)、[unattended-readiness-2026-10-22.md](evidence/issue-123/unattended-readiness-2026-10-22.md)、[msm-artifact-handoff-2026-10-27.md](evidence/issue-123/msm-artifact-handoff-2026-10-27.md)
  - MSM 補完起動 Worker: [msm-worker-readback-2026-10-26.md](evidence/issue-123/msm-worker-readback-2026-10-26.md)、[msm-worker-recovery-2026-11-18.md](evidence/issue-123/msm-worker-recovery-2026-11-18.md)
  - Pages / Analytics 検証（#265 / #266）: [2026-10-16-target-serving.md](evidence/issue-265-266/2026-10-16-target-serving.md)、[2026-10-17-root-analytics.md](evidence/issue-265-266/2026-10-17-root-analytics.md)、[2026-10-18-two-analytics-versions.md](evidence/issue-265-266/2026-10-18-two-analytics-versions.md)
  - MSM Run 不一致調査（#354）: [issue-354-msm-discovery-2026-11-04.md](evidence/issue-354-msm-discovery-2026-11-04.md)
- **CI・端末・UI・経路・環境証跡**:
  - CI 分割・計測: [independent-shards-20261101.md](evidence/ci/independent-shards-20261101.md)、[account-sync-workers-20261101.md](evidence/ci/account-sync-workers-20261101.md)、[account-sync-project-shards-20261101.md](evidence/ci/account-sync-project-shards-20261101.md)、[arita-calculation-wait-20261109.md](evidence/ci/arita-calculation-wait-20261109.md)、[impact-selection-20261110.md](evidence/ci/impact-selection-20261110.md)
  - 実機・Local・UI: [ipad-safari-acceptance.md](evidence/issue-144/ipad-safari-acceptance.md)、[issue-235-inbound-umk-local.md](evidence/issue-235-inbound-umk-local.md)、[issue-257-worktree-cache.md](evidence/issue-257-worktree-cache.md)、[header-218/README.md](evidence/header-218/README.md)、[alt-responsive-copy-review.md](evidence/alt-responsive-copy-review.md)、[ui/416-443-local-validation.md](evidence/ui/416-443-local-validation.md)、[issue-374/README.md](evidence/issue-374/README.md)
- **テスト・依存アーカイブの補助メモ**: [vendor/README.md](../vendor/README.md)、[web/e2e/no-legacy.md](../web/e2e/no-legacy.md)、[tests/fixtures/forecast-policy-README.md](../tests/fixtures/forecast-policy-README.md)、[tests/fixtures/msm-portable/README.md](../tests/fixtures/msm-portable/README.md)、[tests/fixtures/schema4/README.md](../tests/fixtures/schema4/README.md)、[tests/fixtures/static-root-analytics/README.md](../tests/fixtures/static-root-analytics/README.md)
