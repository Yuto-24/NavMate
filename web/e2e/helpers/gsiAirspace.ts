import type { RjfmCivilTrainingTestAirspaceName, RjfmMapReference } from "../../src/types";

const rjfmMapReferenceFixture: RjfmMapReference = {
  revision: "2026-08-17-rjfm-umk-guidance-v3",
  contentFingerprint: "c".repeat(64),
  pca: {
    name: "MIYAZAKI_SPECIAL_CONTROL_AREA",
    polygonVertices: [
      { latitudeDeg: 31.934444444444445, longitudeDeg: 131.52 },
      { latitudeDeg: 31.834444444444443, longitudeDeg: 131.5327777777778 },
      { latitudeDeg: 31.851666666666667, longitudeDeg: 131.74166666666665 },
      { latitudeDeg: 31.951666666666664, longitudeDeg: 131.73111111111112 },
    ],
    exclusionCenter: {
      latitudeDeg: 31.883333333333333,
      longitudeDeg: 131.45,
    },
    exclusionRadiusKm: 9,
    sourceAltitudeLowerM: 200,
    sourceAltitudeUpperM: 800,
    operationalAltitudeLowerFtMsl: 656,
    operationalAltitudeUpperFtMsl: 2700,
    altitudeBoundsInclusive: true,
    operationalAltitudePolicyStatus: "USER_APPROVED_NOT_EXACT_METRIC_CONVERSION",
    sourceIds: [
      "mlit-special-control-area-consolidated-2024-02-08",
      "user-approved-rjfm-guidance-policy-2026-08-16",
    ],
  },
  civilTrainingTestAirspace: {
    availability: "REMOTE_GSI_GEOJSON",
    dataUse: "DISPLAY_ONLY_LIVE_REFERENCE",
    contentFingerprintScope: "CONFIGURATION_ONLY_LIVE_GEOJSON_EXCLUDED",
    sourcePageUrl: "https://www.mlit.go.jp/koku/koku_tk10_000004.html",
    layerMetadataUrl: (
      "https://maps.gsi.go.jp/development/ichiran.html"
      + "#kokuarea_minkankunren"
    ),
    tileUrlTemplate: (
      "https://maps.gsi.go.jp/xyz/kokuarea_minkankunren/"
      + "{z}/{x}/{y}.geojson"
    ),
    tileUrls: [
      "https://maps.gsi.go.jp/xyz/kokuarea_minkankunren/8/221/103.geojson",
      "https://maps.gsi.go.jp/xyz/kokuarea_minkankunren/8/221/104.geojson",
    ],
    tiles: [
      {
        url: "https://maps.gsi.go.jp/xyz/kokuarea_minkankunren/8/221/103.geojson",
        expectedPolygonNames: ["KS4-1/4", "KS4-1", "KS4-3", "KS4-5"],
      },
      {
        url: "https://maps.gsi.go.jp/xyz/kokuarea_minkankunren/8/221/104.geojson",
        expectedPolygonNames: [
          "KS4-2",
          "KS4-7",
          "KS4-6",
          "KS4-1/4",
          "KS4-1",
          "KS4-3",
          "KS4-5",
          "KS4-8",
        ],
      },
    ],
    featureNamePrefix: "KS4-",
    checkedAtUtc: "2026-08-17T04:16:51Z",
    caution: "地図には誤差が含まれる場合があります。この表示は参照専用で、NAV LOG計算やPCA判定には使用しません。",
    sourceIds: [
      "mlit-civil-training-test-airspace-map-2026-08-17",
      "mlit-gsi-boundary-caution-2026-08-17",
      "gsi-civil-training-test-airspace-geojson-2026-08-17",
    ],
  },
};

interface GsiAirspaceFeatureFixture {
  type: "Feature";
  properties: Record<string, string>;
  geometry: {
    type: string;
    coordinates: unknown;
  };
}

interface GsiAirspaceCollectionFixture {
  type: "FeatureCollection";
  features: GsiAirspaceFeatureFixture[];
}

