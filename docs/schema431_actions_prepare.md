# GitHub Actions で v2.3.2 のSchema移行を準備・公開する

`static-app-release` の `operation=prepare-schema431` は、固定した Schema 4→5 移行を
検証し、定期更新を一時停止して、既存の手動 `prepare` を実行する。
成功時は plan と後工程に必要な成果物を暗号化して保存する。
**publish は別途、正確な plan SHA-256 への承認を必要とする。この操作に公開機能はない。**

承認後は別操作の `publish-schema431` で、元のprepare成果物を復元して固定toolingの
`publish()` を実行できる。WSLにCloudflare/Googleの認証を追加する必要はない。
prepareの前に、公開用driverのレビュー・merge、既存Pages token、鍵の保持、
planを非公開で確認できる環境を揃える。plan取得後に公開経路を実装すると30分期限を失う。

この文書と実装の追加は、本番停止・prepare・publishの実施記録ではない。
実行前に、対象の操作窓と停止・prepare の承認を確認する。
実行方式と固定条件は [Issue #431](https://github.com/Yuto-24/NavMate/issues/431)、
移行の検証内容は [Schema 4→5 の記録](forecast_schema_transition.md) を正本とする。
当初の#431はv2.3.1が対象だったが、保存案内テストの修正を含むv2.3.2へ候補を進めた。
以下は[#437の再審査](https://github.com/Yuto-24/NavMate/pull/437)で受理された別記録の固定値。
旧v2.3.1の記録・Artifact・readback結果を、新候補の証拠としてそのまま使わない。

## 維持する境界

| 対象 | 条件 |
| --- | --- |
| 操作 | `workflow_dispatch`、`main`、空の `release_id`。prepareとpublishは別operation |
| Google WIF | 既存の Repository/Owner ID、`environment:static-production`、`static-app-release.yml@refs/heads/main` の制限を維持。scope は `firebase.readonly` |
| GitHub | 既存の `STATIC_APP_RELEASE_GH_TOKEN`。新しい権限は要求しない |
| Cloudflare | prepareは既存の `STATIC_CLOUDFLARE_READ_TOKEN`、承認後のpublishは既存の `CLOUDFLARE_PAGES_TOKEN` |
| current | `03cc463cf09192e1403f839df4165410c5db8d7b`（v2.2.2） |
| candidate | `f1a5ef49eeab41744635232cddd51c2257871aed`（v2.3.2） |
| 移行tooling | `64225b82c9b2e978409f0b35490be3c83af3f157` の clean checkout |
| `SCHEMA_RECORD` の元バイトSHA-256 | `c8db8b709497e4071d937fba768c89e48c0d7712f0a4a87bfe88f661d72889ba` |

main 上のdriverは、別checkoutの固定toolingをimportして使う。
`reviewed_schema()`、互換性検査、snapshot、隔離build・E2E、plan生成は固定toolingの実装を使い、
移行記録のtooling SHAを書き換えない。新しいdriverのSHAは暗号化したhandoff記録に残る。
通常の自動Release、`replay-release`、`readback` の条件は変更しない。

## 1. 非公開証拠を転送用Secretにまとめる

WSLにある次のファイルを使う。記録の再作成や整形はしない。

- `/home/yuto/autonavlog-releases/schema4-5-v2.3.2-20261113/SCHEMA_RECORD.json`
- その記録が参照する `old_to_new`、`old_writer_coexistence`、`storage_sync_roundtrip` の3報告

このPRを含むレビュー済みcheckoutから、既存のPython環境で実行する。
packはPython標準ライブラリだけを使い、Node.jsやCloudflare/Google認証は不要。
受理済みの新4ファイルを使い、reapply helperは再実行しない。
旧転送のSecretは新pinでは通らないため、新しくpackした組で2つとも更新する。

```sh
umask 077
transfer_dir="/home/yuto/autonavlog-releases/schema431-transfer-$(date -u +%Y%m%dT%H%M%SZ)"
python scripts/static_ops/schema431_bundle.py pack \
  --schema-record /home/yuto/autonavlog-releases/schema4-5-v2.3.2-20261113/SCHEMA_RECORD.json \
  --output "$transfer_dir"
```

新規0700ディレクトリに、0600の `evidence.secret` と `archive.key` を作る。
前者は4ファイルの元バイトをgzip/Base64でまとめたもの。後者は成果物用に生成した
32バイトのランダムなAES鍵であり、資格情報ではない。
**Base64は暗号化ではないため、両ファイルは非公開のまま扱う。**

記録の元バイトhash、各報告のhashと内部identity、固定candidate/current/tooling、
参照path、容量を検証できなければpackは失敗する。
元記録の絶対pathにも対応するが、参照先は上記の固定証拠ディレクトリ内に限る。
symlink、親ディレクトリへの移動、無関係な絶対pathは受け付けない。

既存のGitHub認証で、`static-production` environmentに次の2つのSecretを登録する。
Repository Variableやworkflow inputへ内容・鍵を貼り付けない。

```sh
gh secret set STATIC_SCHEMA431_EVIDENCE --repo Yuto-24/NavMate \
  --env static-production < "$transfer_dir/evidence.secret"
gh secret set STATIC_SCHEMA431_ARCHIVE_KEY --repo Yuto-24/NavMate \
  --env static-production < "$transfer_dir/archive.key"
```

この登録は運用時の事前作業であり、PRの実装・テストでは行わない。
新しいIAM identity、WIF条件の緩和、Cloudflare/Google権限の追加は必要ない。
Environment Secretの設定方法と48 KiB制限は
[GitHub公式手順](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
を参照。

### 容量と期限

| 対象 | 上限・扱い |
| --- | --- |
| 転送Secret | エンコード後48,000バイト。展開後JSONは36 MiB、記録本体1 MiB、報告は各8 MiBまで |
| 転送の有効期間 | packから24時間。期限切れは停止前に拒否。同じ元証拠から新しい転送を作り直す |
| 暗号化成果物 | 1実行につき最大512 MiB、格納ファイルの合計は480 MiB・25,000件まで |
| Actions Artifact | 暗号文だけを1日保持。通常Artifactを秘密保管先とは扱わない |
| plan | 既存どおりprepare終了時刻から30分。Artifactの保持期限とは別 |

実行前に既存の[plan/limits・共有容量確認](static_operations.md#quota-evidence-and-monitoring)
を行い、prepareとpublishそれぞれ最大512 MiBのArtifactを保持できる余裕を確認する。
コードの容量制限はGitHub側の利用可能残量を保証しない。
上限超過や保存失敗を平文Artifactで回避しない。
Secretが収まらない場合は停止前の不足条件として扱い、証拠を削ったりhashだけに置き換えたりしない。

ActionsとWSLの復号には、上記の容量上限を持つレビュー済みdriverを使う。
旧driverは256 MiBを超える暗号文を拒否する。既存転送が24時間の有効期間内なら、
同じSecretと鍵を使える。元証拠と暗号形式は共通である。

## 2. mainから明示的に実行する

`static-app-release` の **Run workflow** で次を指定する。

- Branch: `main`
- `operation`: `prepare-schema431`
- `release_id`: 空欄

定期更新、別のアプリ公開、手動操作が重ならない操作窓を確保する。
workflowの共有concurrencyを維持したうえで、実行中の自己RunだけをAPIから照合する。
Run ID、attempt、Repository/Owner ID、workflow ID/path、event、main、head SHAが一致し、
`in_progress`の場合だけ除外する。両公開workflowの全Runを調べ、その他の
running/queued/waiting等、重複、一覧欠落・変化は拒否する。別Runのcancelは行わない。

処理は次の順で進む。

1. Secret、鍵の組合せと期限、元証拠、固定tooling、runner条件を検証する。
   受け取ったSecretと鍵はprovider/producerの子プロセスへ引き継がない。
2. 固定v2.3.2のRelease/tag/VERSIONと、既存の[候補CI](https://github.com/Yuto-24/NavMate/actions/runs/43383649255)
   の成功を再確認する。canonical/approved/config、environmentのshadowing、Pages全inventory、
   稼働Rules、workflowのactive/idle、現在のautomationを読み取る。
   3報告を含む元証拠を固定toolingの `reviewed_schema()` で実際に受理できることも必須。
3. 直前のsnapshotを再照合してから、automationがtrueならfalseへ変更し、APIでread-backする。
   既にfalseの場合はその状態を保つ。workflowはactiveのままにする。
4. 停止後snapshotで、automation以外に変化がないことを確認する。
   schema付きの通常Operatorで既存 `prepare()` を呼び、隔離build、E2E、成果物検査、再照合を行う。
5. plan、journal、元証拠、`prepared/upload`、`prepared/feed-report.json`をAES-256-GCMで
   暗号化して保存する。candidate checkout、node_modules、cache、資格情報、生ログ全体は含めない。
   失敗時の限定したbuild出力は、下記の暗号化journal内にだけ記録する。
   通常終了時はrunner上のこの実行が作った平文を削除する。

固定buildは一部の生成物をroot所有のまま残すため、runner権限で削除できない場合がある。
暗号化成果物の引き渡しを先に確定し、通常削除が権限不足になった場合だけ、
この実行が新規作成したprivate storeを `sudo -n` で削除する。
対象pathを固定し、provider資格情報は渡さない。削除に失敗しても暗号文のuploadは試行する。

停止前の読み取りだけは、schema付き互換性検査を委譲した別Operatorでautomation=trueを観測できる。
公開設定をfalseと偽って読み替える処理ではない。
実prepareでは、固定toolingが要求する `STATIC_AUTOMATION_ENABLED=false` をそのまま検証する。

build呼出し中だけumaskを022にする。固定toolingが作るbuild先の親は、runner所有で
group/otherの権限を持たない実ディレクトリであることを先に確認する。
private storeとbuild先自体は、既存どおり0700で作る。
これにより、Docker内のrootがコピーした公開用assetをrunnerが読み取れる。
固定toolingのbuild・E2E・成果物検査はそのまま実行し、成功・例外のどちらでも元のumaskへ戻す。
publishのfresh buildも同じ処理を継承する。証拠・鍵・journal・plan・暗号文の非公開保存は維持する。

## 3. planを非公開で確認する

Actionsのsummaryには処理段階、停止状態、暗号化保存とuploadの結果、成功時のplan SHA-256だけが出る。
`PREPARED`だけでなくArtifact uploadの成功も確認する。
`schema431-<Run ID>-<attempt>` Artifactから `.aesgcm` ファイルを取得する。
保存・失効の挙動は[GitHub公式のArtifact仕様](https://docs.github.com/en/actions/tutorials/store-and-share-data)に従う。

WSLで、pack時に保持した `archive.key` と同じ鍵を使う。
旧v2.3.1のArtifactを調べる場合は、その実行の旧driverと旧鍵を使う。
新driverの固定値や新しい鍵で旧記録を読み替えない。
復号には既存の `PyJWT[crypto]` 依存関係に含まれる `cryptography` を使う。
[AESGCM](https://cryptography.io/en/latest/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM)
の認証に失敗した暗号文は展開しない。

```sh
python scripts/static_ops/schema431_bundle.py unpack \
  --archive /private/download/schema431-result-RUN-ATTEMPT.aesgcm \
  --key "$transfer_dir/archive.key" \
  --store /home/yuto/autonavlog-releases/schema431-plan-RUN-ATTEMPT
```

保存先は新規0700ディレクトリに限る。元の証拠ディレクトリにファイルがある場合は、
一致を確認するだけで上書きしない。planの元バイトとreceiptの絶対pathを保持する。
固定toolingのpublishはreceiptのpathも再照合するため、任意の場所への証拠移動やplan編集は不可。
`prepared/upload`とfeed reportは既存 `validate_build()` が再確認できる形式を維持する。
後のpublishは既存どおりfresh buildを行うため、candidate checkoutやcacheの引継ぎは不要。

planのcandidate/current/tooling、設定・Rules/schema receipt、preparedの検証結果、
plan SHA-256とsummaryの一致を人が確認する。
承認対象は**確認したplanの正確な64桁SHA-256**。その値を後で再計算して自動承認したことにしない。
publish用の入力には、その承認済みdigestと元のRun ID・attemptを指定する。
PRのmergeやReleaseの作成だけでは、そのplanへの公開承認にならない。

`within_plan_window=false`、30分超過、設定・Rules・source・tooling・証拠の変化、
既存feed鮮度条件の失敗があれば、そのplanは公開に使えない。
時刻を書き換えず、新しい操作窓でfresh preflightから新規prepare・レビューを行う。
有効な元証拠のidentityまで変わった場合は転送の作り直しだけでは足りず、証拠の再審査が必要。

## 4. 承認済みplanをActionsで公開する

`static-app-release` の **Run workflow** で次を指定する。入力に非公開証拠や鍵を入れない。

| 項目 | 指定値 |
| --- | --- |
| Branch | `main` |
| `operation` | `publish-schema431` |
| `release_id` | 空欄 |
| `prepare_run_id` | 確認したprepareのRun ID |
| `prepare_run_attempt` | そのprepareのattempt |
| `reviewed_plan_sha256` | 人が確認し、公開を承認したplanの64桁SHA-256 |

このjobだけが既存の `CLOUDFLARE_PAGES_TOKEN` を受け取る。
GitHub token、WIFのRepository/Owner ID、workflow_ref、environment、
`firebase.readonly` scope、共有concurrencyはprepareと同じ境界を維持する。
`STATIC_SCHEMA431_ARCHIVE_KEY` はprepare時と同じ鍵が必要。公開・記録取得が済むまで削除しない。

公開前に、元Runが同じRepositoryのmainで実行したprepareであること、指定attemptが最新かつ成功し、
その `manual-prepare` jobも成功していることをAPIで照合する。
対象名のArtifactが一意で有効なことを確かめ、外側ZIPから期待する暗号文1ファイルだけを取り出す。
取得中に元Runが再実行された場合、復号やplanの照合に失敗した場合は公開しない。
[GitHubのArtifact API](https://docs.github.com/en/rest/actions/artifacts)と
[attempt別Jobs API](https://docs.github.com/en/rest/actions/workflow-jobs)を使い、
欠落・重複・不完全な一覧を成功扱いしない。

Jobs応答の `run_attempt` は[GitHubのjob schema](https://github.com/github/rest-api-description/blob/main/descriptions/api.github.com/api.github.com.2022-11-28.json)
では省略可能な項目である（2026-11-12確認）。指定attemptのendpointから取得するため、
jobの当該項目だけは省略を許容する。値があれば整数型と指定attemptとの一致を要求し、
nullや異なる値は拒否する。元Runの最新attempt、jobのRun ID・source SHA、全件照合、
`manual-prepare` の一意性と成功確認は引き続き必須とする。

復号後はhandoffのRun/attempt/driver SHA、元planのSHA-256、30分期限を照合する。
証拠の元バイトと絶対pathを維持し、固定toolingの `publish()` に承認値をそのまま渡す。
fresh snapshot、prepared検証、feed workflow停止、fresh build・E2E、upload直前検査、
canonical照合、承認SHA切替、workflow復帰は既存処理が行う。
Rules/indexesの書換え、別候補への公開、automation=trueへの変更は許可しない。

成功しても **automationはfalseのまま**。元planがfalseの状態で作られているためであり、
公開後の本番受入と定期更新の再開判断は別工程になる。
summaryの `PUBLISHED` とArtifact upload成功を確認し、
`schema431-publish-<Run ID>-<attempt>` の暗号化記録を取得する。
同じ `unpack` コマンドで、新規private storeへ復元できる。
記録には元prepare成果物と `publish-status.json` が入り、fresh checkout・cache・生ログ全体は含まれない。

部分失敗をそのまま繰り返さないため、publish jobの **Re-runは拒否する**。
失敗時は下記のremote stateを確認する。期限切れや状態の変化を、digestの再計算や時刻の編集で回避しない。
公開後は同一originで既存Project・保存内容・同期などの受入を行い、確認後に再開を個別に承認する。

## 失敗時の状態と復旧

失敗後の自動再開・rollbackはない。停止要求の応答が失われた場合は、falseに変わっている可能性がある。

| 状態 | 意味と次の確認 |
| --- | --- |
| `NOT_STARTED` | prepare driverに到達していない。この経路による停止操作はない |
| `automation=UNCHANGED` | この実行による停止要求なし。既に停止中だった場合もあるため `automation_before` と現在値を確認 |
| `automation=UNKNOWN` | 停止を試行したが結果を確定できない。Repository Variableをread-backし、再開を推測しない |
| `automation=CONFIRMED` | falseへの変更とread-backを確認済み。後続失敗でも停止を維持 |
| 暗号化またはArtifact upload失敗 | planの取得成功とは扱わない。平文の退避はしない。残る停止状態を確認し、新規prepareまたは復旧を選ぶ |
| `stage=archive` | 暗号化保存で失敗。`archive_error`は固定の診断コード。診断だけの暗号文を保存できても`BLOCKED`を維持 |
| `cleanup=FAILED` | 暗号文は取得可能な場合があるが、runnerの後始末は完了していない。停止を維持し、runner終了とremote stateを確認 |
| timeout・cancel・runner消失 | 最後のjournal/statusは途中経過。Artifactを取得できない場合もある。必ずremote stateを読み直す |

停止試行後の失敗では、可能な場合にjournalと元証拠だけの暗号化した復旧記録を保存する。
未検証の途中build、provider応答、生ログ全体は保存しない。
失敗した処理の種類と位置は、非公開journalの `failure` に記録する。
固定toolingのMSM生成・Docker image build・隔離build/test・static検査が非ゼロ終了した場合は、
終了コードとstdout/stderrの末尾各16 KiBも記録する。既知の資格情報は切詰め前に除去し、
argv・環境変数・stdinは保存しない。これらの詳細は公開summaryには出さない。
記録は既存の暗号化bundle内に入り、鍵・転送形式・復号手順は変わらない。
timeoutやプロセス起動失敗では出力を取得できない場合がある。診断の取得・保存に失敗しても、
元の失敗状態、暗号化記録の保存、後始末を継続する。
完成成果物を含む暗号化保存に失敗した場合は、証拠・journal・handoffだけの小さい暗号文を試す。
この記録は`prepared=false`、plan digestなしで、planとprepared成果物を含まない。
元の処理失敗と保存失敗は別々にjournalへ残し、公開summaryには許可した固定コードだけを出す。
診断の暗号化も失敗した場合は`archive_recovery_error`を記録する。
publish後の保存失敗では、実際の公開結果と変更状態を記録に保持する。`BLOCKED`だけから
本番未変更とは判断しない。暗号文は一時ファイルへの書込み完了後に確定し、既存結果を上書きしない。
handoffやstatusの書込みに失敗しても、作成済み暗号文のupload条件の通知と平文のcleanupを試行する。
status自体を更新できない場合、summaryは途中の状態のまま残りうる。jobの失敗を無視せず、remote stateを確認する。
強制終了時の平文はephemeralなGitHub-hosted runnerの破棄に依存し、保存完了を保証しない。

復旧では `STATIC_AUTOMATION_ENABLED`、`STATIC_APPROVED_SHA`、両workflowの状態とRun一覧、
canonical、Pages、Rules、設定を読み直す。currentと承認SHAの一致を確認してから、
別途承認された再開か、新規prepareを選ぶ。
既存の[失敗段階別の手順](static_operations.md#wsl-からのアプリ更新-prepare--publish)に従い、
prepareから公開操作へ自動で進めない。publishの失敗後も、自動rollbackや無条件の再開は行わない。
publishのsummaryにはautomation/workflow/production/approved_shaの変更状態が出る。
`UNKNOWN` は要求の結果を確定できていない状態であり、変更されていないことを意味しない。

公開と必要な記録の取得確認後、不要になった転送Secretを削除する。GitHub Secret自体に自動失効はなく、
24時間制限はdriverが検証する転送の期限である。

```sh
gh secret delete STATIC_SCHEMA431_EVIDENCE --repo Yuto-24/NavMate --env static-production
gh secret delete STATIC_SCHEMA431_ARCHIVE_KEY --repo Yuto-24/NavMate --env static-production
```

Artifactは1日で失効する。早期削除は取得・確認後に行う。
ローカルの鍵は必要な暗号化記録を開ける間だけ非公開で保持し、転送ファイルと不要な復号物も整理する。
SecretやArtifactの削除は、既に取得したコピーや鍵を失効させるものではない。

## 検証範囲

provider mockで停止前後の障害、自己Runと他Runの識別、欠落・改変証拠、容量、
暗号文の認証失敗、privateな復旧記録、誤公開経路を検証する。
publish側では取得元のRun/attempt/job、Artifactの一意性と外側ZIP、承認digest、期限、
公開の各段階の失敗、再実行拒否、公開後もautomation=falseを維持することを確認する。
CIでは実際の固定tooling checkoutと実Git sourceを使い、synthetic recordの転送後に
その `reviewed_schema()` が受理し、不正identity・欠落・改変を拒否することを確認する。
これは本番のprivate record、WIF、実build、Artifact保存の運用受入を代替しない。
本番のSecret登録、停止、prepare、publishは実装・PR・テスト中には実施しない。

### #432で確認したCIの権限回帰

[pytest shard 2の失敗](https://github.com/Yuto-24/NavMate/actions/runs/42988397511/job/130415096735)は、
テスト成功後の `.coverage` アップロードで発生した。テストから直接呼ぶ `run()` が
umaskを077に変更したまま戻しておらず、その後に生成するcoverageファイルも0600になった。
Docker内のrootが作るファイルを、ホストのrunnerユーザーが読めなかった。
同じユーザーが作成・読取するローカル検証では、この境界を確認できていなかった。

このdriverでは処理中だけ077を使い、正常終了・失敗・初期化例外のいずれでも元のumaskへ戻す。
回帰テストでは、private成果物が0600を維持することと、処理後の通常ファイルが呼出し元の
権限設定で作成されることを確認する。CI側でcoverageの権限を変更する回避策は追加していない。

### 2026-11-13のprepare失敗で確認した診断の欠落

[Run 43351930429](https://github.com/Yuto-24/NavMate/actions/runs/43351930429)は、
automationの停止確認後に `build-test` で失敗した。暗号化記録のuploadとcleanupは成功したが、
planは生成されていない。`build-test` はMSM生成、Docker build、隔離テスト、成果物検査、
build後のsnapshot照合を含むため、この段階名だけでE2E失敗とは判断できない。

当時のdriverは例外の詳細を保存せず、固定toolingの `command()` も非ゼロ終了時の出力を返さない。
そのため、当該RunのArtifactを復号しても失敗コマンドやstderrは復元できない。
今回の変更では、固定toolingのコードや実行条件を変えず、例外tracebackに残ったその関数の
`CompletedProcess` だけを読み取る。対象は固定したbuildコマンドに限定する。
この診断追加は過去の出力を復元せず、実際のbuild失敗を直したことも意味しない。
原因の特定には、新しいprepareで取得した証拠が必要となる。

### 2026-11-13の再実行で確認した保存案内テストの不一致

[Run 43372389420](https://github.com/Yuto-24/NavMate/actions/runs/43372389420)の
暗号化記録から、static artifact検査25件は成功し、static E2Eは11件中1件が失敗したと確認した。
`static-production.spec.ts` は「容量不足による自動削除」を要求していたが、
候補v2.3.1の本番向け案内は「データ削除・容量不足・プライベートブラウズ終了で失われる」に
変更済みだった。旧文言は共通開発環境の案内にだけ残っていた。
直接の原因は、[v2.3.0の文言変更](https://github.com/Yuto-24/NavMate/commit/c3f68c7f1284debcc8468025ad0e45c68f0eb3a5)に
対して、このテストの期待値が更新されていなかったこと。

テストでは対象モードの保存案内に範囲を絞り、データ削除・容量不足・プライベートブラウズ終了と
データ消失の説明があることを確認する。案内自体やService Worker・APIの検査は変更しない。
通常CIではこのテストを実行していなかったため、既存のLocalブラウザジョブでも同じ1件を実行する。
公開設定や実feedは不要な検査であり、本番成果物に対する全static E2Eは引き続き公開前に行う。
この修正は固定候補 `c717ac6b` には入らないため、mainの更新後に同じprepareを再実行しても解決しない。
候補内のテストを実行時に書き換えたり省略したりせず、新候補の決定と移行証拠の再審査を先に行う。
旧tagや元証拠のidentityを書き換えて修正を取り込まない。

### 2026-11-13に確認したcheckoutとDockerコピーの権限不整合

[Run 43444033782](https://github.com/Yuto-24/NavMate/actions/runs/43444033782)は、
隔離build・テストコマンドの終了後、`seal_build()`から呼ぶ`check_static()`の
`Path.read_bytes()`で`PermissionError`になった。暗号化記録の保存・cleanupは成功したが、
planは生成されなかった。診断には対象ファイル名がないため、その実行で最初に失敗した
ファイル自体は未特定である。

driverのumask 077を継承したGit checkoutは、公開用assetを0600で作る。
候補の`prepare_local.py`は`web/public`を`shutil.copytree()`でコピーするため、
Docker内のroot所有のコピーにも0600が引き継がれる。Viteの`copyFileSync()`は
そのmodeと所有者を保持し、ホストのrunnerは読めない。
当初のテストは`web/static/404.html`と`_headers`の直接コピーだけを再現していた。
Nodeはコピー元のrunner所有も保持するため、この2ファイルだけでは読取失敗にならず、
[CI 43448777492](https://github.com/Yuto-24/NavMate/actions/runs/43448777492)で再現不足が判明した。
回帰テストにはPythonによる公開assetの中間コピーを含め、各段階の所有者とmodeを確認する。
既存のhandoffはfreshnessの追記に必要なファイル・ディレクトリだけ所有者を変更する。
従来のDocker回帰テストは最初から0644のassetを生成しており、checkout由来の0600を検出できなかった。

対処は、privateな親ディレクトリを確認したうえで、固定buildを呼ぶ間だけumaskを022にすること。
候補・tooling・移行証拠のidentity、buildと検証の内容は変更しない。
回帰テストでは実Git checkoutと候補のコピー処理を使い、従来条件での読取失敗と、
prepare・publish両adapterでの非root読取・成果物検証を確認する。
これは固定toolingの全文置換や、検証前の再帰的なchmod/chownを許可する一般ルールではない。

### 2026-11-14に確認した保持feedと暗号化転送上限の不整合

[Run 43564781932](https://github.com/Yuto-24/NavMate/actions/runs/43564781932)は
`stage=build-test`、`archive_status=FAILED`で停止し、Artifactを保存できなかった。
当時は暗号化保存の例外を記録せず、成功したprepareの後もstageが`build-test`のままだった。
したがって、このRunのbuild・E2E成否と、実際に返された保存例外は確定できない。

同日の[本番release inventory](https://navmate.yuto24.com/release.json)は183ファイル、
合計332,950,019バイトだった。[MSM catalog](https://navmate.yuto24.com/weather/msm/catalog.json)の
35 assetだけで301,086,239バイトあり、すべて固定producerの7日保持範囲内だった。
新規生成で置き換わり得る最大3 Runについて、最大サイズの3 assetを差し引いても
260,150,268バイトが残る。気象データだけで旧240 MiB上限を超え、静的アプリや証拠を含む
正当な完成成果物を転送できないことを確認した。

転送の展開後上限を480 MiB、暗号文上限を512 MiBに変更する。固定producerの保持内容、
候補、移行証拠、公開検証を維持し、新上限の超過時も停止する。実行前のActions容量確認は必要である。
回帰テストでは336 MiBの圧縮されにくい合成データを使い、旧暗号文上限も超える成果物の
暗号化・復号・元バイト一致を確認する。容量超過や保存障害では、診断だけの暗号文を保存し、
公開可能なplanとして扱わないことも検証する。この観測を、他の転送上限を一律に増やす規則にはしない。
