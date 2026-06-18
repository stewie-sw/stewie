/* LOCAL-ONLY review gallery: renders every STEWIE design-system component in a cockpit-shell layout so
 * the brand, the §11 IA, and the sim-vs-truth behavior are all visible in one screenshot. Not shipped. */
import * as React from "react";
import { createRoot } from "react-dom/client";
import {
  Button, ModeBar, SourceToggle, WorkAreaTabs, Panel, MetricTile, SubsystemChip, Icon,
  ICON_NAMES, truthAvailable,
  type StewieMode, type SourceLayer, type WorkArea,
} from "../src/index";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: "var(--sp-6)" }}>
      <div className="ds-display" style={{ color: "var(--dim)", fontSize: 10, marginBottom: "var(--sp-3)" }}>{title}</div>
      <div style={{ display: "flex", gap: "var(--sp-4)", flexWrap: "wrap", alignItems: "center" }}>{children}</div>
    </div>
  );
}

function Gallery() {
  const [mode, setMode] = React.useState<StewieMode>("SIM-OPERATE");
  const [sources, setSources] = React.useState<SourceLayer[]>(["forecast", "truth", "belief"]);
  const [area, setArea] = React.useState<WorkArea>("plan");
  // the sim-vs-truth invariant, live: leaving a truth-bearing mode drops the truth layer
  React.useEffect(() => {
    if (!truthAvailable(mode)) setSources((s) => s.filter((x) => x !== "truth"));
  }, [mode]);

  return (
    <div className="ds-root" style={{ minHeight: "100vh", padding: "var(--sp-5)" }}>
      {/* top bar: mode (truth boundary) + source (provenance) — the two sim-vs-truth axes */}
      <div style={{ display: "flex", gap: "var(--sp-5)", alignItems: "center", flexWrap: "wrap",
        paddingBottom: "var(--sp-4)", borderBottom: "1px solid var(--line)", marginBottom: "var(--sp-5)" }}>
        <span className="ds-display" style={{ color: "var(--accent)", fontSize: 16 }}>STEWIE</span>
        <ModeBar mode={mode} roleRank={3} onChange={setMode} />
        <SourceToggle mode={mode} active={sources}
          onToggle={(l, on) => setSources((s) => (on ? [...s, l] : s.filter((x) => x !== l)))} />
        <span style={{ marginLeft: "auto", color: "var(--muted)", fontSize: 11 }}>sandbox · director</span>
      </div>

      <WorkAreaTabs active={area} onSelect={setArea}
        readiness={{ plan: "•", navigation: "•", perception: "!", metrics: "•" }} />

      <div style={{ marginTop: "var(--sp-5)" }}>
        <Section title="Buttons">
          <Button variant="primary" icon="play">Execute plan</Button>
          <Button variant="ghost" icon="download">Export Plan IR</Button>
          <Button variant="danger" icon="safe-stop">Safe-stop</Button>
          <Button size="sm" icon="target">Pick site</Button>
          <Button disabled>Disabled</Button>
        </Section>

        <Section title="Metric tiles (forecast vs truth, energy, slip, battery)">
          <MetricTile label="Makespan" value="42.6" unit="min" />
          <MetricTile label="Energy" value="2.04" unit="MJ" status="ok" />
          <MetricTile label="Peak slip" value="0.31" status="warn" />
          <MetricTile label="Battery reserve" value="8" unit="%" status="danger" />
        </Section>

        <Section title="Panels + subsystem chips">
          <div style={{ width: 300 }}>
            <Panel title="Navigation" subsystem="LODE" actions={<Button size="sm">Replan</Button>}>
              <div style={{ color: "var(--muted)", fontSize: 12, lineHeight: 1.6 }}>
                Routed path, nav contract, Plan IR + posture plan. The command rail arms only in OPERATE.
              </div>
            </Panel>
          </div>
          <div style={{ width: 300 }}>
            <Panel title="Physics" subsystem="FORGE">
              <div style={{ display: "flex", gap: "var(--sp-3)" }}>
                <MetricTile label="Sinkage" value="2.1" unit="cm" />
                <MetricTile label="Drum fill" value="74" unit="%" status="ok" />
              </div>
            </Panel>
          </div>
        </Section>

        <Section title="Subsystem chips">
          <SubsystemChip name="DART" /><SubsystemChip name="LODE" />
          <SubsystemChip name="LEAP" /><SubsystemChip name="FORGE" />
        </Section>

        <Section title="Icon set (replaces the emoji glyphs)">
          {ICON_NAMES.map((n) => (
            <span key={n} title={n} style={{ display: "inline-flex", flexDirection: "column", alignItems: "center",
              gap: 4, color: "var(--txt)", width: 56 }}>
              <Icon name={n} size={22} />
              <span style={{ fontSize: 9, color: "var(--dim)" }}>{n}</span>
            </span>
          ))}
        </Section>

        <div style={{ color: "var(--dim)", fontSize: 11, borderTop: "1px solid var(--line)", paddingTop: "var(--sp-3)" }}>
          Mode: <b style={{ color: "var(--txt)" }}>{mode}</b> · truth layer{" "}
          {truthAvailable(mode) ? "available" : "DISABLED (no truth channel on real hardware)"} · sources:{" "}
          {sources.join(", ") || "none"}
        </div>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<Gallery />);