const gsiTile103PolygonNames: RjfmCivilTrainingTestAirspaceName[] = [
  "KS4-1/4",
  "KS4-1",
  "KS4-3",
  "KS4-5",
];
const gsiTile104PolygonNames: RjfmCivilTrainingTestAirspaceName[] = [
  "KS4-2",
  "KS4-7",
  "KS4-6",
  "KS4-1/4",
  "KS4-1",
  "KS4-3",
  "KS4-5",
  "KS4-8",
];
const gsiTile103Ring = [
  [131.25, 32.12],
  [131.48, 32.12],
  [131.48, 32.28],
  [131.25, 32.28],
  [131.25, 32.12],
];
const gsiTileBoundaryLatitude = 31.952162238024968;
const gsiTile104Ring = [
  [131.32, gsiTileBoundaryLatitude],
  [131.55, gsiTileBoundaryLatitude],
  [131.55, 31.92],
  [131.32, 31.92],
  [131.32, gsiTileBoundaryLatitude],
];
const gsiTile103BoundaryDefinitions = [
  {
    name: "KS4-1/4",
    coordinates: [
      [131.332425, 32.0198],
      [131.347334, 31.966921],
      [131.330727856, gsiTileBoundaryLatitude],
    ],
  },
  {
    name: "KS4-1/4",
    coordinates: [
      [131.281417314, gsiTileBoundaryLatitude],
      [131.298788, 31.996833],
      [131.332425, 32.0198],
    ],
  },
  {
    name: "KS4-1",
    coordinates: [
      [131.26199, 31.953105],
      [131.270026, 31.95758],
      [131.281417314, gsiTileBoundaryLatitude],
    ],
  },
  {
    name: "KS4-1",
    coordinates: [
      [131.330727856, gsiTileBoundaryLatitude],
      [131.377136, 31.983763],
      [131.535484, 31.989806],
      [131.613460733, gsiTileBoundaryLatitude],
    ],
  },
  {
    name: "KS4-1",
    coordinates: [
      [131.261473182, gsiTileBoundaryLatitude],
      [131.26199, 31.953105],
    ],
  },
  {
    name: "KS4-3",
    coordinates: [
      [130.980556, 31.994444],
      [131.332425, 32.0198],
      [131.261473132, gsiTileBoundaryLatitude],
    ],
  },
  {
    name: "KS4-3",
    coordinates: [
      [130.979182216, gsiTileBoundaryLatitude],
      [130.980556, 31.994444],
    ],
  },
  {
    name: "KS4-5",
    coordinates: [
      [130.836781, 32.197636],
      [130.990439, 32.07944],
      [130.979182216, gsiTileBoundaryLatitude],
    ],
  },
  {
    name: "KS4-5",
    coordinates: [
      [130.904940776, gsiTileBoundaryLatitude],
      [130.863127, 31.980683],
      [130.78125, 32.009545151],
    ],
  },
  {
    name: "KS4-5",
    coordinates: [
      [130.78125, 32.012954614],
      [130.836781, 32.197636],
    ],
  },
] satisfies Array<{ name: string; coordinates: number[][] }>;
const gsiTile104BoundaryDefinitions = [
  {
    name: "KS4-2",
    coordinates: [
      [131.567778, 31.584167],
      [131.338889, 31.539722],
      [131.390248, 31.716566],
      [131.55241, 31.743382],
      [131.670556, 31.603333],
      [131.567778, 31.584167],
    ],
  },
  {
    name: "KS4-7",
    coordinates: [
      [131.214366, 31.772685],
      [131.383816, 31.694158],
      [131.338889, 31.539722],
      [131.157497, 31.583613],
      [131.208632, 31.729445],
      [131.214366, 31.772685],
    ],
  },
  {
    name: "KS4-6",
    coordinates: [
      [131.187036, 31.658287],
      [131.148611, 31.588056],
      [131.02, 31.651944],
      [130.975556, 31.840556],
      [131.214372, 31.772769],
      [131.187036, 31.658287],
    ],
  },
  {
    name: "KS4-1/4",
    coordinates: [
      [131.330727856, gsiTileBoundaryLatitude],
      [131.31733, 31.935081],
      [131.281417314, gsiTileBoundaryLatitude],
    ],
  },
  {
    name: "KS4-1",
    coordinates: [
      [131.281417314, gsiTileBoundaryLatitude],
      [131.31733, 31.935081],
      [131.330727856, gsiTileBoundaryLatitude],
    ],
  },
  {
    name: "KS4-1",
    coordinates: [
      [131.613460733, gsiTileBoundaryLatitude],
      [131.633337, 31.878577],
      [131.555313, 31.745282],
      [131.383611, 31.694167],
      [131.2, 31.779444],
      [131.261634, 31.805264],
      [131.241597, 31.878577],
      [131.261473182, gsiTileBoundaryLatitude],
    ],
  },
  {
    name: "KS4-3",
    coordinates: [
      [131.261473132, gsiTileBoundaryLatitude],
      [131.241597, 31.878577],
      [131.042778, 31.852222],
      [130.979182216, gsiTileBoundaryLatitude],
    ],
  },
  {
    name: "KS4-5",
    coordinates: [
      [130.979182216, gsiTileBoundaryLatitude],
      [130.975556, 31.840556],
      [130.947537, 31.904714],
      [130.904940776, gsiTileBoundaryLatitude],
    ],
  },
  {
    name: "KS4-8",
    coordinates: [
      [131.670556, 31.603333],
      [131.794444, 31.456111],
      [131.586667, 31.415833],
      [131.568333, 31.583611],
      [131.670556, 31.603333],
    ],
  },
] satisfies Array<{ name: string; coordinates: number[][] }>;

