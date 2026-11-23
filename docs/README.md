# NavMate ドキュメント案内

このリポジトリの文書は **読者向けの仕様・設計（日本語・上流工程の範囲）** と **Agent・運用者向けの運用手順・開発／検証・技術調査・証跡アーカイブ** に役割を分けて整理しています。

- **製品と操作の概要**: [README](../README.md)（機能概要・データ保存と安全上の注意・開発/運用への入口）
- **利用者向け公開記録（UI 生成入力）**: [変更履歴 (CHANGELOG)](../CHANGELOG.md)、[既知の不具合 (KNOWN_ISSUES)](../KNOWN_ISSUES.md)
  - アプリ内「お知らせ」ダイアログの生成入力です。公開済みリリースノートは改変せず、UI 文言の変更時は [UI 文言確認手順](ui_copy_review.md) に従います。
- **過去の個別検証・障害調査（Agent 向け）**: [証跡アーカイブ](evidence/) は実施時点の観測と再利用可能な判断材料を保持します（英語可）。現在の本番状態や最新仕様の根拠にはしません。

## 1. 仕様・設計の正本（読者向け・上流工程の範囲）

何ができるか、どのように設計されているか、計算規則・入出力の意味・制約・失敗時の振る舞いのみを記載しています。実装詳細はコード本体を参照してください。

### 航法計算・経路・地図・地形

| テーマ | 正本 | ここで分かること |
| --- | --- | --- |
| NAV LOG 計算・表示規則 | [計算規則](calculation_rules.md) | 丸め、VAR/VOR、各 Flight Phase、燃料計画、RJFM 方針、30° CUT・表示規則 |
| 四捨五入モード | [四捨五入モード](rounding_mode_helpers.md) | 計算・表示への丸め適用、UI 配置根拠、一時設定のライフサイクル・失敗時保持 |
| 出発 VOR 基準 | [出発位置の VOR Tracking Mode](airport-vor-departure.md) | 出発位置 VOR 追跡モード、対応 14 局、第 1 Leg 磁気基準、保存互換性 |
| RJFM 到着高度 | [RJFM 到着時の特定 VREP 計画高度](rjfm_arrival_vrep_altitudes.md) | RJFM 向け ARITA / SHIRAHAMA の 1,500 ft 自動計画と手動入力優先規則 |
| RJFM 帰路・延長案内 | [RJFM 帰路補完と西側延長参考案内](rjfm_inbound_guidance.md) | RJFM 帰路補完（UMK/ARITA）、KS4-3 回避境界・安全余裕、参考案内カードの扱い |
| MAP 経路作成・KML/KMZ | [MAP での経路作成・再編集・KML/KMZ 取込](map_route_builder.md) | MAP 経路作成、確定済み経路の再編集、KML/KMZ 取込・連結規則 |
| 背景地図・出典 | [MAP の背景画像](map_background.md) | 地理院タイルの配信元・表示範囲、欠損時処理、出典表示要件 |
| 区間別SEA | [区間別SEA](sea.md) | 左右3 NM・前方端点、自動参考値、巡航Caution、保存、未確定と算出限界 |
| 地形入力（DEM / KML） | [地形入力と被覆の検証](terrain_inputs.md) | GSI DEM10B 復号・被覆判定、地形点 KML の標高基準・障害物除外境界 |

### 出典・参照データ来歴

| テーマ | 正本 | ここで分かること |
| --- | --- | --- |
| 出典公開方針 | [出典・provenance 方針](source_policy.md) | 内部運用資料の非公開境界と公開資料の出典管理方針 |
| 一次資料の確認状況 | [一次資料の確認状況](primary_source_audit.md) | SR22 AFM/POH・公開航空資料・内部参照の確認粒度と確認状態の定義 |
| データ来歴 | [データ来歴](data_provenance.md) | 同梱性能データ、空港・RJFM 参照、VOR/DME 局、気象、AIP データの来歴 |
| VREP 登録カタログ | [登録 VREP カタログと地図選択仕様](reference/vrep.md) | 公表座標528点の選択・保存済み経路の更新と [旧カタログの原典表](reference/vrep-169-confirmed-source.md) |
| AIP 地図表示用データ | [AIP 地図表示用データの出典・正規化](reference/aip_map_geodata_20261029.md) | SWIM 配布 ZIP（[ソース記録](../data/reference/aip/20261029/sources/README.md)）の採用範囲と正規化・形式間照合 |

