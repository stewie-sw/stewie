import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AuthorityPane } from "./panes/Authority";
import { ModelsPane } from "./panes/Models";
import { ReportPane } from "./panes/Report";
import { PANES, RANK, visiblePanes } from "./panes";
import type { Pane, Role } from "./panes";
import { useRole } from "./session";
import { BODIES, PHYSICS_BACKENDS, PRODUCT_MODES, RUNNABLE_PROFILES } from "./workspace";
import type { PhysicsBackend, ProductMode, RunnableProfile } from "./workspace";
import { WorkspaceProvider, useWorkspace } from "./workspace_context";

// [REQ:RF-02] the workspace rail: product mode / runnable profile / physics backend, URL-synced (a change
// writes the query params; a reload restores them). This is the routeable/shareable state model (FS-25).
function WorkspaceRail() {
  const { state, patch } = useWorkspace();
  return (
    <div className="workspace-rail" data-testid="workspace-rail">
      <label>Mode
        <select data-testid="ws-productMode" value={state.productMode}
          onChange={(e) => patch({ productMode: e.target.value as ProductMode })}>
          {PRODUCT_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </label>
      <label>Profile
        <select data-testid="ws-runnableProfile" value={state.runnableProfile}
          onChange={(e) => patch({ runnableProfile: e.target.value as RunnableProfile })}>
          {RUNNABLE_PROFILES.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </label>
      <label>Body
        <select data-testid="ws-body" value={state.body}
          onChange={(e) => patch({ body: e.target.value })}>
          {BODIES.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
      </label>
      <label>Backend
        <select data-testid="ws-physicsBackend" value={state.physicsBackend}
          onChange={(e) => patch({ physicsBackend: e.target.value as PhysicsBackend })}>
          {PHYSICS_BACKENDS.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
      </label>
    </div>
  );
}

// a migrating pane's identity placeholder (RF-01); real content lands per pane in later rows.
function PanePlaceholder({ pane }: { pane: Pane }) {
  return (
    <section data-pane={pane.id} aria-label={pane.label}>
      <h1>{pane.label}{pane.system ? <span className="sysb"> {pane.system}</span> : null}</h1>
      <p className="migrating">
        Migrating pane — the vanilla cockpit remains authoritative for {pane.label} until its parity gate passes.
      </p>
    </section>
  );
}

function PaneRoute({ pane, role }: { pane: Pane; role: Role }) {
  if (RANK[role] < RANK[pane.minRole]) return <Navigate to="/plan" replace />; // fail-closed role gate (RF-01)
  if (pane.id === "release" || pane.id === "metrics") return <AuthorityPane pane={pane} />; // FR-03 authority
  if (pane.id === "report") return <ReportPane />; // RF-03: first migrated pane (real /world evidence)
  if (pane.id === "models") return <ModelsPane />; // BD-03: body/backend compatibility matrix
  return <PanePlaceholder pane={pane} />;
}

function Shell() {
  const role = useRole();
  const nav = visiblePanes(role);
  const { search } = useLocation(); // preserve the workspace state (URL query) across pane navigation
  return (
    <div className="cockpit-shell">
      <header className="conops-spine">
        <span className="brand">STEWIE</span>
        <nav aria-label="cockpit panes">
          {nav.map((p) => (
            <NavLink key={p.id} to={{ pathname: `/${p.id}`, search }} data-view={p.id} className="vtab">{p.label}</NavLink>
          ))}
        </nav>
        <span className="role-badge" data-role={role} title="current operator role">{role}</span>
      </header>
      <WorkspaceRail />
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

export function App() {
  return (
    <WorkspaceProvider>
      <Shell />
    </WorkspaceProvider>
  );
}
