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
