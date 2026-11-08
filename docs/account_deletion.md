# NavMate Account deletion (#181)

The Account dialog starts deletion only after an explicit confirmation. The
browser requires a current Google identity, a fresh Firebase token, and a
server read of the corresponding account record. Offline or expired credentials
do not queue a deletion. Project deletion and its offline Undo remain the
separate #185 operation.
The Account dialog disables both deletion confirmation steps and deletion retry
while offline, with a persistent reason beside the control. Reconnecting updates
the control; the fresh-token and server-identity preflight remains mandatory.

The `googleAccounts/{subject}` record stores an internal account ID and one of
`ACTIVE`, `DELETING`, or `DELETED`. The first ID preserves the #184 deterministic
`account_v1_…` mapping and the existing #185/#186 Project path. Deletion first
commits `DELETING`; Firestore Rules then reject Project writes from every device.
The deleting device removes the account's remote Project documents in small
idempotent batches, removes its account IndexedDB namespace and anonymous
originals claimed by that ID, then marks the account `DELETED`. A failed cleanup
leaves `DELETING` in place and offers a retry after reconnect/re-authentication;
the old generation never reopens for normal syncing.

On another device, the next successful online account check closes its old
Application context, marks the cached generation unusable offline, and removes
that account's Local copies. Until connectivity
returns, the already cached Local copy can remain visible on that device, but
Rules prevent it from uploading. A deleted identity does not automatically
create a new NavMate account on token refresh. Detecting `DELETED`, or discovering
that the cached generation has been replaced, signs out this device's Firebase
session. A successor created on another device cannot reconnect it automatically.
The retired cache marker is retained until explicit login, so failed logout
persistence cannot reconnect a successor after reload. Logout failure keeps access
closed and offers the existing logout retry. `DELETING` still offers deletion
retry for the same generation rather than reporting completion. A replaced
generation closes authentication even if its successor is already `DELETING`.
If Local cleanup fails after confirmed deletion, authentication still ends and
the notice directs the user to close other tabs and explicitly log in to retry
cleanup before entry. An explicit Google login may
register a new `account_v2_…` ID. Its Project documents have a separate
generation path and cannot import Local rows claimed by an older account.
Other Google identities and their namespaces are unaffected. The Google Account
and Firebase Authentication user are not deleted.

The #186 Legacy link is tied to the original account ID. A newly registered
generation skips that migration so it cannot inherit deleted Legacy data. The
link dialog itself remains an authentication-only operation. #182 Share is not
implemented yet; a future Share adapter must gate access on the issuer's active
account generation and drain all snapshots before marking it `DELETED`.

The account record and Rules must be deployed together before exposing this UI
in a Local build. The first online login creates the account record; a returning
device with a cached ID may continue Local work during a transient outage.
Deleting account data is irreversible. Physical browser/production acceptance
must use a real Google account, deployed Rules, and two devices, and separately
verify the old device after reconnect plus a deliberate re-registration.

Account resolution carries the provider's current authentication generation.
Deletion invalidates outstanding resolutions before preflight and suppresses
same-owner token/focus refresh until cleanup finishes. Each asynchronous lifecycle
lookup checks that generation before changing the ownership cache or registering
a successor. External logout or an identity switch still closes the old
Application immediately; the new identity is resolved after cleanup finishes.

For #393, completion and deletion-detected notices omit the Google-account
explanation and re-use guidance. Pre-deletion warnings and `DELETING` retry
notices are unchanged. Gemini (`agy`, `gemini-4-argon-high`, 2026-11-08, conversation
`cb7e2200-aaaa-4ae4-b352-39ba7308e45d`) confirmed the three requested shortenings,
selected the offline explanation, and reviewed that wording scope.
The same model confirmed the signed-out Local-cleanup failure guidance separately
in conversation `356ec4f3-568e-47a9-94cf-54d472202cac`.

These automated checks do not complete #181 production acceptance. After a
separately authorized deployment, verify the changed two-device authentication
boundary, offline control, and notices with a dedicated test identity. Keep #181
open until its remaining production checks and roadmap update are complete.
