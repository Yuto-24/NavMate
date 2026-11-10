import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { resolve } from "node:path";

const root = resolve("..");
const python = process.env.AUTONAVLOG_REFERENCE_PYTHON ?? "python3";
const fixture = (mode = "ftd") => JSON.parse(readFileSync(resolve(root, `tests/fixtures/schema4/${mode}.json`), "utf8"));
const normalized = (record: any) => JSON.parse(execFileSync(python, ["-c",
  "import json,sys;from autonavlog.local_persistence import migrate_record;print(migrate_record(json.load(sys.stdin)).model_dump_json())"],
{ cwd: root, input: JSON.stringify(record), encoding: "utf8", env: { ...process.env, PYTHONPATH: `${root}/src` } }));
async function start(page: Page, options: any) {
  await page.goto("/e2e/storage-upgrade-harness/index.html");
  await expect(page.locator("#ready")).toHaveText("Ready");
  await page.evaluate(options => (window as any).upgrade.init(options), options);
}
const call = (page: Page, operation: string, ...args: any[]): Promise<any> =>
  page.evaluate(({ operation, args }) => (window as any).upgrade[operation](...args), { operation, args });
const row = async (page: Page, id: string) => (await call(page, "snapshot")).find((value: any) => value.id === id);

// See docs/forecast_schema_transition.md for the accepted own-device Latest policy.
test("schema4 adapters retain exact v2.2.2 source", () => {
  const provenance = JSON.parse(readFileSync(resolve("e2e/fixtures/v2.2.2/provenance.json"), "utf8"));
  expect(provenance.commit).toBe("03cc463cf09192e1403f839df4165410c5db8d7b");
  for (const [name, hash] of Object.entries(provenance.files)) {
    expect(createHash("sha256").update(readFileSync(resolve("e2e/fixtures/v2.2.2", name))).digest("hex")).toBe(hash);
  }
});

test("schema4 anonymous Saved/Draft and Latest retain calculations across migration, reload and failed write", async ({ page: old, context }) => {
  await start(old, { schema4: true });
  const saved = fixture(), latest = fixture("msm"); latest.checkpoint = null;
  await call(old, "write", saved, null); await call(old, "write", latest, null, true);
  const next = await context.newPage(); await start(next, { schema5: true });
  const expectedSaved = normalized(saved), expectedLatest = normalized(latest);
  expect(await call(next, "read", saved.id)).toEqual(expectedSaved);
  expect(await call(next, "read", latest.id)).toEqual(expectedLatest);
  // Validation alone must not rewrite the stored source.
  expect((await row(next, saved.id)).draft).toEqual(saved.draft);
  const edited = { ...expectedSaved, token: randomUUID(), draft: { ...expectedSaved.draft, pilot_name: "new draft" } };
  await call(next, "write", edited, saved.token);
  const before = await call(next, "snapshot");
  expect(await call(old, "attempt", "write", [{ ...saved, token: randomUUID() }, saved.token])).toBe("PROJECT_REVISION_CONFLICT");
  expect(await call(next, "attempt", "write", [{ ...edited, draft: { id: edited.id } }, edited.token, true])).toBe("domain validation failed");
  expect(await call(next, "snapshot")).toEqual(before);
  await next.reload(); await next.evaluate(() => (window as any).upgrade.init({ schema5: true }));
  expect(await call(next, "read", saved.id)).toEqual(edited);
  expect(await call(next, "read", latest.id)).toEqual(expectedLatest);
  // Schema4 cannot read a migrated record, but must leave the original intact.
  expect((await call(old, "list")).unavailable).toContain(saved.id);
  expect(await call(next, "snapshot")).toEqual(before);
});

