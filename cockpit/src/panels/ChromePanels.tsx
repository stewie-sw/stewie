/* FS-20 chrome destinations, opened from the profile menu as a modal overlay (out of the work-area bar):
 *   Admin (director)  — the operator roster (/admin/operators) + the FS-19 audit ledger.
 *   System (operator+) — /healthz + /metrics readout.
 *   Settings (any)     — theme (UI-2) + base font size (UI-1), persisted via the store.
 * Role is gated here too (defense in depth), independent of the menu's gating. */
import { useEffect, useState } from "react";
import { Button, MetricTile, Panel } from "@stewie/design-system";
import { useCockpit, type ChromeView } from "../store";
import { fetchOperators, fetchHealth, fetchMetrics, type OperatorRow, type Health } from "../api";
import { EventsTable } from "./EventsTable";

const CHROME_TITLE: Record<ChromeView, string> = { admin: "Admin", system: "System", settings: "Settings" };
const CHROME_MIN_RANK: Record<ChromeView, number> = { admin: 3, system: 2, settings: 0 };

function AdminPanel() {
  const [ops, setOps] = useState<OperatorRow[] | null>(null);
  useEffect(() => {
    void fetchOperators().then(setOps);
  }, []);
  const cell: React.CSSProperties = { padding: "var(--sp-1) var(--sp-3)", borderBottom: "1px solid var(--line)", textAlign: "left" };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-4)" }}>
      <Panel title="Operators">
        {!ops ? <span style={{ color: "var(--muted)" }}>Loading…</span> : ops.length === 0 ? (
          <span style={{ color: "var(--muted)" }}>No operators visible (director-only).</span>
        ) : (
          <table data-testid="operators-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--fs-sm)", color: "var(--txt)" }}>
            <thead><tr>{["Email", "Role", "Status"].map((h) => (
              <th key={h} style={{ ...cell, color: "var(--dim)", textTransform: "uppercase", fontSize: "var(--fs-cap)" }}>{h}</th>
            ))}</tr></thead>
            <tbody>{ops.map((o) => (
              <tr key={o.email}>
                <td style={cell}>{o.email}</td>
                <td style={{ ...cell, color: "var(--accent)", textTransform: "uppercase", fontSize: "var(--fs-cap)" }}>{o.role}</td>
                <td style={{ ...cell, color: o.status === "active" ? "var(--ok)" : "var(--muted)" }}>{o.status}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Panel>
      <Panel title="Audit log (FS-19)"><EventsTable n={50} /></Panel>
    </div>
  );
}

function SystemPanel() {
  const [health, setHealth] = useState<Health | null>(null);
  const [uptime, setUptime] = useState<number | null>(null);
  useEffect(() => {
    void fetchHealth().then(setHealth);
    void fetchMetrics().then((m) => setUptime(m ? m.uptimeS : null));
  }, []);
  return (
    <Panel title="System health">
      <div style={{ display: "flex", gap: "var(--sp-3)", flexWrap: "wrap" }}>
        <MetricTile label="Status" value={health ? health.status : "…"} status={health?.ok ? "ok" : health ? "warn" : "default"} />
        <MetricTile label="Version" value={health?.version ?? "…"} />
        <MetricTile label="Uptime" value={uptime != null ? Math.round(uptime) : (health ? Math.round(health.uptimeS) : "…")} unit="s" />
      </div>
    </Panel>
  );
}

function SettingsPanel() {
  const { theme, fontPx, setTheme, setFontPx } = useCockpit();
  return (
    <Panel title="Display settings">
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-4)" }}>
        <div>
          <div style={{ color: "var(--dim)", fontSize: "var(--fs-cap)", textTransform: "uppercase", marginBottom: "var(--sp-2)" }}>Theme</div>
          <div style={{ display: "flex", gap: "var(--sp-2)" }}>
            <Button variant={theme === "dark" ? "primary" : "ghost"} size="sm" onClick={() => setTheme("dark")}>Dark</Button>
            <Button variant={theme === "light" ? "primary" : "ghost"} size="sm" onClick={() => setTheme("light")}>Light</Button>
          </div>
        </div>
        <div>
          <div style={{ color: "var(--dim)", fontSize: "var(--fs-cap)", textTransform: "uppercase", marginBottom: "var(--sp-2)" }}>
            Base font size — {fontPx}px
          </div>
          <div style={{ display: "flex", gap: "var(--sp-2)" }}>
            {[12, 13, 14, 16].map((px) => (
              <Button key={px} variant={fontPx === px ? "primary" : "ghost"} size="sm" onClick={() => setFontPx(px)}>{px}</Button>
            ))}
          </div>
        </div>
      </div>
    </Panel>
  );
}

export function ChromePanel() {
  const { chrome, roleRank, closeChrome } = useCockpit();
  if (!chrome) return null;
  const allowed = roleRank >= CHROME_MIN_RANK[chrome];
  return (
    <div role="dialog" aria-label={CHROME_TITLE[chrome]} onClick={closeChrome}
      style={{ position: "fixed", inset: 0, zIndex: 200, background: "rgba(2,4,8,.66)",
        display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "var(--sp-6)" }}>
      <div className="ds-root" onClick={(e) => e.stopPropagation()}
        style={{ width: "min(720px, 96vw)", maxHeight: "86vh", overflow: "auto", background: "var(--panel)",
          border: "1px solid var(--line)", borderRadius: "var(--r-lg)", boxShadow: "var(--shadow-modal)", padding: "var(--sp-5)" }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: "var(--sp-4)" }}>
          <span className="ds-display" data-testid="chrome-title" style={{ fontSize: 14, color: "var(--txt)" }}>{CHROME_TITLE[chrome]}</span>
          <span style={{ marginLeft: "auto" }}><Button size="sm" onClick={closeChrome}>Close</Button></span>
        </div>
        {!allowed ? (
          <div style={{ color: "var(--muted)" }}>Your role does not permit {CHROME_TITLE[chrome]}.</div>
        ) : chrome === "admin" ? <AdminPanel /> : chrome === "system" ? <SystemPanel /> : <SettingsPanel />}
      </div>
    </div>
  );
}
