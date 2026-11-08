# Forecast recalculation (#356 / corrected #277)

An explicit calculation compares Forecast inputs with the **last successful
calculation**, using `forecast_selection_fingerprint`. Changed inputs keep that
Run. Unchanged inputs select the newest usable normal Run in that single action;
if no newer normal Run exists, the same usable Run remains selected.

For example: success with Run A → altitude edit → calculate with A → calculate
again without edits → select the newest normal Run. A warning is not required to
arm this behavior. Failed calculations do not replace the comparison baseline or
Last Calculation. Editing away and back compares the resulting inputs with that
same baseline, rather than maintaining a click counter.

## Identity and persistence

The existing fingerprint covers Project identity, timing, airports, route,
section altitude/phase/manual inputs, TGL, descent rate, aircraft settings,
planning/reference state (including adopted departure VOR), and rounding mode.
It excludes selected Forecast, save/revision bookkeeping and acknowledgements.
Typed planning normalization preserves equality across browser JSON number
roundtrips. The calculation fingerprint remains separate and identifies the Run
actually used; historical snapshot hashes are not rewritten.

Opening, restoring, saving and displaying a Project never acquire another Run.
The next explicit calculation compares with the restored successful snapshot.
If there is no successful Forecast baseline, a saved pin remains pinned. FTD
never requests Forecast refresh. A rounding change counts as an input change;
restored rounded results retain the existing rounding recovery rules.

Local acquisition replays the same user action after each requested catalog or
payload. Replay does not change the baseline or become a new user click. The
existing compute-only backup receives the same explicit refresh decision and
fixed model/Run identity. Adoption preserves Project, outcome, provenance and
Last Calculation together.

The calculation service defaults to pinned selection. Explicit refresh uses the
shared MSM→GSM policy. Missing or invalid MSM candidates may be skipped while
seeking a usable MSM Run; they never establish model exclusion. A missing fixed
Run is not replaced because acquisition failed. Actual model coverage exclusion
retains the existing MSM→GSM policy. A fixed Run outside changed inputs cannot be
updated simply by repeating that failed calculation.

## Old-Run Advisory

A current server catalog plus complete, library-validated data establishes the
latest usable MSM Run for the request. Cache-only or expired-catalog acquisition
does not establish current latest status. A pinned MSM Run at least three
3-hour intervals (9 hours) older receives `FORECAST_STALE_RUN`; newer Runs receive
no additional Advisory. The comparison records the selected Run, verified latest
Run, interval count and check time in the saved issue metadata. If latest status
becomes unknown, an existing verified Advisory for the same Run can remain with
its original evidence. Unknown status alone adds nothing.

The same Advisory appears in the Warning area in normal text color and next to
the NAV LOG fuel table. It does not block calculation or require acknowledgement.

## Regression coverage

- `test_project_fingerprints.py`: relevant inputs and excluded bookkeeping
- `test_local_calculation.py`: success baseline, edits/edit-back, Save, restore,
  failure continuity, rounding and FTD
- `test_local_forecast.py` / `test_msm_continuity.py`: portable replay, expired and
  cached catalogs, healthy older candidates, fixed-Run failures, model policy,
  Advisory boundaries and persisted evidence
- `local-weather-unit.spec.ts` / `local-weather.spec.ts`: bounded cache transport,
  real portable MSM, browser recalculation, saved NAV LOG and workflow layout

Catalog monitoring and publication gates remain separate; see
[Local Weather](local_weather.md) and [Static operations](static_operations.md).
