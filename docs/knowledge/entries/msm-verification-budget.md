# MSM全件検証を短い試行上限で中断しない

- ID: MSM-VERIFY-BUDGET
- Status: provisional
- Scope: NavMate `scripts/static_ops` の `--verify-payloads` 経路。
- Trigger / search terms: `attempt timed out`、`Retained payload integrity failure`、`wait_for_candidate`。
- Last verified: 2026-11-17。基準コミット `7213effafa7d9695bb9eacfa344a29553a20f73a` と対象テストで確認。本番での修正受入は未実施。
- Evidence: [公開後検証の失敗](https://github.com/Yuto-24/NavMate/actions/runs/43893765453/job/133405446692)、[復元時の再失敗](https://github.com/Yuto-24/NavMate/actions/runs/43893765453/job/133422468625)、[回帰テスト](../../../tests/unit/test_static_verification_budget.py)。

## Observation and impact

2回目のジョブはアップロードまで成功した。公開後検証の初回はrelease不一致、2回目以降はNPZ検証中に時間切れとなり、計300秒で終了した。最後に表示されたNPZ名は中断位置であり、そのファイルの破損や単独取得時間を示すものではない。

3回目のジョブでは復元時の整合性エラーが再発した。公開後検証の時間切れとは分けて調査する。

## Cause and evidence

旧実装の30秒は1ファイルではなく、メタデータと全payloadを検証する子プロセス全体の上限だった。再試行で完了済みの取得もやり直すため、一巡に30秒以上かかる状況では全体上限だけを延ばしても完了できない。

修正は全件検証の子プロセスに総時間の残りを割り当てる。メタデータのみの既存経路は短い試行上限を維持する。全件検証で実際の不一致や取得エラーが返った場合は、従来どおり残時間内で再試行する。別試行の部分成功は合成しない。

## Next-time action

最初にアップロードの成否と検証の成否を分ける。`--verify-payloads` の有無、子プロセスに渡す上限、再試行の対象を確認する。総時間の上限と、`fetch()` のsocket timeoutは別物であり、socket timeoutだけでは応答本文全体の時間を制限できない。

復元不一致は対象・Run・期待サイズ／SHA-256・実測値で調査する。不一致を無視した保存や、catalogの書換えによる通過は行わない。診断ログに応答本文、認証情報、未検証の任意メタデータは含めない。

## Limits and counterexamples

この記録は1件の事故についてのObservationであり、一般的な配信障害の原因を断定するものではない。総時間を超える転送は修正後も失敗する。復元不一致の原因、配信拠点差、初回release不一致の理由は未確定。

対象テストは取得したソースの隔離コピーで実行した。Dockerでの全体CI、独立レビュー、本番の全payload照合を代替しない。必須確認が完了するまでPR提出と本番反映は行わない。
