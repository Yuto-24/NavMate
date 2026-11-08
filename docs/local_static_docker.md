# Local版のDocker起動と自動更新

`compose.local.yaml` は、`build:static -- --local-runtime` の配布物をローカルで配信する構成です。
計算・Project保存はブラウザ内で行い、mainとMSMは別コンテナで自動更新します。
ルートの `compose.yaml` は引き続きLegacy版です。

## 初回準備

Docker EngineとCompose v2を用意します。NodeやPythonをホストへインストールする必要はありません。
Git管理外の `.env.local-static` に、気象取得用の公開Web設定を記載します。

```dotenv
VITE_TAF_PROXY_URL=https://autonavlog-taf.utomatsu.workers.dev/taf
```

通常のLocal DockerはFirebase認証・Firestore同期・Legacyアカウント移行に接続しません。
既存の環境変数や `.env` にアカウント設定が残っていても、通常のローカル配布物から除外します。開発用の共有設定は後述のoverrideで有効化します。
管理token、service account、Git認証情報は記載しません。TAFの利用originは許可が必要です。
本番Pagesは従来のFirebase設定を使用し、ローカル配布物は本番用の検査では拒否します。

```bash
docker compose -f compose.local.yaml up -d --build --wait
```

初回は実MSM取得とブラウザ検証を行うため時間がかかります。完了前のWebは503を返します。
初回準備にwaitの上限がある環境では `--wait-timeout 3600` を追加します。
以降の再起動では最後の配布物を読み込み、裏側で更新を再開します。

Web配信だけがWSL host networkの8123番を使用し、Windowsから `http://localhost:8123/`、
既存Tunnel経由では `https://dev-navlog.yuto24.com/` を開きます。
localhostとdevでは保存領域が別です。普段使うブラウザ・URLを維持し、サイトデータを消去しないでください。
Git同期と更新処理は通常のコンテナネットワークで動かし、検証用サーバーは更新コンテナ内のloopbackだけに置きます。

## 開発用FirestoreでProjectを共有する（任意）

開発環境は既存の **NavMate-dev（`navmate-6b281`）** を使い、本番の
`navmate-prod` と分離します。未ログイン時はブラウザがFirebaseの匿名認証を自動で行い、
共通の `devWorkspaces/shared/projects` を既存のFirestore同期処理で利用します。
ヘッダーの「アカウント」からGoogleでログインすると、同じ開発用DBの個人領域へ切り替わります。
ログアウトすると共通Projectへ戻ります。開発用のGoogleログイン・アカウント同期・削除を検証できます。
SQLite・専用保存API・管理者の認証情報は使いません。

**開発環境を利用できる人は、共通のProjectを編集・削除できます。**
匿名認証は利用者を限定するアクセス制限ではありません。個人のGoogleアカウントの保存領域とは
分けていますが、共有するデータだけを置いてください。

### Firebase側の準備

2026-11-08の読み取り確認では、開発用Webアプリと `(default)` Firestore DBが存在し、
匿名認証・Google認証・共有領域のRulesは設定済みでした。個人用の世代管理Rulesは未反映でした。
設定変更前に対象プロジェクトと稼働中Rulesを再確認してください。

1. `navmate-6b281` のAuthenticationで匿名認証とGoogle認証を有効にし、利用するdevホストを
   承認済みドメインに含めます。Google認証の詳細は[認証ガイド](authentication.md)を参照してください。
2. `firebase/firestore.dev.rules` を開発用DBに反映します。Google個人領域のRulesは本番と同じ
   アカウント世代・削除の契約を使い、匿名認証向けの共有領域を追加しています。
   以前の共有専用構成から更新する場合も、アカウント文書と世代別ProjectのRulesが必要です。
   反映前に稼働中Rulesとの差分を確認します。

   ```bash
   firebase deploy --config firebase.dev.json --only firestore:rules --project navmate-6b281
   ```

遠隔の認証設定とRulesの変更は、実装PRとは別に承認して実施します。本番の
`firebase/firestore.rules` と既存の本番用デプロイ手順は変更しません。
Rulesは匿名認証の発行先が `navmate-6b281` の場合だけ共有領域を許可します。

### Local Dockerの設定

Git管理外の `.env.dev-shared` に、NavMate-dev Webの公開設定を記載します。
専用の変数名を使い、本番用の設定を引き継ぎません。

```dotenv
VITE_DEV_FIREBASE_API_KEY=development-web-api-key
VITE_DEV_FIREBASE_AUTH_DOMAIN=navmate-6b281.firebaseapp.com
VITE_DEV_FIREBASE_PROJECT_ID=navmate-6b281
VITE_DEV_FIREBASE_APP_ID=1:97279151816:web:b151fe8f89650850f75ffd
```

```bash
docker compose -f compose.local.yaml -f compose.local-shared.yaml up -d --build --wait
```

updaterが開発用設定でアプリを作成します。ビルドと起動処理は本番Project IDの指定を拒否し、
Legacyアカウント移行にも接続しません。設定の切替時は同じmainのSHAでも再ビルドします。
新しい配布物への更新完了後、開いていたタブを再読み込みしてください。
通常の `compose.local.yaml` だけなら端末内保存となり、本番DBへ自動では接続しません。

### 保存と端末の切替

- 保存はまずブラウザ内に行い、開発用Firestoreへ同期します。同期済みのProjectと最後の計算結果を、
  別端末でも保存済み一覧から選んで開けます。新しいタブでの自動選択やリアルタイム共同編集は行いません。
