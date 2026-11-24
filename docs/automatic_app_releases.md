# Stable Releases to Serverless production

安定版 GitHub Release（`vX.Y.Z`）が公開された際、Rules・indexes・Project schema・IndexedDB版が不変の通常更新に限り `static-app-release.yml` が `https://navmate.yuto24.com` へ自動公開する契約の正本です（`STATIC_APP_RELEASE_ENABLED == true` で有効化）。

After explicit activation, a published stable `vX.Y.Z` GitHub Release is the app
publication authorization for unchanged access/data contracts. Ordinary PR merges
do not publish the app. `release/1.x`, `release/2.x` and `main` target the existing
`https://navmate.yuto24.com` Pages project `navmate`, production branch `main`.
The Pages branch is a delivery target, independent of the application source branch.
Validate this delivery first with 1.x. After moving production to 2.x, end 1.x
maintenance/releases; the global version comparison also prevents a late 1.x
Release from replacing 2.x. No legacy server stop is part of this mechanism.

## Release作成前の経路判定

通常の入口はリリース準備PRです。`release-preflight` は本番の承認済みSHAと
canonical `release.json` の一致を確認し、候補との差分から次の経路を表示します。
PRでの表示には公開権限がありません。VERSION更新後のRelease publisherで再判定し、
実際の公開直前にも既存の本番照合を行います。

