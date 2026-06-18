/* The STEWIE cockpit shell (front-end rewrite §11 IA). Phase 0: shell + design system. Phase 1: auth gate,
 * FS-20 profile menu, FS-17 command authority. Phase 2: theme/font prefs applied to the root, the FS-20
 * chrome overlay, and the data-light work areas (Metrics -> the FS-19 events timeline; Reports -> stub).
 * One window; the map/world canvas is the spatial spine (Cesium/Three.js is Phase 4). */
import { useEffect, useState } from "react";
import {
  ModeBar, SourceToggle, WorkAreaTabs, Panel, MetricTile, Button,
} from "@stewie/design-system";
import { useCockpit } from "./store";
import { fetchHeightfield, submitPlan, type Heightfield, type MissionOrder, type PlanResult } from "./api";
import { AuthGate } from "./AuthGate";
import { ProfileMenu } from "./ProfileMenu";
import { useCommandAuthority } from "./useCommandAuthority";
import { ChromePanel } from "./panels/ChromePanels";
import { EventsTable } from "./panels/EventsTable";
import { NavigationView } from "./panels/NavigationView";
import { PerceptionView } from "./panels/PerceptionView";
import { MapCanvas3D } from "./panels/MapCanvas3D";
import { CesiumGlobe } from "./panels/CesiumGlobe";

const TXT = "var(--txt)";
const MUTED = "var(--muted)";

function PlanResultPanel({ r }: { r: PlanResult }) {
  return (
    <Panel title="Plan result">
      {r.error ? (
        <div style={{ color: "var(--accent)", fontSize: "var(--fs-sm)" }} data-testid="plan-error">Plan failed: {r.error}</div>
      ) : (
        <div data-testid="plan-result">
          <div style={{ marginBottom: "var(--sp-2)", fontSize: "var(--fs-sm)",
            color: r.feasible ? "var(--ok)" : "var(--accent)" }}>
            {r.feasible ? "● feasible" : "○ infeasible"} · {r.nActions} IR actions{r.planId ? ` · ${r.planId}` : ""}
          </div>
          <div style={{ display: "flex", gap: "var(--sp-2)", flexWrap: "wrap" }}>
            {r.makespanS != null && <MetricTile label="Makespan" value={(r.makespanS / 60).toFixed(1)} unit="min" />}
            {r.energyMJ != null && <MetricTile label="Energy" value={r.energyMJ.toFixed(2)} unit="MJ" status="ok" />}
            {r.massKg != null && <MetricTile label="Mass moved" value={r.massKg.toFixed(0)} unit="kg" />}
          </div>
        </div>
      )}
    </Panel>
  );
}

function CommandRail() {
  const { mode, roleRank, orders, clearOrders, placeMode, setPlaceMode } = useCockpit();
  const { isOwner, takeover } = useCommandAuthority();
  const [result, setResult] = useState<PlanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const live = mode === "OPERATE";
  const ag08 = live && roleRank >= 2;
  const canCommand = ag08 && isOwner;

  const runPlan = async () => {
    setBusy(true);
    setResult(null);
    const mo: MissionOrder[] = orders.map((o) => ({
      action: o.kind === "cut" ? "borrow" : "pad", kind: o.kind,
      x: o.x, y: o.y, footprint_m2: 16, depth_m: 0.3, // operator defaults (shown in the queue), not hidden
    }));
    setResult(await submitPlan(mo));
    setBusy(false);
  };

  return (
    <aside style={{ width: 280, borderLeft: "1px solid var(--line)", padding: "var(--sp-4)",
      display: "flex", flexDirection: "column", gap: "var(--sp-4)", background: "var(--panel)", overflow: "auto" }}>
      <div className="ds-display" style={{ fontSize: 10, color: MUTED }}>Command rail</div>
      {!isOwner && (
        <div data-testid="readonly-banner" style={{ border: "1px solid var(--accent)", borderRadius: "var(--r-sm)",
          padding: "var(--sp-2) var(--sp-3)", color: TXT, fontSize: "var(--fs-sm)", lineHeight: 1.5 }}>
          Read-only window — another window holds command authority (FS-17).
          <div style={{ marginTop: "var(--sp-2)" }}><Button size="sm" onClick={takeover}>Take over command</Button></div>
        </div>
      )}
      <Panel title="Build queue" actions={orders.length ? <Button size="sm" onClick={clearOrders}>Clear</Button> : undefined}>
        <div style={{ display: "flex", gap: "var(--sp-2)", marginBottom: "var(--sp-3)" }}>
          <Button size="sm" variant={placeMode === "cut" ? "primary" : "ghost"} onClick={() => setPlaceMode("cut")}>Cut</Button>
          <Button size="sm" variant={placeMode === "fill" ? "primary" : "ghost"} onClick={() => setPlaceMode("fill")}>Fill</Button>
        </div>
        {orders.length === 0 ? (
          <div style={{ color: MUTED, fontSize: 12 }}>Pick Cut/Fill, then click the terrain to place orders (16 m² × 0.3 m default).</div>
        ) : (
          <ol data-testid="order-queue" style={{ margin: 0, paddingLeft: "var(--sp-4)", color: TXT, fontSize: "var(--fs-sm)", lineHeight: 1.7 }}>
            {orders.map((o, i) => (
              <li key={i}><span style={{ color: o.kind === "cut" ? "var(--accent)" : "var(--ok)" }}>{o.kind}</span> @ ({o.x.toFixed(0)}, {o.y.toFixed(0)}) m</li>
            ))}
          </ol>
        )}
      </Panel>
      {result && <PlanResultPanel r={result} />}
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-2)" }}>
        <Button variant="primary" icon="play" data-cmd-authority
          onClick={live ? undefined : runPlan}
          disabled={live ? !canCommand : (!isOwner || orders.length === 0 || busy)}>
          {busy ? "Solving…" : live ? "Send to rover" : "Simulate plan"}
        </Button>
        <Button variant="danger" icon="safe-stop" data-cmd-authority disabled={!(live && isOwner)}>Safe-stop</Button>
        <div style={{ color: "var(--dim)", fontSize: 10, lineHeight: 1.5 }}>
          {canCommand
            ? "OPERATE · live · operator+ · this window — real rover commands armed under SF-01."
            : "Simulate runs /plan (cut-fill balance + route). Real commands need OPERATE + live + operator+ (AG-08) in the command-authority window."}
        </div>
      </div>
    </aside>
  );
}

