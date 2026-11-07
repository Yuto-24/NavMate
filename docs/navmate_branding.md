# NavMate branding integration (#199)

The **v2.0.0 naming/icon change** was merged in
[PR #285](https://github.com/Yuto-24/NavMate/pull/285) on 2026-10-24. It was based
on main `58127b3` (1.22.9) and branding commit `dfef4ba`; #282 and #283 features
were excluded from that minimal release boundary. PR #200 was superseded and
closed without merging; it remains historical reference.

The repository is now `Yuto-24/NavMate`, with the same repository ID `1314030412`.
[Issue #199](https://github.com/Yuto-24/NavMate/issues/199) tracks the remaining
reference alignment and records existing-data acceptance. Implementation, merge,
publication and user acceptance remain separate evidence.

The user-approved name `NavMate` replaces the human-facing product name in the
Web header, browser title, startup/information/disclaimer text, static 404 page,
server fallback, API metadata, CLI help and current product documentation.
Existing wording otherwise remains unchanged. The user approved the source PNG
on 2026-10-23. Its SHA-256 is
`30faff87f7820ae4e62cc4c3b1bca016137b3af041672166472aaf5cf166c3e6`.
The exact original is retained at `assets/branding/navmate-adopted-source.png`.
User-authorized deterministic crop `(26, 28, 1228, 1230)` removes extraneous
outer edges, preserving the rounded tile and aircraft. No alpha cleanup,
flattening, recoloring or image generation is performed.
`scripts/build_navmate_icons.py` reproduces PNG (32/180/192/512 px) and ICO
(16/32/48 px) derivatives using Pillow 12.3.0 and checks the original checksum first.
The manifest declares `purpose: any`, not an unverified maskable safe area;
no service worker or offline capability is added.

## Reproduce icon assets

From the repository root, create an optional, isolated tooling environment:

```sh
python3 -m venv /tmp/navmate-icon-tools
/tmp/navmate-icon-tools/bin/python -m pip install 'Pillow==12.3.0'
/tmp/navmate-icon-tools/bin/python scripts/build_navmate_icons.py
git diff --exit-code HEAD -- web/public
```

Pillow is only needed when regenerating the committed assets, not by the
application runtime. The final command verifies byte-for-byte reproduction
against the committed PNG/ICO assets; it does not discard changes.

## Compatibility boundaries

- Keep Python distribution/package `autonavlog`, CLI `autonavlog-web`, web package
  `autonavlog-web`, and the application interfaces unchanged
- Keep `AUTONAVLOG_*`, Compose projects/services/images, `autonavlog-data`, paths,
  authentication headers, owner-storage hash domain and generated-worktree marker
- Keep IndexedDB, Local/Session Storage, Weather Cache and export identifiers,
  Project schemas, Last Calculation and all existing migration logic
- Keep persisted reference-data provenance labels and historical release/evidence
  records; no branding-specific data migration is introduced
- Use `Yuto-24/NavMate` in active GitHub API targets, repository identity checks,
  workflow conditions and operator commands. Do not accept old-name redirects
  in publication or dispatch checks. Historical evidence URLs and reference-data
  provenance retain their original spelling; they are not current API targets.
- The existing `compose.local.yaml` Git clone URL is retained: on 2026-11-08 JST,
  `git ls-remote` through both names resolved `main` to
  `726cf95cf386b1f39c52d9babc57e68ecf29b705`. This Git compatibility path is distinct
  from the redirect-rejecting Actions HTTP clients. It does not require a local
  runtime replacement for this change.

## Current verification and remaining acceptance

- [#187 home-screen/icon acceptance](https://github.com/Yuto-24/NavMate/issues/187#issuecomment-6630050367)
  was closed as completed on 2026-11-04 following the user's acceptance. Its
  earlier unchecked body is not the latest status. No offline support is implied.
- [#199](https://github.com/Yuto-24/NavMate/issues/199) records completed product-name
  updates in current Open Issues. [PR #377](https://github.com/Yuto-24/NavMate/pull/377)
  corrected the static publication preflight; the remaining release/probe workflow,
  app-release, external-trigger and dispatch-receipt checks use the new repository.
  Public-repository checks, reviewed SHA, runner, origin/configuration checks,
  redirect rejection and publication verification remain in place.
- A read-only observation on 2026-11-08 JST returned HTTP 200 for the canonical
  root, `/release.json` and `/manifest.webmanifest`. The title and manifest names
  were NavMate; release metadata reported clean v2.2.0 at
  `2d344ce45a8a1a0ab25c659247afd4aef853977c`. This is the observed serving version,
  not evidence that the repository-alignment changes have been deployed or that
  the full inventory/payload publication gate passed.
- Existing branding and persistence tests cover unchanged identifiers and
  synthetic Saved/Latest/Last Calculation records, including IndexedDB versions
  1 and 2 and server-side storage/import. Separately, on 2026-11-08 JST the user
  confirmed that both pre-rename Projects and Last Calculation open without
  problems in the current NavMate. This is user-reported acceptance in their
  storage context, not a new claim of automated real-device coverage.

This alignment does not change `VERSION`, `CHANGELOG.md`, v1.x branding, storage
schemas/keys or runtime identifiers. It introduces no branding migration.
The Worker must be deployed through a separately authorized operation before its
updated GitHub targets are live. No production, Rules or scheduler changes are
authorized by this implementation; Legacy import remains enabled.

## Separate production publication gate

The general release path accepts an explicit candidate commit. For a Rules change, the generic
[`--rules-transition` record](static_operations.md#rulesが異なる更新だけに必要な検証記録)
binds the selected candidate/project/Rules and reviewed evidence for both the old
application/new Rules and candidate application/new Rules to the prepared plan.
Reuse the historical v1.22.7 evidence within its verified scope and review/test
the candidate delta; identical Rules hashes alone do not establish app compatibility. Verify the actually deployed Rules,
indexes and schema. Keep current fail-closed checks intact; this candidate does
not authorize a Rules change or establish live production compatibility.
