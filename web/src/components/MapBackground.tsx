import { useState } from "react";
import { TileLayer, useMapEvents } from "react-leaflet";
import { localMode } from "../executionMode";

// Keep OSM underneath: missing imagery and areas outside Japan remain navigable.
// Only viewport tiles are requested; there is no prefetch or offline tile cache.
// Do not use Leaflet's emptyImageUrl: TileLayer treats it as an aborted load.
const transparentTile = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="256" height="256"/%3E';
const gsiBounds: [[number, number], [number, number]] = [[20, 122], [46, 154]];
const gsiCredit = '<a href="https://maps.gsi.go.jp/development/ichiran.html">地理院タイル</a>';
const landsatCredit = `${gsiCredit} / データソース：Landsat8画像（GSI,TSIC,GEO Grid/AIST）, Landsat8画像（courtesy of the U.S. Geological Survey）, 海底地形（GEBCO）`;
const photoCredit = `${gsiCredit} / GRUS画像（© Axelspace）`;

export function MapBackground({ imagery }: { imagery: boolean }) {
  const [zoom, setZoom] = useState<number | null>(null);
  const map = useMapEvents({ zoomend: () => setZoom(map.getZoom()) });
  const currentZoom = zoom ?? map.getZoom();
  return <>
    <TileLayer
      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      maxZoom={localMode ? 19 : 18}
      zIndex={1}
      referrerPolicy="strict-origin-when-cross-origin"
    />
    {imagery && currentZoom >= 2 && <TileLayer
      url="https://cyberjapandata.gsi.go.jp/xyz/lndst/{z}/{x}/{y}.png"
      attribution={landsatCredit}
      minZoom={2}
      maxZoom={19}
      maxNativeZoom={13}
      bounds={gsiBounds}
      errorTileUrl={transparentTile}
      zIndex={2}
      referrerPolicy="strict-origin-when-cross-origin"
    />}
    {imagery && currentZoom >= 14 && <TileLayer
      url="https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg"
      attribution={photoCredit}
      minZoom={14}
      maxZoom={19}
      maxNativeZoom={18}
      bounds={gsiBounds}
      errorTileUrl={transparentTile}
      zIndex={3}
      referrerPolicy="strict-origin-when-cross-origin"
    />}
  </>;
}
