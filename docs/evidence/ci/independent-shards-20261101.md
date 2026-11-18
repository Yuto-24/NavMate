# Independent CI shards

## Purpose and boundary

Reduce the elapsed time of Local browser and Python checks without removing tests or checks.
Account Sync is a separate change; this PR alone does not establish a ten-minute workflow.
No paid/larger runner, repository permission, merge rule, release version or deployment changes.

## Hosted baseline

The latest completed main run when implementation began was
[41256028478](https://github.com/Yuto-24/AutoNavLog/actions/runs/41256028478)
on `aa8dd0a90b24d49bf22279706fdacea0285175bb` (2026-11-01):

- Workflow elapsed: 13m46s.
- Account Sync: 13m31s; intentionally unchanged in this PR.
- Python: 12m45s, including Docker build 79s and checks 681s; pytest itself 655.39s.
- Local browser: 10m37s, including dependency installation variability.

A separate [PR326 run](https://github.com/Yuto-24/AutoNavLog/actions/runs/41266357658)
had successful Python in about 9m26s and Local browser in about 13m33s.
Its failed Account Sync run did not execute migration, so its shorter duration is not a
successful full-suite measurement. These different runs demonstrate variability, not a paired
speedup estimate.

## Partitioning and verification

Local uses the existing regression command on one runner; auth, scroll, all browser/device
acceptance projects and TAF run on another. Every existing command and worker setting remains.

Python collects the whole suite on each runner, then partitions files deterministically by
recorded duration. Keeping whole files preserves fixture scopes and test order. New files are
assigned automatically. Every shard exports the complete and selected node IDs; the aggregate
requires equal complete collections and exact-once coverage of that collection. It also requires
both coverage databases and combines them into one report. Existing non-pytest checks run on
both shards, and original `pytest` / `local-browser` check names remain required-style aggregates.

To refresh timings, run the unsharded suite with `--junitxml=<path>` under the same environment,
run `python scripts/pytest_timing_weights.py <path> > scripts/pytest_file_durations.json`.
The converter resolves unittest class names to their existing source file and fails on unknown
sources rather than silently recording class names as files. Recheck
the deterministic assignments and complete test/coverage union. Timing weights do not determine
which tests are eligible. Hosted full-run success and elapsed time must be recorded separately
from local timings; setup/queue time and CDN variability remain outside the partition estimate.


## Timing weights

The committed per-file weights sum JUnit testcase durations from a 2026-11-01 local unsharded
run of main `8d1fc040b1128ba3c85a766462ea88f5e1c588ea`: 2,360 collected tests, Python 3.12.14,
pytest 8.4.2; testcase time sum 260.421s and elapsed 265.42s. This run used an existing environment
with installed package 2.1.1, so the version assertion failed; the runtime-contract assertion also
failed against the in-progress matrix workflow. The remaining 2,358 passed. These are timing
weights, not a successful baseline validation. Final checks use an isolated 2.1.2 installation
and the updated contract that still enforces Python 3.12 while allowing test-suite matrices.

The largest file, `tests/unit/test_rjfm_inbound_guidance.py`, measured 145.99s locally and about
398s between file-summary timestamps in the hosted baseline. File-level sharding preserves its
order but cannot subdivide that critical path. Unmeasured new files receive the median measured
file weight and remain included automatically. The weights guide balancing only; final hosted
runtime remains the acceptance evidence.

## Issue #459: shared checks and current timings

The 2026-11-01 entries above describe the original partition, not the current check ownership.
The baseline is main `eb64a785` after #452/#458, with the complete responsibility table in
[testing.md](../../testing.md#issue-458-現行保証の担当とlegacy専用テストの廃止).
[Main Run 44239461740](https://github.com/Yuto-24/NavMate/actions/runs/44239461740)
passed all 29 jobs: 609s from Run creation to `ci-required`, 6,684s summed job duration.
Python shard 2 was longest at 569s (build 72s, checks 490s); shard 1 took 514s
(build 83s, checks 423s). These are individual hosted observations, not billing or CPU time.

### Ownership and retained repetition

- Shared release/lint/type/data/schema/package checks run on Python shard 1 only.
  Both shards still run pytest with coverage in their own Python 3.12 Docker test image.
  Their existing aggregate requires both successes and exact-once collection/coverage union.
  `run_ci_checks.sh` without arguments remains the full local validation command.
- Device sync runners no longer start the migration harness. Only `contracts` needs port 8186,
  and retains its startup, health check, cleanup, Rules, storage-upgrade and migration tests.
- The auth runner keeps its Local asset build for real Worker notification tests and the
  suite-owned Vite servers; it no longer starts the unused port 4174 HTTP server.
- Docker images remain independently built. No unmeasured image-transfer path, shared mutable
  environment, or new scheduler is introduced. Local preparation remains per runner because
  actual Worker suites require its wheel/data/manifest. TAF and backup builds have different
  configuration inputs and remain separate.
- `release-sources` retains PR body/base validation. `release-build` retains Node 24 release
  packaging; Docker's Node 22 build checks a different supported environment. These are not
  removed merely because the commands resemble shared Python/web checks.

The classifier, selected suites, device profiles, assertions, main full regression and
`ci-required` contract are unchanged. Tests/CI changes select all suites; documentation-only,
release-only, Python, Web and mixed-change fixtures continue to check the existing selection.
New Python files are still collected without an allowlist and receive median timing weight.
Whole-file partitioning retains fixture/order boundaries, so one heavy file can remain a limit.

### Local timing refresh

The unsharded baseline Docker test stage at `eb64a785` ran on 2026-11-18 with
Python 3.12.16, pytest 8.4.2 and pytest-cov 6.3.0: **3,640 passed, 1 existing skip**, no failures,
510.02s pytest elapsed, 91% total coverage. The existing skip is
`test_root_owned_build_cleanup_preserves_a_fixed_scope`: Docker's root role cannot exercise
that nonroot DAC regression. The separate static-tooling handoff job remains unchanged.
Release, ruff, mypy, data/schema validation and
sdist/wheel build also passed. JUnit testcase durations total 501.780s across 128 files.
`pytest_timing_weights.py` converted this report directly into the current weights; two deleted
Legacy files were removed and 29 previously unmeasured files gained timings.

| Assignment applied to the same measured files | Shard 1 | Shard 2 |
| --- | ---: | ---: |
| Old weights: measured testcase time sum | 198.296s (1 file) | 303.484s (127 files) |
| Updated weights: measured testcase time sum | 250.890s (62 files) | 250.890s (66 files) |

This table is a deterministic partition calculation, **not a measured CI speedup**. The largest
file remains `test_rjfm_inbound_guidance.py` at 198.296s. New CI regression tests introduced after
the baseline measurement deliberately exercise the median-default path until a later refresh.
The baseline is a local observation; short source checks and npm setup also ran on the host,
so it is not a controlled performance benchmark or a replacement for hosted measurements.

The first focused lint check found two overlong lines in the new CI source tests. They were
wrapped without changing assertions; lint and 206 focused classification/gate/scope/version
checks then passed. The full `release-sources` command subsequently passed 284 tests and six
UI evidence/source records; the browser partition's three Node source tests and Web typecheck
also passed. Browser automation and runtime deployment are
not applicable to this CI-only change under AGENTS.md; product code and UI copy are unchanged.

### Final local shard validation

Both updated shards completed successfully using the Docker test stage and the three capability
workflow mounts required by CI. They ran concurrently in separate containers on the same host;
this is not a hosted two-runner benchmark. The new tests were included through the normal
complete collection, with no timing-file allowlist.

| Local execution | Selected | Result | pytest elapsed | Container command elapsed |
| --- | ---: | --- | ---: | ---: |
| Shard 1, `run_ci_checks.sh all` | 2,042 | 2,041 passed, 1 existing skip | 255.72s | 267.609s |
| Shard 2, `run_ci_checks.sh pytest` | 1,617 | 1,617 passed | 254.40s | 257.071s |

The two container command durations total 524.680s; this excludes image build and is not
GitHub runner time. The baseline JUnit node IDs are all present in the final collection, plus
18 new CI regression cases. `check_pytest_shards.py` verified 3,659 collected tests exactly once
across both manifests. Both coverage databases combined successfully: 14,283 statements,
1,323 missing, 91% total, matching the baseline totals. Shared release/lint/type/data/schema
checks and package build passed on shard 1. The first final shard run and aggregate had no failures.

The real shard durations are close for this run, but comparing unsharded baseline elapsed time
to sharded elapsed time would overstate the change: hosted CI already had two shards.
Only the computed same-input assignment table above compares old and new weights directly.
No additional high-cost baseline matrix was run solely to turn this local observation into a
performance claim. Hosted representative-change comparison remains outstanding below.

### Acceptance boundary

The effective main Ruleset was read back on 2026-11-18: `ci-required` from GitHub Actions
(integration ID 15368, Ruleset 20705217) remains required. No repository rule was changed.
The old “main not yet accepted” knowledge entry was corrected using the successful baseline.

Changed-workflow hosted elapsed time, summed runner duration and first-attempt failures remain
unmeasured until the PR Run completes. CI/review monitoring is not authorized for this task;
pending results must not be reported as success or as a measured speedup. A representative PR
comparison and post-merge main acceptance remain separate from local Python measurements.
The five-minute target is unmet by the baseline; shared-check removal alone does not establish it.
