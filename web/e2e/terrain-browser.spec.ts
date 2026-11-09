import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

test.beforeEach(async ({ page }) => {
  await page.route("http://127.0.0.1:4193/", route => route.fulfill({ contentType: "text/html", body: "<!doctype html><html></html>" }));
  await page.goto("/");
});

test("native PNG decoder preserves signed centimetres, zero, and missing values", async ({ page }) => {
  const bytes = [...readFileSync(new URL("./fixtures/terrain/dem-signed.png", import.meta.url))];
  const result = await page.evaluate(async data => {
    const { decodeDemPng } = await import("/src/terrainTransport.ts");
    const values = await decodeDemPng(new Uint8Array(data));
    const rejected: boolean[] = [];
    for (const input of [new Uint8Array(data.slice(0, 40)), new Uint8Array(data.slice(0, -12)),
      new Uint8Array(data.map((v, i) => i === 60 ? v ^ 1 : v)), new Uint8Array([1, 2]),
      new Uint8Array(data.map((v, i) => i === 24 ? 16 : v))]) {
      try { await decodeDemPng(input); rejected.push(false); } catch { rejected.push(true); }
    }
    return { values: values.slice(0, 5), count: values.length, rejected };
  }, bytes);
  expect(result).toEqual({ values: [.01, -.01, null, 0, 1], count: 65536, rejected: [true, true, true, true, true] });
});

