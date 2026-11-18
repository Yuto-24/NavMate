import { expect, test } from "@playwright/test";
import { parseGsiCivilTrainingAirspaceTile } from "../src/rjfmAirspace";
import { rjfmMapReferenceFixture, type GsiAirspaceCollectionFixture, gsiTile103PolygonNames, gsiTile103Ring, gsiTileBoundaryLatitude, gsiTile104BoundaryDefinitions, gsiAirspaceTile103Fixture, gsiAirspaceTile104Fixture, gsiTile103WithFirstPolygonRing, hasArtificialTileEdgeBoundary, gsiPayloadForMode } from "./helpers/gsiAirspace";

test("GSI live tile Polygon contract fails closed on payload drift", () => {
  const tile = rjfmMapReferenceFixture.civilTrainingTestAirspace.tiles[0];
  const parsed = parseGsiCivilTrainingAirspaceTile(
    gsiAirspaceTile103Fixture,
    tile,
  );
  expect(parsed.polygons.map((polygon) => polygon.name)).toEqual(gsiTile103PolygonNames);
  expect(parsed.boundaries).toHaveLength(10);
  expect(parsed.boundaries[0]?.positions).toEqual([
    [32.0198, 131.332425],
    [31.966921, 131.347334],
    [gsiTileBoundaryLatitude, 131.330727856],
  ]);
  const malformedNonKs4Lines: GsiAirspaceCollectionFixture = {
    ...gsiAirspaceTile103Fixture,
    features: gsiAirspaceTile103Fixture.features.map((feature) => (
      feature.geometry.type === "LineString"
      && feature.properties["空域名称"]?.startsWith("KS3-")
        ? { ...feature, geometry: { ...feature.geometry, coordinates: [[0, 0]] } }
        : feature
    )),
  };
  expect(parseGsiCivilTrainingAirspaceTile(malformedNonKs4Lines, tile).boundaries)
    .toHaveLength(10);
  const missingBoundaryName: GsiAirspaceCollectionFixture = {
    ...gsiAirspaceTile103Fixture,
    features: gsiAirspaceTile103Fixture.features.filter((feature) => (
      !(feature.geometry.type === "LineString"
        && feature.properties["空域名称"] === "KS4-5")
    )),
  };
  expect(() => parseGsiCivilTrainingAirspaceTile(missingBoundaryName, tile)).toThrow(
    "GSI tile is missing an expected KS4 LineString boundary name",
  );

  for (const rejectedMode of [
    "missing-polygon",
    "duplicate-polygon",
    "unexpected-polygon",
    "unexpected-geometry",
  ] as const) {
    expect(() => parseGsiCivilTrainingAirspaceTile(
      gsiPayloadForMode(gsiAirspaceTile103Fixture, rejectedMode, true),
      tile,
    )).toThrow();
  }
});

test("GSI live tile accepts 2D and finite 3D positions only", () => {
  const tile = rjfmMapReferenceFixture.civilTrainingTestAirspace.tiles[0];
  const twoDimensional = parseGsiCivilTrainingAirspaceTile(
    gsiAirspaceTile103Fixture,
    tile,
  );
  expect(twoDimensional.polygons[0]?.positions[0]?.[0]).toEqual([32.12, 131.25]);

  const threeDimensionalRing = gsiTile103Ring.map(
    ([longitude, latitude]) => [longitude, latitude, 0],
  );
  const threeDimensional = parseGsiCivilTrainingAirspaceTile(
    gsiTile103WithFirstPolygonRing(threeDimensionalRing),
    tile,
  );
  expect(threeDimensional.polygons[0]?.positions[0]?.[0]).toEqual([32.12, 131.25]);

  for (const invalidAltitude of ["0", Number.NaN, Number.POSITIVE_INFINITY]) {
    const invalidAltitudeRing = gsiTile103Ring.map(
      ([longitude, latitude]) => [longitude, latitude, invalidAltitude],
    );
    expect(() => parseGsiCivilTrainingAirspaceTile(
      gsiTile103WithFirstPolygonRing(invalidAltitudeRing),
      tile,
    )).toThrow("GSI Polygon coordinate altitude is not finite");
  }

  const extraElementRing = gsiTile103Ring.map(
    ([longitude, latitude]) => [longitude, latitude, 0, 1],
  );
  expect(() => parseGsiCivilTrainingAirspaceTile(
    gsiTile103WithFirstPolygonRing(extraElementRing),
    tile,
  )).toThrow(
    "GSI Polygon coordinate must contain longitude, latitude, and optional altitude",
  );
});

