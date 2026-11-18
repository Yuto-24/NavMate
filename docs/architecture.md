# アーキテクチャ

NavMate の全体構成、Static Web 本番経路と Legacy runtime の位置づけ、計算コアの独立性、永続化と表示投影の責務分担を定めます。

## 実行構成（Static Web 本番と Legacy 検証経路）

- **正式本番経路（Static Web / Local-first）**：**React SPA + ブラウザ内 Python / Pyodide（Local 計算）+ ブラウザ内永続保存**（任意で Google ログイン・アカウント同期）で構成します。通常の画面操作・Project 保存・NAV LOG 計算はブラウザ内で完結し、FastAPI や Docker サーバーを必要としません。
- **Legacy 経路（移行・検証用）**：従来の FastAPI + Docker Compose 環境は、移行期間中のアカウント連携・移行サービスおよび参照実行系として維持します。
- **共有計算コア**：航法計算・性能補間・Readiness 判定・NAV LOG 表示投影を担う Python 計算コアは Web 固有型や HTTP / ブラウザ保存 I/O に依存せず、Static Web と Legacy の両方で共有します。同一の入力・性能データ版・方針版・Forecast Run からは決定論的に同一の結果を生成します。

```text
React SPA
   └─ 共通 Application 契約（Local 実行 / Legacy 接続、失敗時の自動フォールバックなし）
         ├─ Local: ブラウザ内計算コア + 端末内永続保存 + 静的気象フィード / TAF Proxy
         └─ Legacy: 検証用サーバーファサード + サーバー永続保存 + 気象取得プロバイダ
               └─ 共通 Python 計算コア（計画・航法・性能計算・表示投影）
```

詳細は [Application 境界と Session](application_contract.md) および [Browser Platform 境界](platform_capabilities.md) を参照してください。

## Project 保存と計算結果の分離

### Local（Static Web）の保存層

ブラウザ内の永続保存領域により、一時的な同一タブ再読み込み用復元および破棄可能な気象キャッシュとは独立して、明示保存チェックポイント、検証済み最新下書き、最後に正常完了した計算結果、および単一の自動保存（Latest）を保持します（詳細は [Local Project 永続化契約](local_persistence.md)）。

### Legacy（サーバー側）の 4 層構造

Legacy 環境では、Project 入力と最後の正常計算をサーバー上の永続ボリュームに 4 つの役割へ分けて保持します。

| 保存する情報 | 目的と振る舞い |
| --- | --- |
| 明示保存チェックポイント | 利用者の明示保存ごとにリビジョン管理される確定版 |
| 自動保存ドラフト | 検証を通過した最新下書き（読込時はチェックポイントより優先）。所有者ごとに未名前付き保存を 1 件だけ `Latest` として管理 |
| 直前の正常計算記録 | 計算時の計画スナップショット、計算結果、目的地風、気象来歴、入力整合性情報、保存時刻を保持する単一記録 |
| 所有者状態管理 | 所有者ごとに最後に開いた Project や `Latest`、削除再試行対象を管理（パスに生識別子を含めない） |

### 共通の不変条件

- **失敗時の状態保護**：計算中の例外・中断・ブロッカー判定・単なる入力編集によって、すでに確定保存されている直前の正常計算結果や保存済み Project は上書き・消去されません。
- **再計算要否（stale 判定）**：現在の作業中入力が保存済みの計算時スナップショットと異なる場合、NAV LOG は直前の正常結果を表示したまま「再計算が必要」として扱います（RJFM 数値案内も現在の参照データと一致する場合のみ表示）。古い計算の課題は現在の準備状況に混入させません。
- **原子的保存と破損隔離**：保存時は検証を伴う原子的置換を行い、破損した自動保存は有効なチェックポイントへフォールバックし、破損した直前計算記録は隔離して通常操作を妨げません。

## 気象・目的地 TAF と表示投影

- **気象モデルの共有境界**：MSM / GSM のモデル仕様・探索・復号・補間・来歴は気象ライブラリ（`jma-gpv-weather`）を正本とし、アプリケーションはモデル優先順位・Run 固定・入力不変時の再計算による最新 Run 更新・最終要求条件での再計算を制御します（[気象モデル選択](forecast_selection.md) / [再計算と Run 更新](forecast_refresh.md) / [Local Static 気象運用](local_weather.md)）。計算コア自体は HTTP やブラウザ保存領域へ直接アクセスしません。
- **FTD モード**：Project が FTD モードの場合、地上風と 5,000 ft 風から固定気象を構成して共通の気象契約へ接続し、計算コア内の分岐を増やしません。
- **目的地 TAF の独立性**：目的地と到着予定時刻に対応する TAF の卓越風を NAV LOG の独立した目的地情報欄へ参考表示しますが、到着区間の航法計算（WCA・MH・GS・ETE・燃料）は TAF の取得成否にかかわらず CALM 固定で影響を受けません。通信失敗や時刻範囲外は計算ブロッカーにしません（FTD モードでは TAF を取得しません）。
- **表示専用投影**：重なりのない計算区間（Calculation Zone）が距離・時間・燃料の唯一の集計元です。NAV LOG 表示モデルは計算コア側で生成する表示専用投影（Physical Leg 小計、継承空欄、PA 記号、目的地情報行、区間区切りを含む）であり、フロントエンド側で合計を再集計しません。

> **参考（PoC 採用判断・固定基準・運用手順）**：Python / Pyodide の採用判断記録は [local_calculation_poc.md](local_calculation_poc.md#architecture-decision-2026-09-13)、固定 MSM 回帰基準は [local_calculation_core.md](local_calculation_core.md)、Static Web 本番配信は [static_production.md](static_production.md) を参照してください。
