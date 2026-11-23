# Knowledge index

Read [the workflow](README.md) before adding or applying lessons. For the full map of specifications, runbooks, and evidence, see [the documentation hub](../README.md). Search by the task, affected paths, tool, or error; inspect applicability before reuse.

## Existing canonical sources
- [ETD時計のフォーカス離脱](../web-design/tokens_and_implementation.md#etd時計のフォーカス離脱): フォーカスで開くnative popoverは、別入力欄への移動でも明示的に閉じる。iPhone WebKitで計算ボタンの遮蔽を再現し、時計内移動を保った修正を検証。
- [Agent workflow](../agent_workflow.md)
- [PR本文更新によるCIキャンセル](../testing.md#pr本文更新によるciキャンセル): PR #478。本文編集もCIを起動し、先行Runのcancelledが集約失敗へ波及する。テスト本体の失敗と分け、本文を先に更新して最後にpushする。
- [多数のassertionによるPlaywrightの記録負荷](../testing.md#多数のassertionによるplaywrightの記録負荷): PR #494。iPad WebKitの格子検証で約5万4千件のassertion記録が累積しtimeout。Playwright 1.62.1の親step検索を確認し、検証内容を保って反復単位の `test.step()` で区切る。
- [スクロール中の位置測定と時計の停止](../testing.md#スクロール中の位置測定と時計の停止): PR #489。別々の座標取得と停止時刻の取得・指定の間に時間が進む問題。位置の同時測定と、固定時刻からの時計制御で検証条件を保つ。
- [DESCENT時間とGoogle Earth受入](../testing.md#descent時間とgoogle-earth受入issue-173): #173。時間不足だけでなく超過も検証し、RJFM帰路の保存運用時間と一般EOCのsnap例外を維持する。数値・KML構造検証とEarth実表示受入を分ける。
- [EOC高度連続性とsnap時間差](../testing.md#eocの高度連続性とsnap時間差issue-470): #470。前段の実効CRUISE時間による高度到達と、snapによる描画時間差を分離。旧Goldenの高度不連続、保存済みsnap根拠の照合、30秒以内の描画補正の検証境界。
- [再利用イメージのPython Reference版ずれ](../testing.md#再利用イメージの-python-reference-と-local-wheel): Issue #418。PYTHONPATHだけではdistribution metadataは更新されず、古い版番号が計算fingerprintに入る。Local wheelと現行パッケージを揃える。旧環境での変更前UIの失敗だけから既存不具合と断定しない。
- [Large Account Sync payloads](../firebase_account_operations.md#3-large-payload-gzip-v1-rollout-and-compatibility): Legacy移行のバッチ容量制限とFirestoreの1文書上限は別。Project・checkpoint・Last Calculationを欠落なく保存する可逆圧縮（[仕様正本](../account_sync.md#large-project-payloads)）、旧クライアントの停止、NavMate先行更新、再試行記録の互換性。ローカル合成データで検証し、本番反映・再移行は別途承認。
- [Local StaticのMSMキャッシュ](../local_static_docker.md#msm取得キャッシュの容量管理): 2026-11-17の1環境で約44 GB。Legacyの20 GiB・7日の整理と#257のWorktree対策は別経路。取得cacheと配信Runの保持を分け、updaterの排他区間で整理する。開発用backup・終了時の資源整理は[Worktree手順](../development_worktrees.md#作業終了時の整理)を参照。
- [AIP出典拡張の手動公開](../schema_transition.md#aip出典拡張の手動公開indexeddb-23): 出典定義・union・固定description以外のschema差分を拒否する。DB2→3で同一保存領域の旧タブを停止し、別端末はCASと未同期データの保持・回復を検証する。過去のForecast証跡は流用しない。
- [Forecast schema 4 → 5 transition](../forecast_schema_transition.md): Issue #423（2026-11-15 v2.3.2 完了）。旧版生成データ、旧タブとの共存、同一端末 Latest 置換の了承範囲、手動公開の証拠と制約。WSL helper、remote tag照合、受理済み記録を再生成しない運用。
- [Releaseの期限・受渡し・再実行の知見](../schema431_actions_prepare.md#操作窓を始める前の確認): planとprepared feedの別々の30分条件、取得・レビューの事前準備、v2.3.2の公開結果と検証限界。2026-11-15、tooling `64225b82` / driver `2394d59d`で確認。未実装の改善はリンク先Issueへ。
- [CI変更影響と所要時間](../evidence/ci/impact-selection-20261110.md): Issue #421。PR #428を出発点に、2026-11-17の通常PR・main実測、Localと同期本体の律速を確認。Rulesetにci-requiredを登録し再取得済み。同一通常PR差分のHostedは20分43秒→11分05秒、5分未達の律速はPython。独立runnerの生成物依存とcomponent fixtureのreload依存を修正。2026-11-18のmain Run 44239461740は29 job成功、必須checkまで10分09秒・runner合計111分24秒。#459の変更後比較は別途必要（共有検査・Python分配の基準は[分配証跡](../evidence/ci/independent-shards-20261101.md#issue-459-shared-checks-and-current-timings)）。
- [現行保証とLegacyテストの境界](../testing.md#issue-458-現行保証の担当とlegacy専用テストの廃止): Issue #458。共有facade・数値・移行・予備APIを維持し、旧通常adapter / queueだけを廃止。KML・GSI・同期componentの移管先と、通知・Static回復のCI担当を記録。
- [Existing evidence](../evidence/)（[2026-11-18 MSM Worker復旧記録](../evidence/issue-123/msm-worker-recovery-2026-11-18.md)を含む）
- [Static browser acceptance](../static_web_browser_acceptance.md#observation-startup-after-reload-2026-11-14): PR #438のiPhone WebKit traceで確認した、reload後のPyodide初期化と結果検証の待機上限の不一致。起動待ちと保存結果の完全一致検証を分ける。起動性能の改善は#422。
- [起動性能と配布データの境界](../evidence/performance/startup-422-20261118.md): Issue #422。異なる時刻の単純比較を避け、前後を交互に測定。未使用AIP原本の配布除外は、予備APIのデータ照合対象も揃える必要がある。計算に必要な原本PDFは維持する。統合後はLast Calculationを持つProjectでも再測定。配布前のヘルパー読込は古いインストールと未生成のpackage metadataの両方に依存しないことを確認する。
- [App publication audit](../app_publication_audit.md): prepare/publish重複、排他、部分失敗、診断境界。#440で共通の期限表示・確認記録・工程計測を追加。2026-11-15の既存Runのstep計測ではArtifact uploadは2秒／4秒。build-onceは保留。
- [承認済みアプリとAIP検査の配布形式不一致](../app_publication_audit.md#2026-11-22-承認済みアプリとaip検査の配布形式不一致): 2026-11-22観測。旧アプリ自身のテスト成功だけでは、新toolingとの互換性を保証しない。確認済み旧SHAに限定したMSM更新と、新コミットのAIP欠落拒否を検証する。
- [Source CI再利用の境界](../app_publication_audit.md#source-ci再利用issue-460): #460。アプリSHAのpush CI・必要suiteと、環境が一致するWeb検査inventoryを別々に照合。CI待ちは新アプリ昇格だけを保留し、配信中SHAの天気更新は検査を再実行して継続。Static build内のtscと候補artifact E2Eは再利用対象外。 [2026-11-23のLocal受入](../app_publication_audit.md#local実運用受入と時間比較2026-11-23-jst)では、Updater自身の更新と実取得が必要だった。Node/npm一致でもGit版が異なり、型検査だけ再利用した。
- [Pages履歴とpreflightの通信上限](../app_publication_audit.md#2026-11-17-pages履歴取得の通信上限によるpreflight停止): v2.4.0のRun 43944939018。失敗時刻以前の保持履歴769件が旧20件指定では最低42GETを要し、40回上限で停止。25件指定で全件照合を実API確認済み。926件では引き続き停止し、履歴削除や上限緩和は含めない。
- [Schema #431 Actions prepare/publish](../schema431_actions_prepare.md): 固定toolingを維持した証拠転送、自己Runの識別、planへの個別承認と暗号化記録。30分期限内に公開へ進めるよう、公開経路を先に準備する。2026-11-13に確認した診断欠落、保存案内テストの文言不一致と候補の再審査、privateなcheckoutからDockerコピーへ引き継がれる権限不整合。2026-11-14の保持feed容量と転送上限の不整合、保存失敗時の診断引継ぎ。
- [MSM 補完起動 Worker](../msm_external_trigger.md): `autonavlog-msm-trigger` 仕様、段階CLI、`ops.mjs` による `.state/wrangler.json` 上書きと `observability` 差分、2026-11-18 復旧観測。

- [AIP形式間照合と配布境界](../testing.md#aip地図参照データissue-311): Issue #311。KMLの5件差は高度帯・管制主体の統合表現。Hiroshima・Sapporoには水平形状差もあり、Shapefileを採用して差を保持する。地図用データは計算用ZIPとfingerprintの外に同梱する。
- [MAP background imagery](../map_background.md): Issue #243の配信元・出典、倍率と欠損時の表示、端末保存の境界。
- [SEA計算と取得の切り分け](../sea.md): Issue #314。区間の評価と旧手動値の保持条件。#485の本表統合では最終進入のCPにSEA専用行が必要（[検証上の境界](../testing.md#sea取得とlocal開発サーバーの切り分けissue-314)）。ネイティブfetchのreceiverとViteのmanifest更新後起動失敗は[検証記録](../testing.md#sea取得とlocal開発サーバーの切り分けissue-314)を参照。
- [Terrain inputs](../terrain_inputs.md): Issue #313のDEM10B PNG復号、画素被覆、欠損と標高基準（実タイル確認の限界と検証コマンドは [testing.md](../testing.md#地形入力gsi-dem10b--地形点-kmlの検証)）。

- [WX cloud/RH feasibility](../wx_profile_feasibility.md): Issue #374。指定KML経路のMSM/GSM実GPV、雲高推定の限界、portableの追加コストとAPI境界。2026-11-09確認、Safari実機は未検証。

## Reusable entries

Entries below preserve scoped observations, not repository-wide rules.

| ID / entry | Trigger and scope | Status | Last verified / evidence |
| --- | --- | --- | --- |
| [MSM-VERIFY-BUDGET](entries/msm-verification-budget.md) | 全件検証が30秒ごとに再開する／保持payloadの整合性エラー | provisional | 2026-11-17、Run 43893765453と対象回帰テスト。本番未検証 |
| [MSM-TRIGGER-OPS-DRIFT](entries/msm-trigger-worker-ops-drift.md) | `ops.mjs` による `.state/wrangler.json` 上書き、`observability` 差分、`.state` 欠落、OAuth 401/403、CA 不足、`FRESH` と dispatch の区別 | provisional | 2026-11-18、Worker 再配置と自然 Cron 1 tick 観測。`DISPATCH_ACCEPTED` 経路は未実証 |

Use [TEMPLATE.md](TEMPLATE.md); keep details in their canonical document and link here. Do not turn this index into a transcript or broad file inventory.
