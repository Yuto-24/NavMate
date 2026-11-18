# NavMate Web design system

This directory freezes the implementation reference for the responsive Web UI.

> **Current layout summary**: Route creation/re-edit and flight planning use **one map and one operation pane** (#416). Above 700 px, the map sits on the left and the operation pane on the right (only operation contents scroll); at 700 px and below, the map precedes the operation pane without pinning over inputs. Readiness and calculation sit at the operation footer, with NAV LOG (Summary → horizontal table → TIME/FUEL PLAN → guidance) below the workspace.
> The 2026-08-13 fidelity ledger and concept images below predate the green theme and #132/#218/#416/#443 revisions and are retained as historical baseline only.

## Concept images (historical 2026-08-13 baseline)

- `primary-workspace.png`: KML/KMZ import, flight-plan input, route map, and
  readiness status in one desktop workspace.
- `calculated-review.png`: calculated NAV LOG and confirmation items.

The images are visual references only. All labels, inputs, tables, map markers,
and actions remain code-native and accessible.

## Tokens

| Token | Value | Use |
| --- | ---: | --- |
| `--brand-950` | `#194638` | headings |
| `--brand-900` | `#225c4d` | primary actions |
| `--brand-800` | `#1b4b3f` | action hover |
| `--brand-accent` | `#225c4d` | selected controls and focus |
| `--color-navy-950` | `#0b1f33` | aviation point indices and map tooltip text |
| `--color-navy-800` | `#173b5e` | route line |
| `--color-teal-700` | `#0c7c78` | VREP/manual values/automatic success |
| `--color-amber-700` | `#a8660d` | confirmation items |
| `--color-red-700` | `#b42318` | blockers and unavailable values |
| `--color-slate-50` | `#f7f9fb` | utility rails |
| `--color-slate-200` | `#d8e0e8` | borders and dividers |
| Body text | `#252c35` | charcoal text on white |
| `--color-white` | `#ffffff` | primary canvas |
| `--radius-sm` | `6px` | fields and compact controls |
| `--radius-md` | `10px` | purposeful panels |

The green brand palette is separate from warning, error, aviation-map, VREP,
and manual-value colors. Selected controls retain checked markers or underlines;
keyboard focus uses a solid pine-green outline on white, and a white inset on selected segments.
Custom radio controls use `:focus` for their visible focus treatment: WebKit
can clear `:focus-visible` after arrow-key selection while retaining DOM focus.
`map-checkpoint.spec.ts` covers Tab entry and arrow-key selection in both engines.
The historical fidelity ledger below predates the green theme.

The primary background is true white. There are no gradients, glow effects, or
decorative cards. Shadows are reserved for temporary overlays.

## Typography

- UI and content: `Inter`, `Noto Sans JP`, system sans-serif fallback.
- Page title: 22–24 px / 700.
- Section title: 16–18 px / 700.
- Controls: 14 px / 600.
- Table/body: 13–14 px / 400–600.
- Supporting text: 12 px / 400 with at least 1.5 line height.

## Component inventory

- A white, 56 px sticky header keeps the adopted NavMate icon, current Project menu,
  Save, New, Account and More on one row. Desktop also displays the NavMate name.
  Project names truncate in the trigger; its title and the wrapping text in the panel
  expose the full name. The panel contains the existing name input, revision and saved
  Project selector with separate Open/Delete buttons. Selection alone performs no action.
  Save/New retain their accessible names and show only icons at 630 px and below.
- Local Account uses UserRound when signed out and CircleUserRound when signed in;
  its accessible name includes the state. Local and Legacy dialogs render into the
  document body so the sticky header cannot constrain their overlay order. Existing
  authentication, Local-first synchronization and Legacy migration remain unchanged.
- More carries the normal green unread dot or amber Known Issue update dot and the
  corresponding accessible notification. Its panel contains Information, the version,
  existing ground-preparation description and storage location. Opening More does not
  mark notices read; opening Information does. No `/ Local` suffix is displayed.
  The form/disclosure panels use native buttons and Tab order (not ARIA menu roles).
  Escape restores trigger focus; leaving the panel or clicking outside closes it.
- Draft route confirmation leads to one Planning pane with a compact readiness/calculation footer; no separate numbered progress rail.
- NAV LOG calculation success uses a non-blocking, polite live-region toast at the
  bottom right, below modal overlays. It closes after five seconds or via its close
  button without changing layout, results, or readiness. Ordinary App, authentication
  and synchronization notices also expire after five seconds; unresolved failures
  remain in their owning history/dialog. Persistent storage warnings and inline
  validation are not transient Toasts.
- KML/KMZ drop zone and paste dialog.
- Multiple imported route candidates are chosen in a dialog; the resulting ordered points stay in the shared Draft card until route confirmation.
- Flight-plan fields: DATE, ETD JST, read-only KML-derived FROM/TO, FUEL
  (default 90 gal), RUN UP, nose fairing, A/C, VAR, and TGL.
- Route map with airport, waypoint, VREP, RCA, EOC, and CP markers.
- Check Point creation starts with the corresponding Leg's `CPを追加`, followed by a
  map click, then a single Add/Save action (with a close icon). Further map clicks
  can replace the pending coordinate without a second activation button. Each Leg shows its CPs in along-Leg distance order, with rename/delete
  controls and projection errors. Orphaned CPs remain accessible. No manual coordinate input.
- Draft and route re-edit maps support full-screen display and keyboard/touch return,
  without remounting the map or resetting the draft, selection or viewport.
- The route timeline distinguishes points from their outgoing Legs. TC, MC, distance,
  cruising altitude and flight phase belong to the Leg between its endpoints. Altitude
  presets show a numeric field and unit only for a custom value. Fixed altitude rules,
  VREP passage altitude, arrival airport elevation and adopted pattern altitude remain intact.
- The operation-pane footer contains a compact readiness summary and calculation button.
  Details retain next action, provenance, blockers, confirmation and acknowledgement
  controls. New blockers expand details automatically; warnings remain manually expandable.
- NAV LOG Summary above the main table with canonical TTL DIST and TTL TIME, plus
  destination TAF wind as reference data.
- NAV LOG result table aligned to the 19-column 別添8-1 layout. FROM and TO stay
  visible while the table scrolls horizontally; VOR/DME remains scrollable.
- TIME / FUEL PLAN below the main table, outside its horizontal scroll region.

## Container and responsive rules

- The Header remains one row from 320 px through desktop widths. Only the Project
  name shrinks; Save, New, Account and More keep 40 px targets. At 630 px and below,
  hide the redundant product name and Save/New text, retaining the adopted icon.
  Sticky positioning reserves the header's normal-flow height. Root scroll padding
  keeps focused/scrolled-to content below it. Panels stay within the viewport and
  scroll vertically on short screens. Header/panels sit above map controls and below
  modal dialogs and blocking calculation overlays. Persistent message bars stick below the
  header at 56 px. The redundant workflow step rail is omitted.
  `web/e2e/header.spec.ts` checks 320/390/1100/1239/1240/1241/1440 px before and after
  scrolling, including workflow positions, long names, keyboard access and overlay order
  in Chromium and WebKit. Account and persistence suites cover their existing operations.
- Above 700 px, Draft/re-edit and flight planning align the map on the left and the
  operation pane on the right, including 820/1100/1240/1241/1440 px. Only operation
  contents scroll; imports, Draft actions and the planning calculation footer remain usable.
- At 700 px and below, the map precedes the operation pane without covering inputs.
  The Draft point list may scroll, but the map does not stay pinned over the form.
- NAV LOG remains below the workspace. Its Summary, horizontal table scroll region,
  TIME / FUEL PLAN and vertical page flow are unchanged.
- Do not hide blockers, confirmation controls, required sources, or action reasons
  at any viewport width. Keep revision provenance accessible through Details at every width.
  Keep linked OpenStreetMap attribution visible even in
  the empty-map overlay.

## Copy lock

Above the fold may contain only the product identity, the three workflow steps,
the imported route controls, flight-plan labels, `準備状況`, its next action,
reference provenance, and the current primary action. Marketing copy, claims,
metrics, badges, and unrelated navigation are prohibited.

Information is a low-priority utility inside More. The More unread indicator is the only
copy-lock exception; it must not displace the workflow rail or move a workflow region.

The generated Information snapshot uses a namespaced SHA-256 content ID over every user-visible
entry, excluding internal IDs, GitHub Issue references and parser source-line metadata, using stable key ordering. The browser stores that
ID under `autonavlog.information.lastSeenUpdate`. The legacy `lastSeenRelease` value is retained and
migrates only when the immutable `a4a92da` v1.10.0 baseline ID matches exactly; unknown, malformed,
or same-version-changed values remain unread. `autonavlog.information.knownIssuesSeen` separately stores
Known Issue IDs and visible-body hashes. Additions/edits warn in amber and in the accessible name;
removals/reordering produce only the normal dot. Opening the dialog marks everything read immediately.

The dialog subtitle is `NavMateのお知らせ`. Show `既知の不具合` first (hide the entire section at zero),
then `更新履歴`, with all historical entries expanded. Known Issues use amber panels, distinct from runtime
errors. User-facing content comes from `KNOWN_ISSUES.md` and the 利用者向け section of `CHANGELOG.md`, with no developer Issues,
distribution section or implementation jargon. Release dates are stored by GitHub Releases and are not
displayed in Information. See [the release workflow](../release_lines.md).

## NAV LOG layout revision (Issue #132)

The historical calculated-review.png concept predates the NAV LOG Summary and
separate TIME / FUEL PLAN requirement. The current reference flow is NAV LOG
Summary, horizontally scrollable main table, TIME / FUEL PLAN, then guidance.
The 2026-08-13 fidelity ledger below remains historical evidence for the
earlier calculated view; current Playwright coverage verifies this revised
layout at 390 px, 1,100 px, and 1,440 px.
JSON download/copy actions follow the NAV LOG and its applicable guidance, outside the
horizontal scroll region, with a 1rem top margin and the same content inset and
maximum width as NAV LOG. Buttons retain their 0.5rem gap and wrap on narrow screens.

## NAV LOG main-table grid (Issue #276)

The paper-derived columns have 2 px right-hand rules after TO, TAS, MC, MH,
ZONE/CUM ETE, ETO, and ATE; other internal column rules are 1 px. The outer
frame and header/detail boundary are 2 px, while body-row rules are 1 px dotted.
Leg separator rows retain their blank content and short height, but render one
cell per column so vertical rules continue through them. No extra heavy rule
marks a leg or phase change. TIME / FUEL PLAN is unchanged.

Rules are indexed from the fixed right-hand FUEL column so additional leading
VOR/DME columns cannot shift them. Separate cell borders keep FROM/TO rules
attached to those sticky cells during horizontal scrolling. Browser assertions
in `web/e2e/helpers/navLogGrid.ts` check every column and row type, added/removed
VOR columns, scrolling, and print media; the existing workflow-order test covers
1,100 px and 1,440 px. These criteria come from the explicit Issue #276 contract;
this implementation does not establish visual parity against the original paper
image, which was not available in the repository or issue attachments.

## Implementation fidelity ledger (verified 2026-08-13 JST)

### Render and inspection method

- Accepted concepts: `primary-workspace.png` and `calculated-review.png`.
- Verification execution date: 2026-08-13 (`Asia/Tokyo`).
- Implementation renders: Playwright Chromium against the built FastAPI-served SPA.
- Native desktop viewport: 1440 × 1000.
- Native mobile viewport: 390 × 844; the mobile image is a full-page capture.
- Screenshot evidence is written to the Playwright test output and is not
  version-controlled in this directory.
- The requested `agent-browser` binary was not installed, so the documented Playwright
  Chromium fallback was used. Its screenshot artifacts were inspected at native aspect ratio.

### Concept-to-implementation comparison

| Area | Concept | Implementation | Result |
| --- | --- | --- | --- |
| Header | Navy product bar, version, Information, project identity, save/new actions | Explicit one/two-row Header; unread dot at every width, amber only for Known Issue additions/edits | Historical; superseded by Issue #218 above |
| Workflow | Three numbered stages directly below header | Route, flight plan, review/calculation rail with completed states | Historical; superseded by Issue #416 above |
| Desktop layout | Input / route / readiness columns | 24% / fluid / 25% three-column workspace | Historical; superseded by Issue #416 above |
| Route workspace | Map over compact POINT/ROLE/ALT/PHASE table | Leaflet/OSM route, airport/VREP/RCA/EOC markers, editable Leg table | Historical; superseded by Issue #416 above |
| Readiness | Provenance, next action, blockers/confirmations, primary calculation action | Same order; duplicate causes collapsed by code/Leg/segment | Match |
| Calculated view | Dense NAV LOG, destination TAF wind, and fuel strip | 19-column NAV LOG plus reference wind and TIME/FUEL tables | Historical; superseded by Issue #132 above |
| Visual language | White canvas, navy/teal, amber/red status, thin borders, no gradients | Same token family and restrained radii | Match |
| Mobile | Single-column stack with all safety/status content retained | 390 px stack, full-width controls, no body horizontal overflow | Match |

### Copy and data differences

- Concept project/route values were illustrative; implementation copy comes from the real
  Project, reference manifest, performance manifest, CalculationOutcome, and Issue models.
- The initial implementation render shows a purposeful empty map state because no KML has
  yet been selected; the primary concept showed a populated example route.
- Destination labels show the 100 ft rounded circuit altitude (`1,000 ft`) and verification
  status. The VREP row shows the standard 5 NM altitude (`1,500 ft`).
- The fixed development weather mode and bundled unverified airport references intentionally
  add fail-closed blockers that were not present in the polished concept.

### Intentional remaining deviations

- The concept map is a generated static geography; implementation uses live OpenStreetMap
  raster tiles and remains usable when tiles are unavailable.
- At desktop height, long readiness lists scroll inside the right rail so the calculation action
  remains reachable.
- The current bundled RJFM/RJFO reference rows remain `UNVERIFIED`; visual fidelity does not
  override the primary-source release gate.
- New work defaults to FORECAST; saved FTD plans retain their selected weather mode.

## Provenance disclosure and map credits

Readiness keeps the weather mode visible. Reference/performance revisions and the
`ftd-fixed-v1` result ID are available in its native `詳細` disclosure; the stored values,
calculation fingerprints and real forecast run IDs are unchanged. The duplicated footer
revisions are removed. Static map-precision/date, altitude-rule and ground-preparation
explanations are removed from the normal view; conditional warnings and calculation
conditions remain independent of this display choice.

Map credits are separate from revision metadata. The base layer still displays its
OpenStreetMap copyright link on the map, as required by the
[OSM tile policy](https://operations.osmfoundation.org/policies/tiles/).
The live `kokuarea_minkankunren` GeoJSON is fetched from GSI, validates/extracts the
approved KS4 features, and renders them over the base map. While those layers are
displayed, their credit joins the existing bottom-right Leaflet attribution, keeping
the linked MLIT source page and GSI layer page plus the processing indication.
There is no separate explanation row below the map. The combined attribution uses
12 px text and wraps within the map at narrow widths. The legend sits above the
measured attribution height, including after resizing; the OSM credit stays visible
when airspace is unavailable. Source links retain the platform external-link behavior.
This credit is not moved behind Details: both the
[GSI terms](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html) and
[MLIT terms](https://www.mlit.go.jp/link.html) require source identification, with a
processing indication for edited content. The current GSI tile-list page did not expose
the individual layer entry to the text reader; this was not treated as permission to
omit a credit or as proof of a layer-specific exception.

The compact credit text was determined with Gemini CLI (`gemini-3.8-flash-medium`):
`国土交通省・国土地理院データを加工`.
This live GSI source is unchanged; the attribution exemption for Shapefile/KML
from the AIP ZIP does not apply to this implementation.


## New MAP routes (Issue #174)

New work uses the #416 accepted compact Draft card: a 320 px card beside the
predominant desktop MAP, with aligned 48 px file/paste controls and an orange
route confirmation action. At 700 px and below, the MAP precedes the card.
KML/KMZ and map selection share the same Draft. Planning and Readiness appear
only after confirmation, in one right-hand pane above 700 px and below the MAP
on phones. The final accepted stock prototype defines the visual spacing,
muted waypoint dots and connecting line. Draft edits do not auto-fit or recenter
the MAP; fullscreen keeps the same map instance and viewport.
ETD is a 24-hour HH:mm entry without locale-dependent AM/PM controls.

Confirmation moves the viewport and keyboard focus to the flight-plan DATE input
after the confirmed Project's Planning DOM is committed. A frame callback may run
before React mounts that panel, so the focus request is retained until the panel
exists and consumed once. A committed route with a storage error keeps the error
message in view while focusing the Planning input. Existing MAP regressions cover
the frame-before-commit order without replacing the Local Worker or calculation.
The Local test helper holds renderer host tasks until it observes the requested
focus frame, including when asynchronous confirmation schedules that frame after
an earlier renderer task. Deferring a task by one frame alone does not establish
this order.


Checkpoint entry (#224 / #272) uses the same validation and save path for the
name input's Enter key and the existing Add/Save buttons. Composition state,
`isComposing`, `keyCode === 229` and repeated keydown events do not submit.
A synchronous save lock covers Enter/click mixtures until the asynchronous save
settles; failures retain the draft and permit retry. Each MAP coordinate pick
focuses the mounted name input once and scrolls it into view; ordinary draft
updates and manual focus changes do not focus it again. Opening or editing a
checkpoint without a MAP pick does not request name focus.
`web/e2e/checkpoint-enter.spec.ts` covers Local and Legacy, including 390/1100/1440px
MAP-to-name-to-Enter flows. Composition events are simulated; these checks do not
establish physical IME behavior or mobile software keyboard activation.

### #416 個人確認フィードバック

- 確定済み経路は KML/KMZ の情報とアクセス可能な領域名を保持し、重複する可視見出しを出さない。ファイル名と内包ファイル名は完全一致した場合だけ重複を省く。
- ETD は `HH:mm` の直接入力を保持し、24 時間の時計ダイアログからも選べる。ダイアログ内の編集は確定まで計画に反映せず、取消・Escape で破棄する。AM/PM は使わない。
- CP の名称必須・関連 Leg 判定は維持する。入力中に名称欄が動く赤い警告ブロックではなく、画面の高さを変えないスクリーンリーダー向け live status を使用する。範囲外の地点を別 Leg に自動で付け替えない。
- 高度の任意値選択には直下の注意を表示する。既存の候補外警告が該当する場合はそちらだけを表示し、計算・高度候補の規則を変えない。
### Notification layout (partial #443)

Ordinary App success/error messages and the calculation-complete Toast share a
fixed, non-modal region. Showing or closing these messages must not change the
workflow geometry or page scroll position. Toast text does not intercept clicks on
underlying planning controls; its explicit buttons remain operable. The region is fixed near the viewport bottom, is bounded by the viewport, and remains behind dialogs. Explicit
navigation to invalid planning inputs and a newly calculated NAV LOG is separate
and remains intentional.

App messages and provider authentication/synchronization notices now expire after
five seconds or manual dismissal. Expiration affects presentation only. Failed App
operations remain inspectable in the existing Header “その他” panel; auth and sync
failures remain in the existing account dialog with the existing available recovery
actions. Operation keys prevent a successful unrelated operation from clearing
another failure. A cancelled Project load does not count as a successful retry.
Sync Undo failures are retained separately by item.

Persistent storage warnings, blocking dialogs, inline validation and project
deletion Undo are not transient Toasts and are unchanged. The focused harness
checks notification timing, independent failure retention/recovery, layout and
existing ten-second Undo with a synthetic sync transport. It does not establish
live account/network behavior, all calculation/focus paths, or every validation
state; complete repository suites and UI copy-review gates cover those separate boundaries.

Focused regression: `npm --prefix web run test:notification`. PR/main CI runs
all 18 cases in the existing Local `auth` runner after preparing Local assets.
The dedicated loopback harness
uses the real App/Application and an in-memory invalid file, not personal data.
