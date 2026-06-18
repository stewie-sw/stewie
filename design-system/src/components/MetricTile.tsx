/* MetricTile — a labelled value with an optional unit and status (ok | warn | danger). Used across the
 * Metrics/Execution area and the command rail (energy, makespan, slip, battery, drum fill). */

export type MetricStatus = "default" | "ok" | "warn" | "danger";

export interface MetricTileProps {
  label: string;
  value: string | number;
  unit?: string;
  status?: MetricStatus;
}

export function MetricTile({ label, value, unit, status = "default" }: MetricTileProps): JSX.Element {
  const cls = ["ds-metric", status !== "default" && `ds-metric--${status}`].filter(Boolean).join(" ");
  return (
    <div className={cls}>
      <div className="ds-metric__label">{label}</div>
      <div className="ds-metric__value">
        {value}
        {unit && <span className="ds-metric__unit">{unit}</span>}
      </div>
    </div>
  );
}
