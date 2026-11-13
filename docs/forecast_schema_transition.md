# Manual Project schema 4 → 5 transition (#423)

The manual transition can admit the optional forecast model addition after independent
compatibility review. It does not authorize publication. Automatic app releases still
reject any schema difference. Rules and indexes must remain identical; this transition
cannot be combined with a Rules transition.

## Pinned application evidence

| Identity | Reviewed source |
| --- | --- |
| Current v2.2.2 | `03cc463cf09192e1403f839df4165410c5db8d7b` |
| Historical candidate v2.3.0 | `1a4cc915d1a871d9044942078d00aea90e37d340` |
| Historical readback candidate v2.3.1 | `c717ac6baaa3d7556120d2a7f6c9435f165f132b` |
| Current prepare candidate v2.3.2 | `f1a5ef49eeab41744635232cddd51c2257871aed` |
| Before Project schema blob | `b3bdd7e593eb9a7c6257994762934c35cfdda430` |
| After Project schema blob | `d19086279b8f903d0c6209ab9e5065974af5d294` |
| Candidate Local repository blob | `5b6178c23ed9788f08b465d9003088e4ad9e2978` |
| Tooling | Pin the clean, reviewed tooling commit used for prepare in the private record; the PR records the tested/reviewed commit. Do not substitute the older tooling in the v2.3.0 tag. |

