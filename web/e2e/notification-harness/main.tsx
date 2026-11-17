import { ApplicationError } from "../../src/application";
// Test-only entry: actual App and local Application; synthetic invalid import, no personal files.
import { flushSync } from "react-dom";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "@fontsource-variable/noto-sans-jp";
import "../../src/styles.css";
import "../../src/flightPlanLayout.css";
import "../../src/routePlanningLayout.css";
import App from "../../src/App";
import { localMode } from "../../src/executionMode";
import { CalculationProgressOverlay } from "../../src/components/CalculationProgressOverlay";
import { LegacyMigrationBoundary } from "../../src/components/LegacyAccountControl";
import { browserPlatform } from "../../src/browserPlatform";
import { BrowserFileInput, type FileInputProps } from "../../src/BrowserFileInput";
function NotificationFileInput(props: FileInputProps) {
  return <><BrowserFileInput {...props} /><button type="button" disabled={props.busy}
    style={{position:"fixed",left:16,bottom:16,zIndex:1000,width:140,maxWidth:140}}
    onClick={() => props.onFile(new File(["not a route"], "test.txt"))}>Test: invalid route</button><button type="button" disabled={props.busy}
    style={{position:"fixed",left:170,bottom:16,zIndex:1000,width:140,maxWidth:140}}
    onClick={() => props.onFile(new File([`<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>Test</name><LineString><coordinates>131.4486111111,31.8772222222,0 131.5,32.4,0 131.7372222222,33.4794444444,0</coordinates></LineString></Placemark></Document></kml>`], "synthetic.kml"))}>Test: valid route</button></>;
}
import { startApplication } from "../../src/createApplication";

const root = document.getElementById("root");
if (!root) {
  throw new Error("NavMate root element is unavailable");
}

const view = createRoot(root);
let generation = 0;
startApplication(browserPlatform, ({ application, platform }) => {
  if (new URLSearchParams(location.search).has("fail-new")) {
    application.newWork = async () => { throw new Error("Test: new work failed"); };
  }
  if (new URLSearchParams(location.search).has("fail-load")) {
    const load = application.loadProject.bind(application);
    let attempts = 0;
    application.loadProject = async (...args) => {
      if (++attempts === 1) throw new Error("Test: load failed");
      if (attempts === 2) return null; // Same cancellation result as confirmDiscard rejection.
      return load(...args);
    };
  }
  if (new URLSearchParams(location.search).has("fail-link")) {
    let attempts = 0;
    platform.openExternalUrl = () => { if (++attempts === 1) throw new Error("Test: source link failed"); };
  }
  if (new URLSearchParams(location.search).has("pending-import")) {
    const mode = new URLSearchParams(location.search).get("pending-import");
    platform.clipboard.readText = async () => { if (mode === "denied") throw new Error("Test: clipboard denied"); return ""; };
    const originalImport = application.importRoute.bind(application);
    application.importRoute = async input => {
      if (input.filename === "pending.kmz") throw new ApplicationError("Select document", "KMZ_DOCUMENT_SELECTION_REQUIRED", {candidates:["a.kml","b.kml"]});
      return originalImport(input);
    };
  }
  // Unmount the previous account immediately, including dialogs and pending UI work.
  flushSync(() => view.render(
    <StrictMode>{localMode
      ? <App key={++generation} application={application} platform={platform} FileInput={NotificationFileInput} />
      : <LegacyMigrationBoundary><App application={application} platform={platform} FileInput={NotificationFileInput} /></LegacyMigrationBoundary>}</StrictMode>,
  ));
}, progress => {
  flushSync(() => view.render(progress.error
    ? <main className="loading-screen"><p role="alert">{progress.error}</p><p>Legacyのデータは保持されています。</p><button onClick={progress.retry}>再試行</button><button onClick={progress.signOut}>ログアウト</button></main>
    : <CalculationProgressOverlay title="NavMateへ引継ぎ中" percent={progress.percent} message={progress.message} onSignOut={progress.signOut} />));
}).catch(() => view.render(
  <main className="loading-screen">
    <p role="alert">起動できませんでした。画面を再読み込みしてください。</p>
    <button onClick={() => window.location.reload()}>再読み込み</button>
  </main>,
));
