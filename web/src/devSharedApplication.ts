import { initializeApp, getApps } from "firebase/app";
import { browserLocalPersistence, initializeAuth, getAuth, signInAnonymously } from "firebase/auth";
import { collection, getFirestore } from "firebase/firestore";
import { createAccountContext } from "./accountContext";
import { FirestoreSyncRepository } from "./firestoreSyncRepository";
import type { LocalAccountContext } from "./localProjectRepository";
import type { PlatformCapabilities } from "./platform";

export const DEV_PROJECT_ID = "navmate-6b281";
export const DEV_WORKSPACE_ID = `dev_shared_${DEV_PROJECT_ID}`;

export async function createDevSharedSyncRepository(context: LocalAccountContext) {
  const { VITE_DEV_FIREBASE_PROJECT_ID: projectId, VITE_DEV_FIREBASE_API_KEY: apiKey,
    VITE_DEV_FIREBASE_AUTH_DOMAIN: authDomain, VITE_DEV_FIREBASE_APP_ID: appId } = import.meta.env;
  // Never fall back to the production Firebase project or its signed-in account.
  if (projectId !== DEV_PROJECT_ID || !apiKey || !authDomain || !appId) throw new Error("Invalid development Firebase configuration");
  const name = "navmate-dev-shared";
  let app = getApps().find(value => value.name === name);
  if (!app) {
    app = initializeApp({ projectId, apiKey, authDomain, appId }, name);
    initializeAuth(app, { persistence: browserLocalPersistence });
  }
  if (app.options.projectId !== DEV_PROJECT_ID) throw new Error("Invalid development Firebase app");
  const auth = getAuth(app);
  await auth.authStateReady();
  if (!auth.currentUser) await signInAnonymously(auth);
  const user = auth.currentUser;
  if (!user?.isAnonymous) throw new Error("Development workspace requires anonymous authentication");
  const assert = () => {
    context.assertActive();
    if (auth.currentUser?.uid !== user.uid || !auth.currentUser.isAnonymous) throw new Error("Development authentication changed");
  };
  assert();
  const db = getFirestore(app);
  return new FirestoreSyncRepository(db, "", assert, undefined,
    collection(db, "devWorkspaces", "shared", "projects"));
}

export function createDevSharedApplication(platform: PlatformCapabilities) {
  // Reuse the existing local outbox, conflict handling and durable anonymous import.
  // This ID names a shared local namespace; it is not a Google account or Firebase UID.
  return createAccountContext(platform, undefined, true, createDevSharedSyncRepository, DEV_WORKSPACE_ID);
}
