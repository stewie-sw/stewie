/* The STEWIE cockpit shell (front-end rewrite §11 IA). Phase 0: shell + design system. Phase 1: auth gate,
 * FS-20 profile menu, FS-17 command authority. Phase 2: theme/font prefs applied to the root, the FS-20
 * chrome overlay, and the data-light work areas (Metrics -> the FS-19 events timeline; Reports -> stub).
 * One window; the map/world canvas is the spatial spine (Cesium/Three.js is Phase 4). */
import {
  ModeBar, SourceToggle, WorkAreaTabs, Panel, MetricTile, Button,
} from "@stewie/design-system";
import { useCockpit } from "./store";
import { AuthGate } from "./AuthGate";
import { ProfileMenu } from "./ProfileMenu";
import { useCommandAuthority } from "./useCommandAuthority";
import { ChromePanel } from "./panels/ChromePanels";
import { EventsTable } from "./panels/EventsTable";
import { NavigationView } from "./panels/NavigationView";
import { MapCanvas3D } from "./panels/MapCanvas3D";

const TXT = "var(--txt)";
const MUTED = "var(--muted)";

function CommandRail() {
  const { mode, roleRank } = useCockpit();
  const { isOwner, takeover } = useCommandAuthority();
  const live = mode === "OPERATE";
  const ag08 = live && roleRank >= 2;
  const canCommand = ag08 && isOwner;
  return (
    <aside style={{ width: 280, borderLeft: "1px solid var(--line)", padding: "var(--sp-4)",
      display: "flex", flexDirection: "column", gap: "var(--sp-4)", background: "var(--panel)" }}>
      <div className="ds-display" style={{ fontSize: 10, color: MUTED }}>Command rail</div>
      {!isOwner && (
        <div data-testid="readonly-banner" style={{ border: "1px solid var(--accent)", borderRadius: "var(--r-sm)",
          padding: "var(--sp-2) var(--sp-3)", color: TXT, fontSize: "var(--fs-sm)", lineHeight: 1.5 }}>
          Read-only window — another window holds command authority (FS-17).
          <div style={{ marginTop: "var(--sp-2)" }}><Button size="sm" onClick={takeover}>Take over command</Button></div>
        </div>
      )}
      <Panel title="Selection">
        <div style={{ color: MUTED, fontSize: 12, lineHeight: 1.6 }}>No entity selected. Pick a site, rover, or order on the map.</div>
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
  const { workArea, mode, sources, theme } = useCockpit();
  const accent = theme === "light" ? "#1d6ae5" : "#e8273f";
  return (
    <div style={{ position: "relative", flex: 1, minWidth: 0, overflow: "hidden" }}>
      <MapCanvas3D accent={accent} />
      {/* info card over the live 3D world (pointer-events off so it never eats canvas interaction) */}
      <div style={{ position: "absolute", left: "var(--sp-4)", bottom: "var(--sp-4)", pointerEvents: "none",
        background: "rgba(8,8,12,.66)", border: "1px solid var(--line)", borderRadius: "var(--r-md)",
        padding: "var(--sp-2) var(--sp-3)", color: MUTED, fontSize: 11, lineHeight: 1.5 }}>
        <span className="ds-display" style={{ fontSize: 11, color: TXT }}>Map / World</span>
        <div>work area <b style={{ color: TXT }}>{workArea}</b> · mode <b style={{ color: TXT }}>{mode}</b></div>
        <div>layers: {sources.join(", ") || "none"}</div>
        <div style={{ color: "var(--dim)" }}>grid = scaffold · real DEM mesh binds to /dem/heightfield (backend) · Cesium globe = GPU</div>
      </div>
    </div>
  );
}

function DataArea({ children }: { children: React.ReactNode }) {
  return <div style={{ flex: 1, minWidth: 0, overflow: "auto", padding: "var(--sp-5)", background: "var(--bg)" }}>{children}</div>;
}

function MetricsView() {
  return (
    <DataArea>
      <div style={{ display: "flex", gap: "var(--sp-3)", marginBottom: "var(--sp-4)", flexWrap: "wrap" }}>
        <MetricTile label="Makespan" value="42.6" unit="min" />
        <MetricTile label="Energy" value="2.04" unit="MJ" status="ok" />
        <MetricTile label="Peak slip" value="0.31" status="warn" />
        <MetricTile label="Battery reserve" value="8" unit="%" status="danger" />
      </div>
      <Panel title="Event timeline (FS-19)"><EventsTable n={50} /></Panel>
    </DataArea>
  );
}

function ReportsView() {
  return (
    <DataArea>
      <Panel title="Reports">
        <div style={{ color: MUTED, fontSize: 12, lineHeight: 1.6 }}>
          Mission-control reports are produced by the Plan flow (the PDF served from a plan run). The report
          list + viewer bind here in a later phase.
        </div>
      </Panel>
    </DataArea>
  );
}

function Cockpit() {
  const { mode, sources, workArea, roleRank, theme, fontPx, setMode, toggleSource, setWorkArea } = useCockpit();
  const rootClass = theme === "light" ? "ds-root light" : "ds-root";
  const center =
    workArea === "navigation" ? <NavigationView /> :
    workArea === "metrics" ? <MetricsView /> :
    workArea === "reports" ? <ReportsView /> : <MapCanvas />;
  return (
    <div className={rootClass} style={{ height: "100vh", display: "flex", flexDirection: "column",
      ["--fontpx" as string]: `${fontPx}px` } as React.CSSProperties}>
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
        {center}
        <CommandRail />
      </div>
      <ChromePanel />
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