function MapCanvas() {
  const { workArea, mode, sources, theme, orders, addOrder } = useCockpit();
  const accent = theme === "light" ? "#1d6ae5" : "#e8273f";
  const [hf, setHf] = useState<Heightfield | null>(null);
  const [view, setView] = useState<"local" | "globe">("local");
  const [picked, setPicked] = useState<{ lat: number; lon: number } | null>(null);
  useEffect(() => {
    let live = true;
    fetchHeightfield("haworth").then((h) => live && setHf(h)).catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  return (
    <div style={{ position: "relative", flex: 1, minWidth: 0, overflow: "hidden" }}>
      {view === "globe"
        ? <CesiumGlobe onPick={(lat, lon) => setPicked({ lat, lon })} />
        : <MapCanvas3D accent={accent} heightfield={hf} orders={orders} onPlace={addOrder} />}
      {/* Local (DEM terrain) vs Globe (planetary site picker) — the §11 planetary/local spine */}
      <div style={{ position: "absolute", top: "var(--sp-4)", right: "var(--sp-4)", display: "flex", gap: 2 }}>
        <Button size="sm" variant={view === "local" ? "primary" : "ghost"} onClick={() => setView("local")}>Local</Button>
        <Button size="sm" variant={view === "globe" ? "primary" : "ghost"} onClick={() => setView("globe")}>Globe</Button>
      </div>
      <div style={{ position: "absolute", left: "var(--sp-4)", bottom: "var(--sp-4)", pointerEvents: "none",
        background: "rgba(8,8,12,.66)", border: "1px solid var(--line)", borderRadius: "var(--r-md)",
        padding: "var(--sp-2) var(--sp-3)", color: MUTED, fontSize: 11, lineHeight: 1.5 }}>
        <span className="ds-display" style={{ fontSize: 11, color: TXT }}>Map / World</span>
        <div>work area <b style={{ color: TXT }}>{workArea}</b> · mode <b style={{ color: TXT }}>{mode}</b></div>
        <div>layers: {sources.join(", ") || "none"}</div>
        {view === "globe" ? (
          <div style={{ color: "var(--dim)" }} data-testid="globe-info">
            planetary globe (Moon · NASA Trek){picked ? ` · picked ${picked.lat.toFixed(2)}°, ${picked.lon.toFixed(2)}°` : " · click to pick a site"} · pixels = GPU
          </div>
        ) : (
          <div style={{ color: "var(--dim)" }}>
            {hf ? `terrain: REAL LOLA ${hf.n}×${hf.n} @ ${hf.windowM} m (×${2.5} relief)` : "terrain: grid scaffold (no /dem/heightfield)"}
            {" · "}orders: {orders.length} (click terrain)
          </div>
        )}
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
    workArea === "perception" ? <PerceptionView /> :
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