### 気象・選択・予備経路

| テーマ | 正本 | ここで分かること |
| --- | --- | --- |
| モデル選択（MSM→GSM） | [気象モデル選択（MSM → GSM）](forecast_selection.md) | モデル優先順位、気象ライブラリとの責任分担、モデル・Run 保存と旧 MSM 互換 |
| 再計算・Run 更新 | [再計算と Run 更新](forecast_refresh.md) | 入力変更時の Run 固定／更新規則と旧 Run 注意表示 |
| Local Static 気象運用 | [Local Static 気象運用とキャッシュ境界](local_weather.md) | 静的 MSM/GSM 配信、ブラウザキャッシュ契約、取得障害の分類と切替 |
| 目的地 TAF Proxy | [目的地 TAF 用 Serverless Proxy](taf_proxy.md) | 目的地 TAF 用 Proxy の機能・失敗隔離・濫用防止・無料枠契約 |
| 計算専用予備サーバー | [計算専用予備サーバー](forecast_backup.md) | 既定無効の予備計算 API 境界、実行・レート制限、有効化前条件 |

### アプリケーション・永続化・アカウント・UI

| テーマ | 正本 | ここで分かること |
| --- | --- | --- |
| 全体アーキテクチャ | [アーキテクチャ](architecture.md) | Static / Legacy 境界、保存層構造、表示投影、気象プロバイダ接続 |
| Application 境界・Session | [Frontend Application 境界と Session ライフサイクル](application_contract.md) | 操作契約、エラー正規化、同一タブ再読み込み時の復元ライフサイクル |
| Browser Platform 境界 | [Browser Platform 境界](platform_capabilities.md) | ファイル入出力・Clipboard・3D KML 出力・外部リンク・接続ヒントの分離 |
| ブラウザ内永続化 | [Local Project 永続化契約](local_persistence.md) | ブラウザ内 Project 永続化、競合保護・互換移行・容量退避境界 |
| Google ログイン | [Google ログインとアカウント認証境界](authentication.md) | Google 認証、安定したアカウント識別、名前空間分離、失効時遮断 |
| Account Sync | [Account Sync（アカウント同期）](account_sync.md) | クラウド同期、大容量可逆圧縮、競合解決、削除 Undo |
| アカウント削除 | [アカウント削除と世代分離](account_deletion.md) | アカウント削除の状態遷移、他端末遮断、再登録時の世代分離 |
| Legacy アカウント連携・移行 | [Legacy アカウント連携と NavMate 移行](legacy_migration.md) | Legacy 所有者連携、一括移行の状態遷移、不可逆性とリトライ契約 |
| UI デザイン・レイアウト | [NavMate Web デザイン・レイアウト仕様](web-design/README.md) | 画面構成、レスポンシブ配置規則、配色・書体基準、文言ロック・NAV LOG 表仕様 |
| NavMate ブランド統合 | [NavMate ブランド統合と互換性境界](navmate_branding.md) | ブランド名・リポジトリ名と既存識別子の互換境界、アイコン仕様 |

## 2. 運用・配信・リリース手順（運用者・Agent 向け）

