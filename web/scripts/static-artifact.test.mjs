import { execFileSync, spawnSync } from "node:child_process";
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, truncateSync, readFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { inventory, checkArtifact, limits, sha256, sourceDirty } from "./static-artifact.mjs";
const msmFile = `weather/msm/${sha256("msm")}.npz`;
const gsmFile = `weather/gsm/${sha256("gsm")}.npz`;
function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), "static-artifact-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  for (const name of ["local", "weather/msm"]) mkdirSync(join(root, name), { recursive: true });
  const put = (name, value) => writeFileSync(join(root, name), typeof value === "string" ? value : JSON.stringify(value));
  for (const name of ["index.html", "_headers", "404.html", "local/core.whl", "local/data.zip"]) put(name, name);
  put("local/manifest.json", { version: "1.0.0", pyodideVersion: "0.27.7", wheels: ["core.whl"], data: "data.zip",
    sha256: { "core.whl": sha256("local/core.whl"), "data.zip": sha256("local/data.zip") } });
  put(msmFile, "msm");
  put("weather/msm/catalog.json", {
    schema_version: 1, generated_at: new Date(Date.now() - 1000).toISOString(),
    expires_at: new Date(Date.now() + 60000).toISOString(), listings: {},
    assets: [{ run: "20260915000000", file: `${sha256("msm")}.npz`, bytes: 3, sha256: sha256("msm") }],
  });
  const seal = () => {
    const files = inventory(root); delete files["release.json"];
    put("release.json", { version: "1.0.0", pyodideVersion: "0.27.7", dirty: false, files });
  };
  seal(); return { root, put, seal };
}
test("portable artifact inventory includes all files, validates hashes and weather", t => {
  const { root } = fixture(t); const report = checkArtifact(root);
  assert.equal(report.version, "1.0.0"); assert.ok(report.totalBytes > 0); assert.equal(report.fileCount, 9);
});
test("tampering or an unrecorded asset rejects deployment", t => {
  const { root, put } = fixture(t); put("index.html", "changed");
  assert.throws(() => checkArtifact(root), /inventory mismatch/);
});
test("oversize files fail before upload, including sparse files", t => {
  const { root, put } = fixture(t); put("oversize", "");
  truncateSync(join(root, "oversize"), limits.assetBytes + 1);
  assert.throws(() => checkArtifact(root), /exceeds 25 MiB/);
});
test("expired feed blocks deployment; historical inspection is explicitly labelled", t => {
  const { root, put, seal } = fixture(t);
  const catalog = JSON.parse(readFileSync(join(root, "weather/msm/catalog.json")));
  catalog.generated_at = "1999-12-31T23:00:00Z";
  catalog.expires_at = "2000-01-01T00:00:00Z"; put("weather/msm/catalog.json", catalog); seal();
  assert.throws(() => checkArtifact(root), /expired/);
  assert.equal(checkArtifact(root, { freshWeather: false }).freshWeather, false);
});
test("a sealed but mismatched Local package is rejected", t => {
  const { root, put, seal } = fixture(t); put("local/core.whl", "other build"); seal();
  assert.throws(() => checkArtifact(root), /Local asset hash mismatch/);
});
test("provider runtime is rejected even with a fresh inventory", t => {
  const { root, put, seal } = fixture(t); put("_worker.js", "export default {}"); seal();
  assert.throws(() => checkArtifact(root), /Runtime or private/);
});

