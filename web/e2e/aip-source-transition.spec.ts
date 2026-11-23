import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createHash, randomUUID } from "node:crypto";
import { resolve } from "node:path";

const root = resolve("..");
const fixture = () => JSON.parse(execFileSync(process.env.AUTONAVLOG_REFERENCE_PYTHON ?? "python3", ["-c", `
import json
from test_vrep_refresh import LocalApplication, ROOT, calculate, record_from, install_snapshot, LEGACY
app=LocalApplication(ROOT/'data',forecast_fixture=ROOT/'tests/fixtures/msm')
try:
 r=record_from(calculate(app))
 for key in ('draft','checkpoint'): install_snapshot(r[key],LEGACY[0])
 r['draft']['pilot_name']='retained distinct draft'
 print(json.dumps(r))
finally: app.close()
`], { cwd: root, encoding: "utf8", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1",
  PYTHONPATH: `${root}/src:${root}/tests/integration` } }));
async function start(page: Page, options: any) {
  await page.goto("/e2e/storage-upgrade-harness/index.html");
  await expect(page.locator("#ready")).toHaveText("Ready");
  await page.evaluate(options => (window as any).upgrade.init(options), options);
}
const call = (page: Page, operation: string, ...args: any[]): Promise<any> =>
  page.evaluate(({ operation, args }) => (window as any).upgrade[operation](...args), { operation, args });

test("pre-AIP adapters retain the exact reviewed DB2 source", () => {
  const provenance = JSON.parse(readFileSync(resolve("e2e/fixtures/pre-aip/provenance.json"), "utf8"));
  expect(provenance.commit).toBe("c95e30a0b4ee0e42804fab832747601a172da4db");
  for (const [name, hash] of Object.entries(provenance.files)) {
    expect(createHash("sha256").update(readFileSync(resolve("e2e/fixtures/pre-aip", name))).digest("hex")).toBe(hash);
  }
});

for (const accountMode of [false, true]) test(`DB2 readers stop before AIP writes and DB3 retains Saved, Draft, Latest and calculations (${accountMode ? "account" : "anonymous"})`, async ({ page: old, context, browser }) => {
  const account = accountMode ? "aip-" + randomUUID() : null, subject = account ?? "";
  const saved = fixture(), latest = fixture(); latest.checkpoint = null;
  await start(old, { preAip: true, account, subject });
  await call(old, "write", saved, null); await call(old, "write", latest, null, true);
  if (accountMode) await call(old, "flush");
  await old.evaluate(record => sessionStorage.setItem("old-session", JSON.stringify(record)), saved);
  const before = await call(old, "snapshot");
  const next = await context.newPage(); await start(next, { schema5: true, account, subject });
  await call(next, "list");
  expect(await call(next, "snapshot")).toEqual(before); // The DB upgrade never rewrites records.
  expect(await call(next, "read", saved.id)).toEqual(saved);
  const updated = await call(next, "prepareReferenceUpdate", saved);
  expect(updated.draft.route_nodes[1].reference_snapshot.source.format).toBe("AIP_SHAPEFILE");
  expect(updated.draft.pilot_name).toBe("retained distinct draft");
  expect(updated.lastCalculation).toEqual(saved.lastCalculation);
  await call(next, "write", updated, saved.token);
  if (accountMode) await call(next, "flush");
  const after = await call(next, "snapshot");
  for (const [operation, args] of [["list", []], ["read", [saved.id]], ["open", [saved]],
    ["write", [{ ...saved, token: randomUUID() }, saved.token]], ["delete", [saved.id, saved.token]],
    ...(accountMode ? [["pending", []]] : [])] as [string, any[]][]) {
    expect(await call(old, "attempt", operation, args)).toBe("LOCAL_STORAGE_FAILED");
  }
  expect(await call(next, "snapshot")).toEqual(after);
  expect(await old.evaluate(() => JSON.parse(sessionStorage.getItem("old-session")!))).toEqual(saved);
  await call(next, "dispose"); await start(next, { schema5: true, account, subject });
  expect(await call(next, "read", saved.id)).toEqual(updated);
  expect(await call(next, "read", latest.id)).toEqual(latest);
  if (accountMode) {
    const fresh = await browser.newContext(), device = await fresh.newPage();
    try {
      await start(device, { schema5: true, account, subject, device: "fresh-device" }); await call(device, "flush");
      expect(await call(device, "read", saved.id)).toEqual(updated);
      expect(await call(device, "read", latest.id)).toEqual(latest);
    } finally { await call(device, "dispose"); await fresh.close(); }
  }
  await call(next, "dispose"); await call(old, "dispose");
});

