import { IDBFactory } from "fake-indexeddb";
import { IndexedDbProjectRepository } from "../src/localProjectRepository";
import { browserPlatform } from "../src/browserPlatform";
import { expect, test } from "@playwright/test";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { ApplicationError } from "../src/application";
import type { AutoNavLogApplication, UpdateProjectInput } from "../src/application";
import type { WebState } from "../src/types";
import { LocalApplication } from "../src/localApplication";
import { LegacyApplication } from "../src/legacyApplication";
import type { LocalProjectRepository } from "../src/localProjectRepository";
import { authenticationProgress, StartupProgressStore, type StartupProgress } from "../src/startupProgress";
import { readStartupAsset } from "../src/localStartupAsset";

const originalFetch = globalThis.fetch;
test.afterEach(() => { globalThis.fetch = originalFetch; });
const state = { project: null, outcome: null, savedProjects: [] } as unknown as WebState;

test("#422 startup never regresses and each Application has its own progress lifetime", () => {
  const first = new StartupProgressStore(), second = new StartupProgressStore();
  const observed: StartupProgress[] = [];
  const unsubscribe = first.subscribe(() => observed.push(first.getSnapshot()));
  first.update({ stage: "assets", percent: 60 });
  first.update({ stage: "runtime", percent: 70 });
  first.update({ stage: "assets", percent: 55 });
  first.update({ stage: "assets", percent: NaN });
  first.update({ stage: "projects", percent: 101 });
  expect(first.getSnapshot()).toEqual({ stage: "assets", percent: 60 });
  expect(second.getSnapshot()).toEqual({ stage: "runtime", percent: 5 });
  first.complete();
  first.update({ stage: "projects", percent: 98 });
  expect(first.getSnapshot()).toEqual({ stage: "assets", percent: 100 });
  unsubscribe();
  first.complete();
  expect(observed.map(value => value.percent)).toEqual([60, 100]);
});

test("#422 downloads report comparable bytes and preserve the exact asset", async () => {
  const fractions: number[] = [];
  const body = new ReadableStream<Uint8Array>({ start(controller) {
    controller.enqueue(new Uint8Array([0, 255]));
    controller.enqueue(new Uint8Array([2, 3, 4, 5]));
    controller.enqueue(new Uint8Array([6, 7]));
    controller.close();
  } });
  const bytes = await readStartupAsset(new Response(body, { headers: { "content-length": "8" } }), value => fractions.push(value));
  expect([...bytes]).toEqual([0, 255, 2, 3, 4, 5, 6, 7]);
  expect(fractions).toEqual([0.25, 0.75, 1]);
  for (const headers of [{}, { "content-length": "1", "content-encoding": "gzip" }]) {
    const progress: number[] = [];
    expect([...await readStartupAsset(new Response(new Uint8Array([1, 2]), { headers }), value => progress.push(value))]).toEqual([1, 2]);
    expect(progress).toEqual([]);
  }
  const broken = new Response(new ReadableStream({ start(controller) { controller.error(new Error("transport failed")); } }),
    { headers: { "content-length": "8" } });
  await expect(readStartupAsset(broken, () => {})).rejects.toThrow("transport failed");
});

test("#422 migration joins Local startup without regression; new work gets a fresh lifetime", () => {
  const migration = new StartupProgressStore(authenticationProgress);
  migration.update({ stage: "migration", percent: 32 });
  migration.update({ stage: "migration", percent: 0 }); // retry
  expect(migration.getSnapshot().percent).toBe(32);
  const local = new StartupProgressStore();
  local.restart(true);
  expect(local.getSnapshot().percent).toBeGreaterThan(migration.getSnapshot().percent);
  local.update({ stage: "projects", percent: 90 });
  expect(local.getSnapshot().percent).toBe(94);
  local.complete();
  expect(local.getSnapshot().percent).toBe(100);
  local.restart();
  expect(local.getSnapshot()).toEqual({ stage: "runtime", percent: 5 });
  local.update({ stage: "projects", percent: 90 });
  expect(local.getSnapshot().percent).toBe(90);
});

