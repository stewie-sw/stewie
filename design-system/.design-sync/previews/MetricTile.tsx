import { MetricTile } from "@stewie/design-system";

export const Makespan = () => <MetricTile label="Makespan" value="42.6" unit="min" />;
export const EnergyOk = () => <MetricTile label="Energy" value="2.04" unit="MJ" status="ok" />;
export const SlipWarn = () => <MetricTile label="Peak slip" value="0.31" status="warn" />;
export const BatteryDanger = () => <MetricTile label="Battery reserve" value="8" unit="%" status="danger" />;
