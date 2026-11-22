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
    {plan.intervals.filter(interval => interval.warning || (interval.status === "manual" && interval.automatic_ft === null))
      .map(interval => <p className="sea-warning" key={interval.key}>
        {interval.from_name} → {interval.to_name}：
        {interval.warning === "below-automatic" ? `手動SEAが自動値（${interval.automatic_ft} ft）を下回っています。`
          : interval.warning === "unconfirmed" ? "地形データの未取得・欠損・不正、または未対応の評価範囲によりSEAは未確定です。"
          : "地形データの不足などによりSEAの自動値を算出できないため、手入力値の比較および安全性の確認はできません。航空図などの公式資料で別途ご確認ください。"}
      </p>)}
  </section>;
}
