# Platform Capability boundary (#120)

`web/src/platform.ts` is the runtime contract. `main.tsx` supplies `browserPlatform`
and `BrowserFileInput` to the existing application/React composition. There is no
platform detection in feature components, DI container, registry, Native adapter,
or PWA requirement. A future shell supplies the same capabilities and its file-open
control at this composition point. Domain and Calculation Core do not import this
contract; Python/Pyodide still uses the existing Importer and CalculationService.

| Responsibility | Owner |
| --- | --- |
| File content acquisition, download, Clipboard, external URL, connectivity hint | Browser Platform |
| File picker/drop DOM events and file selection cancellation | `BrowserFileInput`, supplied by the composition root |
| KML/KMZ parsing, archive limits, document selection and route candidates | Existing `import_kml_or_kmz` / `import_kml_text` |
| Operations, working state, draft commit, calculation and error meaning | #118 Application |
| Reload-only adoption, snapshot validation, raw edits, recovery failure policy | #119 Application Session |
| Project / Latest / checkpoint / revision / Last Calculation, migration, transactions and conflict/quota policy | #124 Local Project Repository |
| Browser storage handles and creation of the existing IndexedDB Repository | Platform persistence access |
| Information read markers and fallback to in-memory markers | Information feature, using injected key/value storage |

## Files and Importer

Picker and drop both provide a content source to `files.read`. The result is
`PlatformFile { name, mediaType, content: Uint8Array }`; no filesystem path crosses
into Application or Importer. `fileInput.ts` only serializes bytes into the existing
`ImportRouteInput` contract (`filename` plus `content_base64`, or pasted `kml_text`,
and optional `kmz_kml_filename`). Filename identifies the format/source and the
selected KMZ member identifies a document inside the archive, never a local path.

The Browser rejects oversized selected files before reading them. The shared Python
Importer remains authoritative for archive, expanded-content, XML, coordinate and
route limits. Local and Legacy both call it; Local now supports compressed KMZ and
returns `KMZ_DOCUMENT_SELECTION_REQUIRED` with the same `details.candidates` as
Legacy. Pending bytes and document selection still belong to #119 reload recovery.
Picker cancellation is a no-op, reselecting the same file remains possible, and a
failed read/import preserves the previous candidates. No ZIP/XML parser was added.

## Result export and Clipboard

The NAV LOG actions serialize the displayed `CalculationOutcome` and destination
wind into UTF-8 JSON (`format: autonavlog.navlog`, `version: 1`). Edited Project
inputs are deliberately excluded: they may no longer describe that calculation.
This is a result document, not a Project backup or a second Repository schema.
It does not trigger calculation, checkpoint, revision or durable Project writes.
The existing Session lifecycle may still save its ephemeral working snapshot.

3D KML uses `project_vertical_profile` in
`src/autonavlog/application/vertical_profile.py`, shared with the future #55
time/altitude chart. The facade derives it exclusively from `last_calculation.project`
and `last_calculation.outcome`; it is not persisted as a new schema. The KML
serializer accepts only that projection and a stale flag, and saves through
`platform.files.save`. Editing or a failed recalculation leaves this projection's
source unchanged. A new successful calculation replaces it. Missing legacy
geometry or descent metadata disables KML export and asks for recalculation.
When an effective BLOCKER prevents a new Last Calculation, the displayed NAV LOG,
JSON and destination wind retain the same last successful snapshot as KML.
The current readiness status and failed-attempt diagnostics remain in readiness
and working recovery; an initial failure without a last success keeps its prior
failure display behavior.

The projection preserves calculation-zone time, distance, geometry and phase.
Climb uses the saved departure elevation and the first CLIMB target, interpolated
over its calculated elapsed time. Ordinary Leg altitude transitions use saved
elapsed time without restarting at Check Point splits. Descent uses the existing
metadata reader, inserts level-off, and retains the saved deceleration duration
(including zero). TO retains the calculated visual-arrival altitude; export does
not invent a landing descent. Dedicated RJFM return geometry stays on its saved
physical route and operational time; the exporter does not add a route extension.

