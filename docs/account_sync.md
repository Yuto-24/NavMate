# Account Sync (#185)

Google ログイン済み端末間で Project と Last Calculation を Firestore へ同期する契約の正本です。`gzip-v1:` による大容量ペイロードの可逆圧縮（1,000,000 UTF-8 bytes 上限）、CAS 競合時の明示選択（Local / Remote / Both）、削除 Undo と `PENDING_DELETE` 期限を規定します。アカウント削除と世代分離は [Account deletion](account_deletion.md) を参照してください。

Local mode composes `AccountProjectRepository` with `AccountSyncController` and
`AccountSyncRepository`. The initial remote adapter uses the existing Firebase SDK's
Firestore transactions and snapshots. Domain Project / WorkingCalculation schemas and
UI have no Firebase types, document paths, or server timestamp fields.

## Setup

Enable Google authentication as described in [authentication.md](authentication.md).
Create the default Cloud Firestore database in the same Firebase project, in production
mode, then deploy this repository's `firebase/firestore.rules` and
`firebase/firestore.indexes.json` with the Firebase CLI:

```sh
firebase deploy --only firestore:rules,firestore:indexes --project YOUR_FIREBASE_PROJECT_ID
```

Deployment changes the remote project's security policy and requires explicit approval.
Do not use test-mode public rules or an admin/service-account credential in the browser.
The configured Local build automatically enables Account Sync after login; the standard
Compose Legacy UI retains its existing server persistence. No remote deployment is
performed by the implementation PR.

Rules compare the path's Google subject with the authenticated token's Google identity,
not with a client-supplied account_id, email, display name, or arbitrary Firebase UID.
Unknown paths and physical tombstone deletion are denied. Payloads are JSON strings so
ordinary Project JSON, including nested arrays, remains independent of Firestore types.
The adapter's document-size/quota failures preserve the Local outbox and show their
impact on cross-device continuation; no Local Project is evicted or switched to Legacy.

## Large Project payloads

The Firestore envelope remains schema 1 with its existing string `payload`, document
path, CAS version and revision. Local IndexedDB and domain records remain unchanged.
Both the browser adapter and Legacy REST adapter understand these two representations:

- Existing JSON text.
- `gzip-v1:` followed by canonical standard Base64 of gzip-compressed UTF-8 JSON.

Writers try gzip at 256 KiB and keep it only when its Base64 representation is smaller.
The stored payload budget is 1,000,000 UTF-8 bytes, leaving room for the normal envelope
under Firestore's 1 MiB document limit. Compression is lossless: no Project field,
checkpoint, calculation, provenance or numeric precision is dropped. Readers continue
to accept valid historical uncompressed documents above the new write budget.

Decoded payloads are bounded at 16 MiB, including during streaming decompression, to
prevent compressed data from causing unbounded allocation. Invalid Base64, corrupt or
truncated gzip, invalid UTF-8/JSON and identity mismatch fail closed. If a new record
exceeds the decoded limit or cannot fit the stored budget after compression, the whole
atomic write group fails before writing; Local data and its pending outbox stay intact.
This format does not provide unlimited-size storage or split records into chunks.

Legacy receipts retain the original JSON and compare decoded content, so encoding is
not a new Project identity or operation version. Lost acknowledgements and retries
continue to use the existing CAS and receipt rules. Both migration and ordinary Account
Sync must use this codec; fixing only the first import would fail on a later edit.

### Rollout and older clients

When deploying payload compression updates, deploy the NavMate reader/writer before enabling the updated Legacy migration server so browser clients capable of reading `gzip-v1:` payloads are in place before Legacy migration can produce compressed documents.
New code reads existing JSON without a database rewrite. Older browser and Legacy adapters
cannot parse `gzip-v1:` as JSON and stop before overwriting that Project. Old tabs may
therefore report a sync/read failure after a large Project is saved; update them while
preserving their Local data and any pending edits.

During the window after NavMate is deployed and before the Legacy migration server is updated, Legacy migration reads only the Project IDs in its migration plan. Unrelated compressed Projects in NavMate do not affect migration, but migration fails if an older Legacy adapter reads a `gzip-v1:` document for an ID in that migration plan (for example, on retry after a partial migration if an updated NavMate client wrote or updated one of those IDs).

