import { useState } from "react";

import { useResource } from "../fetchState";
import { useWorkspace } from "../workspace_context";

// [REQ:BD-03] the Models pane's body/profile UI: it binds the REAL /physics/compatibility matrix and shows
// (a) the support verdict for the CURRENT workspace body x physics-backend, and (b) the full body-by-backend
// compatibility matrix. A microgravity body (Bennu/Phobos) reads REFUSED fail-closed (regime out of range);
// a gravity-loaded validated body reads SUPPORTED. The body + physics-backend selectors live in the workspace
// rail (App.tsx) and drive `state.body` / `state.physicsBackend`.
interface Cell {
  supported: boolean;
  regime_ok: boolean;
  reason: string;
}
interface CompatResp {
  ok: boolean;
  backends: string[];
  bodies: string[];
  matrix: Record<string, Record<string, Cell>>;
}

export function ModelsPane() {
  const { state } = useWorkspace();
  const [allowAnalog, setAllowAnalog] = useState(false); // BD-03 soil override (params_for_body allow_analog)
  const compat = useResource<CompatResp>(
    `/physics/compatibility${allowAnalog ? "?allow_analog=true" : ""}`,
  );

  const current =
    compat.status === "ready" ? compat.data.matrix[state.body]?.[state.physicsBackend] : undefined;

  return (
    <section data-pane="models" aria-label="Models">
      <h1>Models <span className="sysb">FORGE</span></h1>

      <label className="soil-override">
        <input type="checkbox" data-testid="models-allow-analog" checked={allowAnalog}
          onChange={(e) => setAllowAnalog(e.target.checked)} />
        Soil override — run microgravity bodies against an explicit gravity-loaded analog (caveated)
      </label>

      <div className="report-block" data-testid="models-verdict" data-state={compat.status}>
        <h2>Support verdict — {state.body} × {state.physicsBackend}</h2>
        {compat.status === "loading" && <p className="state-loading">Loading compatibility…</p>}
        {compat.status === "error" && (
          <p className="state-error">Compatibility unavailable ({compat.error}) — sign in to view.</p>
        )}
        {compat.status === "ready" && !current && (
          <p className="state-empty">No verdict for {state.body} × {state.physicsBackend}.</p>
        )}
        {compat.status === "ready" && current && (
          <p className={current.supported ? "verdict-ok" : "verdict-no"} data-supported={current.supported}>
            <strong>{current.supported ? "SUPPORTED" : "REFUSED"}</strong> — {current.reason}
          </p>
        )}
      </div>

      <div className="report-block" data-testid="models-matrix" data-state={compat.status}>
        <h2>Body × backend compatibility</h2>
        {compat.status === "loading" && <p className="state-loading">Loading matrix…</p>}
        {compat.status === "error" && <p className="state-error">Matrix unavailable ({compat.error}).</p>}
        {compat.status === "ready" && (
          <table className="compat">
            <thead>
              <tr>
                <th>body</th>
                {compat.data.backends.map((b) => <th key={b}>{b}</th>)}
              </tr>
            </thead>
            <tbody>
              {compat.data.bodies.map((body) => (
                <tr key={body} data-current={body === state.body}>
                  <td>{body}</td>
                  {compat.data.backends.map((be) => {
                    const cell = compat.data.matrix[body][be];
                    return (
                      <td key={be} className={cell.supported ? "c-ok" : "c-no"} title={cell.reason}>
                        {cell.supported ? "✓" : cell.regime_ok ? "—" : "✕"}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
