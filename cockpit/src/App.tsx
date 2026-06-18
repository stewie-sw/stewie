/* The STEWIE cockpit shell (front-end rewrite §11 IA): one window, the 5-mode bar + 4-source toggle on a
 * top strip, the 6 work-area tabs, a PERSISTENT map/world canvas at center, and a right command rail whose
 * real-rover controls arm only in OPERATE (AG-08 + SF-01). Phase 0 proves the stack + the design system;
 * the map is a placeholder (Cesium/Three.js is Phase 4) and the panes are stubs to be filled per phase. */
import {
  ModeBar, SourceToggle, WorkAreaTabs, Panel, MetricTile, Button, Icon,
} from "@stewie/design-system";
import { useCockpit } from "./store";

const TXT = "var(--txt)";
const MUTED = "var(--muted)";

function CommandRail() {
  const { mode, roleRank } = useCockpit();
  const live = mode === "OPERATE";
  const canCommand = live && roleRank >= 2;
  return (
    <aside style={{ width: 280, borderLeft: "1px solid var(--line)", padding: "var(--sp-4)",
      display: "flex", flexDirection: "column", gap: "var(--sp-4)", background: "var(--panel)" }}>
      <div className="ds-display" style={{ fontSize: 10, color: MUTED }}>Command rail</div>
      <Panel title="Selection">
        <div style={{ color: MUTED, fontSize: 12, lineHeight: 1.6 }}>
          No entity selected. Pick a site, rover, or order on the map.
        </div>
      </Panel>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-2)" }}>
        <Button variant="primary" icon="play" disabled={!canCommand}>
          {live ? "Send to rover" : "Simulate"}
        </Button>
        <Button variant="danger" icon="safe-stop" disabled={!live}>Safe-stop</Button>
        <div style={{ color: "var(--dim)", fontSize: 10, lineHeight: 1.5 }}>
          {canCommand
            ? "OPERATE · live · operator+ — real rover commands armed under SF-01."
            : "Real commands need OPERATE + live + operator+ (AG-08). Otherwise simulation only."}
        </div>
      </div>
    </aside>
  );
}

function MapCanvas() {
  const { workArea, mode, sources } = useCockpit();
  return (
    <div style={{ position: "relative", flex: 1, minWidth: 0,
      background: "radial-gradient(circle at 50% 40%, #14141a, #05060c 70%)",
      display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden" }}>
      <div style={{ textAlign: "center", color: MUTED }}>
        <Icon name="layers" size={40} />
        <div className="ds-display" style={{ fontSize: 12, marginTop: "var(--sp-3)", color: TXT }}>
          Map / World canvas
        </div>
        <div style={{ fontSize: 11, marginTop: "var(--sp-1)" }}>
          work area: <b style={{ color: TXT }}>{workArea}</b> · mode: <b style={{ color: TXT }}>{mode}</b>
        </div>
        <div style={{ fontSize: 11, marginTop: "var(--sp-1)" }}>
          source layers stack here: {sources.join(", ") || "none"}
        </div>
        <div style={{ fontSize: 10, marginTop: "var(--sp-3)", color: "var(--dim)" }}>
          (Cesium globe + local DEM — Phase 4)
        </div>
      </div>
      {/* the Metrics work area overlays a small forecast-vs-truth readout on the canvas */}
      {workArea === "metrics" && (
        <div style={{ position: "absolute", top: "var(--sp-4)", left: "var(--sp-4)", display: "flex", gap: "var(--sp-3)" }}>
          <MetricTile label="Makespan" value="42.6" unit="min" />
          <MetricTile label="Energy" value="2.04" unit="MJ" status="ok" />
          <MetricTile label="Peak slip" value="0.31" status="warn" />
        </div>
      )}
    </div>
  );
}

export default function App() {
  const { mode, sources, workArea, roleRank, setMode, toggleSource, setWorkArea } = useCockpit();
  return (
    <div className="ds-root" style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      {/* top strip: the two sim-vs-truth axes, always visible */}
      <header style={{ display: "flex", gap: "var(--sp-5)", alignItems: "center", flexWrap: "wrap",
        padding: "var(--sp-3) var(--sp-4)", borderBottom: "1px solid var(--line)", background: "var(--head)" }}>
        <span className="ds-display" style={{ color: "var(--accent)", fontSize: 16 }}>STEWIE</span>
        <ModeBar mode={mode} roleRank={roleRank} onChange={setMode} />
        <SourceToggle mode={mode} active={sources} onToggle={toggleSource} />
        <span style={{ marginLeft: "auto", color: MUTED, fontSize: 11 }}>sandbox · director</span>
      </header>

      <div style={{ padding: "var(--sp-2) var(--sp-4) 0", background: "var(--head)" }}>
        <WorkAreaTabs active={workArea} onSelect={setWorkArea}
          readiness={{ plan: "•", navigation: "•", perception: "!", metrics: "•" }} />
      </div>

      {/* main: persistent map canvas + the command rail */}
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <MapCanvas />
        <CommandRail />
      </div>
    </div>
  );
}