test("untracked source is dirty while unrelated Codex state is excluded", t => {
  const root = mkdtempSync(join(tmpdir(), "static-source-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  execFileSync("git", ["init", "--quiet", root]);
  mkdirSync(join(root, ".codex")); writeFileSync(join(root, ".codex", "state"), "unrelated");
  assert.equal(sourceDirty(root), false);
  mkdirSync(join(root, "src")); writeFileSync(join(root, "src", "untracked.py"), "source");
  assert.equal(sourceDirty(root), true);
});

test("dirty artifacts fail production checks unless explicitly allowed for development", t => {
  const { root, put } = fixture(t);
  const release = JSON.parse(readFileSync(join(root, "release.json")));
  put("release.json", { ...release, dirty: true });
  assert.throws(() => checkArtifact(root), /Dirty source artifact/);
  const report = checkArtifact(root, { allowDirty: true });
  assert.equal(report.dirty, true);
  assert.equal(report.allowDirty, true);
  const cli = join(import.meta.dirname, "check-static.mjs");
  assert.throws(() => execFileSync(process.execPath, [cli, root], { stdio: "pipe" }));
  const accepted = JSON.parse(execFileSync(process.execPath, [cli, root, "--allow-dirty"], { encoding: "utf8" }));
  assert.equal(accepted.dirty, true);
});
test("a missing dirty flag is not proof of a clean source even with a development opt-out", t => {
  const { root, put } = fixture(t);
  const release = JSON.parse(readFileSync(join(root, "release.json")));
  delete release.dirty; put("release.json", release);
  assert.throws(() => checkArtifact(root), /Missing or invalid/);
  assert.throws(() => checkArtifact(root, { allowDirty: true }), /Missing or invalid/);
});

test("optional GSM publication validates integrity and expiry without making it a scheduled feed", t => {
  const { root, put, seal } = fixture(t);
  assert.equal(checkArtifact(root).gsmWeatherExpiresAt, null);
  mkdirSync(join(root, "weather/gsm"));
  put(gsmFile, "gsm"); seal();
  assert.throws(() => checkArtifact(root), /GSM payloads require a catalog/);
  const catalog = {
    schema_version: 1, generated_at: new Date(Date.now() - 1000).toISOString(),
    expires_at: new Date(Date.now() + 60000).toISOString(), listings: {},
    assets: [{ run: "20260915060000", file: `${sha256("gsm")}.npz`, bytes: 3, sha256: sha256("gsm") }],
  };
  put("weather/gsm/catalog.json", catalog); seal();
  assert.equal(checkArtifact(root).gsmWeatherExpiresAt, catalog.expires_at);
  put(gsmFile, "bad"); seal();
  assert.throws(() => checkArtifact(root), /GSM asset mismatch/);
  put(gsmFile, "gsm");
  put("weather/gsm/catalog.json", { ...catalog, generated_at: "1999-12-31T23:00:00Z", expires_at: "2000-01-01T00:00:00Z" }); seal();
  assert.throws(() => checkArtifact(root), /GSM catalog expired/);
});

for (const model of ["msm", "gsm"]) {
  for (const field of ["schema_version", "generated_at", "listings"]) {
    test(`${model} publication rejects a catalog missing ${field}`, t => {
      const { root, put, seal } = fixture(t);
      const catalog = JSON.parse(readFileSync(join(root, "weather/msm/catalog.json")));
      if (model === "gsm") {
        mkdirSync(join(root, "weather/gsm")); put(gsmFile, "gsm");
        catalog.assets = [{ run: "20260915060000", file: `${sha256("gsm")}.npz`, bytes: 3, sha256: sha256("gsm") }];
      }
      delete catalog[field]; put(`weather/${model}/catalog.json`, catalog); seal();
      assert.throws(() => checkArtifact(root), new RegExp(`${model.toUpperCase()} catalog format invalid`));
    });
  }
}

for (const model of ["msm", "gsm"]) {
  for (const malformed of ["numeric-run", "duplicate-run", "bad-listing"]) {
    test(`${model} publication rejects ${malformed} catalog metadata`, t => {
      const { root, put, seal } = fixture(t);
      const catalog = JSON.parse(readFileSync(join(root, "weather/msm/catalog.json")));
      if (model === "gsm") {
        mkdirSync(join(root, "weather/gsm")); put(gsmFile, "gsm");
        catalog.assets = [{ run: "20260915060000", file: `${sha256("gsm")}.npz`, bytes: 3, sha256: sha256("gsm") }];
      }
      if (malformed === "numeric-run") catalog.assets[0].run = Number(catalog.assets[0].run);
      if (malformed === "duplicate-run") catalog.assets.push({ ...catalog.assets[0] });
      if (malformed === "bad-listing") catalog.listings = { source: 42 };
      put(`weather/${model}/catalog.json`, catalog); seal();
      assert.throws(() => checkArtifact(root), /format invalid/);
    });
  }
}


test("local artifacts exclude accounts and cannot pass production validation", t => {
  const { root, put } = fixture(t);
  const release = JSON.parse(readFileSync(join(root, "release.json")));
  put("release.json", { ...release, localRuntime: true, configuration: {} });
  assert.throws(() => checkArtifact(root), /cannot pass a production check/);
  assert.equal(checkArtifact(root, { localRuntime: true }).version, "1.0.0");
  for (const key of ["VITE_FIREBASE_PROJECT_ID", "VITE_LEGACY_MIGRATION_URL"]) {
    put("release.json", { ...release, localRuntime: true, configuration: { [key]: "production" } });
    assert.throws(() => checkArtifact(root, { localRuntime: true }), /exclude production account configuration/);
  }
});

test("local build clears shell and dotenv account settings before invoking Vite", t => {
  const { root, put } = fixture(t);
  const accountKeys = ["VITE_FIREBASE_API_KEY", "VITE_FIREBASE_AUTH_DOMAIN",
    "VITE_FIREBASE_PROJECT_ID", "VITE_FIREBASE_APP_ID", "VITE_LEGACY_MIGRATION_URL"];
  put(".env.production", accountKeys.map(key => `${key}=dotenv-production`).join("\n"));
  // Stop before costly build work, observing the real child environment sent to npm.
  put("npm", `#!${process.execPath}
import { writeFileSync } from "node:fs";
writeFileSync("observed.json", JSON.stringify(Object.fromEntries(${JSON.stringify(accountKeys)}.map(key => [key, process.env[key]]))));
process.exit(9);
`);
  put("package.json", { type: "module" });
  chmodSync(join(root, "npm"), 0o700);
  const env = { ...process.env, PATH: root + ":" + process.env.PATH,
    AUTONAVLOG_TEST_FIXTURES: "0", AUTONAVLOG_MSM_FEED: root,
    VITE_TAF_PROXY_URL: "https://weather.example/taf" };
  for (const key of accountKeys) env[key] = "shell-production";
  const build = resolve("scripts/build-static.mjs");
  const local = spawnSync(process.execPath, [build, "--local-runtime"], { cwd: root, env });
  assert.notEqual(local.status, 0);
  assert.deepEqual(JSON.parse(readFileSync(join(root, "observed.json"))),
    Object.fromEntries(accountKeys.map(key => [key, ""])));
  const sharedEnv = { ...env, VITE_DEV_SHARED_PROJECTS: "1", VITE_DEV_FIREBASE_PROJECT_ID: "navmate-prod" };
  const wrongProject = spawnSync(process.execPath, [build, "--local-runtime"], { cwd: root, env: sharedEnv, encoding: "utf8" });
  assert.match(wrongProject.stderr, /requires a local build and the NavMate-dev/);
  sharedEnv.VITE_DEV_FIREBASE_PROJECT_ID = "navmate-6b281";
  const missingDevKeys = spawnSync(process.execPath, [build, "--local-runtime"], { cwd: root, env: sharedEnv, encoding: "utf8" });
  assert.match(missingDevKeys.stderr, /VITE_DEV_FIREBASE_API_KEY is required/);
  for (const key of accountKeys.filter(key => key !== "VITE_LEGACY_MIGRATION_URL")) {
    sharedEnv[key.replace("VITE_FIREBASE_", "VITE_DEV_FIREBASE_")] = key === "VITE_FIREBASE_PROJECT_ID" ? "navmate-6b281" : "dev-config";
  }
  const shared = spawnSync(process.execPath, [build, "--local-runtime"], { cwd: root, env: sharedEnv });
  assert.notEqual(shared.status, 0);
  assert.deepEqual(JSON.parse(readFileSync(join(root, "observed.json"))),
    Object.fromEntries(accountKeys.map(key => [key, ""])));
  const forbiddenProduction = spawnSync(process.execPath, [build], { cwd: root, env: sharedEnv, encoding: "utf8" });
  assert.match(forbiddenProduction.stderr, /requires a local build/);
  for (const key of accountKeys) env[key] = "";
  const production = spawnSync(process.execPath, [build], { cwd: root, env, encoding: "utf8" });
  assert.notEqual(production.status, 0);
  assert.match(production.stderr, /VITE_FIREBASE_API_KEY is required for production/);
});


test("only the development Firebase project is accepted for shared local artifacts", t => {
  const { root, put } = fixture(t);
  const release = JSON.parse(readFileSync(join(root, "release.json")));
  for (const projectId of ["navmate-prod", "other", undefined]) {
    put("release.json", { ...release, localRuntime: true, configuration: {
      VITE_DEV_SHARED_PROJECTS: "1", VITE_DEV_FIREBASE_PROJECT_ID: projectId } });
    assert.throws(() => checkArtifact(root, { localRuntime: true }), /exclude production account/);
  }
  put("release.json", { ...release, localRuntime: true, configuration: {
    VITE_DEV_SHARED_PROJECTS: "1", VITE_DEV_FIREBASE_PROJECT_ID: "navmate-6b281" } });
  assert.equal(checkArtifact(root, { localRuntime: true }).version, "1.0.0");
  assert.throws(() => checkArtifact(root), /cannot pass a production check/);
});
