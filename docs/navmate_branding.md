# NavMate branding integration (#199)

プロダクト名 `NavMate`・リポジトリ `Yuto-24/NavMate` と、既存パッケージ／保存キー／環境変数名 `autonavlog` の互換境界、および承認済みアイコン派生アセットの再生成手順を定めます。

## Summary and dated rollout records

- **v2.0.0 branding merge (2026-10-24)**: [PR #285](https://github.com/Yuto-24/NavMate/pull/285) merged the **v2.0.0 naming/icon change** based on main `58127b3` (1.22.9) and branding commit `dfef4ba` (#282/#283 features excluded; PR #200 superseded and closed).
- **Repository identity**: `Yuto-24/NavMate` (repository ID `1314030412`). [Issue #199](https://github.com/Yuto-24/NavMate/issues/199) tracks reference alignment and existing-data acceptance. Implementation, merge, publication and user acceptance remain separate evidence.
- **Adopted icon source (2026-10-23)**: User-approved source PNG at `assets/branding/navmate-adopted-source.png` (SHA-256 `30faff87f7820ae4e62cc4c3b1bca016137b3af041672166472aaf5cf166c3e6`). `scripts/build_navmate_icons.py` uses Pillow 12.3.0 with deterministic crop `(26, 28, 1228, 1230)` to reproduce PNG (32/180/192/512 px) and ICO (16/32/48 px) derivatives. The manifest declares `purpose: any` (no service worker or offline capability).
- **Human-facing product name**: `NavMate` replaces the product name in the Web header, browser title, startup/information/disclaimer text, static 404 page, server fallback, API metadata, CLI help and current product documentation.

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

## Dated verification observations (2026-11-04 / 2026-11-08)

- [#187 home-screen/icon acceptance](https://github.com/Yuto-24/NavMate/issues/187#issuecomment-6630050367)
  was closed as completed on 2026-11-04 following the user's acceptance (no offline support implied).
- [#199](https://github.com/Yuto-24/NavMate/issues/199) records completed product-name
  updates. [PR #377](https://github.com/Yuto-24/NavMate/pull/377)
  corrected the static publication preflight; release/probe workflows,
  app-release, external-trigger and dispatch-receipt checks use `Yuto-24/NavMate`.
  (Note: the `autonavlog-msm-trigger` Worker itself was updated to the `Yuto-24/NavMate` fix commit on 2026-11-18; see [msm_external_trigger.md](msm_external_trigger.md).)
- Read-only observation on 2026-11-08 JST returned HTTP 200 for the canonical
  root, `/release.json` and `/manifest.webmanifest` (observed serving version: clean v2.2.0 at
  `2d344ce45a8a1a0ab25c659247afd4aef853977c`, dated snapshot only).
- Existing branding and persistence tests cover unchanged identifiers and
  synthetic Saved/Latest/Last Calculation records (IndexedDB v1/v2 and server storage/import). Separately, on 2026-11-08 JST the user
  confirmed that pre-rename Projects and Last Calculation open without
  problems in NavMate in their storage context.

## Separate production publication gate

The general release path accepts an explicit candidate commit. For a Rules change, the generic
[`--rules-transition` record](static_operations.md#rulesが異なる更新だけに必要な検証記録)
binds the selected candidate/project/Rules and reviewed evidence for both the old
application/new Rules and candidate application/new Rules to the prepared plan.
Reuse the historical v1.22.7 evidence within its verified scope and review/test
the candidate delta; identical Rules hashes alone do not establish app compatibility. Verify the actually deployed Rules,
indexes and schema. Keep current fail-closed checks intact; this candidate does
not authorize a Rules change or establish live production compatibility.
