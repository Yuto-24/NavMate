# 日別一覧欠落時のLocal MSM計算

2026年11月8日、2.2.2候補で11月9日09:00 JSTの代表ルートが計算できることを確認した。
利用者の元のProjectは未取得のため、その便の成功を示すものではない。

## 原因と修正

`_PortableClient._discover_catalog` は要求する日別一覧の1つでも欠けると、
保存済みRunを検証する前に停止していた。更新停止後に日付が進むと発生する。
2.2.1の「検証できる保存済みデータで継続」という説明に対して、この実装条件が残っていた。

欠けた一覧を空文字で補わず、実在する要求対象一覧だけを固定依存
`jma-gpv-weather 0.5.0` の `parse_listing` / `select_compatible_runs` へ渡す。
NPZのhash・size・形式・Run/source identityと、実際の気象queryの検証は従来の経路を通す。
一覧が不完全なら、期限内のcatalogでも最新Run確認済みとは記録しない。

## 保存済み実データによる確認

- 本番v2.2.1の保存済み配信catalog。SHA-256:
  `fd672b2e14f519d6407c6a0509915167315e172f413b306560cfe0c9546b2822`。
- 生成: `2026-11-07T07:16:57.679883Z`、期限: `2026-11-07T13:16:57.679883Z`。
  11月8日の日別一覧は存在しない。日時と一覧は変更していない。
- ETD: `2026-11-09T09:00:00+09:00`。
- 経路: RJFM → 米ノ津 → 玉名 → 大牟田 → RJFS
  （既存 `issue_43_golden.kml`、主な計画高度6500/7500/6500 ft）。
- `LocalApplication.dispatch_response("calculate")` の取得中断・再開を通して成功。
  結果は `READY_FOR_COPY`、選択Runは `20261107000000`。
- 使用NPZ: `735f66eb88c8e7e453e00f6d8f77c1d35896bdf14fde83d53053080050b6ff24.npz`、
  13,151,741 bytes。catalog記載のhash・sizeを照合した。
- 最終要求の有効時刻は00:00〜01:25:23 UTC。経路上の24件のALOFT／SURFACE_TEMPERATURE要求で、
  上空風・気温、地上気温と高度の適用範囲を検証した。
  query高度は1253〜7500 ft。最新Run確認済みとは記録しない。

## 反映範囲

2.2.2は `release/2.x` を基点にした修正。mainのGSM・backupなどは取り込まない。
mainへの移植はこのリリースに含めない。
実装・検証の証拠は本番公開の証拠とは別であり、公開状況はPRとReleaseに記録する。

## 回帰検証

- Python: MSM継続・Local取得再開・versionの31テストが成功。
  一覧欠落での成功、必要値・高度・時刻不足、破損、source identity不整合、固定Run不在、
  全一覧欠落での失敗とLast Calculation保持を確認した。
- Pyodide: `expired MSM continues locally with cached data and a missing new Run` が成功。
  新しい日別一覧を除去し、実計算・reload後のcache再利用・新Run取得失敗からの継続を確認した。
- release source validation、Web typecheck、対象PythonのRuff/mypy、diff checkが成功。
- GPT-6.1 Solが別の読み取り専用コンテキストで差分と固定依存を確認し、必須修正なし。
- Gemini CLIへの文言依頼は外部送信の自動承認審査で拒否された。
  利用者向けリリース文言は2.2.1の既存説明をそのまま再利用した。
