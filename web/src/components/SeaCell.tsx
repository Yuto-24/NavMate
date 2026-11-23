import type { SeaInterval } from "../sea";

export function SeaCell({ interval }: { interval?: SeaInterval }) {
  const value = interval ? (interval.automatic_ft == null ? undefined : `${interval.automatic_ft}${interval.reference ? "*" : ""}`) ?? "未確定" : "";
  return <td className="nav-log-sea-cell" data-display-text={value}>{value}</td>;
}
