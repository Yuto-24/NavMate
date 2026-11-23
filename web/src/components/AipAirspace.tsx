import type { CSSProperties } from "react";
import { GeoJSON, Pane } from "react-leaflet";
import { aipCategories, type AipAirspace } from "../aipAirspace";

export function AipAirspaceLayers({ data, hidden, imagery }: { data: AipAirspace; hidden: string[]; imagery: boolean }) {
  return <Pane name="aip-airspace" style={{ zIndex: 350, pointerEvents: "none" }}>
    {data.layers.filter(layer => !hidden.includes(layer.id)).map(layer => <GeoJSON
      key={layer.id} data={layer.data} interactive={false}
      style={{ className: `aip-airspace aip-${layer.id}`, color: aipCategories.find(([id]) => id === layer.id)?.[imagery ? 3 : 2], weight: imagery ? 2.5 : 1.5, opacity: 1, fillOpacity: 0.04 }}
    />)}
  </Pane>;
}

export function AipAirspaceControl({ data, failed, hidden, onChange, pcaVisible, onPcaChange, pcaColor, imagery }: {
  data: AipAirspace | null; failed: boolean; hidden: string[]; onChange: (id: string) => void;
  pcaVisible: boolean; onPcaChange: (visible: boolean) => void; pcaColor: string; imagery: boolean;
}) {
  return <details className="aip-layer-control">
    <summary>空域表示</summary>
    <div className={`aip-layer-options${imagery ? " is-imagery" : ""}`}>
      <label style={{ "--airspace-color": pcaColor } as CSSProperties}>
        <input type="checkbox" checked={pcaVisible} onChange={event => onPcaChange(event.target.checked)} />宮崎特別管制区（PCA）
      </label>
      {aipCategories.map(([id, label, color, imageryColor]) => <label key={id} style={{ "--airspace-color": imagery ? imageryColor : color } as CSSProperties}>
        <input type="checkbox" checked={!hidden.includes(id)} onChange={() => onChange(id)} />{label}
      </label>)}
      {(failed || !data) && <p role="status">{failed ? "AIP空域を読み込めませんでした。再読み込みしてください。" : "AIP空域を読み込み中…"}</p>}
    </div>
  </details>;
}
