# アプリ公開工程の棚卸し（Issue #339）

**現行の再build・停止制御・公開gateを維持し、安全な診断と停止検知を先に改善する。**
build-onceは成立条件を定義できるが、削減可能な時間と成果物再利用の安全性を裏付ける証拠が不足している。
共通concurrencyだけでは、失敗したrunの終了後や別hostからの公開を保護できない。
この文書は調査結果と後続実装の分割案であり、公開・再開・設定変更の承認ではない。

調査日は2026-11-08（JST）。コードの基準は
[`b764d27b`](https://github.com/Yuto-24/NavMate/tree/b764d27b4c46dcd50b46909bebe17a91630d4fc5)。
[Issue #339 アプリ公開工程の棚卸し](https://github.com/Yuto-24/NavMate/issues/339)の完了条件を扱う。
現在の本番状態やv2.1.3公開後の復旧完了は、この調査では判定していない。

## 根拠と観測できたコスト

- [app_release.py](../scripts/static_ops/app_release.py): `prepare` / `publish`、`Operator.build` / `verify`、`Journal`。
- [build_app_release.sh](../scripts/static_ops/build_app_release.sh): 隔離環境内の候補依存関係・build・検証。
- [release_automation.py](../scripts/static_ops/release_automation.py): Actions用の排他確認・Release選択・report。
- [アプリ公開workflow](../.github/workflows/static-app-release.yml)と[MSM公開workflow](../.github/workflows/static-production.yml)。
- [PR #305 正式Releaseの自動公開](https://github.com/Yuto-24/NavMate/pull/305): 手動経路との排他、fresh rebuild、単調なversion更新、失敗時の停止維持を導入した判断。
- [公開実行41296549132のjob](https://github.com/Yuto-24/NavMate/actions/runs/41296549132/job/124818496178): GitHub jobs APIのstep時刻と公開ログを読み取りで確認。

| 対象実行の工程 | 開始→終了（2026-11-01 UTC） | 経過時間・結果 |
| --- | --- | --- |
| job全体 | 10:13:47→11:00:02 | 46分15秒、failure |
| prepare | 10:14:19→10:37:17 | 22分58秒、success |
| publish | 10:37:17→10:59:57 | 22分40秒、failure |

公開ログのprepareは`OK/build-test`、publishは`BLOCKED/canonical-verification`。
publish時のautomation・workflow・productionのmutationは`CONFIRMED`、approved_shaは`UNCHANGED`だった。
`production=CONFIRMED`はuploadコマンドの正常終了を意味し、canonical一致や復旧完了を意味しない。
Issue本文はv2.1.3の実配信確認を報告しているが、このrunのログだけで同じ受入を再証明できない。

この値は1回のstep全体の時間であり、MSM生成・依存導入・build・E2E・upload・照合の内訳は未計測。
`Journal.stage`には時刻がなく、子プロセス出力は`command`にcaptureされる。
prepared/freshのRun差、provider HTTP status、canonical内の失敗箇所も取得できたログでは不明。
publish時間をそのまま再buildの削減量とみなさず、過去の403やAnalytics挿入差分と原因を同一視しない。

## 現行工程と重複する検証の役割

| 工程 | 実行内容と目的 | 重複・コストの判断 |
| --- | --- | --- |
| prepare snapshot | source/current/tooling SHA、設定、canonical、Pages ID/設定/idle、live Rules・schema互換性を固定 | 可変の外部状態を読む。publish側の再読取は必要 |
| prepare build-test | 候補clone、現行feed復元、実MSM再取得・decode、隔離buildとE2E、独立inventory/private-material検査 | 公開前レビューの成立性を確かめる。全体22分58秒に含まれる |
| plan保存 | SHA、snapshot、prepare終了後の時刻、release/feed report digestを保存 | dist自体を単一の不変bundleとして認証する契約ではない |
| publish preflight | reviewed plan hash、30分以内のplan、snapshot、prepared inventory/reportと現在のfeed鮮度を再検証 | 待機中の改変・期限切れ・設定driftを拒否。古いprepareはfresh build前に停止する |
| pause / quiescence | automation=falseとworkflow disableをread-backし、停止後のsnapshotを比較 | 停止中に公開可能な状態を作る。新旧deployment IDの扱いは下記参照 |
| fresh-build-test | `fresh/`で`Operator.build`全体を再実行 | prepared distはuploadしない。上流Run・保持feed・時刻が変わり得るため同一計算とは限らない |
| pre-upload | fresh inventory/coverage、trusted Wrangler、停止状態・Pages ID/設定・Rulesを再確認 | 外部状態とuploadするbytesの最終照合。待機後にも必要 |
| upload | 最小upload directoryから既存Pagesへ公開 | コマンド成功と実配信の一致を分離する |
| canonical-verification | candidate release/catalog、root/manifest、missing asset、Pages identityを照合。変数・Rules・排他も再確認 | 配信がまだ旧版・部分反映・変換済みの場合に承認SHAを進めない |
| approved-sha / resume | SHAを更新・read-backし、`verify`を再実行、workflowをenable、元がtrueのautomationだけ復元 | SHA更新の前後で2回照合。再開前にも配信一致を要求する |

`Operator.build`は両段階で、現行feedの保持asset復元、25時間admissionとRun末尾までの
`--full-run`生成、Docker image build、候補wheel/pip/npm/Chromium導入、release/data/schema検査、
typecheck、static build、artifact tests、production E2Eを行う。
最後にtrusted toolingがfreshness hintを封入し、独立inventoryとupload contextを検証する。
Docker layerの再利用はあり得るが、実際のcache hitや各工程の時間は未計測。
同じSHAでもbase image tagや依存導入、feed bytesが同一とは証明されていない。

`unchanged`はpause前には同じsourceのMSM更新によるPages IDの変化を許容する。
pause後のfresh buildとupload準備ではdeployment IDも固定する。
`validate_feed`は生成30分以内・catalog寿命6時間・残存2時間以上・現在から24時間coverage・
7日以内のRun・全NPZのbytes/hash/decode/Runを要求する。planの30分条件だけでは代替できない。

### canonical検証の実際の範囲

アプリの`Operator.verify`は次を順に実行し、SHA更新後にも同じ列を繰り返す。

1. `wait_for_candidate.py`を最大300秒（外側commandは330秒）で実行。
   既定経路はrelease JSON全体の一致と、candidate inventoryに対するcatalog bytes/hash・鮮度を検査する。
2. `monitor`でcatalogを再取得し、残存時間・生成時刻などを確認する。
3. `/`と`/local/manifest.json`のheaders・本文、存在しないassetの404を検査する。
   rootだけは確認済みAnalytics単一挿入の厳密な例外がある。
4. Pagesの成功deploymentのcommitとproject設定digestを確認する。

**release内の全inventory一致と、全ファイルをHTTPで再取得して照合することは異なる。**
アプリ経路は`--verify-payloads`を渡しておらず、配信NPZ全件の取得・decodeは行わない。
MSM workflowは[Issue #362の公開後検証](https://github.com/Yuto-24/NavMate/pull/363)で追加された
`--verify-payloads`を使用する。この差をアプリ経路にも適用済みとは扱わない。
[既存runbook](static_operations.md#wsl-からのアプリ更新-prepare--publish)の「release 全 inventory」は
この区別を明記していないため、本調査では上記コード上の範囲を採用する。
アプリへのpayload検証追加は別の動作変更として判断する。

## build-onceの判断

**現時点では採用を保留し、再buildを維持する。** 単に`fresh`を`prepared`へ置換しない。
成立させるには、レビュー対象とupload対象が同一の変更不可bundleであることを、trusted toolingで
独立に確かめる必要がある。必要な対応関係はsource SHA/version、tooling SHA、build環境identity、
公開設定digest、dist全inventory、feed report digest、Run/coverage/生成・失効時刻である。
候補コードが作った自己申告やdigestだけでは、隔離境界やartifactの検査を代用しない。

| prepare後の変化 | build-once案でも必要な扱い |
| --- | --- |
| 変化なし・待機あり | bundleを再hashし、現在時刻でfeedを再検証。snapshot、Rules、排他、公開対象、upload直前・公開後gateを維持 |
| planが30分超、改変、source/tooling/設定/Rules/schemaの変化 | 再利用不可。新しいprepare・digestと適切な人手レビュー／stable-release policy判定が必要 |
| catalog生成30分超、残存2時間未満、coverage不足 | 再生成が必要。timestampやfreshness hintだけの更新は禁止。feedを変えれば同じbundleではなくなる |
| 上流に新Run | 現行appは同Run再取得を許すが、fresh buildでは新Runを選ぶ可能性がある。既存bundleを使う場合のRun採用基準を明示して合意するまで現行維持 |
| 同SHAのMSM公開が進行 | 最新保持feedとdeployment identityを再評価。古いbundleが新しい予報を巻き戻す扱いを決める必要がある |
| pause後のdeployment変化・別operatorの介入 | uploadを止めて再棚卸し。再利用や追加retryで競合を隠さない |

アプリ部分だけ再利用してfeedを再生成する案も、現状では統合distの再封入と検証が必要。
どのE2Eを再実行するかは、変更された入力とテストが保証する契約から決める。
物理的な配信分離は[Issue #270 アプリとMSMの配信独立化](https://github.com/Yuto-24/NavMate/issues/270)の範囲。

## 共通concurrencyで置換できる範囲

**現在のconcurrencyを維持し、variable停止・workflow disableは削除しない。**
同じrepositoryの両workflowは`static-production`、`cancel-in-progress: false`、`queue: max`を使う。
最大100件のpendingを保持し、超過分はcancelされる。待機開始順とdispatch順は同じとは限らないため、
順序に依存せず開始後にsource/versionを再判定する。
根拠は[GitHubのconcurrency仕様](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)。

| 起動経路・状態 | 現行の保護と置換の限界 |
| --- | --- |
| 同group内のapp/feed Actions | workflow全体を直列化。ActionsOperatorは自身が実行中のtrusted workflowであることを確認し、後続pendingを許す |
| schedule・手動dispatch・外部triggerから同feed workflowへ | group内では直列化される。外部feed_refreshは追加opt-in・回数制限もある。group外の直接uploadは対象外 |
| manual feed dispatch | job条件は通常のworkflow_dispatchをautomation=falseでも許す。variableだけを停止装置とみなせない |
| 既存queued/waiting run | disableは既存runのcancelではない。Actions経路は共有lease後方で待たせ、manual Operatorは両workflowの全未完了runを拒否する |
| 同git common directoryのlocal呼出し | `flock`で直列化。ただしActions leaseを取得しない。手動公開の作業窓とremote idle確認も必要 |
| 別clone/host、Dashboard、直接Wrangler | shared group・flockの外。Pages inventoryのGETもatomic lockではない。既存の排他的作業窓が必要 |
| upload後の失敗でActions run終了 | leaseが解放されてもcanonicalと承認SHAが一致するとは限らない。後続の整合性gateと停止維持が必要 |

自動経路だけ停止操作を省く案も、失敗後のlease解放・pending run・手動dispatch・承認SHA切替の
全経路を検証しなければ採用できない。concurrencyは直列化であり、失敗状態の永続的な隔離ではない。
別hostまで保証するremote lockの新設も、今回の調査から直ちに必要とは結論しない。

## 部分失敗と整合性を伴う復旧条件

以下は既存[復旧runbook](static_operations.md)を具体化した判断表。
`CONFIRMED`は個々の操作の確認済み、`UNKNOWN`はtimeout等で成功した可能性がある状態。
`RUNNING/ATTEMPTED`の残留も未完了として扱い、journalだけからremote stateを確定しない。
復旧操作は別途承認し、書き込みの前後で対象を再読取する。

| 停止位置 | 想定される状態 | 必要な再読取と復旧条件 |
| --- | --- | --- |
| pause前 | このscriptのremote mutationなし | canonical/current SHA、Pages、設定、外部Rules操作を確認。原因を直し新規prepare |
| pause / disable / quiescence / build / pre-upload | variableかworkflowだけ停止した可能性。通常productionは旧版 | 両停止状態、両workflowのrun、Pages idle、旧canonical/承認SHA/設定/Rules/予報を確認。一致と排他を確認して元の状態へ戻すか、新規prepareを選ぶ |
| upload / canonical-verification | 新版・旧版・不明のいずれもあり得る。承認SHAは旧版の可能性 | Pages ID/commitと新旧release inventory、root/manifest、catalog/必要なpayload、Rules/設定を照合。取得不能・不一致なら停止を維持。新配信の必要な公開gateを満たすまで承認SHAを進めない |
| approved-sha | 新配信確認済みでもSHA更新はUNKNOWNになり得る | canonicalと実際のvariableを照合し、必要なSHA更新だけ承認の上で実施・read-back。盲目的な再publishはしない |
| resume | 新SHAでもworkflowまたはautomationだけ復帰した可能性 | workflow state、automation、実行中/待機run、canonical/承認SHA・設定・Rules・予報を再確認。整合する場合だけ不足する再開操作を実施 |
| timeout / cancellation / SIGKILL | 最後に記録された段階よりremoteが進んだ可能性 | 段階を問わず上記remote情報を再読取。再開済みの可能性も含めて確認し、追加書き込みを推測で行わない |

uploadを試みた後は、整合性確認なしの再開、自動rollback、同じstoreでのpublish再試行を行わない。
元のautomation=falseは意図的な停止として保持する。read-backで成功を確認できない操作はUNKNOWNのまま残す。
予報が期限切れならその事実を明示し、現在のgateを満たす予報復旧を別途承認する。
「停止中だから再開」では復旧条件を満たさない。

### 停止放置を防ぐ方針

採用候補は**自動再開ではなく、独立した読み取り専用の検知と担当者への復旧導線**。
現行`static-monitor`は別concurrencyでcatalog鮮度を監視するが、workflow disableやvariable停止そのものは検知しない。
app側の`always()` reportもrunner消失や強制終了では保存を保証できない。

後続実装では、app/feedの最終run・停止状態・canonical/承認SHAの整合性と観測時刻をまとめる。
進行中の正常なapp公開、期限・担当者を持つ意図的な停止、終了/timeout後の残留停止を区別する。
判別不能はUNKNOWN、読取失敗を正常扱いしない。想定時間は現行50分step/120分jobの上限を参考にし、
schedule遅延を含む通知時刻の保証とはしない。停止状態が変わらない間の重複通知を避ける。
通知先・担当者・運用上の期限は実装時の承認事項で、今回メッセージ送信や設定追加は行わない。
監視から既存runbookの上表へ進め、復旧後は次の自然なMSM更新が同じapp SHAで完了したことを別に確認する。

## 診断ログの最小契約案

**固定enumと型・長さを制限したallowlistを境界にし、例外文字列やprovider出力をそのまま転送しない。**
現行はstageとmutation履歴を保存する一方、subcheckと工程時間がない。
`command`は失敗を固定メッセージへ変換し、Actionsの一般例外も固定文になるため、詳細原因が落ちる。
Actionsのreportは`reason`を選ぶが、`execute`の例外経路ではreasonを設定していない。

| 公開してよい項目の案 | 制限・用途 |
| --- | --- |
| schema_version、run ID/attempt、source/tooling SHA | 正しい型・桁数のみ。秘密URLやローカルpathをIDに転用しない |
| phase、stage、check、outcome、error_code | 固定enum。未知の例外は`INTERNAL_ERROR`。受信文字列をcodeに使わない |
| started_at、finished_at、duration_ms | UTCと単調時計による経過時間。中断時は終了不明を明示し、時刻を捏造しない |
| target | `/`、`release.json`、`local/manifest.json`、catalog/freshness、固定missing-probe名、検証済みinventory内のhash名NPZに限定。query、fragment、host、絶対path、任意文字列は出さない |
| HTTP status、attempt_count | HTTP statusは整数。transport/TLS/redirect/timeoutは固定分類で分離。Locationやheader全文は出さない |
| expected/observed bytes・SHA-256、Run、coverage・失効時刻 | 検証対象artifactの値だけ。認証情報や設定の秘密値をhash化して公開しない。異常型は値を捨てる |
| upload命令、provider deployment、canonical、approved SHA、workflow、automationの各結果 | 各々NOT_ATTEMPTED/PASS/FAIL/UNKNOWN等で記録。upload正常終了から他をPASSにしない |

canonicalのcheckを少なくとも`release_identity`、`catalog_identity`、`catalog_freshness`、
`root_headers`、`root_content`、`manifest_headers`、`manifest_content`、`missing_asset`、
`pages_identity`に分ける。SHA更新後のverifyはphaseで区別する。
失敗条件はHTTP/TLS/redirect/timeout、schema、bytes/hash、freshness、identity、headersを区別する。
NPZ decode/Runの診断はその検証を実行した経路だけに付け、未実施を成功として表示しない。

既存の`serving-root.body/json`はprivateに限定する。raw bodyは最大8 MiB+1 byte、
JSONにはETag等の生headerが含まれるため、ファイル全体を公開artifactへ移さない。
allowlistの項目を新しいデータ構造に構築し直し、candidateのファイル・例外・自由記述の丸ごとコピーを避ける。

### 保持・取得方法と現行との差

| 層 | 現行 | 後続案 |
| --- | --- | --- |
| Actions summary | mode/SHA/status/stage/changes/reason。runに紐づく。保持期間の実設定は未確認 | 安全なcheck別結果と復旧runbookへのリンクを出す |
| runner終了後の診断 | private runner-temp storeはartifact化されず、終了後取得できない場合がある | 上記allowlistだけの小さいJSONを、run ID/attempt付きのActions artifactとして14日保持する案。公開repoのartifactを秘密保管先と扱わず、容量上限・無料枠・取得権限を確認して別PRで採否を決める |
| 制限付き証拠 | plan/status、Rules receipt、root body等を0700 store/0600ファイルに保存 | 手動では既存の制限付き保管先で案件・担当者・削除期限を記録。Actionsのprivate storeを保存する新基盤は今回は採らない。必要なら保存先・権限・保持期限の承認後に実装 |

sanitized artifactはrun画面またはActions artifacts APIから取得する。期限後や保存失敗時は取得不能と明示し、
現在のprovider状態の再読取は可能でも、当時のHTTP応答や原因を復元できたとは扱わない。
公開summary/log自体の保持はrepository設定に従うため、artifactの14日案と同一視しない。

文書と実装の差として、`automatic_app_releases.md`は詳細journalをprivateと説明するが、
`Journal.finish()`は`rules_receipt`等を含むjournal全体をstdoutへ出す。
`report`のallowlistだけではstep log側の公開範囲を制限できない。
本調査では認証情報の漏洩を確認したとは主張しないが、診断改善時はstdout/stderr/summary/artifactを
同じ境界で検査する必要がある。raw journalを公開しない修正を先行単位に含める。

### 秘密情報を出さない回帰確認

- HTTP body、header/ETag/Location、URL userinfo/query、例外、subprocess stdout/stderr、
  Rules receipt、環境変数へ異なるsentinelを注入し、stdout/stderr/summary/公開JSONの全てで不在を検査する。
- 不正path、長大値、CR/LF、制御文字、偽のSHA/Run、未知enumは拒否または固定値へ縮退する。
  whitelistに似た秘密URLも表示しない。ログ出力を成立させるための追加HTTP取得は行わない。
- canonicalの各check失敗、timeout・中断、read-back失敗をmockで注入し、分類・UNKNOWN・
  承認SHA未更新・無条件resumeなしを確認する。最終状態を上書きして失敗証拠を消さない。
- 既存`test_native_command_failure_output_is_never_exposed`、root serving tests、
  mutation前後の失敗テストと`test_release_automation.py`を再利用し、不足する境界だけ追加する。
  本番への故障注入・公開は不要。

## 後続の最小実装単位

このPRでは文書だけを変更する。次の各単位は個別にレビュー・検証して採否を決める。

| 優先 | 単位 | 必須の回帰確認・判断条件 |
| --- | --- | --- |
| 1 | appの安全なsubcheck分類・工程時刻と、全出力経路のallowlist化 | 秘密sentinel不在、既存の停止・retry回数・順序・upload条件が不変。既存journalの詳細はprivateに保つ |
| 2 | sanitized診断の保持 | サイズ・保持期間・取得方法・無料枠を確認。保存失敗や強制終了でも公開成功を偽らず、privateファイルが混入しない |
| 3 | read-only停止検知とrunbookへの導線 | 意図的停止・正常公開中・残留停止・UNKNOWNをfixtureで区別。自動再開せず、通知先と権限を別途承認 |
| 保留 | build-once | 同等の成功例・失敗例で工程時間とprepared/fresh Run・digest差を計測し、再利用条件と効果を評価。artifact改変・期限切れ・driftを拒否する試験が先 |
| 保留 | Actions経路の停止制御削減 | queued/外部/手動/local/別host・各mutationの部分失敗を含む競合モデルが成立してから判断 |

source固定、予報鮮度・整合性、canonical照合、Rules/schema互換性、無料枠の条件は維持する。
この調査結果を根拠に既存gateを削除・緩和せず、merge・本番公開・停止復旧はそれぞれの承認と証拠で判断する。
