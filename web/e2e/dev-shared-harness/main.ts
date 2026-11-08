// Test-only wiring: every Firebase service is connected to a loopback emulator.
import { initializeApp } from "firebase/app";
import { initializeAuth, browserLocalPersistence, browserPopupRedirectResolver, connectAuthEmulator,
  GoogleAuthProvider, signInWithCredential } from "firebase/auth";
import { initializeFirestore, connectFirestoreEmulator, collection, getDocsFromServer } from "firebase/firestore";
import { FirebaseAuthProvider } from "../../src/firebaseAuthProvider";
const config = { projectId: "navmate-6b281", apiKey: "emulator-only",
  authDomain: "navmate-6b281.firebaseapp.com", appId: "emulator-only" };
const app = initializeApp(config, "navmate-dev-shared");
const auth = initializeAuth(app, { persistence: browserLocalPersistence });
connectAuthEmulator(auth, "http://127.0.0.1:9098", { disableWarnings: true });
const db = initializeFirestore(app, { experimentalForceLongPolling: true });
connectFirestoreEmulator(db, "127.0.0.1", 8089);
const personalApp = initializeApp(config);
const personalAuth = initializeAuth(personalApp, { persistence: browserLocalPersistence,
  popupRedirectResolver: browserPopupRedirectResolver });
connectAuthEmulator(personalAuth, "http://127.0.0.1:9098", { disableWarnings: true });
const personalDb = initializeFirestore(personalApp, { experimentalForceLongPolling: true });
connectFirestoreEmulator(personalDb, "127.0.0.1", 8089);
let subject = "dev-google-one";
// Only the popup is replaced. The production registration, lifecycle, context
// switch and UI actions still run, against the real local Auth/Firestore emulators.
FirebaseAuthProvider.prototype.signIn = function () {
  const part = (value: unknown) => btoa(JSON.stringify(value)).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  const token = `${part({ alg: "none" })}.${part({ sub: subject, email: `${subject}@example.test`,
    email_verified: true, name: subject, iss: "https://accounts.google.com", aud: "navmate-test",
    iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 3600 })}.`;
  return this.signInWith(async () => (await signInWithCredential(personalAuth, GoogleAuthProvider.credential(token))).user);
};
(window as any).devSharedTest = {
  selectGoogle: (value: string) => { subject = value; },
  personalUser: () => personalAuth.currentUser?.uid,
  user: () => ({ uid: auth.currentUser?.uid, anonymous: auth.currentUser?.isAnonymous }),
  records: async () => (await getDocsFromServer(collection(db, "devWorkspaces", "shared", "projects")))
    .docs.map(row => row.data()),
};
if (new URLSearchParams(location.search).has("ordinary")) {
  const [{ createRoot }, { createAccountContext }, { browserPlatform }, { BrowserFileInput }, { default: App }, React] = await Promise.all([
    import("react-dom/client"), import("../../src/accountContext"), import("../../src/browserPlatform"),
    import("../../src/BrowserFileInput"), import("../../src/App"), import("react"),
  ]);
  await Promise.all([import("leaflet/dist/leaflet.css"), import("../../src/styles.css"), import("../../src/flightPlanLayout.css")]);
  const context = createAccountContext(browserPlatform);
  createRoot(document.getElementById("root")!).render(React.createElement(App,
    { application: context.application, platform: context.platform, FileInput: BrowserFileInput }));
} else void import("../../src/main");
