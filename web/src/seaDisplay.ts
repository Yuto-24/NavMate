import type { SeaInterval } from "./sea";
import { wgs84Inverse } from "./vorRadial";
import type { NavLogDisplayRow, NavSection, SectionResult, RouteNode } from "./types";

// RCA/EOC split calculation rows, not SEA intervals. Put each SEA at its
// interval endpoint; section identity and coordinates also disambiguate names.
export function seaIntervalsByRow(rows: NavLogDisplayRow[], intervals: SeaInterval[]): Map<number, SeaInterval> {
  const result = new Map<number, SeaInterval>();
  for (const interval of intervals) {
    const end = interval.coordinates.at(-1);
    if (!end) continue;
    const matches = rows.filter(row => row.section_id === interval.section_id
      && row.to_latitude_deg != null && row.to_longitude_deg != null
      && Math.abs(row.to_longitude_deg - end[0]) < 1e-6
      && Math.abs(row.to_latitude_deg - end[1]) < 1e-6);
    const row = matches.find(row => row.row_type === "CALCULATION_ZONE")
      ?? matches.find(row => row.row_type === "PHYSICAL_LEG_SUMMARY");
    if (row) result.set(row.sequence, interval);
  }
  return result;
}

// The final visual leg omits all calculation child rows. Its CP intervals still
// exist, so show SEA-only endpoint rows there without inventing calculated data.
export function seaOnlyRowsByParent(rows: NavLogDisplayRow[], intervals: SeaInterval[]): Map<number, SeaInterval[]> {
  const result = new Map<number, SeaInterval[]>();
  for (const row of rows) {
    if (row.row_type !== "PHYSICAL_LEG_SUMMARY") continue;
    const sectionIntervals = intervals.filter(interval => interval.section_id === row.section_id);
    if (sectionIntervals.length > 1
      && !rows.some(child => child.section_id === row.section_id && child.row_type === "CALCULATION_ZONE")) {
      result.set(row.sequence, sectionIntervals);
    }
  }
  return result;
}

// Compare positive-length overlap only: touching RCA/EOC is not cruise exposure.
function cruiseZones(interval: SeaInterval, sections: NavSection[], nodes: RouteNode[],
  results: SectionResult[] | null): SectionResult[] {
    if (results === null) return [];
    const section = sections.find(item => item.id === interval.section_id);
    const start = nodes.find(node => node.id === section?.from_node_id);
    if (!section || !start) return [];
    const station = (lon: number, lat: number) => wgs84Inverse(start.latitude_deg, start.longitude_deg, lat, lon).distanceNm;
    const a = interval.coordinates[0], b = interval.coordinates.at(-1);
    if (!a || !b) return [];
    const left = station(a[0], a[1]), right = station(b[0], b[1]);
    return results.filter(zone => zone.section_id === section.id && zone.phase === "CRUISE"
        && zone.from_latitude_deg != null && zone.from_longitude_deg != null
        && zone.to_latitude_deg != null && zone.to_longitude_deg != null
        && Math.min(right, station(zone.to_longitude_deg!, zone.to_latitude_deg!))
          - Math.max(left, station(zone.from_longitude_deg!, zone.from_latitude_deg!)) > 1e-6);
}

export function seaCruiseIntervals(intervals: SeaInterval[], sections: NavSection[], nodes: RouteNode[],
  results: SectionResult[] | null): SeaInterval[] {
  return intervals.filter(interval => cruiseZones(interval, sections, nodes, results).length > 0);
}

export function seaCruiseCautions(intervals: SeaInterval[], sections: NavSection[], nodes: RouteNode[],
  results: SectionResult[] | null): { interval: SeaInterval; altitude: number }[] {
  return intervals.flatMap(interval => {
    if (interval.automatic_ft == null || !interval.geometry_valid) return [];
    const altitudes = cruiseZones(interval, sections, nodes, results)
        .map(zone => zone.planned_altitude_ft_msl.adopted_source === "MANUAL"
          ? zone.planned_altitude_ft_msl.manual_override : zone.planned_altitude_ft_msl.automatic_value)
        .filter((value): value is number => value !== null);
    const altitude = Math.min(...altitudes);
    return Number.isFinite(altitude) && altitude < interval.automatic_ft ? [{ interval, altitude }] : [];
  });
}
