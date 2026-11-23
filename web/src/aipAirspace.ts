import type { FeatureCollection } from "geojson";

// Only published airspace categories; point and route reference layers are not airspace.
export const aipCategories = [
  ["Civil_training_and_testing_areas", "民間訓練・試験空域", "#b82d83", "#ff85d1"],
  ["JSDF_training_and_testing_areas_HIGH", "自衛隊訓練・試験空域（高高度）", "#8455a7", "#d4a6ff"],
  ["JSDF_training_and_testing_areas_LOW", "自衛隊訓練・試験空域（低高度）", "#ae4965", "#ff9bb3"],
  ["Restricted_area_Airspace_restrictions", "飛行制限空域", "#bd382d", "#ff8674"],
  ["Approach_control_area_CIVIL", "進入管制空域（民間）", "#087b78", "#62e3cf"],
  ["Approach_control_area_MIL", "進入管制空域（軍用）", "#417b32", "#a7e576"],
  ["Control_zone_and_Information_zone", "管制圏・情報圏", "#967100", "#ffe06a"],
  ["ACC_Sector_at_or_above_FL335", "ACCセクター（FL335以上）", "#74578b", "#c9a6e5"],
  ["ACC_Sector_below_FL335", "ACCセクター（FL335未満）", "#6f791f", "#d6e97e"],
  ["ADIZ_INNER", "防空識別圏（内側）", "#925d3e", "#efb58a"],
  ["ADIZ_OUTER", "防空識別圏（外側）", "#b45c25", "#ffb479"],
  ["FIR", "飛行情報区", "#5d666f", "#e0e5e9"],
  ["QNH_Application_Area", "QNH適用区域", "#a12f59", "#ff8db4"],
  ["Supersonic_flight_area", "超音速飛行空域", "#825f6e", "#dcb6c7"],
  ["Take_off_flight_path_area", "離陸飛行経路区域", "#477e60", "#97e5b5"],
  ["Corridors", "回廊", "#887247", "#e4d29c"],
] as const;
export const defaultHiddenAipCategories: string[] = aipCategories
  .map(([id]) => id)
  .filter(id => ![
    "Civil_training_and_testing_areas",
    "Approach_control_area_CIVIL",
    "Approach_control_area_MIL",
    "Restricted_area_Airspace_restrictions",
  ].includes(id));
export const pcaColors = { standard: "#a45b13", imagery: "#ffd38a" } as const;
export const pcaPreferenceKey = "autonavlog.pca-visible.v1";
export const aipPreferenceKey = "autonavlog.aip-layers.v1";
interface Asset { file: string; sha256: string; bytes: number }
interface Manifest { schema_version: number; app_version: string; effective_date: string; layers: (Asset & { id: string; feature_count: number })[] }
export interface AipAirspace { effectiveDate: string; layers: { id: string; data: FeatureCollection }[] }
async function checkedJson(url: string, hash: string, bytes?: number): Promise<any> {
  const response = await fetch(url, { signal: AbortSignal.timeout(15000) });
  if (!response.ok) throw new Error("AIP reference unavailable");
  const buffer = await response.arrayBuffer();
  const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", buffer))].map(n => n.toString(16).padStart(2, "0")).join("");
  if (digest !== hash || (bytes !== undefined && buffer.byteLength !== bytes)) throw new Error("AIP reference integrity mismatch");
  return JSON.parse(new TextDecoder().decode(buffer));
}
let pending: Promise<AipAirspace> | undefined;
export function loadAipAirspace(): Promise<AipAirspace> {
  // Shared across Route creation, re-editing and Planning; never part of Project data.
  return pending ??= (async () => {
    const local = await checkedJson("/local/manifest.json", __LOCAL_MANIFEST_SHA256__);
    const reference: Asset = local.mapReference;
    if (!/^reference\/aip\/manifest-[a-f0-9]{64}\.json$/.test(reference?.file)) throw new Error("Missing AIP reference");
    const manifest: Manifest = await checkedJson(`/${reference.file}`, reference.sha256, reference.bytes);
    if (manifest.schema_version !== 1 || manifest.app_version !== local.version) throw new Error("AIP version mismatch");
    const layers = await Promise.all(aipCategories.map(async ([id]) => {
      const asset = manifest.layers.find(layer => layer.id === id);
      if (!asset || !new RegExp(`^${id}-[a-f0-9]{64}\\.geojson$`).test(asset.file)) throw new Error("Missing AIP category");
      const data = await checkedJson(`/reference/aip/${asset.file}`, asset.sha256, asset.bytes);
      if (data.type !== "FeatureCollection" || data.features.length !== asset.feature_count) throw new Error("AIP feature mismatch");
      return { id, data: data as FeatureCollection };
    }));
    return { effectiveDate: manifest.effective_date, layers };
  })().catch(error => { pending = undefined; throw error; });
}
