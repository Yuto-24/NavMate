import { useEffect, useRef, useState } from "react";
import type { SeaPlan, SeaUpdate } from "../sea";
import { parseTerrainKml } from "../terrainKml";


export function SeaPanel({ projectId, plan, disabled, onUpdate, onAcquire }: {
  projectId: string;
  plan: SeaPlan;
  disabled: boolean;
  onUpdate: (patch: SeaUpdate) => Promise<void>;
  onAcquire: () => Promise<void>;
}) {
  const attempted = useRef("");
  const [source, setSource] = useState("");
  const [evidence, setEvidence] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [kmlStatus, setKmlStatus] = useState("");
  const [kmlBusy, setKmlBusy] = useState(false);
  useEffect(() => {
    const key = `${projectId}/${plan.geometry_key}`;
    if (disabled || attempted.current === key) return;
    attempted.current = key;
    if (plan.intervals.some(item => item.geometry_valid && item.terrain.required === 0)) void onAcquire();
  }, [disabled, onAcquire, plan, projectId]);
  const update = (patch: Omit<SeaUpdate, "project_id" | "geometry_key">) => onUpdate({
    project_id: projectId, geometry_key: plan.geometry_key, ...patch,
  });
  return <section className="sea-panel" aria-label="区間別SEA">
    <button className="secondary-button" type="button" disabled={disabled} onClick={() => void onAcquire()}>地形を再取得</button>
    <a href="https://cyberjapandata.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener noreferrer">国土地理院DEM10B</a>
    {plan.intervals.filter(interval => interval.warning || (interval.status === "manual" && interval.automatic_ft === null))
      .map(interval => <p className="sea-warning" key={interval.key}>
        {interval.from_name} → {interval.to_name}：
        {interval.warning === "below-automatic" ? `手動SEAが自動値（${interval.automatic_ft} ft）を下回っています。`
          : interval.warning === "unconfirmed" ? "地形データの未取得・欠損・不正、または未対応の評価範囲によりSEAは未確定です。"
          : "自動値との照合は未実施です。"}
      </p>)}
    <details>
      <summary>地形点KML・DEMの取得状況と出典</summary>
      <p>人工障害物は含みません。DEMは平滑化された標高であり、実地形の最高点を保証しません。SEAは安全性を保証する値ではありません。実運航前に原資料と照合してください。</p>
      {plan.kml_source && <p>採用中のKML：{plan.kml_source.source} ／ {plan.kml_source.verticalReference}
        ／ {plan.kml_source.importedAt}<br />{plan.kml_source.demCompatibilityEvidence}<br /><code>{plan.kml_source.sha256}</code></p>}
      <p>経路用KMLとは別に取り込みます。地表標高・T.P.（東京湾平均海面）基準・使用DEMとの整合を資料で確認してください。</p>
      <label>資料の作成元・識別子<input value={source} onChange={event => setSource(event.target.value)} disabled={disabled} /></label>
      <label>DEMとの標高基準・測量時点の照合根拠<input value={evidence} onChange={event => setEvidence(event.target.value)} disabled={disabled} /></label>
      <label className="checkbox-row"><input type="checkbox" checked={confirmed} disabled={disabled} onChange={event => setConfirmed(event.target.checked)} />KML内の全点の標高値は地表の標高で、単位はm、基準はT.P.（東京湾平均海面）であると確認しました。</label>
      <label>地形点KML<input type="file" accept=".kml" disabled={disabled || kmlBusy || !confirmed || !source.trim() || !evidence.trim()}
        onChange={async event => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file || kmlBusy) return;
          setKmlBusy(true);
          try {
            const kml = await parseTerrainKml(file.size <= 2 * 1024 * 1024 ? await file.text() : "", {
              source, meaning: "terrain", verticalReference: "TP", demCompatibilityEvidence: evidence,
            });
            if (!["available", "partial", "empty"].includes(kml.status)) {
              setKmlStatus("地形点KMLを取り込めませんでした。形式・出典・標高基準を確認してください。採用中のKMLは変更していません。"); return;
            }
            await update({ kml });
            setKmlStatus(`地形点 ${kml.points.length} 件を採用しました。不採用 ${kml.rejected.length} 件。`);
          } catch { setKmlStatus("地形点KMLの保存を確認できませんでした。採用中のKMLを確認してから再試行してください。"); }
          finally { setKmlBusy(false); }
        }} /></label>
      <button className="secondary-button" type="button" disabled={disabled || kmlBusy} onClick={async () => {
        if (kmlBusy) return;
        setKmlBusy(true);
        try { await update({ kml: await parseTerrainKml(null) }); setKmlStatus("地形点KMLを解除しました。"); }
        catch { setKmlStatus("地形点KMLの保存を確認できませんでした。採用中のKMLを確認してから再試行してください。"); }
        finally { setKmlBusy(false); }
      }}>地形点KMLを解除</button>
      {kmlStatus && <p role="status">{kmlStatus}</p>}
      {plan.intervals.map((item, index) => <details key={`${item.key}/${index}`}>
        <summary>{item.from_name} → {item.to_name}：DEM被覆・出典</summary>
        <p>検査済み領域の画素数（未検査領域は集計に含みません）：必要 {item.terrain.required} ／有効 {item.terrain.valid} ／欠損 {item.terrain.missing} ／未取得 {item.terrain.not_acquired} ／不正 {item.terrain.invalid}</p>
        <ul>{item.terrain.provenance.map(p => <li key={p.url}>
          <a href={p.url} target="_blank" rel="noopener noreferrer">{p.source}</a> {p.acquiredAt} {p.verticalReference}
          <code>{p.sha256}</code>
        </li>)}</ul>
      </details>)}
    </details>
  </section>;
}
