# NavMate

**NavMate** は、航空大学校の宮崎課程 NAV2 における航法 LOG の地上準備を支援する、SR22 G6 向け Web アプリです。地図上で経路を作成するほか、Google Earth の KML/KMZ を取り込み、飛行計画と気象データから NAV LOG を計算します。

**[NavMate を開く](https://navmate.yuto24.com)**

NavMate の表示内容は非公式の地上準備資料です。運航資料、完成帳票、別添 8-1 の原本としては使えません。航空大学校の公式様式や計算規則への準拠を保証するものではなく、航空情報・気象・性能データ・警告は利用者が確認してください。

- [バージョン番号 (VERSION)](VERSION) / [変更履歴](CHANGELOG.md) / [既知の不具合](KNOWN_ISSUES.md)
- [ドキュメント全体目次](docs/README.md)（仕様・設計・運用・開発・証跡の一覧）
- [計算規則](docs/calculation_rules.md) / [一次資料の確認状況](docs/primary_source_audit.md)

> **案内**：`CHANGELOG.md`（利用者向け節）と `KNOWN_ISSUES.md` はアプリ内「お知らせ」生成の入力源です。仕様・運用・開発手順・証跡の正本一覧は [ドキュメント全体目次](docs/README.md) を参照してください。

## 主な機能

- **経路作成・取込**：MAP 上で空港・VREP・経由地点を選択。確定済み経路の再編集、KML/KMZ のファイル選択、ドラッグ＆ドロップ、「Google Earth からペースト」に対応
- **NAV LOG 計算**：SR22 G6 の性能、飛行計画、MSM の風・気温を用いた計算（利用可能範囲に応じて GSM 日本域へ切替）、および四捨五入モード・30° CUT 秒数の算出
- **気象・計算結果の確認**：採用した気象モデルと Forecast Run、目的地 TAF の参考風、計算結果と警告を表示
- **宮崎周辺の経路補助**：RJFM 発着の一部経路で UMK・有田・白浜などの規則や区間を補完し、MAP 上に関連する空域情報と西側延長参考案内を表示
- **Project 保存・同期**：ブラウザ内の自動保存、明示保存、計算済み NAV LOG の復元。Google アカウントで別端末との同期およびアカウント削除に対応
- **計算結果の持ち出し**：表示中の NAV LOG を JSON でダウンロード／クリップボードへコピー、および Google Earth 用 3D KML エクスポートに対応

機能の詳細と適用条件は [計算規則](docs/calculation_rules.md)、[MAP での経路作成・再編集・KML/KMZ 取込](docs/map_route_builder.md)、[気象モデル選択（MSM → GSM）](docs/forecast_selection.md) を参照してください。JSON や 3D KML の出力は Project のバックアップ形式ではありません。

NAV LOGでは、C'k Point間の地形を評価したSEAと手動値を表示します（[区間別SEAの仕様・制約](docs/sea.md)、[地形入力と被覆の検証](docs/terrain_inputs.md)）。気象・地形・空域表示は飛行可否や経路の安全性を保証しません。

## 利用とデータ保存

本番 URL は **https://navmate.yuto24.com** です。Cloudflare Pages で配信する Static Web 版が正式な利用経路です。通常の画面操作・Project 保存・NAV LOG 計算はブラウザ内で行い、アプリケーションの実行に FastAPI や Docker サーバは必要ありません。

Project の作業内容と最後に正常完了した計算結果は、ブラウザの IndexedDB に保存されます。通常の編集は自動保存され、明示保存は名前付きのチェックポイントを作成します。同じタブの再読み込みでは作業状態を復元できますが、新しいタブや端末では保存済み Project を明示的に開いてください。

Google ログインを利用すると、対応する Project を Firestore 経由で同期できます。未ログインでもブラウザ内で作業できます。同期が失敗してもローカル保存を優先しますが、他端末へ反映済みとは限りません。競合が発生した場合は利用者による選択が必要です。

**データ保護上の注意**：ブラウザのサイトデータ削除、ストレージの消去・容量制限、別ブラウザへの切替などにより、未同期の Project を失うことがあります。Google ログインだけで未同期データの保全は保証されません。また、初回起動や外部気象データの取得にはネットワークが必要です。完全オフラインでの起動は保証しません。

詳しくは [Local Project 永続化契約](docs/local_persistence.md)、[Google ログインとアカウント認証境界](docs/authentication.md)、[Account Sync（アカウント同期）](docs/account_sync.md)、[Legacy アカウント連携と NavMate 移行](docs/legacy_migration.md) を参照してください。

## 経路の作成と計算

1. 初期 MAP で出発空港と経由地点・到着空港を選択するか、KML/KMZ を取り込みます。
2. 経路候補が複数ある場合は対象を選び、MAP と地点の順序を確認して経路を確定します。
3. Planning で飛行計画・性能・高度などを確認し、NAV LOG を計算します。
4. 計算結果・警告・参照した Forecast Run を確認します。入力変更後は必要に応じて再計算します。

KML はファイル選択、ドラッグ＆ドロップ、クリップボードからの貼り付けに対応します。複数 `LineString` の連結条件、Point Placemark の扱い、経路候補の選択規則は [MAP での経路作成・再編集・KML/KMZ 取込](docs/map_route_builder.md) と [計算規則](docs/calculation_rules.md) を参照してください。

気象の更新や通信障害時には、過去の正常な計算結果が残る場合があります。**表示中の計算結果が現在の入力と一致するか**、使用したモデル・Run とともに確認してください。気象データの取得方式と更新判断は [気象モデル選択（MSM → GSM）](docs/forecast_selection.md) および [再計算と Run 更新](docs/forecast_refresh.md) に記載しています。

## 開発・運用・Agent 向け案内

本番は **React / TypeScript / Vite** の Static Web です。計算コアは **Python** で実装されており、ブラウザでは **Pyodide** を使って実行します。Project の永続化には IndexedDB、Google ログインには Firebase Authentication、アカウント同期には Firestore を使用します。気象データは静的配信と独立した TAF Proxy などから取得します。

設計・ビルド・テスト・運用の詳細は以下の正本を参照してください（詳細な検証コマンドやリリース手順は各運用・テスト文書へ集約しています）。

| 目的 | 参照先 |
| --- | --- |
| 全体設計・境界契約（仕様） | [アーキテクチャ](docs/architecture.md)、[Frontend Application 境界と Session ライフサイクル](docs/application_contract.md) |
| Static Web のビルド・検証・公開 | [Static Web 本番配信・構築手順](docs/static_production.md) |
| Static Web をローカル Docker で配信 | [Local 版 Docker 起動・自動更新](docs/local_static_docker.md) |
| 定常運用・Release ライン | [Static 定常運用・公開手順](docs/static_operations.md)、[バージョンライン・Release 契約](docs/release_lines.md) |
| 気象・TAF・Firebase の運用手順 | [Local 気象・予備サーバー運用手順](docs/local_weather_operations.md)、[目的地 TAF Proxy 運用・検証手順](docs/taf_proxy_operations.md)、[Firebase 認証・同期・削除・移行運用手順](docs/firebase_account_operations.md) |
| テスト・CI 分割・実行コマンド | [テストの責任と CI](docs/testing.md)（Browser E2E の標準入口 `test:e2e` を含む） |
| Agent 作業手順・再利用知見 | [エージェント共通制約 (AGENTS.md)](AGENTS.md)、[エージェント作業手順・モデル設定](docs/agent_workflow.md)、[再利用知見インデックス](docs/knowledge/INDEX.md) |

## Legacy 版（Docker / FastAPI）

従来の FastAPI / Docker Compose 版は、移行・検証用の Legacy 環境として残っています。FastAPI / Dockerは本番配信に不要です。Legacy 版の Project 保存、Cloudflare Access identity、Server storage、Docker volume と接続・更新方法は Static Web とは別の仕様です。

Legacy serverのサポート対象runtimeは Docker / Docker Compose です。host上での直接実行はサポート対象ではありません。

- [Legacy の Docker Compose 定義](compose.yaml)
- [Legacy Cloudflare Tunnel / Access 設定](docs/cloudflare_tunnel.md)
- [Legacy アカウント連携と NavMate 移行](docs/legacy_migration.md)
- [旧サーバ廃止準備・データ救済手順](docs/server_retirement.md)

Legacy のサーバ保存・復元手順を Static Web のデータ保護策として利用しないでください。Legacy の Project データは `compose.yaml` の named volume `autonavlog-data` に保存されます。通常の更新・停止では `docker compose down -v` を実行しないでください。volume が削除され、保存済みデータが失われます。

## ライセンスと問い合わせ

`pyproject.toml` では `LicenseRef-Proprietary` を指定しています。利用・再配布条件はリポジトリ所有者に確認してください。不具合や変更要望は [GitHub Issues](https://github.com/Yuto-24/NavMate/issues) へ登録してください。
