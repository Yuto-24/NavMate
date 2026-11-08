import { initializeApp, getApps } from "firebase/app";
import { browserLocalPersistence, initializeAuth, getAuth, signInAnonymously } from "firebase/auth";
import { collection, getFirestore } from "firebase/firestore";
import { observeAccountContexts } from "./accountContext";
import { createFirestoreSyncRepository, FirestoreSyncRepository } from "./firestoreSyncRepository";
import { createFirebaseAuthProvider } from "./firebaseAuthProvider";
import type { ApplicationContext } from "./createApplication";
import type { AuthProvider } from "./auth";
import type { LocalAccountContext } from "./localProjectRepository";
import type { PlatformCapabilities } from "./platform";

export const DEV_PROJECT_ID = "navmate-6b281";
export const DEV_WORKSPACE_ID = `dev_shared_${DEV_PROJECT_ID}`;

function developmentConfig() {
  const { VITE_DEV_FIREBASE_PROJECT_ID: projectId, VITE_DEV_FIREBASE_API_KEY: apiKey,
    VITE_DEV_FIREBASE_AUTH_DOMAIN: authDomain, VITE_DEV_FIREBASE_APP_ID: appId } = import.meta.env;
  // Never fall back to the production Firebase project or its signed-in account.
  if (projectId !== DEV_PROJECT_ID || !apiKey || !authDomain || !appId) throw new Error("Invalid development Firebase configuration");
  return { projectId, apiKey, authDomain, appId };
}

export async function createDevSharedSyncRepository(context: LocalAccountContext) {
  const config = developmentConfig();
  const name = "navmate-dev-shared";
  let app = getApps().find(value => value.name === name);
  if (!app) {
    app = initializeApp(config, name);
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

export async function startDevSharedApplication(platform: PlatformCapabilities,
  present: (context: ApplicationContext) => void) {
  const config = developmentConfig();
  const existing = getApps().find(app => app.name === "[DEFAULT]");
  if (existing && existing.options.projectId !== DEV_PROJECT_ID) throw new Error("Invalid development Firebase app");
  let auth: AuthProvider;
  try {
    // Google and anonymous sessions use separate Firebase apps. Signing out or
    // deleting a personal account cannot delete the shared anonymous identity.
    auth = await createFirebaseAuthProvider(config);
  } catch {
    const state = { account: null, available: false, notice: "認証を初期化できませんでした。未ログインの端末内作業は利用できます。ログインするには設定を確認して再読み込みしてください。" };
    auth = { getState: () => state, subscribe: () => () => {},
      signIn: async () => { throw new Error(state.notice); }, signOut: async () => {} };
  }
  platform.persistence.requestRetention();
  observeAccountContexts(platform, auth, present, createFirestoreSyncRepository, undefined, undefined,
    { id: DEV_WORKSPACE_ID, createSync: createDevSharedSyncRepository });
}