test("schema4 old open replaces own Latest only; Saved and another device Latest survive real SDK sync", async ({ page: old, context, browser }) => {
  const account = "schema4-" + randomUUID(), subject = account;
  const saved = fixture(), latest = fixture("msm"); latest.checkpoint = null;
  await start(old, { schema4: true, account, subject });
  await call(old, "write", saved, null); await call(old, "flush");
  const loaded = await call(old, "read", saved.id);
  await old.evaluate(record => sessionStorage.setItem("old-session", JSON.stringify(record)), loaded);
  const next = await context.newPage(); await start(next, { schema5: true, account, subject });
  await call(next, "write", latest, null, true); await call(next, "flush");
  const newLatest = normalized(latest);
  expect((await row(next, latest.id)).sync.value.deletion).toBe("ACTIVE");
  const other = structuredClone(newLatest), otherId = randomUUID();
  other.id = otherId; other.draft.id = otherId; other.lastCalculation = null;
  const foreign = await browser.newContext(), device = await foreign.newPage();
  try {
    await start(device, { schema5: true, account, subject, device: "other-device" });
    await call(device, "flush"); await call(device, "write", other, null, true); await call(device, "flush");
    await call(next, "flush");
    const cloudBefore = await call(next, "remoteList");
    await call(old, "open", loaded);
    expect((await row(next, latest.id)).sync.value.deletion).toBe("DELETED");
    // Commit succeeds; subsequent old-domain receive rejects schema5 and retains local rows.
    expect(await call(old, "attempt", "flush", [])).toBe("schema4 domain reader");
    const cloud = await call(next, "remoteList");
    expect(cloud.find((value: any) => value.id === latest.id).deletion).toBe("DELETED");
    for (const id of [saved.id, otherId]) {
      expect(cloud.find((value: any) => value.id === id)).toEqual(cloudBefore.find((value: any) => value.id === id));
    }
    expect(await old.evaluate(() => JSON.parse(sessionStorage.getItem("old-session")!))).toEqual(loaded);
    await call(device, "flush");
    expect((await call(device, "read", saved.id)).lastCalculation).toEqual(normalized(saved).lastCalculation);
    expect(await call(device, "read", otherId)).toEqual(other);
  } finally { await call(old, "dispose"); await call(next, "dispose"); await call(device, "dispose"); await foreign.close(); }
});

for (const sameProfile of [true, false]) test(`schema4 stale writer preserves Saved and pending work (${sameProfile ? "shared" : "different"} profile)`, async ({ page: old, context, browser }) => {
  const account = "schema4-conflict-" + randomUUID(), subject = account, saved = fixture("msm");
  await start(old, { schema4: true, account, subject, device: "old-device" });
  await call(old, "write", saved, null); await call(old, "flush");
  const loaded = await call(old, "read", saved.id);
  const target = sameProfile ? context : await browser.newContext(), next = await target.newPage();
  try {
    await start(next, { schema5: true, account, subject, device: "new-device" }); await call(next, "flush");
    const base = await call(next, "read", saved.id);
    const updated = { ...base, token: randomUUID(), draft: { ...base.draft, pilot_name: "newer saved work" } };
    await call(next, "write", updated, base.token); await call(next, "flush");
    const before = await call(next, "remoteList");
    const edited = { ...loaded, token: randomUUID(), draft: { ...loaded.draft, pilot_name: "old unsent work" } };
    await call(old, "write", edited, loaded.token);
    if (sameProfile) {
      // Account Sync retains the first stale edit locally alongside the remote branch.
      expect((await row(old, saved.id)).sync.conflict.record).toEqual(updated);
      expect(await call(old, "pending")).toEqual([]);
      expect(await call(old, "attempt", "write", [{ ...edited, token: randomUUID() }, edited.token])).toBe("PROJECT_REVISION_CONFLICT");
    } else {
      await call(old, "holdPending");
      expect(await call(old, "attempt", "finishPending", [])).toBe("schema4 domain reader");
      expect((await row(old, saved.id)).sync.sent.value.record).toEqual(edited);
      // Reload the old device into the candidate, receive the conflict, then explicitly retain both.
      await call(old, "dispose"); await start(old, { schema5: true, account, subject, device: "old-device" });
      await call(old, "receive", before);
      expect((await row(old, saved.id)).draft.pilot_name).toBe("old unsent work");
    }
    expect(await call(next, "remoteList")).toEqual(before);
    const resolver = sameProfile ? next : old;
    expect((await row(resolver, saved.id)).lastCalculation).toEqual(saved.lastCalculation);
    const copyId = await call(resolver, "resolve", saved.id, "both"); await call(resolver, "flush");
    expect((await call(resolver, "read", copyId)).draft.pilot_name).toBe("old unsent work");
    expect((await call(resolver, "read", saved.id)).draft.pilot_name).toBe("newer saved work");
    // Existing explicit conflict cleanup removes stale calculations, never ordinary receive.
    expect((await call(resolver, "read", copyId)).lastCalculation).toBeNull();
  } finally { await call(old, "dispose"); await call(next, "dispose"); if (!sameProfile) await target.close(); }
});

