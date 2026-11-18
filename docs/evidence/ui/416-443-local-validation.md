# #416 / #443 統合差分のローカル確認（PR #456 検証記録）

> **位置づけ**: 経路作成・再編集と飛行計画の操作ペイン統合（#416）、5 秒通知（#443）、および PR #456 レビュー指摘対応のローカル検証・レビュー記録です。関連する UI デザインの正本は [web-design/README.md](../../web-design/README.md) を参照してください。
> **残る確認範囲**: 実 Google SDK 同期の再検証と UI 文言全体（登録外文言を含む）の意味確認は、本ローカル検証だけでは完結しません。

## 得られた主な修正・再利用知見

- **CP 保存待ちの操作競合**: `CheckPointMapPicker` に `!busy` を付け、保存応答待ち中の地図クリックによる座標上書きを防止した。
- **地図リサイズ時の中心精度**: Leaflet 1.9.4 の通常 `setView` は `_tryAnimatedPan` でピクセル差を切り捨てるため、安易に `reset: true` を外さず、寸法変化時のみ再生成する既存処理を維持した。
- **既存テストの更新境界**: 認証再試行回数の購読、帰路テストの VREP ラベル、再編集終了時の全画面・スクロール固定解除、ETD 分ボタンのキーボード操作等を確認した。

## 主な検証対象と修正境界

- **CP保存待ち中の地図操作**: [PR #456 指摘](https://github.com/Yuto-24/NavMate/pull/456#discussion_r4600067673)を受け、`CheckPointMapPicker` の有効条件へ `!busy` を追加した。保存成功・失敗の遅延応答2件で待機中の座標保持、要求座標保存、再試行、処理終了後の地図編集再開を確認。修正前 `70d1ed3c` で失敗し、修正版で成功した。
- **経路再編集・フォーカス・通知の修正**（[レビュー 5938134557](https://github.com/Yuto-24/NavMate/pull/456#pullrequestreview-5938134557) 含む）:
  - 既存CP編集中も地図クリックを受け付け、取消で元座標保持、保存で同一ID・関連Leg座標を更新（Local/Legacy 1100・1440px）。CP関連Leg変更時は名称へフォーカスを戻す。
  - 経路再編集の終了時に全画面状態とスクロール固定を解除。閉じたRJFM凡例でも空域取得失敗を表示。
  - 認証再試行回数の購読、アカウント画面を閉じた状態でのログイン失敗Toast単発表示（二重live通知防止・popup取消の無通知維持）、手動計算一致時のエラー解除を確認。
  - ETD 時ボタン確定後に分の現在値近傍候補へフォーカス移動（値自体は保持・Enter/Space対応）、計画フォーカス要求の競合破棄を修正。
  - `KML/KMZ をドロップ` 表示文字列を TSX 1か所へ集約し、コンパクト表示も実 `span` に統一（390/1100/1440px の画素一致・picker/drop/Clipboard 8件確認）。
- **保留判断**: 地図リサイズ時のタイル再生成は、Leaflet 1.9.4 の通常 `setView`（`_tryAnimatedPan` によるピクセル丸め）では中心精度を保てないため、寸法変化時のみ再生成する既存仕様を残した。ログアウト未完了のヘッダー表示追加も任意改善として保留。

## ベースライン検証と再現確認

- **Docker test stage（`./scripts/run_ci_checks.sh`）**: pytest 3,638 passed / 1 skipped（498.46秒、coverage 91%）、release検査、ruff、mypy、性能・runtimeデータ、schema、wheel/sdist ビルドが成功（旧作業版不整合イメージの結果は除外し現行イメージで実行）。UI変更のみの最終調整時は本Python全件結果を再利用し、Web型検査・Application契約 142件・static artifact 25件・release notes 6件・通常Local/Legacyビルド・隔離Legacy `health ok / 2.4.0` を再確認した。
- **Playwright ブラウザ検証（Chromium / WebKit）**:
  - `playwright.focused-ux.config.ts` 56件（600/390px 高度欄切取りなし含む）、`playwright.notification.config.ts` 14件（3幅位置不変・5秒失効・同期Undo・失敗独立保持等）、既存CP操作6件、破損KMLドロップ等4件が成功。
  - Local FTD Golden 1100px、隔離Compose fake weather 3件（移行無効時の既定 `/api/account-link` 404のみ `observeLegacyMigration` 契約として区別）、予備サーバー有効Localの `forecast-backup` 5件が成功。
  - 合成AuthProviderによる実ブラウザー 390/1440px 4件 + 回帰2件、RJFM帰路案内 Legacy回帰1件（1100/1440px で左地図・右操作・下NAV LOG/案内）、Ubuntu 4223 通常ビルドでの閉じた凡例空域エラー目視確認を実施。
- **独立レビュー**: GPT-6 Astra が読み取り専用別コンテキストでレビューし、通知重なり修正後の再確認も含め必須修正なし（テスト実行とは独立証拠）。

## 残るゲート・UI文言照合の記録

- **Hosted CI / 実SDK同期の限界**: CI `44054319804` で見られた stale-device logout は閉じたダイアログを開くテスト操作を追加した一方、実 Firebase emulator は `Could not spawn java -version` で未起動のため3機種実SDK再実行は未実施（合成transport成功で代替しない）。同CIの `Page.handleJavaScriptDialog: session closed`、先行全Localバッチ上限超過、storage/schema 30/32、実SDK offline/conflict 等を本対象試験で読み替えない。新HEADのHosted CIは未確認（非監視）。
- **UI文言の機械照合（`python3 scripts/ui_copy_review.py check`）**: 登録済み6記録の機械照合は成功。ただし登録範囲外を含む文言全体の意味・表示文脈確認は未完了（ユーザー指示により Gemini へ追加送信しない）。
- **先行照合エラー（`Copy or source context changed: more`）の根拠保持**: 現在の機械照合は上記6記録で通過しているが、先行エラー時の設計判断として、ヘッダー旧ブロック（失敗アイコン・読み上げ関連付け欠落）およびペースト旧ブロック（旧aside配置への逆行）への単純復元は取らず、チェック範囲外移動だけで文脈確認済みとはみなさない前提を維持している。地図出典はお知らせ下に保持。
