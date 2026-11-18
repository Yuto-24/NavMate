# Account Sync project shards (2026-11-01)

## 結論と適用条件

Account Sync E2E を `chromium` / `ipad-webkit` / `iphone-webkit` / `contracts` の 4 runner へ分割し、各 runner が独立した Firestore emulator を起動する設計記録である（現行 CI の完全な分割一覧・さらに進んだ 2 分割は [testing.md](../../testing.md#independent-ci-shards) と [impact-selection-20261110.md](impact-selection-20261110.md) を正本とする）。

## 設計判断と再現可能な境界

Split the Account Sync critical path across ordinary GitHub-hosted runners without reducing tests, keeping readiness/encoding fixes (`b42f1b3c082b60452aa016c807d68000cc3bdf6b`) and Local/Python/MSM coverage intact. No paid runner or permissions/deployment change is required.

The aggregate `account-sync` check uses `always()` and checks only the `account-sync-tests` matrix results (`account-sync` does not depend on `web`). Full Playwright collection versus the union of all shard selections is verified in the `web` job via `web/scripts/check-account-sync-partition.mjs`, so partition-check failures propagate through `web` and `ci-required`.

## Suites and independent state

| Runner | Commands / coverage |
| --- | --- |
| chromium | Every sync test in project chromium (13 at implementation) |
| ipad-webkit | Every sync test in project ipad-webkit (13) |
| iphone-webkit | Every sync test in project iphone-webkit (13) |
| contracts | All Firestore Rules (4), storage-upgrade (16), then migration (6) |

Each runner starts its own Firestore emulator with the same pinned Firebase CLI and
`firebase.json`. Rules and indexes are loaded from that configuration at emulator startup;
`test:firestore` is a verification suite, not a prerequisite that installs rules for later suites.
Rules tests, sync application workflows, storage-upgrade cloud fixtures, and real migration
seeding use their own random subjects/records. None consumes records created by a different
suite. Static synthetic identities in readiness/error fixtures do not cross runner boundaries.
The migration harness is still available independently in every runner; contracts keeps both
Chromium and iPad migration projects, and both storage-upgrade projects, unchanged.

All existing suite scripts, test assertions, timeout/retry settings, and worker counts remain.
Sync keeps `--workers=2` without `fullyParallel`; a single project/file can use only one worker,
preserving its internal ordering. This change adds CPU isolation across projects rather than
increasing same-runner concurrency. Each failure artifact includes its suite name.

The aggregate `account-sync` check retains the previous check name and inspects only the `account-sync-tests` results (`always()` makes it evaluate failed/cancelled/skipped/missing prerequisites; its command accepts only success, while proven docs-only changes retain the original skip behavior). The `web` job runs `web/scripts/check-account-sync-partition.mjs` to compare full Playwright collection with the union of shard selections, failing on any unassigned project, duplicate, empty selection, or collection error; partition-check failures propagate to `web` and `ci-required`, not to `account-sync`. Contracts
uses whole configs (not project filters), since storage and migration project names differ from
sync and migration intentionally has no iPhone project.

## Evidence and verification

The unchanged Account Sync in [PR #330's successful run](https://github.com/Yuto-24/AutoNavLog/actions/runs/41275766965)
took 13m23s; workflow elapsed about 13m38s. That is a motivation, not a matched comparison against
this stack's inherited readiness fixes. Target is an Account Sync aggregate under ten minutes;
actual hosted runtime and completion must be measured, including setup and aggregate collection.

Local checks: shell dispatch/stop-on-failure/unknown-suite tests, workflow aggregate contract,
Node collection identity/union regressions, full 39-test project union and 4/16/6 contract
collections, typecheck, ruff, and release/version source validation. CI-only changes do not need
UI screenshots; real emulator/browser execution is validated by hosted CI. No successful local
collection is presented as a browser runtime pass.

Reproduce collection verification with:

```bash
npm --prefix web ci
node --test web/scripts/check-account-sync-partition.test.mjs
node web/scripts/check-account-sync-partition.mjs
```

For runtime reproduction, install the workflow dependencies, prepare the Local fixtures, start
the migration harness as in the workflow, then use a fresh emulator for each invocation of
`sh scripts/run_account_sync_suite.sh <chromium|ipad-webkit|iphone-webkit|contracts>`.
Do not share an emulator between simultaneous shard commands.
