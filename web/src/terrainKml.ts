import type { LonLat } from "./terrain";

/** Out-of-band source verification, not inferred from a filename or KML altitudeMode.
 * Compatibility evidence must cover every point and its datum/epoch against the DEM
 * being used. In particular, ordinary EGM96 absolute KML is not automatically TP.
 */
export interface TerrainKmlEvidence {
  source: string;
  meaning: "terrain" | "obstacle" | "unknown";
  verticalReference: "TP" | "EGM96" | "ellipsoidal" | "unknown";
  demCompatibilityEvidence: string;
}
export interface TerrainKmlPoint {
  placemarkIndex: number;
  coordinate: LonLat;
  elevationM: number;
}
export interface TerrainKmlInput {
  status: "absent" | "available" | "partial" | "empty" | "invalid" | "unconfirmed" | "excluded";
  reason?: string;
  /** Point observations cannot fill a missing DEM area. */
  coverage: "points-only";
  points: TerrainKmlPoint[];
  rejected: { placemarkIndex: number; reason: string }[];
  provenance: {
    source: string;
    sha256: string;
    importedAt: string;
    horizontalReference: "WGS84 longitude-latitude";
    verticalReference: TerrainKmlEvidence["verticalReference"];
    unit: "m";
    meaning: TerrainKmlEvidence["meaning"];
    demCompatibilityEvidence: string;
  } | null;
}

const NAMESPACES = ["http://www.opengis.net/kml/2.2", "http://earth.google.com/kml/2.2"];
const MAX_BYTES = 2 * 1024 * 1024;
const MAX_PLACEMARKS = 10_000;
const NUMBER = "([+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?)";
const COORDINATE = new RegExp(`^\\s*${NUMBER}\\s*,\\s*${NUMBER}\\s*,\\s*${NUMBER}\\s*$`);

/** Browser XML parser only; never load links/styles or render description HTML.
 * This accepts plain KML Point records. Route import/KMZ and Project state are separate.
 */
export async function parseTerrainKml(
  text: string | null,
  evidence?: TerrainKmlEvidence,
): Promise<TerrainKmlInput> {
  const result: TerrainKmlInput = { status: "absent", coverage: "points-only", points: [], rejected: [], provenance: null };
  if (text === null) return result;
  const failure = (status: TerrainKmlInput["status"], reason: string): TerrainKmlInput =>
    ({ ...result, status, reason, points: [] });
  // Bound before allocating UTF-8 bytes and constructing a DOM. Reject DTD/entities
  // before parsing; the parser must never resolve any external resource.
  if (text.length > MAX_BYTES) return failure("invalid", "size-limit");
  const bytes = new TextEncoder().encode(text);
  if (!bytes.length || bytes.length > MAX_BYTES) return failure("invalid", "size-limit");
  try {
    const sha256 = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
      .map(value => value.toString(16).padStart(2, "0")).join("");
    result.provenance = { source: evidence?.source.trim() ?? "", sha256,
      importedAt: new Date().toISOString(), horizontalReference: "WGS84 longitude-latitude",
      verticalReference: evidence?.verticalReference ?? "unknown", unit: "m",
      meaning: evidence?.meaning ?? "unknown", demCompatibilityEvidence: evidence?.demCompatibilityEvidence.trim() ?? "" };
    if (/<!\s*(?:DOCTYPE|ENTITY)\b/i.test(text)) return failure("invalid", "xml-declaration");
    const doc = new DOMParser().parseFromString(text, "application/xml");
    if (doc.getElementsByTagNameNS("*", "parsererror").length || doc.doctype) return failure("invalid", "xml");
    const root = doc.documentElement, ns = root.namespaceURI ?? "";
    if (root.localName !== "kml" || !NAMESPACES.includes(ns)) return failure("invalid", "kml-root");
    if (doc.getElementsByTagNameNS("*", "NetworkLink").length) return failure("invalid", "network-link");
    const placemarks = [...doc.getElementsByTagNameNS(ns, "Placemark")];
    if (placemarks.length > MAX_PLACEMARKS) return failure("invalid", "point-limit");
    if (evidence?.meaning === "obstacle") return failure("excluded", "obstacle-input");
    if (evidence?.meaning !== "terrain") return failure("unconfirmed", "terrain-meaning");
    if (!result.provenance.source) return failure("unconfirmed", "source");
    if (evidence.verticalReference !== "TP" || !result.provenance.demCompatibilityEvidence) {
      return failure("unconfirmed", "vertical-reference");
    }
    for (const [placemarkIndex, placemark] of placemarks.entries()) {
      const reject = (reason: string) => result.rejected.push({ placemarkIndex, reason });
      const geometries = [...placemark.children].filter(node =>
        ["Point", "LineString", "LinearRing", "Polygon", "MultiGeometry", "Model", "Track", "MultiTrack"].includes(node.localName));
      const point = geometries[0];
      if (geometries.length !== 1 || point?.localName !== "Point" || point.namespaceURI !== ns) {
        reject("point-geometry"); continue;
      }
      const modes = [...point.children].filter(node => node.localName === "altitudeMode");
      if (modes.length !== 1 || modes[0]!.namespaceURI !== ns || modes[0]!.textContent?.trim() !== "absolute") {
        reject("altitude-mode"); continue;
      }
      const coordinateNodes = [...point.children].filter(node => node.localName === "coordinates");
      const node = coordinateNodes[0];
      const match = node?.textContent?.match(COORDINATE);
      if (coordinateNodes.length !== 1 || node?.namespaceURI !== ns || node.children.length || !match) {
        reject("coordinates"); continue;
      }
      const lon = Number(match[1]), lat = Number(match[2]), elevationM = Number(match[3]);
      if (![lon, lat, elevationM].every(Number.isFinite) || Math.abs(lon) > 180 || Math.abs(lat) > 90) {
        reject("coordinates"); continue;
      }
      result.points.push({ placemarkIndex, coordinate: [lon, lat], elevationM });
    }
    result.status = result.points.length ? result.rejected.length ? "partial" : "available"
      : result.rejected.length ? "invalid" : "empty";
    return result;
  } catch { return failure("invalid", "parse-unavailable"); }
}