for (const sameProfile of [true, false]) test(`schema4 already-started SDK commit cannot overwrite new Saved (${sameProfile ? "shared" : "different"} profile)`, async ({ page: old, context, browser }) => {
  const account = "schema4-rpc-" + randomUUID(), subject = account, saved = fixture();
  await start(old, { schema4: true, account, subject, device: "old-device" });
  await call(old, "write", saved, null); await call(old, "flush");
  const edit = { ...saved, token: randomUUID(), draft: { ...saved.draft, pilot_name: "started old RPC" } };
  await call(old, "write", edit, saved.token); await call(old, "holdPending");
  let observed!: () => void, release!: () => void;
  const seen = new Promise<void>(resolve => { observed = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  await old.route("http://127.0.0.1:8088/**/documents:commit?*", async route => {
    expect(route.request().postDataJSON().writes[0].currentDocument.updateTime).toBeTruthy();
    observed(); await held; await route.continue();
  });
  await call(old, "startPending"); await seen;
  const target = sameProfile ? context : await browser.newContext(), next = await target.newPage();
  try {
    await start(next, { schema5: true, account, subject, device: "new-device" }); await call(next, "flush");
    const base = await call(next, "read", saved.id);
    const updated = { ...base, token: randomUUID(), draft: { ...base.draft, pilot_name: "new committed work" } };
    await call(next, "write", updated, base.token); await call(next, "flush");
    const before = await call(next, "remoteList"); release();
    expect(["permission-denied", "aborted", "failed-precondition"]).toContain(await call(old, "attempt", "finishStartedPending", []));
    expect(await call(next, "remoteList")).toEqual(before);
    expect(await call(next, "read", saved.id)).toEqual(updated);
    if (!sameProfile) expect((await row(old, saved.id)).sync.sent.value.record).toEqual(edit);
  } finally { release(); await call(old, "dispose"); await call(next, "dispose"); if (!sameProfile) await target.close(); }
});

test("schema4 lost acknowledgement and later offline edit recover through candidate without losing either write", async ({ page: old, context, browser }) => {
  const account = "schema4-ack-" + randomUUID(), subject = account, saved = fixture("msm");
  await start(old, { schema4: true, account, subject });
  await call(old, "write", saved, null); await call(old, "flush");
  const edit = { ...saved, token: randomUUID(), draft: { ...saved.draft, pilot_name: "sent but unacknowledged" } };
  await call(old, "write", edit, saved.token); await call(old, "holdPending");
  // Drop the successful response after the real emulator commit.
  await old.route("http://127.0.0.1:8088/**/documents:commit?*", async route => {
    await route.fetch(); await route.abort("failed");
  });
  await call(old, "startPending");
  const fresh = await browser.newContext(), device = await fresh.newPage();
  try {
    await start(device, { schema5: true, account, subject, device: "fresh-device" });
    await expect.poll(async () => (await call(device, "remoteList")).find((value: any) => value.id === saved.id)?.record.draft.pilot_name).toBe("sent but unacknowledged");
    const offline = { ...edit, token: randomUUID(), draft: { ...edit.draft, pilot_name: "later offline work" } };
    await call(old, "write", offline, edit.token);
    const next = await context.newPage(); await start(next, { schema5: true, account, subject });
    await call(next, "flush"); await call(next, "flush"); await call(device, "flush");
    expect((await call(device, "read", saved.id)).draft.pilot_name).toBe("later offline work");
    expect((await call(device, "read", saved.id)).lastCalculation).toEqual(normalized(saved).lastCalculation);
    expect(await call(next, "pending")).toEqual([]);
    await call(next, "dispose");
  } finally { await call(old, "dispose"); await call(device, "dispose"); await fresh.close(); }
});