[Automatic publication run 42778669318](https://github.com/Yuto-24/NavMate/actions/runs/42778669318/job/129703114029)
selected the historical v2.2.2 → v2.3.0 identities and stopped at the compatibility
gate on 2026-11-10. They are historical publication evidence, not evidence of the
current v2.3.2 candidate or a fresh production observation. A direct
canonical `release.json` read from the implementation environment returned HTTP 403;
current canonical/approved alignment, Pages inventory, live Rules and complete public
configuration must be refreshed with existing authorized access before prepare.

The exact schema difference changes `schema_version` const/default 4 to 5 and adds
nullable `selected_forecast_model` with `MSM`/`GSM` values and default null. Removing
only that addition and reverting only the version must reproduce the old schema.
Changes to required fields, definitions, enums, defaults or any other contract fail.
Both clients retain IndexedDB version 2. This is **not** the version-1 writer fence in
[the reference snapshot transition](schema_transition.md).

## v2.3.2候補の再審査に使う差分確認

2026-11-13、旧候補 `c717ac6baaa3d7556120d2a7f6c9435f165f132b` と
[#435マージ後のmain](https://github.com/Yuto-24/NavMate/commit/753b6ea42b4444aefe9543e3ece276727dc71a33)を比較した。
アプリ本体、保存・同期処理、schema、data、依存関係、Rules・indexesに差分はない。
固定tooling `64225b82c9b2e978409f0b35490be3c83af3f157` の公開・build処理にも変更はない。
v2.3.2の準備ではVERSIONと更新履歴が変わるため、成果物のbytesが同一とは扱わない。

この確認は既存の互換性検証結果を再利用する際の根拠になるが、新候補の承認証拠そのものではない。
最終候補SHAと成功したCIを確定後、同じ範囲の差分を再確認し、3件の元報告を根拠として
新候補への適用を独立レビューする。元のrecord・報告は上書きせず、新しいidentityを持つ別記録を作る。
新記録と3報告が実際の固定 `reviewed_schema()` に受理されてから元バイトhashを固定し、
Actions側のcandidate、Release/tag、候補CI、証拠hash・pathをそのidentityに揃える。
旧v2.3.1用readbackの `MATCH` は新候補の照合結果には使わず、prepare前の本番照合を行う。

最終v2.3.2候補は `f1a5ef49eeab41744635232cddd51c2257871aed`。
2026-11-13にAstraとSolがこのcommitを旧候補と再比較し、上記の等価性を確認した。
再適用の対象は `old_to_new`、`old_writer_coexistence`、`storage_sync_roundtrip` の既存観測。
新候補で実験を再実行したという意味ではなく、元報告にある限界と自端末Latest置換の了承範囲を引き継ぐ。

`scripts/static_ops/schema431_reapply232.py` は、この一組だけを扱うWSL用helper。
旧recordの固定hash、3報告のhashとidentity、全source差分、Release/tag、候補CIを確認する。
各tagをoriginからfetchし、その直後の `FETCH_HEAD^{commit}` と固定SHAを比較する。
ローカルのtagだけでは、remote tagが変わった場合に検出できないため。
公開設定は既存のGitHub認証でRepositoryと3 environmentの完全な一覧から読み取り、
旧recordのdigestと固定validatorで照合する。取得した設定やprovider応答は表示しない。
旧記録が固定toolingの `reviewed_schema()` に受理された後、新しい非公開ディレクトリへ別記録を作る。
新報告には元報告の内容とraw hash、元identity、今回の適用レビューを残す。
新しい4ファイルも同じvalidatorに受理された場合だけ、新recordのhashを表示する。

2026-11-13、利用者のWSLでレビュー済みhelper `65711d8998c70a463d347a5865ceae661fdc924d` を実行し、
`ACCEPTED` と新recordのhashが返ったとの報告を受領した。実行前に両tagをoriginから明示fetchしており、
その後のremote照合でも上記SHAと一致した。新hashは[Actions側の固定値](schema431_actions_prepare.md#維持する境界)へ反映する。
受理済みの新記録は再生成・上書きしない。この実装環境ではprivateな4ファイル自体は読んでいない。

候補CI [43383649255](https://github.com/Yuto-24/NavMate/actions/runs/43383649255) はattempt 2で成功した。
初回の2件のWebKit失敗は、対象動作の前の起動・入力準備で発生していた。根本原因の解決までは
確認できておらず、同一候補の再実行が成功したという観測にとどめる。
[失敗位置と再実行の根拠](https://github.com/Yuto-24/NavMate/pull/437#issuecomment-6847188359)を参照。

helperはActions側のpinやSecretを変更しない。新記録は更新後のpackで元バイトhash・identityと
転送容量48,000バイトを確認する。旧転送が収まったことは、新報告の容量保証にはならない。
freshな本番照合、隔離build・static E2E、prepare/publishとその承認は後続工程に残る。

実行にはPython 3.12と固定toolingのPython依存、Git、既存の `gh` 認証が必要。
Node.js、Docker、Cloudflare/Google認証は使わない。helperのレビュー済みcommitをcheckoutし、
同じRepositoryの別worktreeをtooling `64225b82c9b2e978409f0b35490be3c83af3f157` に固定して渡す。
tooling側で両候補commitを参照でき、originのv2.3.1/v2.3.2 tagをfetchできる必要がある。

```sh
# WSL。未作成の場合だけ実行する。受理済みの新記録がある場合はpackへ進む。
# helperのcheckoutから、固定toolingのclean checkoutを指定する。
python scripts/static_ops/schema431_reapply232.py --tooling "$reviewed_tooling"
```

出力先は `/home/yuto/autonavlog-releases/schema4-5-v2.3.2-20261113`（新規0700、4ファイル0600）。
既存ディレクトリは上書きしない。成功時の `ACCEPTED` と `record_sha256` だけを共有し、
元・新記録の内容や設定一覧をチャット／PRへ貼らない。`BLOCKED` の場合は表示されたstageを確認し、
hash、identity、候補、toolingを変更して通過させない。

## Accepted writer behavior

On 2026-11-10 the Issue owner explicitly accepted the existing own-device Latest
replacement semantics across old/new tabs: opening another Project in an old tab
may tombstone a Latest saved by a new tab in the same browser profile. The real
Chromium/WebKit and SDK/emulator reproduction demonstrated that behavior. It is an
accepted operation, not a promise that every Latest survives. Closing a tab alone
does not discard it. Saved checkpoints and another device's Latest remain protected.

This narrows the initial interpretation of “protect unsynced work” in #423; it does not
permit stale overwrites of Saved, deletion of another device's Latest, or silently
losing conflict branches. `latest_policy = replace-own-device-latest-on-open` records
this boundary explicitly. No new writer fence, database version or application
behavior is introduced by this tooling change.

## Compatibility checks and limits

- `old_to_new`: frozen synthetic records generated by actual v2.2.2 / weather 0.5.0
  code restore Saved, distinct Draft, Latest and Last Calculation in v2.3.0 / weather
  0.6.0. Run-only records become MSM; FTD has no forecast model. IDs, route, input,
  result and fingerprint provenance survive. Existing automatic-name migration adds
  route names (and FTD prefix); manually assigned names stay unchanged. Historical
  rows gain null 30-degree CUT values and empty forecast provenance, not fabricated
  results. Restored readiness is stale; restoration never recalculates.
- `old_writer_coexistence`: actual pinned old storage/SDK adapters exercise accepted
  own-device Latest replacement, protection of Saved/foreign Latest, stale local and
  remote writes, a Commit RPC delayed after its SDK read, and lost acknowledgements
  followed by further offline edits. The first stale account edit is retained with
  its conflict; later edits are blocked. On a different old device, schema-5 receive
  fails while preserving the sent work. Reloading that device into the candidate
  allows explicit Both resolution. Only explicit resolution applies existing stale
  Last Calculation cleanup; ordinary receive retains the historical result.
- `storage_sync_roundtrip`: real IndexedDB, reload, candidate Python validation,
  actual Firebase SDK and emulator Rules, and a separate browser profile exercise
  normalization, Saved/Draft/Latest transport and retained calculations. Invalid
  candidate writes leave the original records intact.

The domain matrix is `tests/integration/test_schema4_transition.py`; fixture generation
and dependency limits are recorded in `tests/fixtures/schema4/README.md`. The browser
matrix is `web/e2e/schema4-transition.spec.ts` and runs with the existing storage-upgrade
suite in CI. The old reader predicate models the independently checked Python rejection
(`literal_error`/`extra_forbidden`); it is not a full old Pyodide application. Emulator
identities are synthetic. Physical Safari devices, live Google identity, production
Firestore and canonical serving acceptance are not established by these tests.

The gate tests cover both transition kinds, exact identities, missing/altered evidence,
retargeted reports, schema/Rules/index drift, unchanged prepare/publish and invalidation
between them. Existing automatic/default release behavior stays fail-closed.

## Read-only production observation under pinned Google WIF

On 2026-11-11, [readback Run 42916903164](https://github.com/Yuto-24/NavMate/actions/runs/42916903164)
failed at Google token exchange with `unauthorized_client` because the existing WIF provider
pins both the `static-production` environment and the exact `static-app-release.yml`
workflow on `main`. This was an authentication-condition rejection, **not** a mismatch
between deployed Firestore Rules and candidate sources.

Do not widen the provider condition or create alternate credentials. Once the
read-only mode has merged, dispatch `static-app-release` on `main` with
`operation=readback` (leave `release_id` empty). Its readback job uses the existing
`firebase.readonly` identity and Cloudflare read token, without entering
`release_automation.py prepare/publish`. Manual release replay separately requires
`operation=replay-release` and a nonempty `release_id`; the release and workflow-run
automatic triggers retain their previous gate. The separate `schema423-readback`
workflow was removed because WIF cannot authorize its `workflow_ref`.

The readback checks the fixed **v2.3.1 candidate** (`c717ac6baaa3d7556120d2a7f6c9435f165f132b`)
against live canonical, Pages inventory and Rules. It does not validate the historical
v2.3.0 candidate identity. For v2.3.0, use the previously recorded release/tag,
source/blob identities and tests above; do not infer a v2.3.0 PASS from v2.3.1 readback.
It also does not validate the new v2.3.2 candidate. The v2.3.2 Actions prepare path
checks its own pinned Release/tag, CI and new private record, then performs a fresh
production snapshot before any pause or build. Do not use the old readback's `MATCH`
as that candidate's observation.
The observation is neither a schema-record re-review nor authorization to stop
schedules, prepare or publish. Recheck production immediately before any separately
approved manual operation.

## Private evidence and operation window

For the fixed v2.3.2 transition following #431, the
[Actions prepare/publish procedure](schema431_actions_prepare.md) transfers the newly reviewed
record and three reports through private environment secrets, runs this exact reviewed
tooling under the existing WIF workflow, and retains only an encrypted plan/result.
The separate `publish-schema431` operation restores that exact prepare artifact and
calls the same fixed tooling after explicit approval of its plan digest. It preserves
the record's tooling identity and does not resume automation after publication.

1. Copy [the failing template](forecast_schema_transition.example.json) outside the
   checkout only if new evidence is needed. For v2.3.2, use the accepted separate
   `SCHEMA_RECORD` pinned to current v2.2.2 and candidate v2.3.2; verify those two
   identities against the fresh prepare snapshot. Keep historical records unchanged.
   Supply the reviewed, clean tooling SHA, verified Firebase project and the digest of
   the complete `app_release.public_configuration(variables)` inventory. Do not copy
   credentials or publish a private configuration inventory in the PR.
2. Retain the validation artifacts and independent review of the exact candidate,
   current application and tooling. For each check, create a JSON evidence report:
   `identity` is an exact copy of **all** transition-record fields except `checks`;
   `check` is the check name; `result`, `reviewed_by`, and `summary` exactly match that
   check in the outer record. Include detailed results/artifact identities and limits
   in the report. Set PASS only after review. Hash the final report bytes into the
   check's `record.sha256` and set its retained path. These are attestations by the
   reviewer, not signatures or automatic proof that a test ran.
3. The gate compares embedded identities, not just hashes, so changing the outer
   candidate/current/tooling/project/configuration cannot reuse an old report. Any
   changed identity requires new reviewed evidence. UNVERIFIED, missing review,
   malformed report, changed bytes or a mismatched role blocks prepare.
4. Follow the existing [manual operation window](static_operations.md#wsl-からのアプリ更新-prepare--publish):
   obtain its separate authorization, pause recurring publication as specified,
   verify idle/canonical/approved alignment and live Rules, and use a new private store.
   Prepare creates a private build/plan; it does not deploy or grant publish approval.

```sh
scripts/static_ops/app_release.sh prepare \
  --sha f1a5ef49eeab41744635232cddd51c2257871aed \
  --current-sha 03cc463cf09192e1403f839df4165410c5db8d7b \
  --store "$STORE" --schema-transition "$SCHEMA_RECORD"
```

Review the exact plan and its digest. Only after separate approval covering that digest
may the operator use the existing `publish` command with the same arguments and
`--reviewed-plan-sha256`. The 30-minute expiry, re-read of record paths/bytes/reports,
source/configuration/tooling checks, fresh build, upload seal, pause/idle checks and
canonical verification remain in force. Drift requires new prepare and review.

No real prepare/publish, workflow pause/resume, `STATIC_APPROVED_SHA` change, Rules
write, Release/tag recreation or production acceptance was performed by this issue's
implementation. Once authorized publication occurs, complete the existing production
acceptance and approved-SHA handoff before resuming automation. A failed or uncertain
operation follows the existing journal/recovery procedure; do not strip forecast
models, roll back to a schema-4 writer, clear storage or overwrite newer work to recover.
