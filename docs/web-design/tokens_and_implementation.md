# Web UI 実装トークン・保存キー・検証参照（Agent 向け）

読者向けの画面・レイアウト仕様は [web-design/README.md](README.md) を正本とします。本資料は CSS トークン定義、端末内ストレージキー、および UI 自動検証の参照情報をまとめた Agent・開発者向けメモです。

## CSS デザイン・タイポグラフィトークン

| トークン | 値 | 用途 |
| --- | ---: | --- |
| `--brand-950` | `#194638` | 見出し |
| `--brand-900` | `#225c4d` | 主要アクション |
| `--brand-800` | `#1b4b3f` | ホバー時アクション |
| `--brand-accent` | `#225c4d` | 選択済みコントロール・フォーカス |
| `--navy-950` | `#0b1f33` | 航空地点番号・地図ツールチップ文字 |
| `--navy-800` | `#173b5e` | 経路ライン |
| `--teal-700` | `#0c7c78` | VREP・手入力値・自動計画成功 |
| `--amber-700` | `#a8660d` | 要確認事項 |
| `--red-700` | `#b42318` | ブロッカー・利用不可値 |
| `--slate-50` | `#f7f9fb` | 補助領域 |
| `--slate-200` | `#d8e0e8` | 枠線・区切り線 |
| 本文色（`color` 直値） | `#252c35` | 白地上の本文 |
| 背景色（直値・CSS 変数なし） | `#ffffff` | メインキャンバス（`styles.css` で直接指定） |
| `--radius-sm` | `6px` | 入力欄・小型コントロール |
| `--radius-md` | `10px` | パネル |

- **書体・サイズ**：`Inter`, `Noto Sans JP`, system sans-serif。ページタイトル 22–24 px / 700、セクションタイトル 16–18 px / 700、コントロール 14 px / 600、表・本文 13–14 px / 400–600、補足 12 px / 400（line-height 1.5 以上）。
- **WebKit フォーカス対策**：カスタムラジオ等は矢印キー移動時に WebKit が `:focus-visible` を外すため `:focus` で表示処理を維持する。

## お知らせ・一時セッション等の保存キーと実装注意

- **お知らせ既読管理**：`autonavlog.information.lastSeenUpdate`（`a4a92da` v1.10.0 基準 ID からのみ `lastSeenRelease` を移行）、`autonavlog.information.knownIssuesSeen`（ID と本文ハッシュ）。
- **ダイアログ描画位置**：ヘッダーの `z-index` 制約を避けるため `document.body` 直下へポータル描画する。
- **IME・確定ガード**：Check Point 名称入力の Enter 送信では `isComposing` / `keyCode === 229` およびキーリピートを除外し、非同期保存ロックでクリックとの二重送信を防ぐ。
- **自動検証入口**：ヘッダー・レスポンシブ（320 / 390 / 1100 / 1239 / 1240 / 1241 / 1440 px）、NAV LOG 罫線、通知タイミング（`test:notification`）等の E2E スイート構成は [testing.md](../testing.md) および [static_web_browser_acceptance.md](../static_web_browser_acceptance.md) を参照してください。
