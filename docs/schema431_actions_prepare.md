# #431: GitHub Actions で v2.3.1 の手動 prepare を実行する

`static-app-release` の `operation=prepare-schema431` は、固定した Schema 4→5 移行を
検証し、定期更新を一時停止して、既存の手動 `prepare` を実行する。
成功時は plan と後工程に必要な成果物を暗号化して保存する。
**publish は別途、正確な plan SHA-256 への承認を必要とする。この操作に公開機能はない。**

この文書と実装の追加は、本番停止・prepare の実施記録ではない。
実行前に、対象の操作窓と停止・prepare の承認を確認する。
実行方式と固定条件は [Issue #431](https://github.com/Yuto-24/NavMate/issues/431)、
移行の検証内容は [Schema 4→5 の記録](forecast_schema_transition.md) を正本とする。

## 維持する境界

| 対象 | 条件 |
| --- | --- |
| 操作 | `workflow_dispatch`、`main`、`prepare-schema431`、空の `release_id` の組合せだけ |
| Google WIF | 既存の Repository/Owner ID、`environment:static-production`、`static-app-release.yml@refs/heads/main` の制限を維持。scope は `firebase.readonly` |
| GitHub | 既存の `STATIC_APP_RELEASE_GH_TOKEN`。新しい権限は要求しない |
| Cloudflare | 既存の `STATIC_CLOUDFLARE_READ_TOKEN`。Pages upload token は渡さない |
| current | `03cc463cf09192e1403f839df4165410c5db8d7b`（v2.2.2） |
| candidate | `c717ac6baaa3d7556120d2a7f6c9435f165f132b`（v2.3.1） |
| 移行tooling | `64225b82c9b2e978409f0b35490be3c83af3f157` の clean checkout |
| `SCHEMA_RECORD` の元バイトSHA-256 | `d384f6619038a2b55a30abf6b08ecd88d9d7aede5292963414fd52d433f9be4d` |

main 上のdriverは、別checkoutの固定toolingをimportして使う。
`reviewed_schema()`、互換性検査、snapshot、隔離build・E2E、plan生成は固定toolingの実装を使い、
移行記録のtooling SHAを書き換えない。新しいdriverのSHAは暗号化したhandoff記録に残る。
通常の自動Release、`replay-release`、`readback` の条件は変更しない。

## 1. 非公開証拠を転送用Secretにまとめる

WSLにある次のファイルを使う。記録の再作成や整形はしない。

- `/home/yuto/autonavlog-releases/schema4-5-v2.3.1-20261111/SCHEMA_RECORD.json`
- その記録が参照する `old_to_new`、`old_writer_coexistence`、`storage_sync_roundtrip` の3報告

このPRを含むレビュー済みcheckoutから、既存のPython環境で実行する。
packはPython標準ライブラリだけを使い、Node.jsやCloudflare/Google認証は不要。

```sh
umask 077
transfer_dir="/home/yuto/autonavlog-releases/schema431-transfer-$(date -u +%Y%m%dT%H%M%SZ)"
python scripts/static_ops/schema431_bundle.py pack \
  --schema-record /home/yuto/autonavlog-releases/schema4-5-v2.3.1-20261111/SCHEMA_RECORD.json \
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
| 暗号化成果物 | 1実行につき最大256 MiB、格納ファイルの合計は240 MiB・25,000件まで |
| Actions Artifact | 暗号文だけを1日保持。通常Artifactを秘密保管先とは扱わない |
| plan | 既存どおりprepare終了時刻から30分。Artifactの保持期限とは別 |

実行前に既存の[plan/limits・共有容量確認](static_operations.md#quota-evidence-and-monitoring)
を行い、最大256 MiBのArtifactを保持できる余裕を確認する。
コードの容量制限はGitHub側の利用可能残量を保証しない。
上限超過や保存失敗を平文Artifactで回避しない。
Secretが収まらない場合は停止前の不足条件として扱い、証拠を削ったりhashだけに置き換えたりしない。

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
2. 固定v2.3.1のRelease/tag/VERSIONと、既存の[候補CI](https://github.com/Yuto-24/NavMate/actions/runs/42821632575)
   の成功を再確認する。canonical/approved/config、environmentのshadowing、Pages全inventory、
   稼働Rules、workflowのactive/idle、現在のautomationを読み取る。
   3報告を含む元証拠を固定toolingの `reviewed_schema()` で実際に受理できることも必須。
3. 直前のsnapshotを再照合してから、automationがtrueならfalseへ変更し、APIでread-backする。
   既にfalseの場合はその状態を保つ。workflowはactiveのままにする。
4. 停止後snapshotで、automation以外に変化がないことを確認する。
   schema付きの通常Operatorで既存 `prepare()` を呼び、隔離build、E2E、成果物検査、再照合を行う。
5. plan、journal、元証拠、`prepared/upload`、`prepared/feed-report.json`をAES-256-GCMで
   暗号化して保存する。candidate checkout、node_modules、cache、資格情報、生ログは含めない。
   通常終了時はrunner上のこの実行が作った平文を削除する。

固定buildは一部の生成物をroot所有のまま残すため、runner権限で削除できない場合がある。
暗号化成果物の引き渡しを先に確定し、通常削除が権限不足になった場合だけ、
この実行が新規作成したprivate storeを `sudo -n` で削除する。
対象pathを固定し、provider資格情報は渡さない。削除に失敗しても暗号文のuploadは試行する。

停止前の読み取りだけは、schema付き互換性検査を委譲した別Operatorでautomation=trueを観測できる。
公開設定をfalseと偽って読み替える処理ではない。
実prepareでは、固定toolingが要求する `STATIC_AUTOMATION_ENABLED=false` をそのまま検証する。

## 3. planを非公開で確認する

Actionsのsummaryには処理段階、停止状態、暗号化保存とuploadの結果、成功時のplan SHA-256だけが出る。
`PREPARED`だけでなくArtifact uploadの成功も確認する。
`schema431-<Run ID>-<attempt>` Artifactから `.aesgcm` ファイルを取得する。
保存・失効の挙動は[GitHub公式のArtifact仕様](https://docs.github.com/en/actions/tutorials/store-and-share-data)に従う。

WSLで、pack時に保持した `archive.key` と同じ鍵を使う。
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
このPRはpublish経路を追加しない。別途承認した後工程でも既存の認証・公開ゲートを満たす必要がある。

`within_plan_window=false`、30分超過、設定・Rules・source・tooling・証拠の変化、
既存feed鮮度条件の失敗があれば、そのplanは公開に使えない。
時刻を書き換えず、新しい操作窓でfresh preflightから新規prepare・レビューを行う。
有効な元証拠のidentityまで変わった場合は転送の作り直しだけでは足りず、証拠の再審査が必要。

## 失敗時の状態と復旧

失敗後の自動再開・rollbackはない。停止要求の応答が失われた場合は、falseに変わっている可能性がある。

| 状態 | 意味と次の確認 |
| --- | --- |
| `NOT_STARTED` | prepare driverに到達していない。この経路による停止操作はない |
| `automation=UNCHANGED` | この実行による停止要求なし。既に停止中だった場合もあるため `automation_before` と現在値を確認 |
| `automation=UNKNOWN` | 停止を試行したが結果を確定できない。Repository Variableをread-backし、再開を推測しない |
| `automation=CONFIRMED` | falseへの変更とread-backを確認済み。後続失敗でも停止を維持 |
| 暗号化またはArtifact upload失敗 | planの取得成功とは扱わない。平文の退避はしない。残る停止状態を確認し、新規prepareまたは復旧を選ぶ |
| `cleanup=FAILED` | 暗号文は取得可能な場合があるが、runnerの後始末は完了していない。停止を維持し、runner終了とremote stateを確認 |
| timeout・cancel・runner消失 | 最後のjournal/statusは途中経過。Artifactを取得できない場合もある。必ずremote stateを読み直す |

停止試行後の失敗では、可能な場合にjournalと元証拠だけの暗号化した復旧記録を保存する。
未検証の途中buildや生ログは保存しない。
強制終了時の平文はephemeralなGitHub-hosted runnerの破棄に依存し、保存完了を保証しない。

復旧では `STATIC_AUTOMATION_ENABLED`、`STATIC_APPROVED_SHA`、両workflowの状態とRun一覧、
canonical、Pages、Rules、設定を読み直す。currentと承認SHAの一致を確認してから、
別途承認された再開か、新規prepareを選ぶ。
既存の[失敗段階別の手順](static_operations.md#wsl-からのアプリ更新-prepare--publish)に従い、
この経路からworkflow enable/disable、承認SHA変更、Rules書換え、Pages deployは行わない。

取得確認後、不要になった転送Secretを削除する。GitHub Secret自体に自動失効はなく、
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
CIでは実際の固定tooling checkoutと実Git sourceを使い、synthetic recordの転送後に
その `reviewed_schema()` が受理し、不正identity・欠落・改変を拒否することを確認する。
これは本番のprivate record、WIF、実build、Artifact保存の運用受入を代替しない。
本番のSecret登録、停止、prepare、publishは実装・PR・テスト中には実施しない。
