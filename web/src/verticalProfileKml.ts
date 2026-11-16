import type { PlatformFile } from "./platform";
import type { ProfilePoint, VerticalProfile } from "./types";

export const kmlCopy = {
  download: "3D KMLをダウンロード",
  saved: "3D KMLのダウンロードを開始しました。",
  stale: "再計算前の結果を出力します。編集した内容は含まれません。",
  unavailable: "3D KMLを出力するには、NAV LOGを再計算してください。",
  description: "最後に成功した計算結果の高度付き経路です。非公式の地上準備用です。",
  flightPath: "飛行経路",
  routePoints: "経路点・計算境界",
  checkPoints: "Check Point（地上の目印）",
  phases: { CLIMB: "CLIMB", CRUISE: "CRUISE", DESCENT: "DESCENT", VISUAL_ARRIVAL: "VISUAL ARRIVAL" },
} as const;

// XML 1.0 text, including untrusted imported/user point names. No HTML/CDATAs.
const xml = (text: string) => text.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/g, "")
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&apos;");
const coordinates = (point: ProfilePoint) =>
  `${point.longitude_deg},${point.latitude_deg},${point.altitude_ft_msl * 0.3048}`;
const data = (values: Record<string, string | number>) => `<ExtendedData>${Object.entries(values)
  .map(([name, value]) => `<Data name="${xml(name)}"><value>${xml(String(value))}</value></Data>`).join("")}</ExtendedData>`;

// Serialization only: all geometry, altitude, timing and phase belong to the
// shared Python projection. The caller owns the PlatformCapabilities save action.
export function exportVerticalProfileKml(profile: VerticalProfile, stale: boolean): PlatformFile {
  const path = profile.segments.map(segment => `<Placemark><name>${xml(kmlCopy.phases[segment.phase as keyof typeof kmlCopy.phases] ?? segment.phase)}</name><styleUrl>#flight</styleUrl>${data({
    section_id: segment.section_id, sequence: segment.sequence, phase: segment.phase,
  })}<LineString><altitudeMode>absolute</altitudeMode><coordinates>${segment.points.map(coordinates).join(" ")}</coordinates></LineString></Placemark>`).join("");
  const markers = (checkPoints: boolean) => profile.markers.filter(marker => (marker.kind === "CHECK_POINT") === checkPoints)
    .map(marker => `<Placemark><name>${xml(marker.name)}</name><styleUrl>#${checkPoints ? "reference" : "boundary"}</styleUrl>${data({
      kind: marker.kind, [checkPoints ? "abeam_altitude_ft_msl" : "altitude_ft_msl"]: marker.point.altitude_ft_msl,
      elapsed_seconds: marker.point.elapsed_seconds, distance_nm: marker.point.distance_nm,
      ...(checkPoints ? { abeam_latitude_deg: marker.point.latitude_deg, abeam_longitude_deg: marker.point.longitude_deg } : {}),
    })}<Point><altitudeMode>${checkPoints ? "clampToGround" : "absolute"}</altitudeMode><coordinates>${checkPoints
      ? `${marker.reference_longitude_deg},${marker.reference_latitude_deg},0`
      : coordinates(marker.point)}</coordinates></Point></Placemark>`).join("");
  const content = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<name>${xml(profile.project_name)}</name><description>${xml(kmlCopy.description + (stale ? " " + kmlCopy.stale : ""))}</description>
<Style id="flight"><LineStyle><color>ffff8000</color><width>4</width></LineStyle></Style>
<Style id="boundary"><IconStyle><color>ff00ffff</color><scale>0.7</scale></IconStyle></Style>
<Style id="reference"><IconStyle><color>ff00ff00</color><scale>0.7</scale></IconStyle></Style>
${data({ departure_time: profile.departure_time, stale: String(stale) })}
<Folder><name>${xml(kmlCopy.flightPath)}</name>${path}</Folder>
<Folder><name>${xml(kmlCopy.routePoints)}</name>${markers(false)}</Folder>
<Folder><name>${xml(kmlCopy.checkPoints)}</name>${markers(true)}</Folder>
</Document></kml>\n`;
  return { name: "navmate-flight-path.kml", mediaType: "application/vnd.google-earth.kml+xml",
    content: new TextEncoder().encode(content) };
}
