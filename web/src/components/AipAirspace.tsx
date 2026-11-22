import { useLayoutEffect, useRef } from "react";
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

export function AipAirspaceControl({ data, failed, hidden, onChange }: {
  data: AipAirspace | null; failed: boolean; hidden: string[]; onChange: (id: string) => void;
}) {
  const controlRef = useRef<HTMLDetailsElement>(null);
  useLayoutEffect(() => {
    const control = controlRef.current!;
    const frame = control.closest<HTMLElement>(".map-frame")!;
    const toolbar = control.parentElement!;
    const options = control.querySelector<HTMLElement>(".aip-layer-options")!;
    const updateHeight = () => {
      if (!control.open) return;
      const available = frame.getBoundingClientRect().bottom - options.getBoundingClientRect().top - 8;
      options.style.setProperty("--aip-available-height", `${Math.max(0, available)}px`);
    };
    const observer = new ResizeObserver(updateHeight);
    observer.observe(frame);
    observer.observe(toolbar);
    control.addEventListener("toggle", updateHeight);
    return () => {
      observer.disconnect();
      control.removeEventListener("toggle", updateHeight);
    };
  }, []);
  return <details ref={controlRef} className="aip-layer-control">
    <summary>空域レイヤー</summary>
    <div className="aip-layer-options">
      {aipCategories.map(([id, label]) => <label key={id}>
        <input type="checkbox" checked={!hidden.includes(id)} onChange={() => onChange(id)} />{label}
      </label>)}
      <p>{failed ? "AIP空域を読み込めませんでした。再読み込みしてください。" : !data ? "AIP空域を読み込み中…" : `AIRAC有効日：${data.effectiveDate}`}</p>
      <p><a data-airspace-source href="https://top.swim.mlit.go.jp/swim/" target="_blank" rel="noopener noreferrer">航空情報センター AIP</a>のShapefileを加工。NOTAM・現在の使用状況は未反映。TCA未収録・ACA対応未確認。</p>
    </div>
  </details>;
}
