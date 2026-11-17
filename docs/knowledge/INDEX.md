# Knowledge index

Read [the workflow](README.md) before adding or applying lessons. Search by the task, affected paths, tool, or error; inspect applicability before reuse.

## Existing canonical sources
- [Agent workflow](../agent_workflow.md)
- [Large Account Sync payloads](../account_sync.md#large-project-payloads): Legacy移行のバッチ容量制限とFirestoreの1文書上限は別。Project・checkpoint・Last Calculationを欠落なく保存する可逆圧縮、旧クライアントの停止、NavMate先行更新、再試行記録の互換性。ローカル合成データで検証し、本番反映・再移行は別途承認。
- [Local StaticのMSMキャッシュ](../local_static_docker.md#msm取得キャッシュの容量管理): 2026-11-17の1環境で約44 GB。Legacyの20 GiB・7日の整理と#257のWorktree対策は別経路。取得cacheと配信Runの保持を分け、updaterの排他区間で整理する。開発用backup・終了時の資源整理は[Worktree手順](../development_worktrees.md#作業終了時の整理)を参照。
- [Forecast schema 4 → 5 transition](../forecast_schema_transition.md): Issue #423。旧版生成データ、旧タブとの共存、同一端末 Latest 置換の了承範囲、手動公開の証拠と制約。最終v2.3.2候補への適用審査、元報告を保持するWSL helper、remote tag照合、受理済み記録を再生成しない運用。
- [Releaseの期限・受渡し・再実行の知見](../schema431_actions_prepare.md#操作窓を始める前の確認): planとprepared feedの別々の30分条件、取得・レビューの事前準備、v2.3.2の公開結果と検証限界。2026-11-15、tooling `64225b82` / driver `2394d59d`で確認。未実装の改善はリンク先Issueへ。
- [CI変更影響と所要時間](../evidence/ci/impact-selection-20261110.md): Issue #421。PR #428を出発点に、2026-11-17の通常PR・main実測、Localと同期本体の律速を確認。Rulesetにci-requiredを登録し再取得済み。同一通常PR差分のHostedは20分43秒→11分05秒、5分未達の律速はPython。独立runnerの生成物依存とcomponent fixtureのreload依存を修正。main受入は未確認。
- [Existing evidence](../evidence/)
- [Static browser acceptance](../static_web_browser_acceptance.md#observation-startup-after-reload-2026-11-14): PR #438のiPhone WebKit traceで確認した、reload後のPyodide初期化と結果検証の待機上限の不一致。起動待ちと保存結果の完全一致検証を分ける。起動性能の改善は#422。
- [App publication audit](../app_publication_audit.md): prepare/publish重複、排他、部分失敗、診断境界。#440で共通の期限表示・確認記録・工程計測を追加。2026-11-15の既存Runのstep計測ではArtifact uploadは2秒／4秒。build-onceは保留。
- [Pages履歴とpreflightの通信上限](../app_publication_audit.md#2026-11-17-pages履歴取得の通信上限によるpreflight停止): v2.4.0のRun 43944939018。失敗時刻以前の保持履歴769件が旧20件指定では最低42GETを要し、40回上限で停止。25件指定で全件照合を実API確認済み。926件では引き続き停止し、履歴削除や上限緩和は含めない。
- [Schema #431 Actions prepare/publish](../schema431_actions_prepare.md): 固定toolingを維持した証拠転送、自己Runの識別、planへの個別承認と暗号化記録。30分期限内に公開へ進めるよう、公開経路を先に準備する。2026-11-13に確認した診断欠落、保存案内テストの文言不一致と候補の再審査、privateなcheckoutからDockerコピーへ引き継がれる権限不整合。2026-11-14の保持feed容量と転送上限の不整合、保存失敗時の診断引継ぎ。実運用は別途承認・受入が必要。

- [MAP background imagery](../map_background.md): Issue #243の配信元・出典、倍率と欠損時の表示、端末保存の境界。
- [Terrain inputs](../terrain_inputs.md): Issue #313のDEM10B PNG復号、画素被覆、欠損と標高基準、実タイル確認の限界。

- [WX cloud/RH feasibility](../wx_profile_feasibility.md): Issue #374。指定KML経路のMSM/GSM実GPV、雲高推定の限界、portableの追加コストとAPI境界。2026-11-09確認、Safari実機は未検証。

## Reusable entries

Entries below preserve scoped observations, not repository-wide rules.

| ID / entry | Trigger and scope | Status | Last verified / evidence |
| --- | --- | --- | --- |
| [MSM-VERIFY-BUDGET](entries/msm-verification-budget.md) | 全件検証が30秒ごとに再開する／保持payloadの整合性エラー | provisional | 2026-11-17、Run 43893765453と対象回帰テスト。本番未検証 |

Use [TEMPLATE.md](TEMPLATE.md); keep details in their canonical document and link here. Do not turn this index into a transcript or broad file inventory.