When that failure occurs, migration returns the account to `LINKED` while keeping Legacy source files, existing Local/remote data, and completed batches intact. After updating the Legacy migration server to support `gzip-v1:`, retry migration through the existing flow in [Legacy migration](legacy_migration.md#data-and-retry) without creating duplicate Project IDs.

Until both the Legacy migration server and old browser tabs are updated, compressed documents remain unreadable to those un-updated components. A rollback to old code cannot read
compressed documents and is not a transparent recovery procedure. Rules and indexes remain
unchanged across this format compatibility layer.

Verification covers a shared Python/browser wire vector, byte-for-byte restoration,
size limits and corrupt input, compressed REST lost-ACK retry with existing receipts,
real SDK/Rules CAS and atomic failure, old-tab pending writes, browser re-save and fresh
device restoration including Last Calculation. Fixtures are synthetic; local/emulator
success is not production or physical-device acceptance.

## Durable contract

The #124 domain record remains checkpoint + draft + Last Calculation. The account
IndexedDB namespace adds separate sync metadata: an opaque CAS version, acknowledged
base, pending group, in-flight operation, conflict and deletion state. The Rules-enforced monotonic sync revision rejects delayed snapshots older than an
acknowledged save. UUID operation identities support CAS and idempotent replay. Explicit
Save revision remains independent of both. Autosave commits to IndexedDB
before any network operation; a failed network write cannot roll back a Local save.

A remote transaction writes every member of an atomic group, or none. Retries use the
same operation identity after a lost acknowledgement. Local edits during transmission
stay dirty against the acknowledged base. Initial download and snapshot invalidations
union all synced Project bodies and Last Calculations into Local storage. Idle retry
ticks do not repeatedly download the entire account. The SDK's cache or optimistic
snapshot is never proof of a committed server write. Synced data can then be listed and
opened offline; this does not supply an offline application shell or cache every runtime
asset (#187).

Anonymous records are durably claimed once by the login account and remain as recovery
originals in the anonymous store, hidden from anonymous use and other accounts. Claim ownership
is part of the anonymous transaction snapshot: a stale Latest replacement or Project open
conflicts if another tab claims a candidate before commit. Latest cleanup also excludes
claimed rows inside the write transaction, preserving originals for interrupted import recovery. Named
Projects enter the account union immediately. Anonymous Latest is staged in the account
Local Repository immediately and remains readable/editable offline. Its upload waits for
the first successful remote union so an existing cloud Latest for this device cannot be overwritten.
If Latest collides, the account Latest remains and a blocking modal asks for a named save
or discard of the claimed Local Latest. Closing/reloading before choosing preserves it.
A failed initial remote connection retains the staged working copy and claimed originals and retries automatically.

A browser origin/profile has one device identity. Account Latest belongs to the last
editing device; merely reading it does not transfer ownership. Opening another Project
or replacing that device's Latest creates a durable tombstone for the discarded Latest.
Other devices' Latest and all explicit checkpoints remain. A conflict copy is a normal
saved Project with a new UUID and independent revision, never a second Latest.

## Conflict and recovery

The first stale edit is retained locally, then additional edits are blocked until an
explicit Local / Remote / Both choice. No silent last-write-wins or field merge occurs.
Both retains the remote UUID and copies the Local branch to a new UUID. Project,
revision, calculation selection and copy are one IndexedDB transaction and one remote
transaction. A repeated conflict retries the same unpublished copy instead of publishing
extra copies. A committed copy keeps its own identity.

Each chosen Last Calculation is rechecked using the existing Python input fingerprint.
A stale result is omitted, never attached to a different Project state. Copy reidentifies
the matching Project/outcome without changing its calculation provenance. Session
recovery retains an opaque repository baseline (checkpoint and CAS base) so a reload
cannot replace an old working checkpoint with a newer remote one before detecting the
first edit's conflict. This baseline is stripped before Python hydration and never synced.

Explicit checkpoint Load commits the replacement draft and any own-device Latest
tombstone as one Local transaction and remote mutation group. It retains Last
Calculation, and remote CAS still requires conflict resolution if another device has
changed the Project. Inspecting a Load that is cancelled must not replace the active
session's repository baseline. Opening the branch selected by conflict resolution
uses that branch's draft; it is not another checkpoint Load.

## Delete and Undo

Deletion atomically stores PENDING_DELETE plus its deadline and hides the Project
immediately. A snackbar offers Undo for approximately ten seconds. The pending state and
Undo deadline sync to other devices. Undo creates another CAS operation restoring ACTIVE.

At the saved deadline, PENDING_DELETE is **effectively DELETED**, even when no browser is
running. Firestore Rules use request time to reject resurrection of an expired pending
record; correctness does not depend on unload or a server timer. The next client sync
normalizes the stored label to DELETED. This is a durable tombstone, not physical deletion
or a user-facing Trash. An offline deletion keeps its original deadline until uploaded.
A stale Local branch can be preserved as a new UUID, but cannot revive a deleted UUID.

## Verification

```sh
npm --prefix web run test:application
AUTONAVLOG_TEST_FIXTURES=1 npm --prefix web run prepare:local
npm --prefix web exec -- playwright install chromium webkit
npx --yes firebase-tools@15.10.1 emulators:exec --only firestore --project demo-autonavlog-sync \
  "npm --prefix web run test:firestore && npm --prefix web run test:sync"
```

Use Java 21 and the repository's supported Python/Node environment. Emulator tests use
the real Firebase SDK with synthetic authenticated Google identities; no live account
or production data is involved. Browser tests cover Chromium and iPhone/iPad WebKit
profiles. The routed HTTP emulator harness forces the SDK's
[long-polling transport](https://firebase.google.com/docs/reference/js/firestore.firestoresettings#firestoresettings_experimentalforcelongpolling)
because WebKit can buffer its streaming response indefinitely. Production uses the SDK
defaults; emulator success does not verify that transport on physical Safari. Windows
Edge is also exercised separately. These profiles do not constitute physical Safari
acceptance.

Physical acceptance must use the configured Local build and deployed Rules: create and
calculate on Windows Chromium, open on iPhone/iPad Safari with the same account, edit
offline and reconnect, resolve each conflict choice, test delete/Undo/expiry, restart
after sync, and check another account cannot see those Projects. Keep #185, #183 and
#116 device acceptance gates open until this is recorded. Cloudflare owner linking and first-use activation are documented in
[Legacy migration](legacy_migration.md).