| 経路 | 条件と次の処理 |
| --- | --- |
| `AUTOMATIC` | Rules・indexes・Project schema・IndexedDB版が不変。従来どおりGitHub Releaseを作成し、自動公開へ進みます。 |
| `MANUAL` | 同一Rules・indexesの下で、既知のAIP出典拡張とIndexedDB 2→3に一致。Release作成を保留し、[GitHub上の移行証跡と承認](schema_transition.md#github上の移行証跡と承認)へ進みます。 |
| `BLOCKED` | 不明な差分、API取得失敗、本番との不一致、または自動証跡の未対応パターン。公開せず個別判断へ回します。 |

初回のIndexedDB 1→2とForecast schema 4→5は既知の契約ですが、この自動証跡経路では
未対応です。それぞれの既存の手動移行手順を使います。任意のRules・indexes変更や、
単なるフィールド追加を安全とは判定しません。

`STATIC_APP_RELEASE_ENABLED=true` のとき、VERSION更新のpublisher完了後に経路を
再確認します。MANUALの証跡自動生成には、別途受入後の
`STATIC_MIGRATION_EVIDENCE_ENABLED=true`も必要です。未設定・無効なら生成せず、
[Firestoreの初回設定・受入](migration_evidence_operations.md)を先に行います。GitHub UIから直接Releaseを作成した場合も本番gateは残りますが、
Release作成前の誘導を受けるにはリリース準備PRを使ってください。
通常公開の全入口（`release: published`・`replay-release`・`workflow_run`）で、実際のタグSHAの
IndexedDB版を現行版と再比較します。版変更や、既存のDB open呼出しとして認識できない版指定は
通常公開を停止し、移行手順で扱います。
本番がすでに移行済みで契約が不変なら、過去の移行証跡を再使用せず通常経路になります。

この変更をmainに導入しただけでは、既存の`release/1.x`・`release/2.x`上の古いpublisherは
更新されません。これらのブランチで次のReleaseを準備する前に、publisher・呼出先の
`release-preflight` workflow・必要なtoolingと依存関係をレビュー済みの変更として反映してください。
古いpublisherからの完了イベントでもmain側の本番gateは残りますが、Release作成前の判定には
なりません。保守ブランチへの反映と非公開証跡の初回設定は、このPRの本番操作には含めません。

## Events and identity

`static-app-release.yml` has the following entrances, for automatic publication, gated by repository variable
`STATIC_APP_RELEASE_ENABLED == true` (absent is disabled). Separately selected migration
dispatches retain their own explicit review and approval gates:

- `workflow_run: completed` of successful `publish-github-release` pushes on
  `main` / `release/1.x` / `release/2.x`. This is the default bridge for Releases created with
  `GITHUB_TOKEN`; those Releases do not themselves trigger `release` workflows.
  The completion bridge itself needs no PAT or dispatch step in the publisher.
  Pre-Release routing has the branch rollout prerequisite above.
- 通常の`test` push CI完了は起動条件にしません。Releaseイベントで起動したread-onlyの
  `source-ci` jobがタグのpush CI成功を待ち、成功後にだけ本番公開jobへ進みます。
  ReleaseがCIより先に作られた場合も自動的に待機します。GitHub Release publisherには待機処理を追加しません。
- `release: published` for Releases created through the UI or another authorized
  publisher. Drafts and prereleases are rejected. This entrance needs the workflow
  present in the released ref and environment permission for its tag (see setup).
- Manual `workflow_dispatch` **on main**, with an existing numeric `release_id`,
  for a missed event, first selected Release or a safe retry. It is not a rollback.

The bridge re-reads the publisher run (path, push event, success, same repository,
supported branch, full SHA), obtains VERSION from that commit, and requires the
actual stable Release and immutable tag ancestor. Every entrance peels annotated
tags, compares API resolution with the fetched tag, checks exact VERSION and
ancestry in the matching source branch, and rechecks identity at every snapshot.
It never uses `latest`, release titles or `target_commitish` as app identity.
V2 candidates must be ancestors of freshly fetched main or `release/2.x`;
only the latter permits a reviewed fix without unrelated main changes.
See [release_lines.md](release_lines.md) for maintenance branch initialization.
Trusted tooling is checked out from main once, retained at that SHA in the plan;
candidate release scripts only execute inside the existing credential-free Docker
build. The automatic path downloads no publisher-run artifacts or caches. The migration
path below uses only its authenticated encrypted prepare archive.

通常の新アプリ昇格は、**ReleaseタグのアプリSHA**と同じpush CIの成功を待ちます。
toolingのSHAやPRの影響選択CIの成功では代用しません。必要なsuite・実行stepが欠ける、
未完了・失敗・cancel・取得不能の場合はfeedを停止せず、現行配信と配信中SHAの
天気更新を維持します。Release専用の事前確認は最大40分待機し、成功後だけ公開jobを開始します。
期限切れ・失敗時には既存のreplayで再試行します。待機中に本番公開の排他は占有しません。

成功Runの小さなWeb検査inventoryだけを取得し、SHA・Run/attempt・GitHubのartifact digest・
toolingと同じ検査定義を照合します。Node・npm・依存lock等が一致する検査だけ省略します。
記録が取得不能・期限切れ・不一致なら従来の検査を実行し、fresh rebuildと候補E2Eは常に維持します。
承認済みの手動公開・復旧例外には、この新しい待機条件や省略を適用しません。
詳細は[source CI再利用の判断記録](app_publication_audit.md#source-ci再利用issue-460)を参照してください。

## Publication and failure behavior

The feed retains **workflow-level** `static-production` concurrency; the app
publication and manual operations hold the same lease at **job-level**, after any
source-CI wait. Every holder uses `cancel-in-progress: false`, `queue: max`.
This retains up to 100 pending jobs/runs; GitHub does not promise ordering.
If capacity is exceeded, inspect cancellations and replay the required Release.
After the publishing job acquires the lease:

1. Canonical clean `release.json.commit` must equal `STATIC_APPROVED_SHA`. Compare
   numeric X.Y.Z tuples to the canonical version: older Releases skip, the same
   version and SHA skip, the same version with a different SHA blocks. Only a newer
   version can publish. A queued older Release cannot roll production backward.
2. Reuse `app_release.prepare`: pin application SHA, tooling SHA, configuration,
   Pages identity and exact Rules/indexes/Project schema contracts; compare live
   Rules against source, build and test in isolation, and retain the plan digest.
   After the container hands back only the writable inventory/hint paths, trusted
   tooling seals `freshness.json` into that inventory so MSM fallback keeps working.
3. Refresh short-lived Rules read authentication, then reuse `app_release.publish`
   with that policy-authorized digest. This does **not** claim a human reviewed or
   approved the generated plan. Existing 30-minute plan freshness/drift gates apply.
4. Pause feed automation and its workflow, rebuild fresh, validate inventory and
   fresh forecast coverage, upload static bytes, and verify canonical inventory,
   serving headers, HTML/manifest, feed and Pages identity. Only then update
   `STATIC_APPROVED_SHA`; verify again before restoring the previous scheduler state.

The Actions operator allows pending work behind its own shared lease. The manual
operator rejects every unfinished feed **and app** run, so it cannot overlap this
publisher. Manual operations still require their existing explicit operation window.
Keep all production app/feed publication workflows in this concurrency group.

Rules are compared as exact UTF-8 bytes (including whitespace/line endings), and
indexes/schema by exact git blob identity. A Rules change hidden in an application
Release, unknown/missing contracts, changed indexes/schema, live Rules drift or
unknown provider state blocks **before any upload**. The automatic route has no
Rules-transition input, compatibility override, Firebase write API or automatic
approval. Changed Rules require individual authorization, current/candidate
compatibility evidence and the existing separate migration procedure in
[static_operations.md](static_operations.md#rulesが異なる更新だけに必要な検証記録).
An environment approval alone does not establish compatibility. Reconcile and
publish that reviewed transition through the manual path; a replay then sees the
same canonical version/SHA and skips. Index migrations remain blocked. A separately reviewed manual one-way schema
transition is documented in [schema_transition.md](schema_transition.md); the automatic
route has no schema-transition input.

On pause/upload/verification/approved-SHA failure, keep the existing journal's
UNKNOWN/CONFIRMED distinctions. There is no unconditional resume or automatic
rollback. A new run uses a new private runner-temp store and prepares again; it
never resumes an old partial upload. If upload succeeded but approved SHA did not
advance, canonical/approved mismatch blocks replay until separately authorized
reconciliation. If the scheduler was paused or its workflow disabled, inspect and
recover under the existing runbook before retrying. Do not simply re-enable it.
Intentional rollback uses the separate reviewed rollback procedure, never this
monotonic automatic route.

Each prepare/publish step has a 50-minute timeout and a fresh one-hour read token.
Token expiry, cancellation or timeout fails closed; inspect remote state before
any retry. The safe stage/status/mutation summary goes to the Actions summary.
Detailed plan and journals are private runner-temp files, not uploaded as public
artifacts; they may be unavailable after runner teardown, so use read-only provider
state for recovery when necessary. `Journal.finish()` keeps the full journal private
and prints only `status`, `review_sha256`, and `plan_sha256` to stdout. Do not log
tokens or candidate command output.

## Activation prerequisites and first publication (separate authorization)

This implementation does not change any live setting, credential, protection,
Rules, Release, deployment or scheduler. Before enabling it, review and prepare:

| Setting | Requirement |
| --- | --- |
| `STATIC_APP_RELEASE_ENABLED` repository variable | Remain absent/false until setup and the first selected 1.x Release are authorized. Set true only for activation. Removing/setting false stops future jobs and subsequent snapshots. |
| `STATIC_APP_RELEASE_GH_TOKEN` secret in `static-production` | Existing dedicated repository credential able to read Releases/contents, Actions runs/workflows, repository/environment variable inventories, and write Actions variables plus enable/disable the feed workflow. A fine-grained token needs Contents read, Actions write, Variables write, Environments read, Metadata read on this repository. Do not grant release creation, Rules write or environment-administration rights. `GITHUB_TOKEN` cannot write Actions variables. |
| `CLOUDFLARE_PAGES_TOKEN` | Reuse the existing environment credential; app release needs the existing Pages read/upload capabilities, no new Pages project or domain. |
| `STATIC_GOOGLE_WORKLOAD_IDENTITY_PROVIDER`, `STATIC_GOOGLE_SERVICE_ACCOUNT` repository variables | Reviewed Google Workload Identity Federation for this repository/workflow and production environment, impersonating an account with Rules **read only** (`firebaserules.releases.get`, `firebaserules.rulesets.get`). OAuth `firebase.readonly`; no key file, stored access token, Rules deployment role or lifetime-extension policy. Establishing trust/permissions is a separate authorized setup task. |
| `static-production` environment | Keep unattended protection for compatible releases. Its current main branch policy already supports the default workflow_run/manual route for both version lines. Direct `release: published` jobs also need separately reviewed tag allowances, limited to official v1/v2 tags; otherwise use the default completion bridge/manual main replay. Do not weaken existing protections. |
| Existing public configuration and `STATIC_APPROVED_SHA` | Preserve exact canonical configuration; require complete repository/environment inventories without shadowing. `STATIC_AUTOMATION_ENABLED=true` and active feed workflow are required before starting an unattended release. |

Read-only setup inventory on 2026-10-28 found only `CLOUDFLARE_PAGES_TOKEN` in the
`static-production` environment and only `STATIC_CLOUDFLARE_READ_TOKEN` at repository
scope. The new opt-in, GitHub credential and WIF variables were absent; environment
deployment policy allowed only branch `main`. No setting was changed. Refresh this
inventory before activation; names/existence are not credential capability proof.

First-publication checklist:

1. Merge reviewed tooling only after normal CI/reviews. Do not create a release or
   enable the opt-in as part of merging this implementation.
2. Select a new stable 1.x release-preparation commit on `release/1.x`, validate the
   candidate/current contracts and existing runtime evidence. VERSION/CHANGELOG
   follow the established explicit release-preparation policy. If Rules differ from
   current production, finish the separately approved transition first.
3. Under separate setup authorization, confirm credentials/WIF permissions,
   canonical/approved alignment, Pages identity, preserved configuration and the
   feed's enabled/idle state. Authorize enabling the opt-in and that first Release.
4. Create the Release through the existing v1 release publisher, or replay the
   explicitly selected existing Release ID on main. Verify the exact workflow run,
   release ID/tag/SHA, canonical app version, approved SHA and fresh MSM inventory.
   A passing PR, accepted event or uploaded artifact is not production acceptance.
5. Confirm the next natural forecast-only publication retains the new app SHA and
   configuration. Later compatible Releases need no per-release approval. A future
   Rules migration still needs its own authorization and evidence.

References: [GitHub event/token behavior](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow),
[workflow_run](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run),
[concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency),
[Google auth action](https://github.com/google-github-actions/auth),
[Rules read scopes](https://firebase.google.com/docs/reference/rules/rest/v1/projects.releases/get).
