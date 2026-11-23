# One-way Project schema publication

初回の `RouteNode.reference_snapshot` 追加（IndexedDB 1→2）と、[AIP出典拡張（IndexedDB 2→3）](#aip出典拡張の手動公開indexeddb-23)に関する手動公開契約です。以下の初回移行の条件・証跡は、後続のAIP移行へ流用できません。v2 系の Schema 4→5 移行は [forecast_schema_transition.md](forecast_schema_transition.md) を参照してください。

This is a manual, separately authorized transition, not an automatic publication
exception. Ordinary and automated releases still require identical schema/index
blobs and Rules bytes. This document covers the optional
`RouteNode.reference_snapshot` plus its two new definitions; all prior fields,
types and required constraints must remain identical. Index changes stay blocked.
The separately reviewed [Project schema 4 → 5 forecast transition](forecast_schema_transition.md)
uses the same manual prepare/publish receipts with its own exact difference and
coexistence evidence. It does not use or weaken the reference-snapshot writer fence
described below.

## Two distinct migrations

`https://navlog.yuto24.com` to `https://navmate.yuto24.com` is the existing Legacy
account activation. Reuse its owner lock, `NAVMATE_ACTIVE`, server-side 423 rejection,
303 navigation redirect and polling redirect. Confirm actual public configuration
and behavior during authorized acceptance; repository defaults and local WSL
settings do not establish that it is active on the public Legacy host.

The same-origin NavMate 1.20.1 `a4de2a226dfa205b8be42fb62a710a1b06271ed8` to the
selected fixed 1.x application is a separate update. Legacy redirect does not retire
an already open NavMate tab. Older code can tombstone an unreadable, same-device
account Latest while opening another Saved Project; it uses the current sync base,
so CAS alone cannot stop that automatic cleanup. The fixed application upgrades
IndexedDB access to version 2 without rewriting record bodies. Old fixed-version-1
clients then fail storage/outbox operations. In-flight old cloud mutations still
need the existing remote CAS; already completed writes remain valid predecessors.

The original v1.23.0 `000ac6ecd85b18ae060cfb711070252c6c6d5af8` does **not** include
this fence and must not be accepted as the fixed candidate. Do not move its tag or
label old test results as evidence for a new commit. Finalize the actual fixed
application SHA after review, and pin it in every record and command. An ordinary
fix PR does not create a new Release: follow the separate release-preparation
contract before selecting a new stable Release. At the original transition, main also opened DB version 2, so the subsequent
1.x to 2.x forward update retained the same storage. The later AIP transition
below introduces DB version 3.

## Required evidence

Copy [the deliberately failing example](schema_transition.example.json) into a
private release store outside the checkout. It is not a production PASS record.
Fill the exact canonical/current app SHA, fixed candidate SHA, clean trusted tooling
SHA, verified Firebase project, canonical origin and public-configuration digest.
The digest is `app_release.fingerprint(app_release.public_configuration(variables))`
over the complete existing GitHub configuration inventory; never log credentials.
Use `git rev-parse <SHA>:data/schemas/project.schema.json` for `before_blob` and
`after_blob`, and `<candidate>:web/src/localProjectRepository.ts` for `writer_blob`.
A schema-identical ordinary release needs no schema transition record.

Each of the three checks needs `PASS`, a nonblank independent reviewer and summary,
and a retained evidence file with its exact SHA-256. The record binds all checks to
its current/candidate/tooling/configuration identities. Hashes bind evidence; they
do not prove compatibility. Cover:

- `old_to_new`: actual old Saved checkpoint/distinct draft, Latest and LastCalculation
  read/hydrate into new code, retaining IDs, coordinates, results and pinned Forecast
  provenance. Apply existing calculation freshness policy: retaining a historical
  calculation does not make it current in a different application version. Use the
  actual-version results and limitations in [implementation validation](schema_transition_validation.md),
  rather than treating the earlier shared-metadata probes as version-transition proof.
- `old_writer_fenced`: real old/new browser tabs, unreadable new Latest cleanup,
  pending/sent mutations, a delayed old SDK transaction, DB upgrade overlap and blocked
  upgrade failure. Preserve Project bodies, old session edits and outbox recovery;
  no old tab may tombstone new work. Verify remote CAS on a different old device.
- `storage_sync_roundtrip`: real IndexedDB reload/process restart and real SDK plus
  emulator Rules for Saved/Latest/LastCalculation and a fresh device. Record synthetic
  identity and emulator transport separately from live Google/production acceptance.

The complete candidate must contain the version-1 to version-2 writer fence, not
just declare it in a JSON record. The tool checks its source identity and narrow
prerequisites, while independent source review and browser/SDK evidence establish
behavior. Both application lines must retain compatible DB access. This transition
is one way: new-to-old reading and an old-app rollback are not acceptance conditions.
Recover with a compatible forward fix, preserving Project data and pending work.
Do not clear IndexedDB, strip snapshots, restore an entire older backup over newer
writes, or roll Rules backward automatically.

## Prepare and publish

Use current reviewed main tooling, not the older scripts inside the 1.x candidate.
Refresh canonical/approved alignment, Pages identity, exact public configuration and
live Rules with existing authorized read access. Missing access or UNKNOWN is a
blocker, not permission to create credentials or change protections. If Rules differ,
reuse the separately reviewed `--rules-transition` record and external Rules procedure.
This tool only reads Rules. Do not combine Rules compatibility attestations with
schema read/write evidence or infer either from the other's hashes.

Before prepare, obtain the separately authorized operation window and pause recurring
publication as required by the existing Rules transition runbook. No scheduler/config
mutation is part of preparing this implementation. In that window, for a new private
`STORE` directory and explicit full `CURRENT`/`CANDIDATE` values:

```sh
scripts/static_ops/app_release.sh prepare \
  --sha "$CANDIDATE" --current-sha "$CURRENT" --store "$STORE" \
  --schema-transition "$SCHEMA_RECORD" --rules-transition "$RULES_RECORD"
```

Omit `--rules-transition` when Rules are identical; omit `--schema-transition` when
schema is identical. Review the exact plan, schema/Rules receipts and isolated build
results. The existing 30-minute plan expiry applies. After **separate publication
approval covering that plan's digest**, use the same arguments and records:

```sh
scripts/static_ops/app_release.sh publish \
  --sha "$CANDIDATE" --current-sha "$CURRENT" --store "$STORE" \
  --schema-transition "$SCHEMA_RECORD" --rules-transition "$RULES_RECORD" \
  --reviewed-plan-sha256 "$REVIEWED_PLAN_SHA256"
```

Record bytes, paths, evidence, source/configuration or tooling changes invalidate
the plan; prepare and review again. The existing pause/idle checks, fresh rebuild,
sealed upload, canonical asset/serving verification, approved-SHA handoff and failure
journal remain in force. No guard deletion or independent Direct Upload bypass is
permitted. A mixed/uncertain state stops; no automatic rollback/resume is added.

Once the manually reviewed transition has passed actual production acceptance,
subsequent releases with identical contracts use the unchanged ordinary/automatic
path. Activation, credentials/WIF/permissions, Rules deployment, environment policy,
first publication and automation enabling remain separately authorized operations.


## AIP出典拡張の手動公開（IndexedDB 2→3）

新しいGitHub操作の入口は[GitHub上の移行証跡と承認](#github上の移行証跡と承認)です。
以下の既存の手動移行手順も、個別に承認された移行・復旧の入口として保持します。


AIP公表座標の出典を保存する候補には、`aip-reference-source-writer-fence` の手動移行を使います。
初回のスナップショット追加やForecastの移行とは別の契約です。
許可するschema差分は、規定の `AipReferencePointSource` 定義追加と、
`ReferencePointSnapshot.source` を旧形式とのunionへ拡張する変更、および
明示オープン時の変換を説明する所定のdescription変更だけです。
他のschema差分、Rules・indexes変更、Rules移行との併用は拒否します。
自動公開でschema差分を拒否する動作は維持します。

IndexedDBは2から3へ一方向に更新します。DB更新自体はレコード本文を変更せず、
Projectの `schema_version` と保存recordの `schemaVersion` も変えません。
同じブラウザー・サイト・保存領域を使う旧タブは、その後の読書きに失敗します。
更新前に進行していたローカル書込みは完了を待ち、その結果を保持します。
古い接続で更新がブロックされた場合、新しい書込みは失敗し、元データを保持します。

別端末の旧クライアントはこのDB更新では停止できません。AIP出典の読取りは旧モデルで拒否されます。
旧端末から開始済みの同期は既存のリモートCASで競合を検出し、新しい保存結果を上書きしないこと、
未同期データを保持したまま新候補へ更新して回復できることを確認します。
旧タブの再読込みは新候補の配信確認後に行い、DBを消去したり旧版へ戻したりせず、互換性のある修正版で回復します。

### 証跡と公開条件

[初回移行の例](schema_transition.example.json)を基に、`kind` を
`aip-reference-source-writer-fence`、`database_version` を `3` にします。
旧版・候補・clean tooling・公開設定・schemaとwriterのblobを実際の対象に固定し、
`old_to_new`、`old_writer_fenced`、`storage_sync_roundtrip` の3報告を独立レビューします。

- `old_to_new`: 旧Saved・別内容のDraft・Latest・LastCalculationを読み、地点ID・手動入力・過去の計算を保持すること。
- `old_writer_fenced`: 同一端末の旧タブ停止、更新のブロックと進行中書込み、開始済みSDK commit、別端末の競合と未同期データの回復。
- `storage_sync_roundtrip`: AIP出典を含む記録のIndexedDB再読込みと、実SDK・エミュレーターを使った別端末への同期。

各報告はJSONとし、`identity` に外側の移行recordの `checks` 以外の全項目を入れます。
`check` は報告の役割、`result` は `PASS` とし、`reviewed_by`・`summary` は外側のcheckと一致させます。
各報告のSHA-256も照合します。過去の報告のhashだけを別候補へ付け替えることはできません。

既存の `prepare` / `publish` と `--schema-transition` を使い、Rules移行は指定しません。
候補・設定・証跡の再照合、30分のplan期限、個別の公開承認は従来どおり必要です。
ローカルの合成データ・ブラウザー・エミュレーターによる成功は、本番公開や実機受入の完了を意味しません。
本番候補と設定に結び付いた証跡の承認、および公開後の受入は別途必要です。


## GitHub上の移行証跡と承認

既知のAIP出典拡張（IndexedDB 2→3、Rules・indexes不変）では、証跡生成とファイル準備を
Actionsが行います。操作者は非公開の証跡を確認し、レビューと最終公開を明示的に承認します。
日常操作でJSON・CLI引数・Secretsを組み立てる必要はありません。
この実装の導入だけでは本番設定や公開は変わりません。

### 初回設定

別途承認された設定作業として、公開NavMateとは別に、リポジトリ所有者が管理する
非公開GitHubリポジトリを用意します。次を設定し、既存の保護設定は維持してください。

| 設定 | 用途 |
| --- | --- |
| `STATIC_MIGRATION_REVIEW_REPOSITORY` variable | 非公開証跡の保管先（`Yuto-24/<repository>`）。移行中も同じ非公開リポジトリである必要があります。 |
| `STATIC_MIGRATION_REVIEW_TOKEN` secret | 保管先だけのMetadata read・Issues read/write。ビルドや候補コードへ渡しません。 |
| `STATIC_MIGRATION_ARCHIVE_KEY` secret | 32 byte鍵のbase64。生成証跡の認証とprepareの暗号化転送に使用します。 |

prepareには既存の`STATIC_CLOUDFLARE_READ_TOKEN`、公開には`CLOUDFLARE_PAGES_TOKEN`を使用します。
GitHubの変数操作には既存の`STATIC_APP_RELEASE_GH_TOKEN`、Rules読取には既存のWIFを再利用し、
GitHub Release作成には公開jobの`GITHUB_TOKEN`を使います。新しい権限や設定の適用は別作業です。

### 証跡確認から公開まで

[static-app-release](https://github.com/Yuto-24/NavMate/actions/workflows/static-app-release.yml)の
**Run workflow**で`main`を選びます。3工程とも同じtooling SHAが必要です。
途中でmainが進んだ場合は、新しい証跡からやり直します。

1. **証跡を確認する。** 自動生成されたRunのSummaryから非公開Issueを開きます。
   手動生成には`evidence-migration`を選び、`candidate_sha`を指定します。空欄なら選択した
   mainのSHAです。実際の現行版と候補版のDockerで、合成Saved・別内容のDraft・Latest・
   LastCalculationを検証します。旧ブラウザーの保存・同期処理、共有する実行コードと依存関係、
   候補のpush CIで実行された契約テストと検査定義の一致も要求します。
2. **独立レビューを記録して準備する。** ソース上の互換性、各検証の結果と限界を独立に確認します。
   PASSはテスト結果であり、レビュー完了や公開承認ではありません。
   `prepare-migration`の`migration_record_id`にIssue番号、`reviewed_record_sha256`に
   そのRunのSummaryのSHA-256を入力します。write以上の権限を持つ人間のGitHubアカウントによる
   dispatchをレビュー記録とします。既存gateを確認後、天気更新を停止してprepareを実行します。
3. **公開を最終承認する。** 非公開Issueに追加されたplanと変更対象を確認します。
   `publish-migration`の`migration_record_id`には今度は**planコメントのID**、
   `reviewed_record_sha256`にはprepare RunのSummaryのSHA-256を入力します。
   これが最終公開承認です。plan作成後30分以内に開始する必要があります。

証跡は候補・現行・tooling・公開設定に固定し、生成から24時間以内に使用します。
合成データもzlib＋base64で圧縮して非公開Issueに残します。実アカウントや実端末の
本番受入を証明するものではありません。prepareのファイルは暗号化済みArtifactだけを
公開リポジトリ側に1日保持し、平文の証跡・設定を公開ログやArtifactへ出しません。

公開は既存の`static-production`排他、fresh build・テスト、予報鮮度、Pages照合、
承認SHA更新を通ります。その後GitHub Releaseを作成・照合し、公開先・承認SHA・Rules・
設定・承認記録が整合する場合だけ天気更新を元の状態に戻します。元が停止中なら停止を維持します。
証跡の編集・Issueの閉鎖は承認を無効にし、公開前と再開前にも再確認します。

### 期限切れ・中断・部分失敗

workflowの**Re-run jobsは使用できません**。新しいdispatchで新しい証跡と承認を取得します。
plan期限切れでも天気更新を無条件に再開しません。公開の副作用がないと確認できた場合は、
証跡生成・レビュー・prepareからやり直します。再prepare時点で天気が停止中なら、
その停止状態が保存されるため、後の再開は既存の復旧手順で別途判断します。

API障害、証跡・設定・Rulesの不一致、不確かな公開状態は停止します。非公開Issueの失敗記録で
stageとUNKNOWN／CONFIRMEDを確認し、[既存の運用手順](static_operations.md)で
本番Pages・承認SHA・予報更新状態を照合してください。成功か不明な書込は再送せず、
部分公開を古い証跡で再試行したり、自動rollbackしたりしません。
非公開記録の保存自体に失敗した場合は、公開ログの最小状態とproviderのreadbackで確認します。