function gsiDisplayMetadata(name: string): Record<string, string> {
  switch (name) {
    case "KS4-1/4":
      return { "下限": "SFC", "上限": "7000FT", "管轄機関": "航空交通管理センター" };
    case "KS4-1":
      return { "下限": "5500FT", "上限": "7000FT", "管轄機関": "航空交通管理センター" };
    case "KS4-2":
      return { "下限": "SFC", "上限": "8000FT", "管轄機関": "航空交通管理センター" };
    case "KS4-3":
    case "KS4-5":
    case "KS4-7":
      return { "下限": "SFC", "上限": "6000FT", "管轄機関": "航空交通管理センター" };
    case "KS4-6":
      return { "下限": "SFC", "上限": "4000FT", "管轄機関": "航空交通管理センター" };
    case "KS4-8":
      return { "下限": "SFC", "上限": "8000FT", "管轄機関": "航空交通管理センター" };
    case "KS3-8":
      return { "下限": "5000FT", "上限": "FL150", "管轄機関": "航空交通管理センター" };
    case "KS3-4":
    case "KS3-5":
    case "KS3-6":
    case "KS3-7":
      return { "下限": "SFC", "上限": "5000FT", "管轄機関": "航空交通管理センター" };
    default:
      throw new Error(`unexpected GSI fixture name: ${name}`);
  }
}

function gsiPolygonFeature(
  name: string,
  ring: number[][],
): GsiAirspaceFeatureFixture {
  return {
    type: "Feature",
    properties: {
      "空域名称": name,
      ...gsiDisplayMetadata(name),
    },
    geometry: {
      type: "Polygon",
      coordinates: [ring],
    },
  };
}

function gsiLineStringFeature(
  name: string,
  coordinates: number[][],
): GsiAirspaceFeatureFixture {
  return {
    type: "Feature",
    properties: {
      "空域名称": name,
      ...gsiDisplayMetadata(name),
    },
    geometry: { type: "LineString", coordinates },
  };
}

