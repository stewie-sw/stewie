import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { PANES, RANK, visiblePanes } from "./panes";
import type { Pane, Role } from "./panes";
import { useRole } from "./session";

// [REQ:RF-01] A migrating pane. For the shell, each pane renders its IDENTITY (label + subsystem badge) as a
// placeholder; the real content migrates pane-by-pane in later rows (RF-02/03, FR-*). The vanilla cockpit at
// / stays authoritative until a pane's parity gate passes (ADR-0007).
function PanePlaceholder({ pane }: { pane: Pane }) {
  return (
    <section data-pane={pane.id} aria-label={pane.label}>
      <h1>
        {pane.label}
        {pane.system ? <span className="sysb"> {pane.system}</span> : null}
      </h1>
      <p className="migrating">
        Migrating pane — the vanilla cockpit remains authoritative for {pane.label} until its parity gate passes.
      </p>
    </section>
  );
}

// Fail-closed: a pane above the current role redirects to Plan (mirrors the vanilla "bounce a demoted operator
// off the gated tab").
function PaneRoute({ pane, role }: { pane: Pane; role: Role }) {
  if (RANK[role] < RANK[pane.minRole]) return <Navigate to="/plan" replace />;
  return <PanePlaceholder pane={pane} />;
}

export function App() {
  const role = useRole();
  const nav = visiblePanes(role);
  return (
    <div className="cockpit-shell">
      <header className="conops-spine">
        <span className="brand">STEWIE</span>
        <nav aria-label="cockpit panes">
          {nav.map((p) => (
            <NavLink key={p.id} to={`/${p.id}`} data-view={p.id} className="vtab">
              {p.label}
            </NavLink>
          ))}
        </nav>
        <span className="role-badge" data-role={role} title="current operator role">
          {role}
        </span>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/plan" replace />} />
          {PANES.map((p) => (
            <Route key={p.id} path={`/${p.id}`} element={<PaneRoute pane={p} role={role} />} />
          ))}
          <Route path="*" element={<Navigate to="/plan" replace />} />
        </Routes>
      </main>
    </div>
  );
}
