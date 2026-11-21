import type { SeaInterval } from "./sea";
import type { NavLogDisplayRow } from "./types";

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
