/* The STEWIE cockpit shell (front-end rewrite §11 IA). Phase 1 adds: the AG-01/02 auth gate, the FS-20
 * profile menu, and the FS-17 single-command-authority election wired into the AG-08 command rail. One
 * window; the map/world canvas is the persistent spine (Cesium/Three.js is Phase 4). */
import {
  ModeBar, SourceToggle, WorkAreaTabs, Panel, MetricTile, Button, Icon,
} from "@stewie/design-system";
import { useCockpit } from "./store";
import { AuthGate } from "./AuthGate";
import { ProfileMenu } from "./ProfileMenu";
import { useCommandAuthority } from "./useCommandAuthority";

const TXT = "var(--txt)";
const MUTED = "var(--muted)";

function CommandRail() {
  const { mode, roleRank } = useCockpit();
  const { isOwner, takeover } = useCommandAuthority();
  const live = mode === "OPERATE";
  const ag08 = live && roleRank >= 2; // AG-08: real commands need OPERATE + operator+
  const canCommand = ag08 && isOwner; // ...AND this window holds command authority (FS-17)

  return (
    <aside style={{ width: 280, borderLeft: "1px solid var(--line)", padding: "var(--sp-4)",
      display: "flex", flexDirection: "column", gap: "var(--sp-4)", background: "var(--panel)" }}>
      <div className="ds-display" style={{ fontSize: 10, color: MUTED }}>Command rail</div>

      {!isOwner && (
        <div data-testid="readonly-banner" style={{ border: "1px solid var(--accent)", borderRadius: "var(--r-sm)",
          padding: "var(--sp-2) var(--sp-3)", color: "var(--txt)", fontSize: "var(--fs-sm)", lineHeight: 1.5 }}>
          Read-only window — another window holds command authority (FS-17).
          <div style={{ marginTop: "var(--sp-2)" }}>
            <Button size="sm" onClick={takeover}>Take over command</Button>
          </div>
        </div>
      )}

      <Panel title="Selection">
        <div style={{ color: MUTED, fontSize: 12, lineHeight: 1.6 }}>
          No entity selected. Pick a site, rover, or order on the map.
        </div>
      </Panel>

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-2)" }}>
        <Button variant="primary" icon="play" data-cmd-authority disabled={live ? !canCommand : !isOwner}>
          {live ? "Send to rover" : "Simulate"}
        </Button>
        <Button variant="danger" icon="safe-stop" data-cmd-authority disabled={!(live && isOwner)}>Safe-stop</Button>
        <div style={{ color: "var(--dim)", fontSize: 10, lineHeight: 1.5 }}>
          {canCommand
            ? "OPERATE · live · operator+ · this window — real rover commands armed under SF-01."
            : "Real commands need OPERATE + live + operator+ (AG-08) in the command-authority window. Otherwise simulation only."}
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

function Cockpit() {
  const { mode, sources, workArea, roleRank, setMode, toggleSource, setWorkArea } = useCockpit();
  return (
    <div className="ds-root" style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      <header style={{ display: "flex", gap: "var(--sp-5)", alignItems: "center", flexWrap: "wrap",
        padding: "var(--sp-3) var(--sp-4)", borderBottom: "1px solid var(--line)", background: "var(--head)" }}>
        <span className="ds-display" style={{ color: "var(--accent)", fontSize: 16 }}>STEWIE</span>
        <ModeBar mode={mode} roleRank={roleRank} onChange={setMode} />
        <SourceToggle mode={mode} active={sources} onToggle={toggleSource} />
        <span style={{ marginLeft: "auto" }}><ProfileMenu /></span>
      </header>

      <div style={{ padding: "var(--sp-2) var(--sp-4) 0", background: "var(--head)" }}>
        <WorkAreaTabs active={workArea} onSelect={setWorkArea}
          readiness={{ plan: "•", navigation: "•", perception: "!", metrics: "•" }} />
      </div>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <MapCanvas />
        <CommandRail />
      </div>
    </div>
  );
}

export default function App() {
  return (
    <AuthGate>
      <Cockpit />
    </AuthGate>
  );
}
