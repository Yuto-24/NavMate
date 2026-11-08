# Local版のDocker起動と自動更新

`compose.local.yaml` は、本番と同じ `build:static` の配布物をローカルで配信する構成です。
計算・Project保存はブラウザ内で行い、mainとMSMは別コンテナで自動更新します。
ルートの `compose.yaml` は引き続きLegacy版です。

## 初回準備

Docker EngineとCompose v2を用意します。NodeやPythonをホストへインストールする必要はありません。
Git管理外の `.env.local-static` に、既存環境と同じ公開Web設定を記載します。

```dotenv
VITE_FIREBASE_API_KEY=your-public-web-api-key
VITE_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your-project
VITE_FIREBASE_APP_ID=your-web-app-id
VITE_TAF_PROXY_URL=https://autonavlog-taf.utomatsu.workers.dev/taf
VITE_LEGACY_MIGRATION_URL=https://your-legacy-host
```

Firebase Web API keyは公開識別子です。管理token、service account、Git認証情報は記載しません。
既存のFirebase・TAF設定は変更しません。利用するoriginが各設定で許可されている必要があります。

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

## dev環境だけでProjectを共有する（任意）

GoogleログインなしでPC・スマートフォンから同じProjectを開く場合は、
`compose.local-shared.yaml` を追加します。通常の `compose.local.yaml` だけなら、
従来どおりブラウザ保存・Google同期です。本番Pagesの配布物・Firestoreは変更しません。

```bash
docker compose -f compose.local.yaml -f compose.local-shared.yaml up -d --build --wait
```

共有版のコードを含むアプリが配信されていることが前提です。Web配信コンテナと
アプリの両方を更新してください。起動しただけでは古いアプリに共有保存は追加されません。
共有時はヘッダーが「サーバー保存」になり、アカウント操作を表示しません。
別端末では同じURLを開き、保存済み一覧からProjectを選んで開きます。
Projectの作業内容、保存時点、最後の計算結果を共有し、計算は引き続きブラウザで行います。
新しいタブでの自動選択やリアルタイム共同編集は行いません。

**このモードに認証はありません。アクセスできる人は共有Projectを読み書き・削除できます。**
URLを他人に知らせていないことはアクセス制限ではありません。許可するoriginは
`LOCAL_SHARED_ORIGINS` に列挙します。これは他サイトからのブラウザ要求を制限する設定で、
ログインや利用者の認証にはなりません。公開先を変える際は設定も確認してください。

- 保存先はComposeの `local-projects` ボリューム内のSQLiteです。配布物の更新・再作成から独立し、
  コンテナ再起動後も保持します。保存先を静的公開ディレクトリに置かないでください。
- 初回は、そのブラウザの**未ログインで作ったProjectだけ**を共有先へコピーします。
  端末内の元データは削除・更新しません。アカウント所有のデータは取り込みません。
  同じIDが共有先で更新済みなら上書きせず、一覧に一部読込不可の警告を出して元データを保持します。
- 取込済みの記録はサーバー側に保持し、共有先で削除したProjectを同じブラウザの元データから復活させません。
  通常版と共有版のタブ復元情報も分け、切替時に古い編集中データを共有先へ書き戻しません。
- 一覧・読込・保存にはサーバー接続が必要です。通信失敗時に端末保存へ黙って切り替えません。
  通信断の前に成功したサーバー保存は保持しますが、保存完了していない編集の保持は保証しません。
- この環境全体を1つの作業場所として扱い、自動保存だけのProject（Latest）は共通の1枠です。
  続きを残したいProjectは名前を付けて保存してください。端末を替える前に保存完了を確認します。
  古い状態からの更新は拒否するため、開いたままの端末へ戻る際はProjectを開き直してください。

停止するときも同じComposeファイルを指定し、ボリュームは削除しません。

```bash
docker compose -f compose.local.yaml -f compose.local-shared.yaml stop
```

通常版へ戻す場合は、共有overrideを外してWebを再作成します。共有ボリュームは残りますが、
共有後の変更が各ブラウザの元データへ逆同期されるわけではありません。

Codex worktreeで試す場合は先に `scripts/codex/setup_worktree.sh` を実行し、
生成されたプロジェクト名・ポート・専用ボリュームを使います。
主環境の8123番や保存ボリュームを使わないでください。検証後は専用runtimeを停止します。

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
今回の切替でIndexedDBの移行や再取込みは行いません。

復旧が必要なら更新サービスと新Webを停止し、保持してある旧Compose構成で旧Webを起動します。
ブラウザの保存領域は巻き戻しません。保存形式が変わった版から戻す場合は互換性を先に確認します。
旧配布物のMSMが失効している場合、旧Webの起動だけではFORECASTは復旧しません。

この構成はローカル用です。本番Pagesの公開・自動更新設定、DNS、Firebase Rulesは変更しません。