| テーマ | 正本 | ここで分かること |
| --- | --- | --- |
| Static Web 本番ビルド・公開 | [Static Web 本番配信・構築手順](static_production.md) | 本番ビルド・検査、Pages 手動配備、アイコン再生成、ロールバック、無料枠条件 |
| 定常運用・アプリ手動公開 | [Static 定常運用・公開手順](static_operations.md) | 毎時 MSM 更新、監視、WSL `prepare` / `publish`、Rules 移行、クオータ確認 |
| Local 気象・予備 API 運用 | [Local 気象・予備サーバー運用手順](local_weather_operations.md) | 静的フィード生成 CLI、wheel 固定境界、実 MSM 受入コマンド、予備 API 環境設定 |
| 目的地 TAF Proxy 運用 | [目的地 TAF Proxy 運用・検証手順](taf_proxy_operations.md) | Wrangler 設定・配備、`ALLOWED_ORIGINS` 規則、リリースチェック、無料枠見積 |
| Firebase・アカウント・移行運用 | [Firebase 認証・同期・削除・移行運用手順](firebase_account_operations.md) | Firebase 設定、Rules 配備、`gzip-v1:` 展開順、Legacy Access 例外、エミュレータ検証 |
| MSM 補完起動 Worker | [MSM 補完起動 Worker](msm_external_trigger.md) | 補完起動 Worker の契約、CLI 注意点、限定 observe 確認、停止境界 |
| カスタムドメイン切替 | [カスタムドメイン切替手順](custom_domain_cutover.md) | 本番ドメイン切替の順序、TAF/Legacy 設定整合、ロールバック方針 |
| 安定版 Release 自動公開 | [安定版 Release 自動公開](automatic_app_releases.md) | 安定版 Release からの自動公開橋渡し、単調更新と停止条件 |
| バージョンライン・Release 契約 | [バージョンライン・Release 契約](release_lines.md) | 開発・保守ブランチ運用、VERSION/CHANGELOG と PR Release 契約 |
| Schema 4→5 手動移行 | [Forecast Schema 4→5 移行手順](forecast_schema_transition.md) | Schema 4→5 移行の互換条件、完了記録、再適用 helper 手順 |
| Schema 4→5 Actions 手順 | [Schema 4→5 Actions 手順](schema431_actions_prepare.md) | Actions による暗号化受け渡し手順、期限境界、実公開知見 |
| 一方通行ストレージ移行 | [Project schema 手動移行手順](schema_transition.md) | 初回スナップショット追加（DB 1→2）、AIP出典拡張（DB 2→3）と [初回の実装検証記録](schema_transition_validation.md) |
| 旧サーバ廃止準備・救済 | [旧サーバ廃止準備・データ救済手順](server_retirement.md) | 旧環境停止の前提条件、移行 URL 除去、オフライン救済と Volume 整理 |
| Local 版 Docker 自動更新 | [Local 版 Docker 起動・自動更新](local_static_docker.md) | ローカル Docker 自動更新、共有開発モード、MSM キャッシュ整理 |
| Legacy Tunnel / Access | [Legacy Cloudflare Tunnel / Access 設定](cloudflare_tunnel.md) | Legacy Docker 版のローカルバインド・Cloudflare Tunnel / Access 設定 |

## 3. 開発・テスト・技術検証・統制（Agent 向け）

