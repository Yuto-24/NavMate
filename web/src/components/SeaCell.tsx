import { useEffect, useState } from "react";
import type { SeaInterval } from "../sea";

function ManualSea({ interval, disabled, onSave }: {
  interval: SeaInterval; disabled: boolean; onSave: (value: number | null) => Promise<void>;
}) {
  const [value, setValue] = useState(interval.manual_ft?.toString() ?? "");
  useEffect(() => setValue(interval.manual_ft?.toString() ?? ""), [interval.manual_ft, interval.key]);
  return <input className="nav-log-number-input" type="number" min={0} max={100000} step="any" disabled={disabled}
    aria-label={`${interval.from_name} → ${interval.to_name} 手動SEA（ft MSL）`}
    value={value} placeholder={interval.automatic_ft?.toString() ?? "未確定"}
    title="空欄にすると手動値を解除します。自動値がない場合は未確定になります。"
    onChange={event => setValue(event.target.value)}
    onBlur={event => {
      if (!event.currentTarget.reportValidity()) return;
      const next = value.trim() ? Number(value) : null;
      if (next !== interval.manual_ft) void onSave(next).catch(() => setValue(interval.manual_ft?.toString() ?? ""));
    }} />;
}

export function SeaCell({ interval, disabled, onSave }: {
  interval?: SeaInterval; disabled: boolean; onSave: (value: number | null) => Promise<void>;
}) {
  return <td className="nav-log-sea-cell nav-log-editable-cell"
    data-display-text={interval ? interval.value_ft?.toString() ?? "未確定" : ""}>
    {interval && <ManualSea interval={interval} disabled={disabled || !interval.geometry_valid} onSave={onSave} />}
  </td>;
}
