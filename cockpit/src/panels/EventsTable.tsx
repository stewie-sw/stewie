/* The FS-19 audit-ledger view: self-fetches GET /events (director-only) and renders newest-first with
 * loading / error / empty / ok states. Reused by the Admin panel and the Metrics work area. */
import { useEffect, useState } from "react";
import { fetchEvents, type EventRow } from "../api";

type State = "loading" | "ok" | "empty" | "error";

export function EventsTable({ n = 50 }: { n?: number }) {
  const [state, setState] = useState<State>("loading");
  const [rows, setRows] = useState<EventRow[]>([]);

  useEffect(() => {
    let live = true;
    fetchEvents(n)
      .then((ev) => {
        if (!live) return;
        setRows(ev);
        setState(ev.length ? "ok" : "empty");
      })
      .catch(() => live && setState("error"));
    return () => {
      live = false;
    };
  }, [n]);

  if (state === "loading") return <Note>Loading events…</Note>;
  if (state === "error") return <Note>Could not load the audit ledger (director-only).</Note>;
  if (state === "empty") return <Note>No events recorded yet.</Note>;

  const cell: React.CSSProperties = { padding: "var(--sp-1) var(--sp-3)", borderBottom: "1px solid var(--line)", textAlign: "left" };
  const th: React.CSSProperties = { ...cell, color: "var(--dim)", textTransform: "uppercase", fontSize: "var(--fs-cap)", letterSpacing: "0.08em" };
  return (
    <table data-testid="events-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--fs-sm)", color: "var(--txt)" }}>
      <thead>
        <tr><th style={th}>Time (UTC)</th><th style={th}>Actor</th><th style={th}>Action</th><th style={th}>Target</th></tr>
      </thead>
      <tbody>
        {rows.map((e, i) => (
          <tr key={i}>
            <td style={{ ...cell, color: "var(--muted)", fontFamily: "var(--font-display)", fontSize: "var(--fs-cap)" }}>{e.tsLabel}</td>
            <td style={cell}>{e.actor}</td>
            <td style={{ ...cell, color: "var(--accent)" }}>{e.action}</td>
            <td style={{ ...cell, color: "var(--muted)" }}>{e.target}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <div style={{ color: "var(--muted)", fontSize: "var(--fs-sm)", padding: "var(--sp-3) 0" }}>{children}</div>;
}