test("#422 startup waits for Project validation and cannot complete after an account closes", async () => {
  let finishListing!: () => void;
  let listingStarted!: () => void;
  const started = new Promise<void>(resolve => { listingStarted = resolve; });
  const listing = new Promise<void>(resolve => { finishListing = resolve; });
  let workerProgress!: (value: StartupProgress) => void;
  const repository = { list: async () => { listingStarted(); await listing; return { projects: [], unavailable: [] }; } } as unknown as LocalProjectRepository;
  const app = new LocalApplication(() => repository, () => ({
    request: async <T>(_operation: string, _body?: unknown, progress?: (value: StartupProgress) => void) => {
      workerProgress = progress!;
      progress?.({ stage: "application", percent: 89 });
      return { ...state } as T;
    }, dispose() {},
  }));
  const result = app.bootstrap();
  let settled = false;
  void result.then(() => { settled = true; }, () => { settled = true; });
  await started;
  expect(settled).toBe(false);
  expect(app.startup.getSnapshot()).toEqual({ stage: "projects", percent: 90 });
  app.dispose();
  workerProgress({ stage: "projects", percent: 100 });
  expect(app.startup.getSnapshot().percent).toBe(90);
  finishListing();
  await expect(result).rejects.toMatchObject({ code: "ACCOUNT_CONTEXT_CLOSED" });
  expect(app.startup.getSnapshot().percent).toBe(90);
});

test("#422 StrictMode's live subscription receives the first queued bootstrap's progress", async () => {
  let report!: (value: StartupProgress) => void, finish!: () => void;
  let initialized = false;
  const app = new LocalApplication(() => ({
    list: async () => ({ projects: [], unavailable: [], tokens: {} }),
  }) as unknown as LocalProjectRepository, () => ({
    request: async <T>(_operation: string, _body?: unknown, progress?: (value: StartupProgress) => void) => {
      if (!initialized) {
        report = progress!;
        await new Promise<void>(resolve => { finish = resolve; });
        initialized = true;
      }
      return { ...state } as T;
    }, dispose() {},
  }));
  const first = app.bootstrap();
  const unsubscribeFirst = app.startup.subscribe(() => {});
  unsubscribeFirst();
  const values: number[] = [];
  const unsubscribeLive = app.startup.subscribe(() => values.push(app.startup.getSnapshot().percent));
  const second = app.bootstrap();
  await expect.poll(() => !!finish).toBe(true);
  try {
    report({ stage: "dependencies", percent: 45 });
    expect(values).toEqual([45]);
  } finally {
    finish();
    await Promise.all([first, second]);
    unsubscribeLive(); app.dispose();
  }
});

const update: UpdateProjectInput = {
  flight_date: "2026-09-11", departure_time_jst: "09:00",
  total_usable_fuel_gal: 90, default_variation_deg_east: 8,
};
function responses(...items: Response[]) {
  const calls: { path: string; options?: RequestInit }[] = [];
  globalThis.fetch = async (path, options) => {
    calls.push({ path: String(path), options });
    const response = items.shift();
    if (!response) throw new Error("Unexpected fetch");
    return response;
  };
  return calls;
}
function json(value: unknown, status = 200) { return Response.json(value, { status }); }

