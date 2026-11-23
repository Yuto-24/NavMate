import catalog from "../../data/reference/vrep.json" with { type: "json" };

interface LegacyReferenceSource {
  url: string; filename: string; sha256: string;
  table_pdf_page: number; table_page: string; table_effective_date: string;
  arp_pdf_page: number; arp_effective_date: string;
  arp_latitude_dms: string; arp_longitude_dms: string;
  arp_latitude_deg: number; arp_longitude_deg: number;
}
/** Both provenance formats remain readable; explicit Project open upgrades verified legacy copies. */
export type ReferencePointSnapshot = Omit<(typeof catalog)[number], "source"> & {
  source: (typeof catalog)[number]["source"] | LegacyReferenceSource;
};
export const referencePoints: readonly ReferencePointSnapshot[] = catalog;

export interface ProjectedCandidate { id: string; x: number; y: number }
/** Deterministic screen-distance clustering shared by every candidate kind. */
export function clusterCandidates<T extends ProjectedCandidate>(points: T[], radius = 40): T[][] {
  const groups: T[][] = [];
  for (const point of points) {
    const group = groups.find(items => Math.hypot(items[0]!.x - point.x, items[0]!.y - point.y) < radius);
    if (group) group.push(point);
    else groups.push([point]);
  }
  return groups;
}

export function validReferenceSnapshot(value: unknown): value is ReferencePointSnapshot {
  if (!value || typeof value !== "object") return false;
  const point = value as ReferencePointSnapshot;
  const finite = (number: unknown, min: number, max: number) => typeof number === "number" && Number.isFinite(number) && number >= min && number <= max;
  const text = (value: unknown, max: number, required = true) => typeof value === "string" && value.length <= max && (!required || value.trim().length > 0);
  const source = point.source;
  const common = text(point.reference_id, 100) && text(point.name, 100) && text(point.name_ja, 100, false) &&
    ["ROUTE_POINT", "VISUAL_REPORTING_POINT"].includes(point.kind) && /^[A-Z]{4}$/.test(point.airport_icao) &&
    finite(point.latitude_deg, -90, 90) && finite(point.longitude_deg, -180, 180) &&
    finite(point.bearing_true_deg, 0, 360) && finite(point.distance_nm, Number.MIN_VALUE, Number.MAX_VALUE) &&
    text(point.note, 1000, false) && text(point.derivation, 500) && Boolean(source) &&
    text(source.url, 500) && text(source.filename, 100) && /^[0-9a-f]{64}$/.test(source.sha256);
  if (!common) return false;
  if ("format" in source) return source.format === "AIP_SHAPEFILE" &&
    text(source.dataset_id, 100) && source.layer_id === "Visual_REP" &&
    Number.isInteger(source.record_index) && source.record_index >= 0 &&
    /^\d{4}-\d{2}-\d{2}$/.test(source.effective_date) && /^[A-Z]{4}( \/ [A-Z]{4})*$/.test(source.airport_designators);
  return Number.isInteger(source.table_pdf_page) && source.table_pdf_page > 0 && text(source.table_page, 100) &&
    /^\d{4}-\d{2}-\d{2}$/.test(source.table_effective_date) && Number.isInteger(source.arp_pdf_page) && source.arp_pdf_page > 0 &&
    /^\d{4}-\d{2}-\d{2}$/.test(source.arp_effective_date) && text(source.arp_latitude_dms, 20) && text(source.arp_longitude_dms, 20) &&
    finite(source.arp_latitude_deg, -90, 90) && finite(source.arp_longitude_deg, -180, 180);
}
