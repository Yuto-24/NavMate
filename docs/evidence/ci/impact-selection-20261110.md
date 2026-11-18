# Issue #421: 変更影響に応じた CI（2026-11-10 / 2026-11-17 実測）

**結論・再利用可能な判断**: 変更影響ルーティング（PR #428）と Browser/Sync 並列分割（PR #448）により、同一通常 PR 差分の Hosted CI は 20 分 43 秒 → 11 分 05 秒へ短縮したが、**5 分目標は未達（律速は Python 第 2 分割の 10 分 10 秒）**。Ruleset `20705217` への `ci-required` 必須チェック登録は 2026-11-17 に実施済み。

PR の選択とブラウザ準備を変更する。現行のルーティング表と shard 構成の正本は [testing.md](../../testing.md) とする。以下は導入・計測時の観測、失敗原因（独立 runner での生成物依存と component fixture の再読込依存）、および限界の記録である。

## 変更前の観測

[PR #417 の run 42641387737](https://github.com/Yuto-24/NavMate/actions/runs/42641387737)
は全体13分36秒。Jobs API の start / complete より Local local は13分、iPhone sync は
12分10秒、web は36秒だった。Local のブラウザ導入は local 39秒、focused-ux 3分52秒。
Local local の回帰本体は10分9秒、iPhone sync 本体は10分31秒だった。

[main の run 42756361714](https://github.com/Yuto-24/NavMate/actions/runs/42756361714)
では同じ導入ステップが local 49秒、acceptance 12分40秒、focused-ux 22分3秒だった。
OS パッケージ取得の遅延は Issue に記録されている。これらは個別観測であり、
平均性能や恒常的な帯域低下を示すものではない。

変更開始時の main `b72923d55401965a22c74ba6d2c6f631d4a90a97` は
[全回帰 run 42805855333](https://github.com/Yuto-24/NavMate/actions/runs/42805855333) が成功。
これは変更前の保証であり、新構成の main 成功とは扱わない。

## 選択とトレードオフ

選択表は [testing.md](../../testing.md#pr-と-main-の-ci) を正本とする。
Web は全 browser / sync を残すため、5分を超える可能性が高い。今回の変更は
無関係な Python / runtime / 配信ツール / service job の省略と、OS 導入のばらつき低減を狙う。
計算・同期の重要回帰や既存 pytest 分配を変更しない。依存関係や CI 自身の PR は全検証する。

## マージ条件

- **2026-11-10 時点の観測**: 有効な Ruleset `20705217` で `required status checks` が未設定であったため、`ci-required` 登録までは CI 失敗によるマージ阻止を保証できていなかった（その後 2026-11-17 に登録実施、下記参照）。

## 計測・受入

Hosted Run のイベント、head SHA、選択 summary、全 job の結論と start / complete、
container 初期化・npm / pip・テスト本体を比較する。全体時間は run 開始から最後の必須 job
完了までとし、queue を含む値と job 内時間を混同しない。テスト件数と skip の差も確認する。

- この PR は CI 変更なので全 suite を実行する。
- 代表的な通常変更の Hosted Run は別に必要。ローカルの選択テストや全検証の時間を
  通常 PR の5分達成の根拠にしない。
- 新構成の main 全回帰は、承認されたマージ後に確認する。
- PR の独立レビュー・CodeRabbit・Hosted 結果は PR 本文から参照する。

## コンテナ初回検証

[PR #428 の初回 run 42815518647](https://github.com/Yuto-24/NavMate/actions/runs/42815518647)
では8 browser job の image 取得・初期化が26〜33秒で成功した。その後 setup-python の
pip cache が `lsb_release` 不在で失敗したため、テスト本体の成功や全体高速化の根拠にはしない。
Python 自体の導入は成功していた。cache を `actions/cache@v4` と明示的な
`PIP_CACHE_DIR` へ分離し、pip の通常導入と checkout の再ビルドを維持した。

## 全 suite の Hosted 完走

[run 42816184788](https://github.com/Yuto-24/NavMate/actions/runs/42816184788)
（PR、`9d3872da`）は20 job がすべて成功し、`ci-required` も成功した。
workflow 開始から最後の必須 job 完了まで20分30秒。image 初期化は8 runner で26〜39秒、
pip install は16〜34秒だった。OS/browser の追加導入 step はない。

| 対象 | 変更前 PR #417 | 今回の全 suite run |
| --- | ---: | ---: |
| workflow 全体 | 13分36秒 | 20分30秒 |
| Local local job | 13分00秒 | 19分30秒 |
| Local 回帰本体 | 10分09秒 | 15分48秒 |
| iPhone sync job | 12分10秒 | 8分11秒 |
| focused-ux の準備（旧: browser install、新: container 初期化） | 3分52秒 | 27秒 |

別 commit・別 runner の観測であり、全体の短縮率や原因別の差分には換算しない。
今回の全体時間は改善しておらず、5分目標の達成とは扱わない。Local は既存選択の70件を収集し、
69 passed / 1 skipped、予報 backup は5 passed。skip は既存の Legacy 専用 pending-save
テスト（`web/e2e/checkpoint-enter.spec.ts:119`）で、Local の選択や assertion を減らしていない。

律速は Local 回帰本体で、10ファイルにわたる実計算・保存・復元を2 workersで実行していた。ファイル内順序を維持した file-level shard と、Chromium sync 後の共有開発検証分離を次候補とした（PR #428 時点では通常変更の Hosted Run と main run は未計測だったため、下記 2026-11-17 で再確認した）。今回の証拠だけで worker 数増加や重要テストの削除は正当化しない。


## 2026-11-17: 残る律速の確認と分割

PR #428 の分類・公式コンテナ・集約を維持し、ブラウザ本体の直列時間を短縮する。
計測は Jobs API の `started_at` / `completed_at` と、同じ job のログを使用した。

| 観測 | 結果 | 全体 | 最長 job / 主な工程 |
| --- | --- | --- | --- |
| [PR #444 VOR計算変更](https://github.com/Yuto-24/NavMate/actions/runs/43699315391) | 成功 | 20分43秒 | Local 19分36秒、iPad sync 12分17秒 |
| [main `7213effa`](https://github.com/Yuto-24/NavMate/actions/runs/43715640669) | 全20 job成功 | 16分15秒 | Local 15分42秒、回帰本体12分29秒、backup 1分35秒 |
| [PR #447 KML変更](https://github.com/Yuto-24/NavMate/actions/runs/43903340197) | 失敗 | 14分58秒 | Chromium sync 14分09秒。失敗を性能達成の証拠にはしない |

PR #444 は通常の航法計算変更で、テストや共有JSONも含むため現行判定で全 suite を選ぶ。
CIだけを変更したPRの代替ではなく、実際の通常変更のベースラインとして扱う。
いずれも初回attemptのRun開始から最終job完了までの観測で、平均値や純粋なCPU時間ではない。

main のコンテナ初期化は22〜35秒で、OS/browser追加導入はない。PR #428 の対策は維持する。
同期本体はiPad 10分29秒、Chromium 6分22秒に加えて共有開発2分26秒。
Local acceptance は認証3分45秒に続けてscroll・acceptance・TAF 4分34秒を実行していた。

今回の変更ではLocalをファイル単位で4分割し、同期の各deviceをテスト単位で2分割する。
認証と共有開発も別runnerへ分離する。同期はrunnerごとに1 workerと専用emulatorを使用する。
既存のLocal 70件（Legacy専用1件skipを含む）、同期54件、Rules 4件、storage-upgrade 32件、
migration 6件を収集して、Localと同期の分割前後が漏れ・重複なく一致することを検証する。

[Playwrightの公式仕様](https://playwright.dev/docs/test-sharding)どおり、Localはファイルを分割せず、
1ファイルの同期は`--fully-parallel`で個別テストを分配する。同期テストは各テストでbrowser contextと
アカウントを作成し、共有のbeforeAll/afterAllを持たない。runner内の同時実行は増やさない。
テスト件数による標準分割なので時間の均等化は保証しない。runner数増加によるqueueと、
image・npm・pip・Firebaseの外部取得は引き続き計測対象とする。

2026-11-17に有効なbranch rulesとRuleset `20705217`を再取得し、required status checksが
未設定であることを確認した。従来branch protection APIは`Branch not protected`（404）。
既存の削除・force push禁止、Code Quality、Copilot review、PR会話解決を維持したまま、
GitHub Actions（integration ID `15368`）の`ci-required`を必須チェックへ追加した。
Ruleset再取得とmainの適用rulesで反映を確認し、既存ルール・conditions・bypass actorsの保持を照合した。
`strict_required_status_checks_policy=false`とし、新たなbase最新化条件は追加していない。
この設定変更はコード外の実施済み操作であり、PRのマージは実施していない。

上記main成功はPR #428の回帰保証であり、今回の分割の成功とは扱わない。
変更後のHosted計測は下記に記す。今回の構成でのmain成功は、承認されたマージ後に確認する。


### 分割の初回Hosted実行で見つかった準備依存

[PR #448の初回Run](https://github.com/Yuto-24/NavMate/actions/runs/43910324293)では
Local全分割は成功し、最長は6分32秒だった。ただし同期と共有開発が失敗したため、
全体12分42秒を性能達成の証拠にはしない。

- [iPad同期の第2分割](https://github.com/Yuto-24/NavMate/actions/runs/43910324293/job/133450333102)は、
  先頭のcomponent検証で動的に挿入したdialogが失われた。traceで同じHTMLの再読込と
  クリック対象のdetachを確認した。通常Appとcomponentを同じページへ載せていたfixtureを、
  既存componentを静的importする専用HTMLへ分離した。resolve/import・Draft guardの4ケースと
  元のassertionを維持する。iPhoneの同じ失敗にも適用する。
- [共有開発runner](https://github.com/Yuto-24/NavMate/actions/runs/43910324293/job/133450333114)は
  `generated/releaseNotes.json`がなく起動できなかった。以前は先行する同期テストのpretestが
  生成していたため、共有開発テストにも同じpretestを明示した。

ローカルでiPadの失敗ケース単独と、関連4ケース×3deviceを再検証して成功。
共有開発も生成JSONを退避した状態から、専用Auth/Firestore emulatorで全6件が成功した。
失敗を避けるためのretry追加、待機上限延長、assertion削除は行っていない。


### 成功した通常PRの前後比較

[計測用draft PR #449](https://github.com/Yuto-24/NavMate/pull/449)は、マージ済みの
PR #444 VOR計算変更を一時baseへ再現したもの。元base `9871a328` / head `4b1e0bc8`の差分と、
再現base `5cffa103` / head `f6341dfe`のmerge-base差分はbyte-for-byte一致を確認した。
CI構成と上記fixture修正を双方のbase/headに同じように適用したため、分類入力には元PRの
通常変更20ファイルだけが渡る。テスト・共有JSON等を含む航法計算変更なので全suiteが選ばれた。
製品コードと既存assertionは比較元と同じで、新しい製品変更を導入していない。

[変更後Run 43914098159](https://github.com/Yuto-24/NavMate/actions/runs/43914098159)は
全28 job成功、Run開始からci-required完了まで11分05秒。最初のjob開始まで20秒を含む。
base/head更新でcancelされた別Runや、fixture準備に失敗した初回Runは性能達成に算入しない。

| 必須検証 | 変更前 PR #444 | 変更後の同一通常差分 |
| --- | ---: | ---: |
| 全体（queue・集約込み） | 20分43秒 | 11分05秒 |
| Localの最長runner | 19分36秒 | 7分57秒 |
| 同期deviceの最長runner | 12分17秒 | 7分43秒 |
| Pythonの最長runner | 9分10秒 | 10分10秒 |

全体は観測値で9分38秒短縮したが、**5分目標は未達**。Pythonの第2分割が律速で、
Docker build 1分22秒、検査本体8分41秒を要した。Pythonの実行構成は今回変更していない。
数値golden・計算・保存の保証を削らず、次の候補は現行テストのファイル別時間の再収集と
分配weightの更新、必要なら既存の全件・coverage集約を維持したPython shard追加とする。
Localにはbackup込みの分割と長いmap/weatherファイル、同期にはテスト件数分配による時間の偏りが残る。

Playwright image初期化は21〜38秒で、OS/browser追加導入はない。npm・pip・Firebase・image取得、
runner性能とqueueのばらつきは残る。一部は実装PRのCIと同時実行しており、平均値や単一要因の
短縮率ではない。job数は20から28へ増え、準備処理の重複と同時実行枠を使うトレードオフがある。

実装PR #448の[Run 43914399276](https://github.com/Yuto-24/NavMate/actions/runs/43914399276)（`b137fcc1`）も全28 job成功・8分57秒（CI変更を含む全検証のため、通常変更の代表測定にはPR #449を参照）。CodeRabbitレビューで判明したworker数・認証配置・分配検査配置・公式コンテナ利用の旧文書不一致は現行コードに合わせて修正済み。
