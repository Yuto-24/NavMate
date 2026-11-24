# Firestoreで移行証跡を確認する運用

移行証跡を専用のFirestoreで読み、GitHub Actionsでレビューと公開を承認します。
**実環境の初回設定・受入・有効化は未実施です。** この実装の導入だけでは公開しません。
互換性と公開条件の正本は[移行仕様](schema_transition.md#github上の移行証跡と承認)です。

## 初回設定の承認対象

次の実環境変更を一式で提示し、実装PRとは別に承認を得てから行います。
本番・開発プロジェクトには権限を追加しません。実際のプロジェクトID、本人のGoogleアカウント、
サービスアカウント、WIF providerの完全名と既存条件、変更前後のIAM bindingを非公開の操作記録に残します。
以下のプレースホルダーを実値で確定できない場合は設定しません。

| 対象 | 設定する内容・権限 |
| --- | --- |
| 新しい証跡専用Firebaseプロジェクト | 本番・開発とは別のID。課金先をリンクせず、Firestore **Standard / Native modeの`(default)` DBを1個だけ**作成。所在地は作成前に本人が決めます。 |
| 専用サービスアカウント | 証跡プロジェクトに新設し、そのプロジェクトだけの`roles/datastore.user`を付与。IAM・Rules変更権限や本番・開発のdata権限は付与しません。鍵ファイルは作りません。 |
| 本人のGoogleアカウント | 初期の閲覧者は本人だけ。データ閲覧は証跡プロジェクトの`roles/datastore.viewer`を基準に、Firebase Consoleのプロジェクト表示に必要な読取権限を導入時に確認します。追加権限が必要なら対象を示して承認し、既存DBの管理権限を流用しません。作成時のOwner権限と日常閲覧権限は区別して記録します。 |
| 専用SAのWIF binding | 既存providerで認証するGitHub principalに、そのSAだけの`roles/iam.workloadIdentityUser`。既存の本番Rules読取SAは変更しません。 |
| クライアントRules・indexes | 証跡DBにだけ`firebase/migration-evidence.rules`の全面拒否と、`firebase/migration-evidence.indexes.json`の原本・表示フィールドのindex除外を適用。アプリの`firebase.json`は使用しません。 |
| GitHub変数 | 下表を設定。有効化変数は受入完了まで`false`。既存環境保護・レビュー要件を維持。 |

[無料枠](https://firebase.google.com/docs/firestore/pricing)は1プロジェクトに1個のDBが対象です。
TTL削除は課金が必要なため使用しません。無料枠超過・API障害・保存不能時は停止し、別の保管先へ切り替えません。
Webアプリ、Firebase Authentication、Cloud Functions、独自の閲覧サーバーは追加しません。

### WIFとIAMの確認順

1. 既存の`STATIC_GOOGLE_WORKLOAD_IDENTITY_PROVIDER`のattribute mappingとcondition、
   本番Rules読取SAのbindingを読み取りで確認します。新SAへ引き継ぐ対象は認証境界だけです。
2. 条件がrepository ID `1314030412`、owner ID `65487096`、`refs/heads/main`、
   `Yuto-24/NavMate/.github/workflows/static-app-release.yml@refs/heads/main`、
   `repo:Yuto-24/NavMate:environment:static-production`を満たすことを確認します。
   providerを緩和したり、repository名だけの無制限なbindingへ変更したりしません。
3. mappingに対応した、既存pool内のrepository IDに限定するprincipalSetを新SAの
   Workload Identity Userに追加します。たとえば`attribute.repository_id`を使用している場合は
   `principalSet://iam.googleapis.com/projects/<WIF_PROJECT_NUMBER>/locations/global/workloadIdentityPools/<POOL>/attribute.repository_id/1314030412`です。
   mappingや既存条件が上記と異なる場合は停止し、差分を確認してから別途判断します。
4. 新SAが持つdata権限を証跡プロジェクトの`roles/datastore.user`だけに限定し、継承された
   組織・folder権限も確認します。本番・開発DBの既存権限を新SAへ追加しません。
5. 承認された設定担当の権限で、専用プロジェクトにだけRulesとindex除外を適用します。
   `firebase deploy --project <EVIDENCE_PROJECT_ID> --config firebase.migration-evidence.json --only firestore:rules,firestore:indexes`
   は**初回設定の別承認後に実行するコマンド**です。workflowのSAにはこの権限を与えません。

### GitHub設定

既存の`VITE_FIREBASE_PROJECT_ID`を全工程で照合し、本番プロジェクトIDが未設定、
または証跡先と同一なら受入操作も含めて停止します。
下表のvariableはGitHubの**repository variables**に設定します。特に有効化フラグは
job開始前の条件式で使うため、environmentだけに設定しません
（[GitHubの変数の適用時点](https://docs.github.com/en/actions/reference/workflows-and-actions/variables)）。
secretは既存の保護された設定範囲を維持し、jobには`static-production`環境を指定します。
次の値は公開Summaryに出しません（管理画面リンクに含まれる証跡プロジェクトIDを除く）。

| 名前 | 用途 |
| --- | --- |
| `STATIC_MIGRATION_EVIDENCE_PROJECT_ID` variable | 証跡専用FirebaseプロジェクトID。アプリの本番・開発IDは禁止。 |
| `STATIC_MIGRATION_EVIDENCE_SERVICE_ACCOUNT` variable | 上記プロジェクトに属する専用SAのメールアドレス。 |
| `STATIC_MIGRATION_EVIDENCE_ENABLED` variable | 最初は`false`。合成データの実環境受入後だけ`true`。 |
| `STATIC_MIGRATION_ARCHIVE_KEY` secret | 既存32 byte鍵のbase64を継続使用。生成証跡の認証とprepare Artifactの暗号化に使用。 |

`STATIC_MIGRATION_REVIEW_REPOSITORY`と`STATIC_MIGRATION_REVIEW_TOKEN`は廃止します。
旧Issueやコメントの内容は自動移行・削除せず、新証跡を生成してください。
既存の`STATIC_APP_RELEASE_GH_TOKEN`、prepareの`STATIC_CLOUDFLARE_READ_TOKEN`、publishの
`CLOUDFLARE_PAGES_TOKEN`、本番Rules読取WIF設定は維持します。
撤回・保持整理・合成データ受入jobにはこれらの本番操作用tokenとRules読取SAを渡しません。
証跡の短期認証は長時間処理後も必要時に更新し、候補buildへ渡しません。

## 合成データでの実環境受入

設定作業の承認後、`STATIC_MIGRATION_EVIDENCE_ENABLED=false`のまま、
[static-app-release](https://github.com/Yuto-24/NavMate/actions/workflows/static-app-release.yml)の
**Run workflow**で`main`、`acceptance-migration`を本人が選びます。
この操作は合成証跡・サンプル・planを保存して読み戻すだけで、公開も天気停止も行いません。
署名と成功した本来の証跡Runを持たないため、公開承認には使用できません。

- 本人の既存GoogleアカウントでSummaryのFirebase Consoleリンクを開きます。
  `migrationRecords`の記録IDとSHA-256を照合し、`original_json`と`display`を読みます。
  `-sample`文書でサンプル全体、`-plan`文書で改行を含む正確なplan原本を読み、
  親記録の`sample_sha256`／`plan_sha256`と一致することを確認します。
- `display`の配列は`[000000]`から始まる添字mapです。省略や圧縮はせず、
  各要素を標準画面で展開します。JSON原本も残るため型と順序を確認できます。
- 未許可のGoogleアカウントと未認証クライアントからの読書きを拒否することを確認します。
  未許可アカウントの利用は本人が同意して管理するテスト用アカウントで行います。
- 新SAの短期認証で、本番・開発DBの既知の合成文書へのGETが拒否されることを確認します。
  文書を列挙・作成・変更せず、成功時は直ちに停止してIAMを見直します。
- GitHub repositoryの可視性とは無関係に、アクセスがFirebase IAMで決まることを確認します。
  公開リポジトリの可視性はこの受入のために変更しません。

正確なplanとサンプルを標準画面で読めない、拒否されるべきアクセスが通る、または
IAM・プロジェクト作成可否を確認できない場合は**有効化しません**。
受入者、日時、tooling SHA、合成記録ID・hash、許可／拒否の結果を非公開の操作記録に残します。
その後、別途承認された有効化として`STATIC_MIGRATION_EVIDENCE_ENABLED=true`にします。
受入用の未完了記録は日次削除されません。必要な保存と処分は初回設定の承認範囲で個別に判断します。

## 詳細確認から公開まで

`main`を選び、以下の工程で同じtooling SHAを使います。mainが進んだ場合は証跡を再生成します。
初期のレビュー・承認・撤回の操作者は本人のGitHubアカウント`Yuto-24`に限定します。

1. **証跡を読む。** VERSION更新のpublisherがMANUALと判定すると、両方の有効化設定が
   `true`の場合だけ証跡を生成します。手動生成は`evidence-migration`と候補SHAを指定します。
   Summaryから[Firebase標準画面](https://firebase.google.com/docs/firestore/using-console)へ移動し、
   記録ID、原本と表示、サンプル、各検証結果と限界、候補・現行・tooling・設定を照合します。
   PASSはテスト結果であり独立レビューの完了ではありません。
2. **レビューを承認してprepareする。** `prepare-migration`の`migration_record_id`へ
   `r<Run ID>-a<attempt>-evidence`、`reviewed_record_sha256`へその記録のSHA-256を入力します。
   既存gateを確認した後に天気更新を停止し、prepareします。
3. **planを読んで公開を承認する。** prepare RunのSummaryから新しい`prepared`記録と
   `-plan`原本を読みます。`publish-migration`に**prepared記録のIDとハッシュ**を入力します。
   このdispatchが最終公開承認です。plan作成から30分以内に既存の期限検査を通る必要があります。

入力名は従来のままですが、Issue番号・コメントIDは拒否します。証跡は生成から24時間以内です。
1組の証跡ではprepareとpublishをそれぞれ1回だけ開始できます。失敗・期限切れ・中断後は
新しい証跡と承認が必要です。元データを上書きしません。
原本・表示・添付文書の欠落や改変、900 KiBの文書上限超過、確認できない保存結果では停止します。

公開は既存の`static-production`排他、fresh build・テスト、予報鮮度、本番Pages照合、
承認SHA更新、GitHub Release作成・照合を通ります。候補・現行・tooling・設定・Rulesと
継続中の承認が一致する場合だけ、天気更新を元の状態に戻します。元が停止中なら停止を維持します。
prepareのArtifactは従来どおり暗号化済みのものだけを1日保持します。
公開ログ・Summary・通常Artifactへ証跡、設定、例外本文を出しません。

## 撤回・失敗・保持

中止する場合は`revoke-migration`に対象の証跡またはprepared記録IDとhashを入力します。
有効化変数を`false`に戻しても撤回できます。公開処理の排他キューには入れませんが、
GitHub環境承認やrunnerの起動待ちはあります。撤回はその証跡一式へ永続的に適用し、
新しい証跡でのみ再承認できます。実行済みの公開を巻き戻す操作ではありません。
公開直前・再開直前などの既存境界で撤回を再確認し、未開始の次の処理を止めます。

**Re-run jobsは使いません。** 失敗記録のstageとUNKNOWN／CONFIRMEDを管理画面で読み、
[既存の復旧手順](static_operations.md)でPages・承認SHA・天気状態を照合します。
期限切れでも自動で天気を再開しません。書込応答が不明なら既知IDの原本を読み戻して確認し、
書込は再送しません。確認不能時は停止します。

日次jobは成功・最終照合済みで未完了の関連処理がない一式だけを、完了から30日後に削除します。
削除直前も同じトランザクションで状態を確認します。失敗・未完了・不明・撤回の記録は自動削除しません。
scheduleは通常公開を起動しません。容量不足は停止条件であり、これらの記録の削除理由にはしません。

## 実装検証と残る受入

エミュレーターによる契約検証は`tests/unit/test_migration_firestore.py`、公開処理との接続は
`tests/unit/test_migration_release.py`で検証します。エミュレーターの認証は本番IAMの証明にはなりません。
ローカル検証、独立レビュー、Hosted CI、合成データの実環境受入、本番公開は別の完了条件です。
本実装PRは実環境設定、有効化、v2.6.0公開、本番デプロイ、マージを含みません。