test("UI and application contract have no transport dependencies", () => {
  const source = resolve("src");
  const uiFiles = ["App.tsx", ...readdirSync(source).filter(name => /^use.*\.tsx?$/.test(name)),
    ...readdirSync(resolve(source, "components")).filter(name => /\.tsx?$/.test(name)).map(name => `components/${name}`)];
  for (const name of [...uiFiles, "application.ts"]) {
    const text = readFileSync(resolve(source, name), "utf8");
    expect(text, name).not.toMatch(/\/api\/|credentials|document\.cookie|\b401\b|new Worker|firebase[\/\"]|comlink|localClient|legacyApplication|localApplication|FastAPI|fetch\(/);
  }
  expect(readFileSync(resolve(source, "application.ts"), "utf8")).not.toMatch(/\bstatus\s*:|RequestInit|Response|\brequest\s*[<(]/);
});

test("Local uses common operations, real progress milestones, and durable repository composition", async () => {
  let created = 0, disposed = 0;
  const operations: string[] = [];
  const repository = { list: async () => ({ projects: [], unavailable: [] }), delete: async () => {},
    read: async () => { throw new ApplicationError("missing", "LOCAL_PROJECT_UNAVAILABLE"); } } as unknown as LocalProjectRepository;
  const app: AutoNavLogApplication = new LocalApplication(() => repository, () => {
    created++;
    return {
      request: async <T>(operation: string) => { operations.push(operation); return state as T; },
      dispose: () => { disposed++; },
    };
  });
  const progress: number[] = [];
  await app.bootstrap();
  await app.updateProject(update);
  await app.updateAndRecalculate(update);
  await app.renameRouteNode("node", "name");
  await app.replaceCheckPoints([]);
  await app.acknowledge("key", true);
  expect(await app.calculate(value => progress.push(value.percent))).toBe(state);
  expect(progress).toEqual([0, 100]);
  expect(operations).toEqual(["bootstrap", "updateProject", "updateAndRecalculate", "renameRouteNode", "replaceCheckPoints", "acknowledge", "calculate"]);
  await expect(app.saveProject("name")).rejects.toMatchObject({ code: "PROJECT_REQUIRED" });
  await expect(app.loadProject("id")).rejects.toMatchObject({ code: "LOCAL_PROJECT_UNAVAILABLE" });
  await app.deleteProject("id");
  await app.newWork();
  await app.bootstrap();
  expect([created, disposed]).toEqual([1, 0]);
  expect(operations.slice(-2)).toEqual(["newWork", "bootstrap"]);
});

test("Local failure never invokes Legacy or emits successful progress", async () => {
  const calls = responses(json(state));
  const domainError = new ApplicationError("missing", "PROJECT_REQUIRED", { candidates: ["a"] });
  const app = new LocalApplication(browserPlatform.persistence.createProjectRepository, () => ({ request: async () => { throw domainError; }, dispose() {} }));
  const progress: number[] = [];
  await expect(app.calculate(value => progress.push(value.percent))).rejects.toBe(domainError);
  expect(progress).toEqual([0]);
  const unavailable = new LocalApplication(browserPlatform.persistence.createProjectRepository, () => { throw new Error("Worker internals"); });
  await expect(unavailable.bootstrap()).rejects.toMatchObject({ code: "APPLICATION_UNAVAILABLE" });
  expect(calls).toEqual([]);
});


test("session decoding preserves invalid text and rejects incompatible UI shapes", async () => {
  const { decodeSession, emptyCheckPointDraft } = await import("../src/applicationSession");
  const { initialPlanningForm } = await import("../src/forms");
  const session = {
    version: 1, working: { version: 1, project: null, outcome: null, destination_wind: null,
      import_result: null, import_filename: null },
    form: { ...initialPlanningForm(), tglCount: "abc", totalUsableFuelGal: "", destinationPatternAltitudeFtMsl: "123" },
    altitudeInputs: { a: "-7" }, navLogDrafts: {}, projectDraft: null,
    calculationInputsAreLocallyCurrent: false, pastedKml: "<incomplete", projectName: "",
    selectedProjectId: "", pendingKmz: null, selectedKmzDocument: "",
    checkPointDraft: { ...emptyCheckPointDraft(), latitude: "invalid" },
    nodeNameDraft: { id: null, name: "" }, vorColumns: [{ id: 0, stationIdentifier: null }],
  };
  expect(session.form.weatherMode).toBe("FORECAST");
  for (const weatherMode of ["FTD", "FORECAST"] as const) {
    const saved = { ...session, form: { ...session.form, weatherMode } };
    expect(decodeSession(JSON.stringify(saved)).form.weatherMode).toBe(weatherMode);
  }
  expect(decodeSession(JSON.stringify(session))).toEqual(session);
  const legacy = structuredClone(session) as typeof session & { form: Record<string, unknown> };
  Reflect.deleteProperty(legacy.form, "departureOrigin");
  expect(decodeSession(JSON.stringify(legacy))).toEqual(session);
  Reflect.deleteProperty(legacy.form, "departureOriginExplicit");
  expect(decodeSession(JSON.stringify(legacy)).form).toEqual({ ...session.form, departureOriginExplicit: true });
  expect(decodeSession(JSON.stringify({ ...legacy, form: { ...legacy.form, departureOrigin: "VOR" } })).form)
    .toMatchObject({ departureOrigin: "VOR", departureOriginExplicit: true });
  expect(() => decodeSession(JSON.stringify({ ...session, form: { ...session.form, departureOriginExplicit: "false" } }))).toThrow();
  expect(decodeSession(JSON.stringify({ ...session, form: { ...session.form, departureOrigin: "VOR" } })).form.departureOrigin).toBe("VOR");
  for (const departureOrigin of [null, 0, "UNKNOWN"]) {
    expect(() => decodeSession(JSON.stringify({ ...session, form: { ...session.form, departureOrigin } }))).toThrow();
  }
  const importing = { ...session, pendingImportDraft: true, selectedImportCandidate: "line:1" };
  expect(decodeSession(JSON.stringify(importing))).toEqual(importing);
  expect(() => decodeSession(JSON.stringify({ ...importing, pendingImportDraft: "true" }))).toThrow();
  expect(() => decodeSession(JSON.stringify({ ...importing, selectedImportCandidate: 1 }))).toThrow();
  expect(() => decodeSession(JSON.stringify({ ...importing, working: { ...session.working, project: { id: "x" } } }))).toThrow();

  const editing = { ...session, working: { ...session.working, project: { id: "project" } },
    editingRouteProjectId: "project", mapRouteDraft: [{ id: "node", original_node_id: "node", name: "RJFM",
      latitude_deg: 31, longitude_deg: 131, airport_id: "RJFM" }] };
  expect(decodeSession(JSON.stringify(editing))).toEqual(editing);
  const longNameEditing = { ...editing, mapRouteDraft: editing.mapRouteDraft.map(point =>
    ({ ...point, name: "既存".repeat(100) })) };
  expect(decodeSession(JSON.stringify(longNameEditing))).toEqual(longNameEditing);
  expect(() => decodeSession(JSON.stringify({ ...editing, editingRouteProjectId: "other" }))).toThrow();
  expect(() => decodeSession(JSON.stringify({ ...editing, editingRouteProjectId: null }))).toThrow();
  expect(decodeSession(JSON.stringify({ ...editing, mapRouteDraft: [] })).editingRouteProjectId).toBe("project");
  for (const malformed of [
    { ...session, version: 99 }, { ...session, form: {} },
    { ...session, navLogDrafts: { a: null } }, { ...session, pendingKmz: {} },
    { ...session, projectDraft: { id: "x", sections: [] } },
    { ...session, checkPointDraft: [] }, { ...session, vorColumns: [null] },
  ]) expect(() => decodeSession(JSON.stringify(malformed))).toThrow();
});

test("failed durable hydration restores the previous runtime working copy", async () => {
  const previous = { version: 1, project: { id: "previous" }, outcome: null,
    destination_wind: null, import_result: null, import_filename: null };
  let current: unknown = previous;
  let opened = false;
  const repository = {
    list: async () => ({ projects: [], unavailable: [] }),
    read: async () => ({ id: "next", draft: { id: "next" }, lastCalculation: null }),
    open: async () => { opened = true; },
  } as unknown as LocalProjectRepository;
  const app = new LocalApplication(() => repository, () => ({
    request: async <T>(operation: string, input?: any) => {
      if (operation === "bootstrap") {
        current = input;
        if (input.project.id === "next") {
          current = null;
          throw new ApplicationError("unavailable reference", "SESSION_RECOVERY_INVALID");
        }
      }
      if (operation === "refreshSavedWork") current = input.working;
      return { ...state, workingRecovery: current } as T;
    }, dispose() {},
  }));
  await expect(app.loadProject("next")).rejects.toMatchObject({ code: "SESSION_RECOVERY_INVALID" });
  expect(current).toEqual(previous);
  expect(opened).toBe(false);
});

for (const storageFails of [false, true]) {
  test(`Local failed recalculation exposes canonical recovery with ${storageFails ? "unchanged" : "committed"} token`, async () => {
    const project = { id: "draft", revision: 0, name: "Draft", metadata: {}, total_usable_fuel_gal: 90 };
    let recovery: any = { version: 1, project, last_calculation: { retained: true }, durableToken: "before" };
    let stored: any = { id: project.id, token: "before", draft: project, checkpoint: null, lastCalculation: recovery.last_calculation };
    const client = () => ({
      request: async <T>(operation: string, input?: any) => {
        if (operation === "bootstrap") recovery = input;
        if (operation === "updateAndRecalculate" || operation === "updateProject") {
          recovery = { ...recovery, project: { ...recovery.project, total_usable_fuel_gal: input.total_usable_fuel_gal } };
          if (operation === "updateAndRecalculate") throw new ApplicationError("calculation failed", "CALCULATION_JOB_FAILED", { retained: true });
        }
        return structuredClone({ ...state, project: recovery.project, workingRecovery: recovery }) as T;
      }, dispose() {},
    });
    const repository = {
      list: async () => ({ projects: [], unavailable: [] }),
      read: async () => structuredClone(stored),
      write: async (record: any, expected: string) => {
        if (storageFails) throw new ApplicationError("storage failed", "LOCAL_STORAGE_FAILED");
        expect(expected).toBe(stored.token);
        stored = structuredClone(record);
      },
    } as unknown as LocalProjectRepository;
    const app = new LocalApplication(() => repository, client);
    await app.bootstrap(recovery);
    const failure = await app.updateAndRecalculate({ ...update, total_usable_fuel_gal: 72 }).catch(error => error);
    expect(failure).toBeInstanceOf(ApplicationError);
    expect(failure.code).toBe(storageFails ? "LOCAL_STORAGE_FAILED" : "CALCULATION_JOB_FAILED");
    expect(failure.committedState.workingRecovery.project.total_usable_fuel_gal).toBe(72);
    expect(failure.committedState.workingRecovery.last_calculation).toEqual({ retained: true });
    expect(failure.committedState.workingRecovery.durableToken).toBe(stored.token);
    if (!storageFails) {
      expect(failure.message).toBe("calculation failed");
      expect(failure.details).toEqual({ retained: true });
      const reloaded = new LocalApplication(() => repository, client);
      await reloaded.bootstrap(failure.committedState.workingRecovery);
      await reloaded.updateProject({ ...update, total_usable_fuel_gal: 71 });
      expect(stored.draft.total_usable_fuel_gal).toBe(71);
    }
  });
}

test("Local route confirmation exposes committed Project after storage failure for save retry", async () => {
  const project = { id: "map-project", revision: 0, name: "Route", metadata: {} };
  let fail = true;
  let stored: any;
  let working: any = { version: 1, project, last_calculation: null };
  const repository = {
    list: async () => ({ projects: [], unavailable: [] }),
    read: async () => stored,
    write: async (record: any, expected: string | null) => {
      expect(expected).toBeNull();
      if (fail) { fail = false; throw new ApplicationError("storage failed", "LOCAL_STORAGE_FAILED"); }
      stored = record;
    },
  } as unknown as LocalProjectRepository;
  const app = new LocalApplication(() => repository, () => ({
    request: async <T>(operation: string, input?: any) => {
      if (operation === "bootstrap") working = input;
      return structuredClone({ ...state, project: working.project, workingRecovery: working }) as T;
    }, dispose() {},
  }));
  const failure = await app.confirmRoute({ ...update, candidate_kind: "map", route_use_confirmed: true }).catch(error => error);
  expect(failure.code).toBe("LOCAL_STORAGE_FAILED");
  expect(failure.details.operation).toBe("confirmRoute");
  expect(failure.committedState.workingRecovery.project.id).toBe(project.id);
  expect(failure.committedState.workingRecovery.durableToken).toBeNull();
  await app.saveProject("Recovered route");
  expect(stored.draft.id).toBe(project.id);
  expect(stored.checkpoint.name).toBe("Recovered route");
});

test("same-account new work drains prior requests, reuses one client, and can repeat", async () => {
  let release!: () => void;
  let created = 0, disposed = 0;
  const operations: string[] = [];
  const app = new LocalApplication(() => ({ list: async () => ({ projects: [], unavailable: [] }) }) as unknown as LocalProjectRepository,
    () => { created++; return {
      request: async <T>(operation: string) => {
        operations.push(operation);
        if (operation === "importRoute") await new Promise<void>(resolve => { release = resolve; });
        return state as T;
      }, dispose: () => { disposed++; },
    }; });
  await app.newWork(); // No runtime is created for untouched work.
  expect(created).toBe(0);
  const prior = app.importRoute({ filename: "old.kml", kml_text: "old" });
  const reset = app.newWork();
  const next = app.bootstrap();
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(operations).toEqual(["importRoute"]);
  release();
  await Promise.all([prior, reset, next]);
  await app.newWork();
  await app.bootstrap();
  expect(operations).toEqual(["importRoute", "newWork", "bootstrap", "newWork", "bootstrap"]);
  expect([created, disposed]).toEqual([1, 0]);
  app.dispose();
  expect(disposed).toBe(1);
  await expect(app.newWork()).rejects.toMatchObject({ code: "ACCOUNT_CONTEXT_CLOSED" });
});

test("account switch interrupts a pending reset without bootstrapping prior work", async () => {
  let release!: () => void;
  const operations: string[] = [];
  const app = new LocalApplication(() => ({ list: async () => ({ projects: [], unavailable: [] }) }) as unknown as LocalProjectRepository,
    () => ({ request: async <T>(operation: string) => {
      operations.push(operation);
      if (operation === "newWork") await new Promise<void>(resolve => { release = resolve; });
      return state as T;
    }, dispose() {} }));
  await app.bootstrap();
  const reset = app.newWork();
  const queued = app.bootstrap();
  await new Promise(resolve => setTimeout(resolve, 0));
  app.dispose();
  release();
  await expect(reset).rejects.toMatchObject({ code: "ACCOUNT_CONTEXT_CLOSED" });
  await expect(queued).rejects.toMatchObject({ code: "ACCOUNT_CONTEXT_CLOSED" });
  expect(operations).toEqual(["bootstrap", "newWork"]);
});

test("Local rounding calculation options do not change Project inputs", async () => {
  const requests: [string, unknown][] = [];
  const app = new LocalApplication(browserPlatform.persistence.createProjectRepository, () => ({
    request: async <T>(operation: string, input?: unknown) => { requests.push([operation, input]); return state as T; }, dispose() {},
  }));
  await app.calculate(undefined, { roundingMode: true });
  await app.calculate(undefined, { roundingMode: false });
  expect(requests).toEqual([["calculate", { rounding_mode: true }], ["calculate", { rounding_mode: false }]]);
});

test("failed Local open rolls back the previous ON result and live mode", async () => {
  const previous = { version: 1, project: { id: "previous" }, outcome: { id: "rounded" }, destination_wind: null };
  let runtime = { ...state, project: previous.project, outcome: previous.outcome, workingRecovery: previous, roundingMode: true } as unknown as WebState;
  const repository = {
    list: async () => ({ projects: [], unavailable: [] }),
    read: async () => ({ id: "next", draft: { id: "next" }, lastCalculation: null }),
    open: async () => { throw new ApplicationError("open failed", "LOCAL_PROJECT_UNAVAILABLE"); },
  } as unknown as LocalProjectRepository;
  const app = new LocalApplication(() => repository, () => ({
    request: async <T>(operation: string, input?: any) => {
      if (operation === "bootstrap") runtime = { ...runtime, project: input.project, outcome: null, workingRecovery: input, roundingMode: false };
      if (operation === "refreshSavedWork") runtime = { ...runtime, project: input.working.project, outcome: input.working.outcome, workingRecovery: input.working, roundingMode: input.rounding_mode };
      return runtime as T;
    }, dispose() {},
  }));
  await expect(app.loadProject("next")).rejects.toMatchObject({ code: "LOCAL_PROJECT_UNAVAILABLE" });
  expect(await app.refreshProjects()).toMatchObject({ roundingMode: true, outcome: previous.outcome, project: previous.project });
});


test("explicit Local Save adopts the same working Project without a recovery bootstrap", async () => {
  let working: any = { version: 1, project: { id: "forecast", revision: 0, name: "Forecast", metadata: {} },
    last_calculation: { retained: true } };
  let stored: any;
  const operations: string[] = [];
  const repository = {
    list: async () => ({ projects: [], unavailable: [] }),
    read: async () => stored,
    write: async (record: any) => { stored = structuredClone(record); },
  } as unknown as LocalProjectRepository;
  const app = new LocalApplication(() => repository, () => ({
    request: async <T>(operation: string, input?: any) => {
      operations.push(operation);
      if (operation === "adoptSavedProject") working = input.working;
      if (operation === "bootstrap") working = input;
      return structuredClone({ ...state, project: working.project, workingRecovery: working }) as T;
    }, dispose() {},
  }));
  const saved = await app.saveProject("Saved forecast");
  expect(operations).toEqual(["state", "adoptSavedProject"]);
  expect(saved.project?.name).toBe("Saved forecast");
  expect(saved.project?.revision).toBe(1);
  expect(saved.workingRecovery?.last_calculation).toEqual({ retained: true });
});


for (const latest of [false, true]) test(`#358 ${latest ? "Latest retains draft" : "load restores checkpoint"}, cancellation and CAS`, async () => {
  const factory = new IDBFactory();
  const repository = new IndexedDbProjectRepository(async raw => structuredClone(raw) as any, async () => {}, () => factory);
  const project: any = { id: "saved", name: "Saved", revision: 1, metadata: {}, total_usable_fuel_gal: 90 };
  const record: any = { schemaVersion: 2, id: project.id, token: "before", checkpoint: latest ? null : project,
    draft: { ...project, total_usable_fuel_gal: 76 }, lastCalculation: { outcome: { provenance: "retained" } }, updatedAt: "before" };
  await repository.write(record, null, latest);
  let working: any = { version: 1, project: record.draft, last_calculation: record.lastCalculation };
  const app = new LocalApplication(() => repository, () => ({
    request: async <T>(operation: string, input?: any) => {
      if (operation === "bootstrap") working = structuredClone(input);
      if (operation === "refreshSavedWork") working = input.working;
      return { ...state, project: working.project, workingRecovery: structuredClone(working) } as T;
    }, dispose() {},
  }));
  let changes: boolean | undefined;
  expect(await app.loadProject(project.id, { confirmDiscard: (_target, dirty) => { changes = dirty; return false; } })).toBeNull();
  expect(changes).toBe(!latest);
  expect(await repository.read(project.id)).toEqual(record);
  expect(working.project).toEqual(record.draft);
  if (!latest) {
    const resolved = await app.loadProject(project.id, { restoreDraft: true });
    expect(resolved?.project?.total_usable_fuel_gal).toBe(76);
    expect(await repository.read(project.id)).toEqual(record);
  }
  const loaded = await app.loadProject(project.id);
  expect(loaded?.project?.total_usable_fuel_gal).toBe(latest ? 76 : 90);
  const restored = await repository.read(project.id);
  expect(restored.draft).toEqual(latest ? record.draft : record.checkpoint);
  expect(restored.lastCalculation).toEqual(record.lastCalculation);
  expect(loaded?.workingRecovery?.durableToken).toBe(restored.token);
  if (!latest) expect(restored.token).not.toBe(record.token);
  await app.loadProject(project.id, { confirmDiscard: (_target, dirty) => { expect(dirty).toBe(false); return true; } });
  // A different tab writes after the confirmed read, before the atomic open.
  const originalOpen = repository.open.bind(repository);
  const newer = { ...restored, token: "other-tab", draft: { ...restored.draft, total_usable_fuel_gal: 65 } };
  repository.open = async (next, expected) => {
    await repository.write(newer, restored.token, false);
    await originalOpen(next, expected);
  };
  await expect(app.loadProject(project.id)).rejects.toMatchObject({ code: "PROJECT_REVISION_CONFLICT" });
  expect(await repository.read(project.id)).toEqual(newer);
  expect(working.project).toEqual(restored.draft);
});


for (const selectedMode of [false, true]) {
  test(`#477 Legacy reconnect preserves the working rounding choice ${selectedMode}`, async () => {
    const urls: string[] = [];
    let unauthorized = true;
    globalThis.fetch = async input => {
      const url = String(input);
      urls.push(url);
      if (url.startsWith("/api/application-session")) {
        return new Response(JSON.stringify({ token: "test-session", state: {
          ...state, workingRecovery: {}, roundingMode: selectedMode,
        } }));
      }
      if (unauthorized) { unauthorized = false; return new Response("", { status: 401 }); }
      return new Response(JSON.stringify({ ...state, workingRecovery: {}, roundingMode: selectedMode }));
    };
    const app = new LegacyApplication();
    await app.bootstrap();
    const refreshed = await app.saveProject("rounding-test");
    expect(refreshed.roundingMode).toBe(selectedMode);
    expect(urls.filter(url => url.startsWith("/api/application-session"))).toEqual([
      "/api/application-session", `/api/application-session?rounding_mode=${selectedMode}`,
    ]);
  });
}
