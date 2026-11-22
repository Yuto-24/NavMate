import { expect, test } from "@playwright/test";
import { seaIntervalsByRow, seaOnlyRowsByParent } from "../src/seaDisplay";
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
