import { Panel, MetricTile, Button } from "@stewie/design-system";

export const Navigation = () => (
  <div style={{ width: 320 }}>
    <Panel title="Navigation" subsystem="LODE" actions={<Button size="sm">Replan</Button>}>
      <div style={{ color: "var(--muted)", fontSize: 12, lineHeight: 1.6 }}>
        Routed path, nav contract, Plan IR + posture plan. The command rail arms only in OPERATE.
      </div>
    </Panel>
  </div>
);

export const Physics = () => (
  <div style={{ width: 320 }}>
    <Panel title="Physics" subsystem="FORGE">
      <div style={{ display: "flex", gap: 12 }}>
        <MetricTile label="Sinkage" value="2.1" unit="cm" />
        <MetricTile label="Drum fill" value="74" unit="%" status="ok" />
      </div>
    </Panel>
  </div>
);