const gsiAirspaceTile103Fixture: GsiAirspaceCollectionFixture = {
  type: "FeatureCollection",
  features: [
    ...gsiTile103PolygonNames.map((name) => gsiPolygonFeature(name, gsiTile103Ring)),
    {
      ...gsiPolygonFeature("KS3-4", [
        [131.1, 32],
        [131.2, 32],
        [131.2, 32.1],
        [131.1, 32],
      ]),
    },
    gsiLineStringFeature("KS3-4", [[132.166667, 32.903056], [132.175356113, 33.137551192]]),
    gsiLineStringFeature("KS3-5", [[132.1875, 32.5802532], [132.1875, 32.904973205]]),
    ...gsiTile103BoundaryDefinitions.map(({ name, coordinates }) => (
      gsiLineStringFeature(name, coordinates)
    )),
  ],
};

const gsiAirspaceTile104Fixture: GsiAirspaceCollectionFixture = {
  type: "FeatureCollection",
  features: [
    ...gsiTile104PolygonNames.map((name) => gsiPolygonFeature(name, gsiTile104Ring)),
    ...gsiTile104BoundaryDefinitions.map(({ name, coordinates }) => (
      gsiLineStringFeature(name, coordinates)
    )),
  ],
};

function gsiTile103WithFirstPolygonRing(
  ring: unknown,
): GsiAirspaceCollectionFixture {
  return {
    ...gsiAirspaceTile103Fixture,
    features: gsiAirspaceTile103Fixture.features.map((feature, index) => (
      index === 0
        ? {
            ...feature,
            geometry: { ...feature.geometry, coordinates: [ring] },
          }
      : feature
    )),
  };
}

function hasArtificialTileEdgeBoundary(
  boundaries: { positions: [number, number][] }[],
): boolean {
  return boundaries.some((boundary) => (
    boundary.positions.length >= 2
    && boundary.positions.every(([latitude]) => latitude === gsiTileBoundaryLatitude)
  ));
}

type GsiFixtureMode =
  | "valid"
  | "malformed"
  | "oversized"
  | "missing-polygon"
  | "duplicate-polygon"
  | "unexpected-polygon"
  | "unexpected-geometry"
  | "http-error"
  | "http-error-with-peer-pending";

function gsiPayloadForMode(
  basePayload: GsiAirspaceCollectionFixture,
  mode: GsiFixtureMode,
  isTile103: boolean,
): GsiAirspaceCollectionFixture {
  if (mode === "malformed" && isTile103) {
    return {
      ...basePayload,
      features: [{
        ...basePayload.features[0],
        geometry: {
          type: "Polygon",
          coordinates: [[
            [0, 0],
            [0.1, 0],
            [0.1, 0.1],
            [0, 0],
          ]],
        },
      }],
    };
  }
  if (mode === "missing-polygon" && isTile103) {
    return {
      ...basePayload,
      features: basePayload.features.filter((feature) => !(
        feature.geometry.type === "Polygon"
        && feature.properties["空域名称"] === "KS4-5"
      )),
    };
  }
  if (mode === "duplicate-polygon" && isTile103) {
    return {
      ...basePayload,
      features: [...basePayload.features, { ...basePayload.features[0] }],
    };
  }
  if (mode === "unexpected-polygon" && isTile103) {
    return {
      ...basePayload,
      features: [
        ...basePayload.features,
        gsiPolygonFeature("KS4-8", gsiTile103Ring),
      ],
    };
  }
  if (mode === "unexpected-geometry" && isTile103) {
    return {
      ...basePayload,
      features: basePayload.features.map((feature) => (
        feature.geometry.type === "Polygon"
        && feature.properties["空域名称"] === "KS4-3"
          ? {
              ...feature,
              geometry: {
                type: "Point",
                coordinates: [131.32, 32.18],
              },
            }
          : feature
      )),
    };
  }
  return basePayload;
}

export { type GsiAirspaceCollectionFixture, type GsiFixtureMode, gsiAirspaceTile103Fixture, gsiAirspaceTile104Fixture, gsiPayloadForMode, gsiTile103PolygonNames, gsiTile103Ring, gsiTile103WithFirstPolygonRing, gsiTile104BoundaryDefinitions, gsiTileBoundaryLatitude, hasArtificialTileEdgeBoundary, rjfmMapReferenceFixture };
