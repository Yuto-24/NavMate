import { expect, test } from "@playwright/test";
import { seaCruiseIntervals, seaIntervalsByRow, seaOnlyRowsByParent } from "../src/seaDisplay";
import type { SeaInterval } from "../src/sea";
import type { NavLogDisplayRow } from "../src/types";

const interval = (key: string, section: string, end: number): SeaInterval => ({
  key, section_id: section, coordinates: [[130, 30], [130, end]],
} as SeaInterval);
const row = (sequence: number, type: NavLogDisplayRow["row_type"], section: string, end: number): NavLogDisplayRow => ({
  sequence, row_type: type, section_id: section, to_latitude_deg: end, to_longitude_deg: 130,
  to_name: "same name",
} as NavLogDisplayRow);

test("SEA follows each CP interval endpoint, not RCA/EOC or duplicate names and parent rows", () => {
  const intervals = [interval("a", "leg1", 31), interval("b", "leg1", 32), interval("c", "leg1", 33), interval("d", "leg2", 33)];
  const rows = [row(1, "PHYSICAL_LEG_SUMMARY", "leg1", 33), row(2, "CALCULATION_ZONE", "leg1", 30.5),
    row(3, "CALCULATION_ZONE", "leg1", 31), row(4, "CALCULATION_ZONE", "leg1", 32),
    row(5, "CALCULATION_ZONE", "leg1", 32.5), row(6, "CALCULATION_ZONE", "leg1", 33),
    row(7, "PHYSICAL_LEG_SUMMARY", "leg2", 33), row(8, "DESTINATION_INFO", "leg2", 33)];
  expect([...seaIntervalsByRow(rows, intervals)].map(([sequence, value]) => [sequence, value.key]))
    .toEqual([[3, "a"], [4, "b"], [6, "c"], [7, "d"]]);
});

test("a final visual Leg retains all CP SEA intervals despite omitted calculation rows", () => {
  const intervals = [interval("cp1", "visual", 31), interval("cp2", "visual", 32), interval("arrival", "visual", 33)];
  const rows = [row(1, "PHYSICAL_LEG_SUMMARY", "visual", 33), row(2, "DESTINATION_INFO", "visual", 33)];
  expect([...seaOnlyRowsByParent(rows, intervals)]).toEqual([[1, intervals]]);
  expect(seaOnlyRowsByParent([row(1, "PHYSICAL_LEG_SUMMARY", "visual", 33)], [intervals[2]!]).size).toBe(0);
});

test("#315 cruise cautions use positive overlap, automatic SEA and updated planning/results", async () => {
  const { seaCruiseCautions } = await import("../src/seaDisplay");
  const { sections, nodes } = {
    sections: [{ id: "leg", from_node_id: "start", phase: "CRUISE", planned_altitude_ft_msl: 1500 }],
    nodes: [{ id: "start", latitude_deg: 30, longitude_deg: 130 }],
  } as unknown as { sections: import("../src/types").NavSection[]; nodes: import("../src/types").RouteNode[] };
  const intervals = [31, 32, 33].map((end, i) => ({ ...interval(String(i), "leg", end),
    coordinates: [[130, end - 1], [130, end]], automatic_ft: 2000, reference: true, manual_ft: 9999, geometry_valid: true } as SeaInterval));
  const zone = (phase: string, start: number, end: number, altitude = 1500) => ({ section_id: "leg", phase,
    from_latitude_deg: start, from_longitude_deg: 130, to_latitude_deg: end, to_longitude_deg: 130,
    planned_altitude_ft_msl: { automatic_value: altitude, manual_override: null },
  } as import("../src/types").SectionResult);
  const result = [zone("CLIMB", 30, 31), zone("CRUISE", 31, 32), zone("DESCENT", 32, 33)];
  const cautions = (results = result) => seaCruiseCautions(intervals, sections, nodes, results).map(c => c.interval.key);
  const visible = (results: import("../src/types").SectionResult[] | null = result) =>
    seaCruiseIntervals(intervals, sections, nodes, results).map(i => i.key);
  expect(visible()).toEqual(["1"]);
  expect(visible([zone("CRUISE", 30.5, 32.5)])).toEqual(["0", "1", "2"]);
  expect(visible([zone("CRUISE", 30.1, 30.2), zone("CRUISE", 32.8, 32.9)])).toEqual(["0", "2"]);
  expect(visible([zone("CLIMB", 30, 33), zone("DESCENT", 30, 33)])).toEqual([]);
  expect(visible(null)).toEqual([]);
  expect(visible([])).toEqual([]);
  expect(cautions()).toEqual(["1"]);
  expect(cautions([zone("CRUISE", 30.5, 32.5)])).toEqual(["0", "1", "2"]);
  expect(cautions([zone("CRUISE", 31, 32, 2000)])).toEqual([]);
  expect(cautions([zone("CRUISE", 31, 32, 2500)])).toEqual([]);
  expect(cautions([zone("CLIMB", 30, 33), zone("DESCENT", 30, 33)])).toEqual([]);
  intervals[1]!.automatic_ft = null;
  expect(visible()).toEqual(["1"]); // Unknown is shown only for a cruise-overlapping interval.
  expect(cautions()).toEqual([]);
  intervals[1]!.automatic_ft = 2000;
  expect(seaCruiseCautions(intervals, sections, nodes, null)).toEqual([]);
  sections[0]!.planned_altitude_ft_msl = 2000;
  expect(seaCruiseCautions(intervals, sections, nodes, null)).toEqual([]);
  expect(cautions([])).toEqual([]);
});