RCA/EOC and Check Point abeam positions use the saved calculation boundaries.
Ground Check Points are separate from altitude-bearing route points, including
VREP. Their ExtendedData describes the abeam time/altitude/distance. Geodesic
sampling at intervals no greater than 1 NM prevents long absolute line chords
from cutting through the globe; it does not replace adopted zone distances.
The serializer converts feet MSL to meters and uses KML `absolute` altitude mode,
following the [Google KML reference](https://developers.google.com/kml/documentation/kmlreference#linestring).
Browser download/XML regression is automated; actual Google Earth rendering
requires a separate acceptance check.

Browser save uses a Blob URL and the standard anchor download attribute; it cleans
up the element immediately and revokes the URL after the browser can consume it.
Success means the download was initiated, not that the user accepted a save dialog
or the OS durably wrote a file. Clipboard write copies the same JSON text.

Clipboard read/write are invoked directly within the user's click activation,
without an earlier async permission probe. Unsupported and denied access produce
`PlatformError` with capability and `UNSUPPORTED` / `FAILED` codes. Read failure
opens the existing manual KML paste dialog; write failure is visible and never
reports a successful copy. Clipboard generally requires a secure context and
Browser permission; file input/download use standard Browser controls.
On Safari, WebKit may show its own Paste UI before resolving the read. The Browser
Platform still calls the native API directly on the click; the application does not
probe permission or bypass WebKit's confirmation. Rejected reads, including a
cancelled platform Paste UI, open manual paste with a direct route to the existing
Browser file picker. Automated WebKit checks can exercise the pending/rejected
promise path but cannot prove the physical iPhone/iPad Paste UI itself.

External reference links use a shared link component and `openExternalUrl`, allow
only HTTP(S), and open with `noopener noreferrer`. Standard anchor affordances
(modifier clicks, context menus and URL copying) are retained. Leaflet's map
attribution remains Leaflet-owned native link markup.
Opening a reference does not enter or finish an Application operation, so it cannot
clear another operation's busy/progress state or unlock a pending Project save.

## Storage and network

Platform supplies the sessionStorage-backed key/value handle, the localStorage
handle for existing Information markers, best-effort retention, and a factory for
the **existing** `IndexedDbProjectRepository`. `LocalApplication` receives only the
Repository factory. IndexedDB transaction mechanics stay inside that adapter.
Platform never lists Projects, manages Latest, advances revisions, validates
records, migrates schemas or decides transaction/quota retry policy.

Only #119 decides whether to adopt a session (same-tab reload), what key to remove,
and how to report failed recovery. Only #124 decides when to evict the disposable
Weather cache and retry a transaction. `browserStorage.ts` implements that existing
dedicated cache eviction callback; #144 still owns actual Weather cache data/TTL.
Unavailable storage does not trigger a Legacy fallback or delete Project data.

`networkAvailability()` is the requested minimal `online` / `offline` / `unknown`
hint from Browser connectivity, not a service health probe. It does not gate Local
import, calculation, storage or export, and does not report weather acquisition
success. Feature-specific fetch/error handling remains with its adapter. No
background polling, connectivity UI, share sheet or preference framework is added.

## Verification

- `npm --prefix web run test:application`: capability errors, byte preservation,
  injected Session/Information storage, existing Repository transactions, and
  architecture dependency checks.
- `platform.spec.ts` runs in both Legacy and production Local Browser suites:
  compressed KMZ picker, KML drop, cancellation/failure preservation, Clipboard
  activation and manual fallback, actual download/copy and denial, external links,
  pending-save isolation, and workflow positions at 1100/1440 px. Local blocks `/api/**` and also exercises
  calculation/export offline after assets have loaded.
- `session.spec.ts` covers KMZ selection/reload in both runtimes, with no Local skip.
- Existing Local calculation/IndexedDB and Legacy Clipboard/Session regressions
  remain in use. Python integration compares KMZ candidates with plain KML and
  checks explicit selection errors; existing Importer security tests retain limits.

These automated checks cover Chromium. They do not claim physical iPad/Safari,
Native shell, PWA installation, offline first-load, or production Static hosting
acceptance; those remain separate runtime/roadmap work.
