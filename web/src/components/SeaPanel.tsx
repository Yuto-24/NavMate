import type { SeaPlan } from "../sea";


export function SeaPanel({ plan, disabled, pending, onAcquire }: {
  plan: SeaPlan;
  disabled: boolean;
  pending: ReadonlySet<string>;
  onAcquire: () => Promise<void>;
}) {
  return <section className="sea-panel" aria-label="区間別SEA">
    {plan.intervals.some(interval => interval.reference && interval.automatic_ft !== null) &&
      <p className="sea-reference-note">* 地形データに一部欠損がある参考値です。実際のSEAは表示値より高い可能性があります。</p>}
    <button className="secondary-button" type="button" disabled={disabled} onClick={() => void onAcquire()}>地形を再取得</button>
    <a href="https://cyberjapandata.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener noreferrer">地形標高データ出典：国土地理院 DEM10B</a>
    {plan.intervals.filter(interval => interval.automatic_ft === null && !pending.has(interval.key))
      .map(interval => <p className="sea-warning" key={interval.key}>
        {interval.from_name} → {interval.to_name}：
        地形データの未取得・欠損・不正、または未対応の評価範囲によりSEAは未確定です。
      </p>)}
  </section>;
}