for (const blocked of [false, true]) test(`DB2 ${blocked ? "blocked upgrade preserves original rows" : "in-flight write finishes before upgrade"}`, async ({ page: old, context }) => {
  const saved = fixture(); await start(old, { preAip: true }); await call(old, "write", saved, null);
  const before = await call(old, "snapshot"); await call(old, "hold", blocked, 2);
  const next = await context.newPage(); await start(next, { schema5: true });
  if (blocked) {
    const prepared = await call(next, "prepareReferenceUpdate", saved);
    expect(await call(next, "attempt", "write", [prepared, saved.token])).toBe("LOCAL_STORAGE_FAILED");
    expect(await call(old, "heldSnapshot")).toEqual(before);
    await call(old, "closeBlocker"); await call(next, "list");
    expect(await call(next, "snapshot")).toEqual(before);
  } else {
    await call(next, "startUpgrade");
    await expect.poll(() => old.evaluate(() => (window as any).upgrade.status.versionchange)).toBe(true);
    expect(await next.evaluate(() => (window as any).upgrade.status.upgraded)).toBe(false);
    await call(old, "release");
    await expect.poll(() => old.evaluate(() => (window as any).upgrade.status.transactionComplete)).toBe(true);
    await call(next, "list");
    expect((await call(next, "read", saved.id)).draft.pilot_name).toBe("transaction completed before upgrade");
    expect((await call(next, "read", saved.id)).lastCalculation).toEqual(saved.lastCalculation);
  }
  expect(await call(old, "attempt", "read", [saved.id])).toBe("LOCAL_STORAGE_FAILED");
});

for (const sameProfile of [true, false]) test(`pre-AIP in-flight SDK write cannot overwrite the AIP update (${sameProfile ? "shared" : "different"} profile)`, async ({ page: old, context, browser }) => {
  const account = "aip-rpc-" + randomUUID(), subject = account, saved = fixture();
  await start(old, { preAip: true, account, subject, device: "old-device" });
  await call(old, "write", saved, null); await call(old, "flush");
  const edited = { ...saved, token: randomUUID(), draft: { ...saved.draft, pilot_name: "old pending work" } };
  await call(old, "write", edited, saved.token); await call(old, "holdPending");
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
    const base = await call(next, "read", saved.id), updated = await call(next, "prepareReferenceUpdate", base);
    await call(next, "write", updated, base.token); await call(next, "flush");
    const before = await call(next, "remoteList"); release();
    expect(["permission-denied", "aborted", "failed-precondition"]).toContain(await call(old, "attempt", "finishStartedPending", []));
    await old.unroute("http://127.0.0.1:8088/**/documents:commit?*");
    expect(await call(next, "remoteList")).toEqual(before);
    expect(await call(next, "read", saved.id)).toEqual(updated);
    if (sameProfile) {
      expect(updated.draft.pilot_name).toBe("old pending work");
      expect(await call(old, "attempt", "list", [])).toBe("LOCAL_STORAGE_FAILED");
    } else {
      expect(await call(old, "attempt", "receive", [before])).toBe("pre-AIP domain reader");
      expect((await call(old, "snapshot"))[0].sync.sent.value.record).toEqual(edited);
      await call(old, "dispose"); await start(old, { schema5: true, account, subject, device: "old-device" });
      await call(old, "receive", before);
      expect((await call(old, "read", saved.id)).draft.pilot_name).toBe("old pending work");
      const copyId = await call(old, "resolve", saved.id, "both"); await call(old, "flush");
      expect((await call(old, "read", copyId)).draft.pilot_name).toBe("old pending work");
      expect((await call(old, "read", saved.id)).draft.route_nodes[1].reference_snapshot.source.format).toBe("AIP_SHAPEFILE");
    }
  } finally { release(); await call(old, "dispose"); await call(next, "dispose"); if (!sameProfile) await target.close(); }
});