- 通信断の間は未同期の変更を端末内に保持し、接続復帰後に再試行します。端末内の保存成功は
  同期完了を意味しません。競合時は既存の選択画面で採用する内容を選びます。
- 既存の未ログインProjectは、既存の同期機能と同じ手順で共有用の端末内保存領域へ取り込みます。
  元データは取込先の印を付けて保持され、未ログイン一覧からは非表示になります。
  Googleアカウント所有のProjectは取り込みません。同期の削除記録により、削除済みProjectを再取込で復活させません。
- Googleログイン時は共通Projectや未ログイン領域を個人領域へ自動取込しません。個人のProjectは
  同じGoogleアカウントでログインした端末間だけで同期されます。アカウント削除後も共通Projectは残ります。
- 個人用の端末内DB・編集セッション・地図表示・認証キャッシュは開発用に分離します。過去にこのURLを
  本番設定で使っていた場合のアカウントデータは取り込まず、そのデータを開発用の削除処理で消しません。
- 自動保存のLatestは端末ごとです。別端末で再開するProjectには名前を付けて保存してください。
  開いている編集内容を他端末の変更で自動置換しません。別端末の保存後は一覧から開き直します。

停止も同じComposeファイルを指定します。共有overrideを外して再作成しても、開発用Firestoreと
共有用のブラウザ保存領域は削除しません。共有側の変更は通常の未ログイン領域へ逆同期されません。

```bash
docker compose -f compose.local.yaml -f compose.local-shared.yaml stop
```

Codex worktreeでは先に `scripts/codex/setup_worktree.sh` を実行し、専用プロジェクトとポートを使います。
自動テストは `firebase.dev.json` のAuth・Firestoreエミュレーターだけへ接続します。
検証用runtimeは終了時に停止し、実DBと主環境の保存データは操作しません。
自動更新時のStaticブラウザ検査も共有設定を引き継ぎますが、Firebase通信を遮断し、
共有用の端末内保存領域を検証します。実際の同期とRulesはエミュレーターで別に確認します。

## 自動更新の動作

- `source` はgit-sync **v4.8.0**でmainを5分ごとに取得します。ホストのcheckoutには書き込みません。
- `updater` はcommitごとの専用領域で、バージョン・データ・schema・型・配布物・Staticブラウザ検査を実行します。
  新しいcommitが途中で到着した場合、その時点で古くなった候補は配信しません。
- MSMは起動時と1時間ごとに確認し、新しい完全なRunがある場合に取得・生成します。
  配信中のアプリSHAからMSMを同梱して再ビルドします。mainの失敗時も、このMSM更新は独立して続きます。
- 検査が成功した配布物だけを、ディレクトリのポインタ交換で切り替えます。
  Webコンテナの再作成やブラウザの強制再読み込みは行いません。
- 失敗は15分後に再試行し、1処理は45分で打ち切ります。失敗した候補で現在の配布物を置き換えません。
  現行と直前の配布物、7日以内のMSM Runを保持します。

MSMカタログの期限は生成から6時間です。更新が止まって失効するとFORECASTは停止しますが、
保存済みProject・Last CalculationとFTDは維持されます。再起動で期限を延長することはありません。
配布物のhash、Run、coverage、期限検査は本番と同じ既存処理を使い、省略しません。

mainの自動更新対象はアプリです。Compose、Python、Node、git-sync、更新処理自体の変更は、
ホスト側のcheckoutを更新して上記の `up --build` を再実行します。
イメージは固定tagを使い、勝手に新しい基盤へ追随しません。

## 状態・ログ・停止

```bash
docker compose -f compose.local.yaml ps
docker compose -f compose.local.yaml logs -f updater
docker compose -f compose.local.yaml stop
```

`web` のhealthcheckは `/release.json` の配信を確認します。`updater` はheartbeatとMSMの期限を確認します。
MSMが失効してもWebを停止させず、FTDと保存済み計算を利用できる状態を保ちます。
`/healthz` やLegacyの `/api/` は提供しません。

更新ログの `published` に配信SHA・Run・期限が記録されます。`update_failed` の詳細ログは
更新コンテナの `/state/logs/` に直近10件を保持し、Webには公開しません。
main更新を一時停止する場合は `source` と `updater` を停止します。この間はMSMも更新されません。

```bash
docker compose -f compose.local.yaml stop source updater
```

更新用のsource・state・publishedボリュームは、Legacyの `autonavlog-data` と別です。
停止・更新で `down -v` を使わず、既存のLegacy volumeと移行バックアップも保持します。

## 既存8123番からの切替と復旧

現在のWebを起動したまま、まず `source updater` だけを起動します。
候補が `published` になった後で現在のWebを停止し、新しい `web` を起動します。
候補の初回生成中に現在の8123番を止める必要はありません。

切替後はdev URLの `/release.json`、MSM期限、普段のWindowsブラウザの保存済み一覧と計算結果を確認します。
通常モードへの切替ではIndexedDBの移行や再取込みは行いません。
共有モードを有効にする場合は、前述の未ログインProjectの取込が行われます。

復旧が必要なら更新サービスと新Webを停止し、保持してある旧Compose構成で旧Webを起動します。
ブラウザの保存領域は巻き戻しません。保存形式が変わった版から戻す場合は互換性を先に確認します。
旧配布物のMSMが失効している場合、旧Webの起動だけではFORECASTは復旧しません。

この構成はローカル用です。本番Pagesの公開・自動更新設定、DNS、本番Firebase Rulesは変更しません。
