# Firebase Authentication, Account Sync, Deletion, and Legacy Migration Operations

This document holds operator setup, deployment, rollout ordering, security configuration, and verification commands for Firebase Authentication, Account Sync (Firestore), Account Deletion, and Legacy Account Migration.

For reader-facing specifications, see:
- [authentication.md](authentication.md)
- [account_sync.md](account_sync.md)
- [account_deletion.md](account_deletion.md)
- [legacy_migration.md](legacy_migration.md)

## 1. Firebase Authentication setup (Google Sign-In)

1. Create a Firebase project on the free **Spark** plan and register a Web app. Account Sync and Account Deletion require Cloud Firestore (including `googleAccounts/{subject}` generation records); Cloud Functions and billing upgrades are not required.
2. Under **Authentication → Sign-in method**, enable **Google** and set the support email. Enable only Google for standard account mode (password auth and provider linking are unsupported; the optional [shared development mode](local_static_docker.md#開発用firestoreでprojectを共有する任意) uses anonymous auth in a separate Firebase app).
3. Under **Authentication → Settings → Authorized domains**, add each UI host (add `localhost` explicitly for local testing if absent). Serve deployed UIs over HTTPS.
4. Configure the Web app's **public** build variables in ignored `web/.env.local` (or in the static build environment):

   ```dotenv
   VITE_FIREBASE_API_KEY=your-web-api-key
   VITE_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
   VITE_FIREBASE_PROJECT_ID=your-project
   VITE_FIREBASE_APP_ID=your-web-app-id
   ```

   Never place a service-account private key or admin credential in any `VITE_*` variable. Changing build-time settings requires rebuilding the static assets.

Official references: [Google sign-in](https://firebase.google.com/docs/auth/web/google-signin), [auth persistence](https://firebase.google.com/docs/auth/web/auth-state-persistence), [session revocation](https://firebase.google.com/docs/auth/admin/manage-sessions), [Auth SDK](https://firebase.google.com/docs/reference/js/auth).

## 2. Firestore Rules and indexes deployment

Create the default Cloud Firestore database in the same Firebase project in **production mode**, then deploy `firebase/firestore.rules` and `firebase/firestore.indexes.json` using the Firebase CLI after explicit approval:

```bash
firebase deploy --only firestore:rules,firestore:indexes --project YOUR_FIREBASE_PROJECT_ID
```

- Do not use test-mode public rules or admin/service-account credentials in the browser.
- **Account Deletion co-deployment**: `googleAccounts/{subject}` records and the corresponding Firestore Rules must be deployed together before exposing Account Deletion UI in a Local build.
- For Rules updates on an active production environment, also follow the `--rules-transition` gate in [static_operations.md](static_operations.md#rulesが異なる更新だけに必要な検証記録).

## 3. Large payload (`gzip-v1:`) rollout and compatibility

- Deploy the NavMate `gzip-v1:` reader/writer **before** enabling an updated Legacy migration server so browser clients can read compressed payloads before Legacy migration can produce them.
- Older browser tabs and un-updated Legacy adapters cannot parse `gzip-v1:` as JSON and stop fail-closed before overwriting a Project.
- During the window after NavMate deploys and before Legacy migration updates: Legacy migration reads only Project IDs in its migration plan. If an older Legacy adapter encounters a `gzip-v1:` document for an ID in that plan (e.g., on retry after partial migration if updated NavMate modified that ID), migration fails and returns the account to `LINKED`, keeping Legacy source files, Local/remote data, and completed batches intact. After updating the Legacy migration server, retry through the standard migration flow ([legacy_migration.md#data-and-retry](legacy_migration.md#data-and-retry)) without creating duplicate Project IDs.
- Rolling back to pre-`gzip-v1:` code cannot read compressed documents and is not a transparent recovery procedure. Rules and indexes are unchanged.
- **Wire / identity technical contract**:
  - Account ID derivation: `account_v1_` + lowercase SHA-256 hex digest of UTF-8 JSON `["autonavlog.account.v1","https://accounts.google.com",googleSubject]`; post-deletion generation uses `googleAccounts/{subject}` (`ACTIVE` / `DELETING` / `DELETED`) -> `account_v2_…`.
  - Account IndexedDB namespace: `autonavlog.projects.<account_id>` (shared dev mode isolated under `dev_navmate-6b281`).
  - Compressed payload wire format: `gzip-v1:` + standard Base64 of gzipped UTF-8 JSON (attempted >= 256 KiB, stored budget 1,000,000 UTF-8 bytes, streaming decode bound 16 MiB).
  - Auth outage startup guard (`firebase 12.19.0` `reloadAndSetCurrentUserOrClear`): intercepts only `identitytoolkit.googleapis.com` / `securetoken.googleapis.com` during SDK init for HTTP 429/5xx or transient 400 (`TOO_MANY_ATTEMPTS_TRY_LATER`, `QUOTA_EXCEEDED`, `INTERNAL_ERROR`).
  - #393 deletion notice copy review records: Gemini (`agy`, `gemini-4-argon-high`, 2026-11-08, conversations `cb7e2200-aaaa-4ae4-b352-39ba7308e45d` and `356ec4f3-568e-47a9-94cf-54d472202cac`).

<a id="configure-the-migration-period"></a>
## 4. Legacy Migration configuration and Cloudflare Access boundary

Use the same Firebase project as NavMate Authentication / Account Sync; no Rules change, service-account key, Cloud Function, or paid plan is required.

Legacy Compose environment (public Firebase Web config, not admin secrets):

```dotenv
AUTONAVLOG_FIREBASE_PROJECT_ID=your-project
AUTONAVLOG_FIREBASE_API_KEY=your-public-web-api-key
AUTONAVLOG_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
AUTONAVLOG_FIREBASE_APP_ID=your-web-app-id
AUTONAVLOG_NAVMATE_URL=https://your-navmate-host/
```

Add the Legacy host to Firebase Authentication authorized domains. Keep the existing Cloudflare Team domain/AUD and loopback binding.

In the NavMate Local build, alongside the `VITE_FIREBASE_*` settings:

```dotenv
VITE_LEGACY_MIGRATION_URL=https://your-legacy-host
```

### Cloudflare Access Bypass and security rules

- Configure a **more specific Cloudflare Access Bypass application ONLY for `/api/navmate-migration/*`** so a Google-authenticated NavMate browser can reach activation endpoints without a cross-site Access cookie. These routes validate Firebase RS256 tokens and `accounts:lookup` directly, resolve the stored link internally, and allow CORS only from `AUTONAVLOG_NAVMATE_URL`.
- **Never** bypass `/api/account-link`, `/api/session`, any Project route, or the Legacy UI. `/api/account-link` POST requires signed Access and Legacy HTTPS Origin/Host match.
- Keep `AUTONAVLOG_TRUSTED_LOCAL_IDENTITY` **unset** on all exposed services.
- Keep the supported Legacy runtime as the existing single-process Uvicorn/Compose deployment; do not add multiple workers or parallel instances sharing the Legacy data directory.
- Keep registry (`account-links.sqlite3`) and Project data in the same preserved `autonavlog-data` volume; never manually edit ownership rows.
- For the `#123` canonical origin (`https://navmate.yuto24.com`): set `AUTONAVLOG_NAVMATE_URL=https://navmate.yuto24.com/` (single URL, not a comma-separated allowlist; middleware derives exact CORS origin and 303 redirect from this single value) and `VITE_LEGACY_MIGRATION_URL=https://navlog.yuto24.com`. Keep `navlog.yuto24.com` and its Access/link routes active until [#146 retirement](server_retirement.md). See [custom_domain_cutover.md](custom_domain_cutover.md).
- Rollout rule: enable both sides together; do not advertise a NavMate build without `VITE_LEGACY_MIGRATION_URL` to linked users during the migration period.

## 5. Verification commands and physical acceptance gates

CI automated checks (`test:application`, `test:auth`, `test:firestore`, `test:sync`, `test:migration`, `test_legacy_migration.py`, `test_migration_remote.py`) use Firebase SDK / emulator / intercepted backends and **do not** by themselves prove live Google popup consent, authorized-domain settings, production Cloudflare Access policy, or physical iPhone/iPad Safari behavior.

### Emulator and local verification (Python 3.12, Node 22+, Java 21)

```bash
npm --prefix web run test:application
npm --prefix web run test:auth

AUTONAVLOG_TEST_FIXTURES=1 npm --prefix web run prepare:local
npm --prefix web exec -- playwright install chromium webkit
npx --yes firebase-tools@15.10.1 emulators:exec --only firestore --project demo-autonavlog-sync \
  "npm --prefix web run test:firestore && npm --prefix web run test:sync"
```

Legacy migration local harness (keep test-only processes on loopback; never expose synthetic auth fixtures):

```bash
pytest tests/integration/test_legacy_migration.py tests/unit/test_migration_remote.py
AUTONAVLOG_TEST_FIXTURES=1 npm --prefix web run prepare:local
PYTHONPATH=src:tests/integration python -m uvicorn migration_harness:app --host 127.0.0.1 --port 8186 &
fixture_pid=$!
trap 'kill "$fixture_pid"' EXIT
curl --fail --retry 10 --retry-connrefused --retry-delay 1 http://127.0.0.1:8186/healthz > /dev/null
npx --yes firebase-tools@15.10.1 emulators:exec --only firestore \
  --project demo-autonavlog-sync "npm --prefix web run test:migration"
```

Note for WebKit emulator testing: the test harness forces Firestore `experimentalForceLongPolling` because WebKit can buffer HTTP emulator streaming responses indefinitely; production uses SDK defaults.

### Live / physical acceptance requirements (post-deploy)

- **Auth / Sync**: verify Google sign-in, browser restart, logout, re-auth, offline edit + reconnect, conflict resolution (`Local` / `Remote` / `Both`), delete/Undo/expiry, cross-device sync (e.g., Windows Chromium + iPhone/iPad Safari), and cross-account isolation on deployed Rules.
- **Account Deletion**: verify two-device authentication/write-blocking boundary, offline control/reason, re-registration as `account_v2_…`, and notices with a dedicated test Google identity.
- **Legacy Migration**: verify link-only leaves Legacy editing/calculation active; first NavMate login shows progress and rejects concurrent Legacy edits; failure releases Legacy lock (within 180 s lease on disconnect) and retries without duplicating IDs; fresh-device login restores data; Legacy navigation redirects 303; cross-owner/cross-account linking is rejected.
