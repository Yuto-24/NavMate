import { expect, test } from "@playwright/test";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { browserPlatform } from "../src/browserPlatform";
import { routeImportInput } from "../src/fileInput";
import { clearSession, readSession, writeSession, SESSION_KEY, type ApplicationSession } from "../src/applicationSession";
import { createInformationState } from "../src/releaseNotes";
import { IndexedDbProjectRepository } from "../src/localProjectRepository";
import { exportVerticalProfileKml, kmlCopy } from "../src/verticalProfileKml";
import type { VerticalProfile } from "../src/types";
import { projectExportFilename } from "../src/projectExportFilename";

test("Project export names preserve Japanese names and use export time in JST across midnight", () => {
  const at = new Date("2026-11-23T15:04:59Z");
  expect(projectExportFilename("宮崎往復", "json", at)).toBe("宮崎往復_20261124-0004.json");
  expect(projectExportFilename("宮崎往復", "png", at)).toBe("宮崎往復_20261124-0004.png");
  expect(projectExportFilename("経路/A:B?", "json", at)).toBe("経路_A_B__20261124-0004.json");
  expect(projectExportFilename("  ", "png", at)).toBe("プロジェクト_20261124-0004.png");
});

const navigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
test.afterEach(() => {
  if (navigatorDescriptor) Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
  else Reflect.deleteProperty(globalThis, "navigator");
});
const navigatorValue = (value: unknown) => Object.defineProperty(globalThis, "navigator", { configurable: true, value });

test("binary content and metadata reach Importer without paths or UTF-8 conversion", async () => {
  const bytes = Uint8Array.from({ length: 100_000 }, (_, i) => i % 256);
  const file = await browserPlatform.files.read({ name: "日本語.kmz", type: "application/vnd.google-earth.kmz", size: bytes.length,
    arrayBuffer: async () => bytes.buffer });
  const input = routeImportInput(file);
  expect(input.filename).toBe("日本語.kmz");
  expect(Buffer.from(input.content_base64, "base64")).toEqual(Buffer.from(bytes));
  expect(Object.keys(input).sort()).toEqual(["content_base64", "filename"]);
  let read = false;
  await expect(browserPlatform.files.read({ name: "large.kml", type: "", size: 10 * 1024 * 1024 + 1,
    arrayBuffer: async () => { read = true; return bytes.buffer; } })).rejects.toMatchObject({ code: "FAILED", capability: "file-read" });
  expect(read).toBe(false);
  await expect(browserPlatform.files.read({ name: "file", type: "", size: 0 } as any)).rejects.toMatchObject({ code: "UNSUPPORTED" });
});

test("Clipboard has explicit unavailable/denied results and does not replace content", async () => {
  navigatorValue({});
  await expect(browserPlatform.clipboard.readText()).rejects.toMatchObject({ code: "UNSUPPORTED", capability: "clipboard-read" });
  await expect(browserPlatform.clipboard.writeText("text")).rejects.toMatchObject({ code: "UNSUPPORTED", capability: "clipboard-write" });
  navigatorValue({ clipboard: { readText: () => Promise.reject(new Error("denied")), writeText: () => Promise.reject(new Error("denied")) } });
  await expect(browserPlatform.clipboard.readText()).rejects.toMatchObject({ code: "FAILED" });
  await expect(browserPlatform.clipboard.writeText("text")).rejects.toMatchObject({ code: "FAILED" });
  let written = "";
  navigatorValue({ clipboard: { readText: async () => "", writeText: async (text: string) => { written = text; } } });
  expect(await browserPlatform.clipboard.readText()).toBe("");
  await browserPlatform.clipboard.writeText("日本語\nKML");
  expect(written).toBe("日本語\nKML");
});

test("network is a hint and persistence retention is best effort", async () => {
  for (const [value, expected] of [[true, "online"], [false, "offline"], [undefined, "unknown"]]) {
    navigatorValue({ onLine: value });
    expect(browserPlatform.networkAvailability()).toBe(expected);
    expect(() => browserPlatform.persistence.requestRetention()).not.toThrow();
  }
  navigatorValue({ storage: { persist: () => Promise.reject(new Error("denied")) } });
  browserPlatform.persistence.requestRetention();
  await Promise.resolve();
  expect(browserPlatform.persistence.createProjectRepository(async record => record as any)).toBeInstanceOf(IndexedDbProjectRepository);
});

