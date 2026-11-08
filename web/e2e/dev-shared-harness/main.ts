// Test-only wiring: every Firebase service is connected to a loopback emulator.
import { initializeApp } from "firebase/app";
import { initializeAuth, browserLocalPersistence, connectAuthEmulator } from "firebase/auth";
import { initializeFirestore, connectFirestoreEmulator, collection, getDocsFromServer } from "firebase/firestore";
const app = initializeApp({ projectId: "navmate-6b281", apiKey: "emulator-only",
  authDomain: "navmate-6b281.firebaseapp.com", appId: "emulator-only" }, "navmate-dev-shared");
const auth = initializeAuth(app, { persistence: browserLocalPersistence });
connectAuthEmulator(auth, "http://127.0.0.1:9098", { disableWarnings: true });
const db = initializeFirestore(app, { experimentalForceLongPolling: true });
connectFirestoreEmulator(db, "127.0.0.1", 8089);
(window as any).devSharedTest = {
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
