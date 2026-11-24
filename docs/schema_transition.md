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

既知のAIP出典拡張（IndexedDB 2→3、Rules・indexes不変）では、GitHub Actionsが証跡を
生成し、本人が証跡専用Firestoreの標準管理画面で詳細を確認します。
操作入口とレビュー・最終公開の承認はGitHubに残します。初期の閲覧・承認者は本人だけです。
テストのPASSは独立レビューや公開承認を代替しません。

証跡・正確なplan・合成サンプル・公開結果・失敗記録を関連付け、原本を上書きせず保持します。
JSON原本と展開表示を照合し、欠落・改変・容量超過・不明な状態では停止します。
証跡24時間、plan30分の期限と、候補・現行・tooling・公開設定の一致検査を維持します。
旧Issue番号・コメントIDによる承認には戻さず、新しい証跡を要求します。
撤回は永続的に適用し、再承認には新しい証跡が必要です。

成功・最終照合済みで関連する未完了処理がない一式だけを完了から30日後に整理します。
失敗・未完了・状態不明・撤回の記録は自動削除しません。
Firestore上の詳細は専用プロジェクトのIAMで保護し、公開ログには出しません。
GitHubへのArtifact転送は暗号化を継続します。

[初回設定・合成データ受入・操作・復旧の手順](migration_evidence_operations.md)を参照してください。
実環境のIAM、本人によるplanとサンプルの詳細閲覧、未許可利用者と本番・開発DBへの
アクセス拒否を確認してから有効化します。実装の導入は公開・本番設定変更を意味しません。