test("terrain KML retains verified source and signed elevations, selects boundary points without claiming DEM coverage", async ({ page }) => {
  const text = readFileSync(new URL("./fixtures/terrain/terrain-points.kml", import.meta.url), "utf8");
  const result = await page.evaluate(async text => {
    const { parseTerrainKml } = await import("/src/terrainKml.ts");
    const { planTerrainCoverage, terrainContainsPoint } = await import("/src/terrain.ts");
    const evidence = { source: "Synthetic survey fixture", meaning: "terrain", verticalReference: "TP",
      demCompatibilityEvidence: "Fixture points use the same TP datum/epoch as the fixture DEM." } as const;
    const parsed = await parseTerrainKml(text, evidence);
    const coverage = planTerrainCoverage([[131.45, 31.88], [131.453, 31.88], [131.453, 31.883], [131.45, 31.883]]);
    return { parsed, selected: parsed.points.filter(p => terrainContainsPoint(coverage, p.coordinate)),
      coverageStatus: coverage.status, invalidRegionMatches: terrainContainsPoint(planTerrainCoverage([]), [131.45, 31.88]),
      evidenceUnchanged: evidence.meaning === "terrain" };
  }, text);
  expect(result.parsed.status).toBe("available");
  expect(result.parsed.coverage).toBe("points-only");
  expect(result.parsed.points.map(p => p.elevationM)).toEqual([123.45, -2.25, 0, 900]);
  expect(result.selected.map(p => p.placemarkIndex)).toEqual([0, 1, 2]);
  expect(result.parsed.provenance).toMatchObject({ source: "Synthetic survey fixture", verticalReference: "TP", unit: "m", meaning: "terrain" });
  expect(result.parsed.provenance?.sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(result.coverageStatus).toBe("incomplete");
  expect(result.invalidRegionMatches).toBe(false);
  expect(result.evidenceUnchanged).toBe(true);
});

test("absent, invalid, empty, unconfirmed datum/meaning and obstacle input remain distinguishable", async ({ page }) => {
  const text = readFileSync(new URL("./fixtures/terrain/terrain-points.kml", import.meta.url), "utf8");
  const obstacle = readFileSync(new URL("./fixtures/terrain/obstacle-shape.kml", import.meta.url), "utf8");
  const result = await page.evaluate(async ({ text, obstacle }) => {
    const { parseTerrainKml } = await import("/src/terrainKml.ts");
    const evidence = { source: "fixture", meaning: "terrain", verticalReference: "TP", demCompatibilityEvidence: "fixture match" } as const;
    const cases = [
      await parseTerrainKml(null), await parseTerrainKml(""), await parseTerrainKml("<kml"),
      await parseTerrainKml('<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>', evidence),
      await parseTerrainKml(text),
      await parseTerrainKml(text, { ...evidence, source: "" }),
      ...await Promise.all(["unknown", "EGM96", "ellipsoidal"].map(verticalReference => parseTerrainKml(text, { ...evidence, verticalReference }))),
      await parseTerrainKml(text, { ...evidence, demCompatibilityEvidence: "" }),
      await parseTerrainKml(obstacle, { ...evidence, meaning: "obstacle" }),
      await parseTerrainKml(obstacle, evidence),
    ];
    return cases.map(p => ({ status: p.status, reason: p.reason, count: p.points.length, rejected: p.rejected }));
  }, { text, obstacle });
  expect(result.map(p => p.status)).toEqual(["absent", "invalid", "invalid", "empty", "unconfirmed", "unconfirmed",
    "unconfirmed", "unconfirmed", "unconfirmed", "unconfirmed", "excluded", "invalid"]);
  expect(result.every(p => p.count === 0)).toBe(true);
  expect(result[10]!.reason).toBe("obstacle-input");
  expect(result[11]!.rejected).toEqual([{ placemarkIndex: 0, reason: "altitude-mode" }]);
});

test("KML rejects unsafe XML and unsupported altitude/geometry without loading links or changing Local state", async ({ page }) => {
  const externalRequests: string[] = [];
  page.on("request", request => { if (!request.url().startsWith("http://127.0.0.1:4193/")) externalRequests.push(request.url()); });
  const result = await page.evaluate(async () => {
    const { parseTerrainKml } = await import("/src/terrainKml.ts");
    const evidence = { source: "fixture", meaning: "terrain", verticalReference: "TP", demCompatibilityEvidence: "fixture match" } as const;
    const wrap = (body: string) => `<kml xmlns="http://www.opengis.net/kml/2.2"><Document>${body}</Document></kml>`;
    const point = (coord: string, mode = "<altitudeMode>absolute</altitudeMode>") =>
      `<Placemark><Point>${mode}<coordinates>${coord}</coordinates></Point></Placemark>`;
    localStorage.setItem("terrain-test-existing-route", JSON.stringify({ id: "unchanged", coordinates: [[31.88, 131.45]] }));
    const before = localStorage.getItem("terrain-test-existing-route");
    const badDocuments = [
      '<!DOCTYPE kml [<!ENTITY ext SYSTEM "https://example.invalid/external">]>' + wrap("&ext;"),
      wrap('<NetworkLink><Link><href>https://example.invalid/kml</href></Link></NetworkLink>'),
      '<kml xmlns="urn:not-kml"/>', "x".repeat(2 * 1024 * 1024 + 1),
      wrap("<Placemark/>".repeat(10001)),
    ];
    const failures = await Promise.all(badDocuments.map(doc => parseTerrainKml(doc, evidence)));
    const invalidPoints = [point("131,31,YES"), point("131,31,NaN"), point("131,31,Infinity"),
      point("181,31,123"), point("131,91,123"), point("131,31"), point("131,31,"),
      point("131,31,1 132,32,2"), point("131,31,123", ""),
      point("131,31,123", "<altitudeMode>relativeToGround</altitudeMode>"),
      point("131,31,123", "<altitudeMode>clampToGround</altitudeMode>"),
      point("131,31,123", '<altitudeMode xmlns="http://www.google.com/kml/ext/2.2">absolute</altitudeMode>'),
      '<Placemark><LineString><altitudeMode>absolute</altitudeMode><coordinates>131,31,100 132,32,200</coordinates></LineString></Placemark>',
      '<Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>131,31,100</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>',
    ];
    const mixed = await parseTerrainKml(wrap(point("131,31,100") + invalidPoints.join("") +
      '<Style><IconStyle><Icon><href>https://example.invalid/icon.png</href></Icon></IconStyle></Style>'), evidence);
    return { failures: failures.map(p => p.status), mixed, unchanged: localStorage.getItem("terrain-test-existing-route") === before };
  });
  expect(result.failures).toEqual(Array(5).fill("invalid"));
  expect(result.mixed.status).toBe("partial");
  expect(result.mixed.points).toEqual([{ placemarkIndex: 0, coordinate: [131, 31], elevationM: 100 }]);
  expect(result.mixed.rejected).toHaveLength(14);
  expect(result.unchanged).toBe(true);
  expect(externalRequests).toEqual([]);
});
