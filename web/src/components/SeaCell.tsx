import { LoaderCircle } from "lucide-react";
import type { SeaInterval } from "../sea";

export function SeaCell({ interval, loading = false }: { interval?: SeaInterval; loading?: boolean }) {
  const value = interval ? (interval.automatic_ft == null ? undefined : `${interval.automatic_ft}${interval.reference ? "*" : ""}`) ?? "未確定" : "";
  const pending = Boolean(loading && interval?.geometry_valid);
  return <td className="nav-log-sea-cell" data-display-text={value}>
    {pending
      ? <span className="sea-loading">
          <LoaderCircle className="sea-loading-icon" aria-hidden="true" size={14} />
          {interval?.automatic_ft == null ? "取得中" : value}
        </span>
      : value}
  </td>;
}