test("GSI live tile validates explicit LineString boundaries independently", () => {
  const tile = rjfmMapReferenceFixture.civilTrainingTestAirspace.tiles[0];
  const boundary = gsiAirspaceTile103Fixture.features.at(-1);
  if (boundary === undefined) throw new Error("boundary fixture is missing");

  const withDuplicateBoundary: GsiAirspaceCollectionFixture = {
    ...gsiAirspaceTile103Fixture,
    features: [...gsiAirspaceTile103Fixture.features, {
      ...boundary,
      geometry: {
        ...boundary.geometry,
        coordinates: [[131.25, 32.13], [131.48, 32.13]],
      },
    }],
  };
  expect(parseGsiCivilTrainingAirspaceTile(withDuplicateBoundary, tile).boundaries)
    .toHaveLength(11);

  const threeDimensionalBoundary: GsiAirspaceCollectionFixture = {
    ...gsiAirspaceTile103Fixture,
    features: [...gsiAirspaceTile103Fixture.features.slice(0, -1), {
      ...boundary,
      geometry: {
        ...boundary.geometry,
        coordinates: [[131.25, 32.12, 0], [131.48, 32.12, 0]],
      },
    }],
  };
  expect(parseGsiCivilTrainingAirspaceTile(threeDimensionalBoundary, tile)
    .boundaries.at(-1)?.positions).toEqual([[32.12, 131.25], [32.12, 131.48]]);

  const tile104 = rjfmMapReferenceFixture.civilTrainingTestAirspace.tiles[1];
  const parsedTile104 = parseGsiCivilTrainingAirspaceTile(gsiAirspaceTile104Fixture, tile104);
  expect(parsedTile104.boundaries).toHaveLength(9);
  expect(parsedTile104.boundaries.map((boundary) => boundary.name)).toEqual(
    gsiTile104BoundaryDefinitions.map(({ name }) => name),
  );
  expect(hasArtificialTileEdgeBoundary(parsedTile104.boundaries)).toBe(false);

  for (const coordinates of [
    [[131.25, 32.12]],
    [[131.25, 32.12], [132.3, 32.12]],
  ]) {
    const malformedBoundary: GsiAirspaceCollectionFixture = {
      ...gsiAirspaceTile103Fixture,
      features: [...gsiAirspaceTile103Fixture.features.slice(0, -1), {
        ...boundary,
        geometry: { ...boundary.geometry, coordinates },
      }],
    };
    expect(() => parseGsiCivilTrainingAirspaceTile(malformedBoundary, tile)).toThrow();
  }

  const missingDisplayMetadata: GsiAirspaceCollectionFixture = {
    ...gsiAirspaceTile103Fixture,
    features: [...gsiAirspaceTile103Fixture.features.slice(0, -1), {
      ...boundary,
      properties: { "空域名称": "KS4-1" },
    }],
  };
  expect(() => parseGsiCivilTrainingAirspaceTile(missingDisplayMetadata, tile)).toThrow();

  const malformedBoundaryName: GsiAirspaceCollectionFixture = {
    ...gsiAirspaceTile103Fixture,
    features: [...gsiAirspaceTile103Fixture.features.slice(0, -1), {
      ...boundary,
      properties: {
        "空域名称": "KS4-",
        "下限": "5500FT",
        "上限": "7000FT",
        "管轄機関": "航空交通管理センター",
      },
    }],
  };
  expect(() => parseGsiCivilTrainingAirspaceTile(malformedBoundaryName, tile)).toThrow();

  const unknownBoundaryName: GsiAirspaceCollectionFixture = {
    ...gsiAirspaceTile103Fixture,
    features: [...gsiAirspaceTile103Fixture.features.slice(0, -1), {
      ...boundary,
      properties: { ...boundary.properties, "空域名称": "KS4-9" },
    }],
  };
  expect(() => parseGsiCivilTrainingAirspaceTile(unknownBoundaryName, tile)).toThrow();
  expect(hasArtificialTileEdgeBoundary(parseGsiCivilTrainingAirspaceTile(
    gsiAirspaceTile103Fixture,
    tile,
  ).boundaries)).toBe(false);
});
