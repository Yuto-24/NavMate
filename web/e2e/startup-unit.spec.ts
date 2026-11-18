import { expect, test } from "@playwright/test";
import { advanceStartup, type StartupProgress, type StartupProgressListener } from "../src/startupProgress";
import { readStartupBytes } from "../src/startupDownload";
import { LocalApplication } from "../src/localApplication";
import type { LocalProjectRepository } from "../src/localProjectRepository";
import type { WebState } from "../src/types";

test("startup remains monotonic through duplicate bootstrap and late worker progress", () => {
  let current: StartupProgress = { percent: 5, stage: "runtime" };
  for (const next of [
    { percent: 52, stage: "download" }, { percent: 5, stage: "runtime" },
    { percent: 75, stage: "application" }, { percent: 60, stage: "download" },
    { percent: 90, stage: "projects" }, { percent: NaN, stage: "runtime" },
  ] as StartupProgress[]) current = advanceStartup(current, next);
  expect(current).toEqual({ percent: 90, stage: "projects" });
});

test("download progress reflects received bytes and preserves the exact payload", async () => {
  const fractions: number[] = [];
  const stream = new ReadableStream<Uint8Array>({ start(controller) {
    controller.enqueue(new Uint8Array([1, 2]));
    controller.enqueue(new Uint8Array([3, 4, 5, 6]));
    controller.enqueue(new Uint8Array([7, 8]));
    controller.close();
  } });
  const bytes = await readStartupBytes(new Response(stream, { headers: { "Content-Length": "8" } }), value => fractions.push(value));
  expect([...bytes]).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  expect(fractions).toEqual([0.25, 0.75, 1, 1]);
});

for (const headers of [{}, { "Content-Encoding": "gzip", "Content-Length": "1" }]) {
  test(`unknown/encoded length advances only after the body completes: ${JSON.stringify(headers)}`, async () => {
    let finish!: () => void;
    const fractions: number[] = [];
    const stream = new ReadableStream<Uint8Array>({ start(controller) {
      controller.enqueue(new Uint8Array([1, 2, 3]));
      finish = () => controller.close();
    } });
    const pending = readStartupBytes(new Response(stream, { headers }), value => fractions.push(value));
    await Promise.resolve();
    expect(fractions).toEqual([]);
    finish();
    expect([...(await pending)]).toEqual([1, 2, 3]);
    expect(fractions).toEqual([1]);
  });
}

test("bootstrap forwards worker progress during recovery and waits for the validated listing", async () => {
  let validate!: () => Promise<void>;
  let finishListing!: () => void;
  const events: StartupProgress[] = [];
  const state = { project: null, savedProjects: [] } as unknown as WebState;
  const app = new LocalApplication(validator => {
    validate = async () => { await validator({}); };
    return {
      restoreWorking: () => validate(),
      list: () => new Promise(resolve => { finishListing = () => resolve({ projects: [], unavailable: [], tokens: {} }); }),
    } as unknown as LocalProjectRepository;
  }, () => ({
    request: async <T>(_operation: string, _input?: unknown, report?: StartupProgressListener) => {
      report?.({ percent: 75, stage: "application" }); return state as T;
    }, dispose() {},
  }));
  let completed = false;
  const boot = app.bootstrap({ version: 1 } as any, progress => events.push(progress)).then(() => { completed = true; });
  await expect.poll(() => events.some(value => value.stage === "projects")).toBe(true);
  expect(events[0]).toEqual({ percent: 75, stage: "application" });
  expect(completed).toBe(false);
  expect(events.every(value => value.percent < 100)).toBe(true);
  finishListing(); await boot;
  const count = events.length;
  await validate();
  expect(events).toHaveLength(count); // later sync operations cannot update startup
});

test("a queued live bootstrap receives initialization progress after StrictMode cleanup", async () => {
  const events: StartupProgress[] = [];
  let firstEffectActive = true;
  let finishInitialization!: () => void;
  let reportFromWorker: StartupProgressListener | undefined;
  let initialized = false;
  const app = new LocalApplication(() => ({
    list: async () => ({ projects: [], unavailable: [], tokens: {} }),
  }) as unknown as LocalProjectRepository, () => ({
    request: async <T>(_operation: string, _input?: unknown, report?: StartupProgressListener) => {
      if (!initialized) {
        reportFromWorker = report;
        await new Promise<void>(resolve => { finishInitialization = resolve; });
        initialized = true;
      }
      return { project: null, savedProjects: [] } as T;
    }, dispose() {},
  }));
  const first = app.bootstrap(undefined, progress => { if (firstEffectActive) events.push(progress); });
  firstEffectActive = false;
  const second = app.bootstrap(undefined, progress => events.push(progress));
  await expect.poll(() => !!finishInitialization).toBe(true);
  try {
    reportFromWorker?.({ percent: 45, stage: "download" });
    expect(events).toEqual([{ percent: 45, stage: "download" }]);
  } finally {
    finishInitialization();
    await Promise.all([first, second]);
    app.dispose();
  }
});
