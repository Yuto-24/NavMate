import { useEffect, useRef } from "react";
import type { SeaPlan } from "../sea";


export function SeaPanel({ projectId, plan, disabled, onAcquire }: {
  projectId: string;
  plan: SeaPlan;
  disabled: boolean;
  onAcquire: () => Promise<void>;
}) {
  const attempted = useRef("");
  useEffect(() => {
    const key = `${projectId}/${plan.geometry_key}`;
    if (disabled || attempted.current === key) return;
    attempted.current = key;
    if (plan.intervals.some(item => item.geometry_valid && item.terrain.required === 0)) void onAcquire();
  }, [disabled, onAcquire, plan, projectId]);
  return <section className="sea-panel" aria-label="区間別SEA">
    <button className="secondary-button" type="button" disabled={disabled} onClick={() => void onAcquire()}>地形を再取得</button>
    <a href="https://cyberjapandata.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener noreferrer">地形標高データ出典：国土地理院 DEM10B</a>
    {plan.intervals.filter(interval => interval.automatic_ft === null)
      .map(interval => <p className="sea-warning" key={interval.key}>
        {interval.from_name} → {interval.to_name}：
        地形データの未取得・欠損・不正、または未対応の評価範囲によりSEAは未確定です。
      </p>)}
  </section>;
}