| テーマ | 正本 | ここで分かること |
| --- | --- | --- |
| エージェント共通制約 | [AGENTS.md](../AGENTS.md) / [CLAUDE.md](../CLAUDE.md) | スコープ制限、モデル独立レビュー、安全境界、Worktree 原則 |
| モデル選択・作業手順 | [エージェント作業手順・モデル設定](agent_workflow.md) | 独立レビュー引き継ぎ、段階的調査・検証、CI 監視停止ルール |
| 文章規範・ドキュメント統制 | [文章規範とドキュメント統制基準](writing-style.md) | 読者向け日本語上流仕様と Agent 向け記録の分離、提出前チェック |
| UI 文言確認手順 | [UI 文言確認手順](ui_copy_review.md) | Gemini CLI 確認・採用理由記録・ソース照合の手順 |
| Codex Worktree 開発環境 | [Codex Worktree 開発環境手順](development_worktrees.md) | 隔離 Compose・開発バックアップ保持・終了時整理・prewarm 抑止 |
| テスト・CI 分割 | [テストの責任と CI](testing.md) | PR 影響判定、CI 分割構成、Browser 検証入口、地形・各スイート担当 |
| Static ブラウザ受入 | [Static Web ブラウザ受入基準](static_web_browser_acceptance.md) | ブラウザ・端末別受入マトリクスと最小実機チェックリスト |
| 実 MSM 受入検査 | [実 MSM 受入検査手順](real_msm_acceptance.md) | 実 MSM パッケージとライブ気象取得の受入検査手順 |
| アプリ公開工程の監査 | [アプリ公開工程の監査](app_publication_audit.md) | 公開工程の重複・排他評価、Pages 履歴通信上限、工程計測境界 |
| Web UI 実装トークン・参照 | [Web UI 実装トークン・保存キー・検証参照](web-design/tokens_and_implementation.md) | CSS トークン定義、お知らせ保存キー、WebKit/IME 実装注意、UI 検証入口 |
| WX 雲・湿度技術検証レポート | [WX 雲・湿度プロファイル技術検証（#374）](wx_profile_feasibility.md) | 雲・湿度プロファイルの技術検証結論、容量概算、上流 API 提案（未実装） |
| 再利用可能な知見 | [再利用知見インデックス](knowledge/INDEX.md) | 知見索引（[運用ルール](knowledge/README.md) / [テンプレート](knowledge/TEMPLATE.md)） |

## 4. 過去の PoC・互換メモ・証跡・フィクスチャ記録（Agent 向け）

- **文書全体統制の棚卸し（2026-11-18）**: [文書統制棚卸し記録](evidence/documentation-governance-20261118.md)
- **旧設計メモ互換入口**: [旧設計メモ互換スタブ](../DESIGN.md)（廃止済み・現行仕様正本への誘導のみ）
- **Pyodide 採用判断と初期基準**: [Pyodide PoC と採用決定](local_calculation_poc.md)、[Pyodide 計算コア固定回帰基準](local_calculation_core.md)
- **公開・運用証跡（Issue #121 / #123 / #265-#266 / #354）**:
  - #121 初期本番監査（旧オリジン）: [remote-production-2026-09-24.md](evidence/issue-121/remote-production-2026-09-24.md)
  - #123 構築・切替・復旧: [local-operations.md](evidence/issue-123/local-operations.md)、[activation-2026-09-26.md](evidence/issue-123/activation-2026-09-26.md)、[custom-domain-2026-09-28.md](evidence/issue-123/custom-domain-2026-09-28.md)、[msm-recovery-2026-10-08.md](evidence/issue-123/msm-recovery-2026-10-08.md)、[msm-recovery-2026-10-21.md](evidence/issue-123/msm-recovery-2026-10-21.md)、[unattended-readiness-2026-10-22.md](evidence/issue-123/unattended-readiness-2026-10-22.md)、[msm-artifact-handoff-2026-10-27.md](evidence/issue-123/msm-artifact-handoff-2026-10-27.md)
  - MSM 補完起動 Worker: [msm-worker-readback-2026-10-26.md](evidence/issue-123/msm-worker-readback-2026-10-26.md)、[msm-worker-recovery-2026-11-18.md](evidence/issue-123/msm-worker-recovery-2026-11-18.md)
  - Pages / Analytics 検証（#265 / #266）: [2026-10-16-target-serving.md](evidence/issue-265-266/2026-10-16-target-serving.md)、[2026-10-17-root-analytics.md](evidence/issue-265-266/2026-10-17-root-analytics.md)、[2026-10-18-two-analytics-versions.md](evidence/issue-265-266/2026-10-18-two-analytics-versions.md)
  - MSM Run 不一致調査（#354）: [issue-354-msm-discovery-2026-11-04.md](evidence/issue-354-msm-discovery-2026-11-04.md)
- **CI・端末・UI・経路・環境証跡**:
  - CI 分割・計測: [independent-shards-20261101.md](evidence/ci/independent-shards-20261101.md)、[account-sync-workers-20261101.md](evidence/ci/account-sync-workers-20261101.md)、[account-sync-project-shards-20261101.md](evidence/ci/account-sync-project-shards-20261101.md)、[arita-calculation-wait-20261109.md](evidence/ci/arita-calculation-wait-20261109.md)、[impact-selection-20261110.md](evidence/ci/impact-selection-20261110.md)
  - 実機・Local・UI: [ipad-safari-acceptance.md](evidence/issue-144/ipad-safari-acceptance.md)、[issue-235-inbound-umk-local.md](evidence/issue-235-inbound-umk-local.md)、[issue-257-worktree-cache.md](evidence/issue-257-worktree-cache.md)、[header-218/README.md](evidence/header-218/README.md)、[alt-responsive-copy-review.md](evidence/alt-responsive-copy-review.md)、[ui/416-443-local-validation.md](evidence/ui/416-443-local-validation.md)、[issue-374/README.md](evidence/issue-374/README.md)、[#173 Google Earth受入資料](evidence/issue-173/README.md)
- **テスト・依存アーカイブの補助メモ**: [vendor/README.md](../vendor/README.md)、[web/e2e/no-legacy.md](../web/e2e/no-legacy.md)、[tests/fixtures/forecast-policy-README.md](../tests/fixtures/forecast-policy-README.md)、[tests/fixtures/msm-portable/README.md](../tests/fixtures/msm-portable/README.md)、[tests/fixtures/schema4/README.md](../tests/fixtures/schema4/README.md)、[tests/fixtures/static-root-analytics/README.md](../tests/fixtures/static-root-analytics/README.md)