test("Session policy and Information state operate on injected storage, without owning Project data", () => {
  const values = new Map([["unrelated", "keep"], [SESSION_KEY, "old"]]);
  const storage = { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); }, removeItem: (key: string) => { values.delete(key); } };
  expect(readSession({ storage, isReload: () => false })).toEqual({});
  expect(values.has(SESSION_KEY)).toBe(false);
  values.set(SESSION_KEY, "malformed");
  expect(readSession({ storage, isReload: () => true })).toEqual({ failed: true });
  expect(values.get("unrelated")).toBe("keep");
  const denied = { ...storage, setItem: () => { throw new Error("denied"); }, removeItem: () => { throw new Error("denied"); } };
  expect(writeSession({} as ApplicationSession, denied)).toBe(false);
  expect(() => clearSession(denied)).toThrow("denied");
  const information = createInformationState(denied);
  const data = { information: { id: "one", releases: [] }, compatibility: { legacyReleaseInformationIds: {} } };
  expect(information.hasUnreadInformation(data)).toBe(true);
  information.markInformationSeen(data);
  expect(information.hasUnreadInformation(data)).toBe(false);
  expect(values.get("unrelated")).toBe("keep");
});

test("3D KML serializes only the shared projection, escapes names and separates ground references", () => {
  const point = { latitude_deg: 32, longitude_deg: 131, altitude_ft_msl: 5000, elapsed_seconds: 300, distance_nm: 10 };
  const profile: VerticalProfile = { project_name: '<name>&"日本語\u0001', departure_time: "2026-09-11T09:00:00+09:00",
    segments: [{ section_id: "saved", sequence: 0, phase: "CLIMB", points: [{ ...point, altitude_ft_msl: 20, elapsed_seconds: 0, distance_nm: 0 }, point] }],
    markers: [{ name: "VREP", kind: "VISUAL_REPORTING_POINT", point, reference_latitude_deg: null, reference_longitude_deg: null },
      { name: "CP<&", kind: "CHECK_POINT", point, reference_latitude_deg: 32.1, reference_longitude_deg: 131.1 }] };
  const original = JSON.stringify(profile);
  const file = exportVerticalProfileKml(profile, true);
  const text = new TextDecoder().decode(file.content);
  expect(file.mediaType).toBe("application/vnd.google-earth.kml+xml");
  expect(file.name).toBe('_name_&_日本語_.kml');
  expect(text).toContain("&lt;name&gt;&amp;&quot;日本語");
  expect(text).not.toContain("\u0001");
  expect(text).toContain("<LineString><extrude>1</extrude><altitudeMode>absolute</altitudeMode>");
  expect(text).toContain("131,32,1524");
  expect(text).toContain("<altitudeMode>clampToGround</altitudeMode><coordinates>131.1,32.1,0");
  expect(text).toContain('<Data name="abeam_altitude_ft_msl"><value>5000</value>');
  expect(text).toContain(kmlCopy.stale);
  expect(new TextDecoder().decode(exportVerticalProfileKml(profile, false).content)).not.toContain(kmlCopy.stale);
  expect(JSON.stringify(profile)).toBe(original);
  expect(exportVerticalProfileKml({ ...profile, project_name: "宮崎航法" }, false).name).toBe("宮崎航法.kml");
  expect(new TextDecoder().decode(exportVerticalProfileKml(profile, false).content)).not.toContain("<description>");
});

test("missing Browser file save / URL support is explicit, and script URLs are rejected", async () => {
  await expect(browserPlatform.files.save({ name: "result.json", mediaType: "application/json", content: new Uint8Array() })).rejects.toMatchObject({ code: "UNSUPPORTED" });
  expect(() => browserPlatform.openExternalUrl("https://example.com")).toThrow(/外部リンク/);
  expect(() => browserPlatform.openExternalUrl("javascript:alert(1)")).toThrow(/リンク/);
});

test("features have no Browser storage/clipboard or file API branches; core stays independent", () => {
  const files = ["App.tsx", "verticalProfileKml.ts", "applicationSession.ts", "releaseNotes.ts", "application.ts", "localApplication.ts",
    ...readdirSync(resolve("src/components")).filter(name => name.endsWith(".tsx")).map(name => `components/${name}`)];
  for (const file of files) {
    const source = readFileSync(resolve("src", file), "utf8").replace(/\/\/[^\n]*/g, "");
    expect(source, file).not.toMatch(/navigator\.|(?:window\.)?(?:sessionStorage|localStorage)\.|\bindexedDB\b|new FileReader|\.createObjectURL\(|\.arrayBuffer\(/);
  }
  for (const file of ["localClient.ts", "local.worker.ts"]) {
    expect(readFileSync(resolve("src", file), "utf8")).not.toMatch(/from ["']\.\/platform/);
  }
});
