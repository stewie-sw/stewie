/* The Navigation/Autonomy work area (FS-05): surfaces the auditable navigation contract from
 * GET /nav/contract — each stage (global route, local trajectory, tracker, recovery, keep-outs, negative
 * obstacles, illumination risk, slip/energy budget, NV-11 ROS lowering) self-reports whether its seam is
 * wired on this host; the live Autoware/Nav2 planner binary is the one gated tier. The Plan IR + posture
 * plan (NV-11/AM-01) lower from an authored plan, which arrives with the map in Phase 4. */
import { useEffect, useState } from "react";
import { Panel } from "@stewie/design-system";
import { fetchNavContract, type NavContract } from "../api";

type State = "loading" | "ok" | "error";

export function NavigationView() {
  const [state, setState] = useState<State>("loading");
  const [c, setC] = useState<NavContract | null>(null);
  useEffect(() => {
    let live = true;
    fetchNavContract()
      .then((nc) => {
        if (!live) return;
        setC(nc);
        setState(nc ? "ok" : "error");
      })
      .catch(() => live && setState("error"));
    return () => {
      live = false;
    };
  }, []);

  const cell: React.CSSProperties = { padding: "var(--sp-2) var(--sp-3)", borderBottom: "1px solid var(--line)", textAlign: "left", verticalAlign: "top" };
  const th: React.CSSProperties = { ...cell, color: "var(--dim)", textTransform: "uppercase", fontSize: "var(--fs-cap)", letterSpacing: "0.08em" };

  return (
    <div style={{ flex: 1, minWidth: 0, overflow: "auto", padding: "var(--sp-5)", background: "var(--bg)" }}>
      <Panel title="Navigation contract (FS-05)">
        {state === "loading" && <Note>Loading the navigation contract…</Note>}
        {state === "error" && <Note>Could not load /nav/contract.</Note>}
        {state === "ok" && c && (
          <>
            <div style={{ display: "flex", gap: "var(--sp-3)", alignItems: "center", marginBottom: "var(--sp-3)", flexWrap: "wrap" }}>
              <span style={{ color: "var(--muted)", fontSize: "var(--fs-sm)" }}>v{c.version}</span>
              <span data-testid="onhost-badge" style={{ fontSize: "var(--fs-cap)", textTransform: "uppercase", letterSpacing: "0.08em",
                color: c.onHostComplete ? "var(--ok)" : "var(--warn)" }}>
                {c.onHostComplete ? "all on-host seams wired" : "on-host incomplete"}
              </span>
            </div>
            <table data-testid="nav-stages" style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--fs-sm)", color: "var(--txt)" }}>
              <thead><tr><th style={th}>Stage</th><th style={th}>Status</th><th style={th}>Seam</th></tr></thead>
              <tbody>
                {c.stages.map((s) => (
                  <tr key={s.stage}>
                    <td style={{ ...cell, fontFamily: "var(--font-display)", fontSize: "var(--fs-cap)", textTransform: "uppercase" }}>{s.stage}</td>
                    <td style={{ ...cell, color: s.present ? "var(--ok)" : "var(--warn)", whiteSpace: "nowrap" }}>
                      {s.present ? "● wired" : "○ gated"}
                    </td>
                    <td style={{ ...cell, color: "var(--muted)", fontFamily: "monospace", fontSize: "var(--fs-cap)" }}>
                      {s.seam}{s.note ? <div style={{ color: "var(--dim)" }}>{s.note}</div> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Panel>

      <div style={{ height: "var(--sp-4)" }} />
      <Panel title="Plan IR + posture plan (NV-11 / AM-01)">
        <Note>
          Authoring a mission lowers its Plan IR (paths, motion/work goals, replan events) and the
          FSM-legal posture plan, emitted on the AG-08-gated command path. Plan authoring binds with the
          map/world canvas in Phase 4; this view then renders the lowered IR for the selected plan.
        </Note>
      </Panel>
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <div style={{ color: "var(--muted)", fontSize: "var(--fs-sm)", lineHeight: 1.6, padding: "var(--sp-2) 0" }}>{children}</div>;
}
