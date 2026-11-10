# v2.2.2 Project records

These synthetic records contain actual FTD/MSM calculations produced by the immutable
v2.2.2 source `03cc463cf09192e1403f839df4165410c5db8d7b`, installed as 2.2.2 with its
vendored `jma-gpv-weather` 0.5.0 wheel. They are not records obtained by deleting fields
from schema 5, and contain no production user data. The envelope uses the old validated
Saved checkpoint plus a distinct draft (`pilot_name = "unsaved draft"`). Tests also use
its checkpoint-null Latest variant. Hashes and source identity are in `provenance.json`.

To regenerate, archive that exact SHA to a temporary directory, install its package
and vendored weather wheel into a separate Python 3.12 environment, and run this
checkout's `generate.py OUTPUT` with `PYTHONPATH` pointing to that old checkout's
`src` and `tests/integration`. The generator asserts the installed versions. Use the
old `test_local_calculation.calculate`, not a helper imported from the candidate.
UUIDs/timestamps vary on regeneration; review and update the manifest with the records.

The original run used current Python dependency packages alongside the pinned weather
wheel; it does not reproduce every historical transitive package or the old deployed
Pyodide runtime. The candidate tests separately check actual normalization, hydration,
calculation freshness, and explicit conflict cleanup. Browser tests use frozen old
TypeScript storage/SDK adapters and real candidate Python validation. Their small old
reader predicate models the separately verified schema-5 rejection, not all old-domain
validation. See [the transition record](../../../docs/forecast_schema_transition.md).
