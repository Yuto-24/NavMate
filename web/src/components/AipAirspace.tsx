import { GeoJSON, Pane } from "react-leaflet";
import { aipCategories, type AipAirspace } from "../aipAirspace";

export function AipAirspaceLayers({ data, hidden }: { data: AipAirspace; hidden: string[] }) {
  return <Pane name="aip-airspace" style={{ zIndex: 350, pointerEvents: "none" }}>
    {data.layers.filter(layer => !hidden.includes(layer.id)).map(layer => <GeoJSON
      key={layer.id} data={layer.data} interactive={false}
      style={{ className: `aip-airspace aip-${layer.id}`, color: layer.id.includes("training") ? "#315caa" : "#946524", weight: 1, fillOpacity: 0.04 }}
    />)}
  </Pane>;
}

export function AipAirspaceControl({ data, failed, hidden, onChange, pcaVisible, onPcaChange }: {
  data: AipAirspace | null; failed: boolean; hidden: string[]; onChange: (id: string) => void;
  pcaVisible: boolean; onPcaChange: (visible: boolean) => void;
}) {
  return <details className="aip-layer-control">
    <summary>空域表示</summary>
    <div className="aip-layer-options">
      <label>
        <input type="checkbox" checked={pcaVisible} onChange={event => onPcaChange(event.target.checked)} />宮崎特別管制区（PCA）
      </label>
      {aipCategories.map(([id, label]) => <label key={id}>
        <input type="checkbox" checked={!hidden.includes(id)} onChange={() => onChange(id)} />{label}
      </label>)}
      <p>{failed ? "AIP空域を読み込めませんでした。再読み込みしてください。" : !data ? "AIP空域を読み込み中…" : `AIRAC有効日：${data.effectiveDate}`}</p>
      <p><a data-airspace-source href="https://top.swim.mlit.go.jp/swim/" target="_blank" rel="noopener noreferrer">航空情報センター AIP</a>のShapefileを加工。NOTAM・現在の使用状況は未反映。TCA未収録・ACA対応未確認。</p>
    </div>
  </details>;
}
