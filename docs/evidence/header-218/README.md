# Issue #218 ヘッダー検証

白い56pxの固定ヘッダーを、320pxからデスクトップまで1段で表示できることを確認した。
Project操作は開閉パネル、お知らせ・版数・保存先はその他パネルへ移し、保存・新規・Accountは常時表示する。
検証日は2026-11-09（JST）。本番公開・実機のVoiceOver/TalkBack受入は行っていない。

## 実画面

- [320pxのヘッダー](mobile.png)、[1440pxのヘッダー](desktop.png)
- [320pxでのProject名全文と保存済み操作](project-menu.png)
- [その他パネルのお知らせ・版数・保存先](more-menu.png)

採用済みアイコンと並べ、白背景・チャコール文字・Pine Greenの操作色を確認した。
アイコン原本、派生画像、manifestは変更していない。

## 検証範囲

| 対象 | 結果と根拠 |
| --- | --- |
| 固定配置・操作 | `header.spec.ts`、Chromium/WebKit各1件成功。320/390/1100/1239/1240/1241/1440pxで56pxの1段、横はみ出し・重なりなし。スクロール前後のworkflow位置、長いProject名、キーボード開閉、外側クリック、フォーカス復帰、modal優先、ヘッダー直下のsticky通知、狭幅のメニュー項目幅を確認。選択のみではrevision/計算結果が変わらないことも確認。 |
| 色とフォーカス | `map-checkpoint.spec.ts` のgreen theme検証2件成功。文字4.5:1以上、フォーカス3:1以上。選択マーカー、既存の地図・空域・VREP意味色を維持。 |
| Local認証 | `npm run test:auth` 9件成功。ログイン有無のアイコン形状・読み上げ、ログイン/ログアウト、busy、同期中の新規操作、幅別dialog配置。認証バックエンドは既存のテストハーネス。 |
| Local保存 | persistenceの7件と、import命名/CUT互換2件成功。自動命名・手動名、Latest、checkpoint、revision競合、削除、遅延編集を検証。 |
| 別タブ復元 | `browser-acceptance.spec.ts` 6構成成功。デスクトップChromium/WebKit、iPhone/iPad/Android端末エミュレーション。実Local WorkerとIndexedDBで計算・保存・別タブ復元。 |
| Legacy | 隔離Composeで`information.spec.ts` / `information-known-issues.spec.ts` 13件成功。通常未読/既知の不具合更新、既読維持、メニュー経由の保存・読込・削除・新規。`web.spec.ts`のタブ限定draft→明示保存・削除も1件成功。 |
| 基本検査 | release validation、version単体2件、Web型検査・Localビルド、applicationテスト140件成功。 |
| 文言 | [Headerの実行記録](../ui-copy/header-218/run.json)・[採用理由](../ui-copy/header-218/adoption.json)、[Legacyの実行記録](../ui-copy/header-218-legacy/run.json)・[採用理由](../ui-copy/header-218-legacy/adoption.json)。Gemini CLIで29項目確認、全記録のソース照合成功。 |

## 独立レビュー

GPT-6.1 Solが読み取り専用で差分を確認した。sticky通知の重なりと狭幅のメニュー項目幅の2件を修正し、
追加したブラウザ検証の成功と最終差分の再確認で、必須の未解決指摘はない。

## 限界と関連資料

追加実行した旧`web.spec.ts`の「desktop workflow renders without the removed A4 output」は、
ヘッダー寸法確認後、外部MSM予報の準備中に30秒の計算待ちがタイムアウトした。
この結果を予報計算の成功とは扱わない。今回は気象処理を変更せず、ヘッダー・保存操作の検証には
Local/LegacyのFTD経路を使用した。

[デザイン仕様](../../web-design/README.md)の古い1〜3段規則を更新した。
同資料のお知らせ副題は、現行コードが`NavMateのお知らせ`であるのに対し空白付きで記載されていたため、
コードに合わせた。過去の比較表は履歴として残し、今回の仕様への参照を加えた。
