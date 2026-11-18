import type { VorColumn } from "./applicationSession";
import { VOR_STATIONS, type VorStation } from "./vorRadial";

export function resolveVorStations(columns: VorColumn[], candidates: VorStation[], selectionKey: string) {
  const assigned = new Set<string>();
  const reserve = (identifier: string | undefined) => {
    const station = VOR_STATIONS.find(candidate => candidate.identifier === identifier);
    if (!station || assigned.has(station.identifier)) return null;
    assigned.add(station.identifier);
    return station;
  };
  // Explicit choices take precedence; reserve every retained automatic choice before filling gaps.
  const selected = columns.map(column => column.stationIdentifier ? reserve(column.stationIdentifier) : null);
  columns.forEach((column, index) => {
    if (column.stationIdentifier === null && column.automaticSelectionKey === selectionKey) {
      selected[index] = reserve(column.automaticStationIdentifier);
    }
  });
  return columns.map((column, index) => {
    if (selected[index] || column.stationIdentifier !== null) return selected[index] ?? null;
    const station = candidates.find(candidate => !assigned.has(candidate.identifier)) ?? null;
    if (station) assigned.add(station.identifier);
    return station;
  });
}

export function retainVorStations(columns: VorColumn[], candidates: VorStation[], selectionKey: string): VorColumn[] {
  const selected = resolveVorStations(columns, candidates, selectionKey);
  return columns.map((column, index) => ({
    ...column,
    automaticStationIdentifier: column.stationIdentifier === null ? selected[index]?.identifier : undefined,
    automaticSelectionKey: column.stationIdentifier === null ? selectionKey : undefined,
  }));
}

export function selectVorStation(
  columns: VorColumn[], columnId: number, identifier: string | null, candidates: VorStation[], selectionKey: string,
): VorColumn[] {
  // A stale event cannot take a station explicitly selected in another column.
  if (identifier && columns.some(column => column.id !== columnId && column.stationIdentifier === identifier)) {
    return columns;
  }
  const retained = retainVorStations(columns, candidates, selectionKey);
  return retainVorStations(retained.map(column => column.id === columnId
    ? { ...column, stationIdentifier: identifier,
        automaticStationIdentifier: column.stationIdentifier === null && identifier === null
          ? column.automaticStationIdentifier : undefined }
    : column), candidates, selectionKey);
}
