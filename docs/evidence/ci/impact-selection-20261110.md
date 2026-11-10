# Issue #421: 変更影響に応じた CI

PR の選択とブラウザ準備を変更する。検証結果・性能値は確認できた範囲で記録し、
新しい構成での main 成功と通常 PR の5分目標は別々に評価する。

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

2026-11-10 に GitHub API で確認した active Ruleset `20705217` は、削除・force push 禁止、
code quality、Copilot review、PR と会話解決を要求するが、required status checks は未設定。
legacy branch protection は404。したがって既存設定だけでは CI 失敗によるマージ禁止を保証できない。
既存規則を維持した上で `ci-required` を必須にする必要がある。設定変更は未実施。

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

律速は Local 回帰本体で、10ファイルにわたる実計算・保存・復元を2 workersで実行している。
次の候補は、ファイル内の順序を維持した Local の file-level shard と、Chromium sync 後の
共有開発検証の分離。採用する場合は全件の exact-once 分配と Hosted 時間を検証する。
今回の証拠だけで worker 数増加や重要なテストの削除を正当化しない。

通常変更を選択した Hosted Run、必須チェックの登録、新構成での main run は引き続き未確認。
この全 suite run をそれらの代替証拠にしない。
