import { flushSync } from "react-dom";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "@fontsource-variable/noto-sans-jp";
import "./styles.css";
import "./flightPlanLayout.css";
import "./routePlanningLayout.css";
import App from "./App";
import { localMode } from "./executionMode";
import { LegacyMigrationBoundary } from "./components/LegacyAccountControl";
import { browserPlatform } from "./browserPlatform";
import { BrowserFileInput } from "./BrowserFileInput";
import { startApplication } from "./createApplication";
import { StartupScreen } from "./components/StartupScreen";
import { authenticationProgress, StartupProgressStore } from "./startupProgress";

const root = document.getElementById("root");
if (!root) {
  throw new Error("NavMate root element is unavailable");
}

const view = createRoot(root);
if (localMode) flushSync(() => view.render(<StartupScreen />));
let generation = 0;
let migrationStartup: StartupProgressStore | undefined;
startApplication(browserPlatform, ({ application, platform }) => {
  if (migrationStartup) application.startup?.restart(true);
  migrationStartup = undefined;
  // Unmount the previous account immediately, including dialogs and pending UI work.
  flushSync(() => view.render(
    <StrictMode>{localMode
      ? <App key={++generation} application={application} platform={platform} FileInput={BrowserFileInput} />
      : <LegacyMigrationBoundary><App application={application} platform={platform} FileInput={BrowserFileInput} /></LegacyMigrationBoundary>}</StrictMode>,
  ));
}, progress => {
  migrationStartup ??= new StartupProgressStore(authenticationProgress);
  migrationStartup.update({ stage: "migration", percent: Math.min(100, Math.max(0, progress.percent)) * 0.4 });
  flushSync(() => view.render(progress.error
    ? <main className="loading-screen"><p role="alert">{progress.error}</p><p>Legacyのデータは保持されています。</p><button onClick={progress.retry}>再試行</button><button onClick={progress.signOut}>ログアウト</button></main>
    : <StartupScreen source={migrationStartup} message={progress.message} onSignOut={progress.signOut} />));
}).catch(() => view.render(
  <main className="loading-screen">
    <p role="alert">起動できませんでした。画面を再読み込みしてください。</p>
    <button className="secondary-button" onClick={() => window.location.reload()}>再読み込み</button>
  </main>,
));
