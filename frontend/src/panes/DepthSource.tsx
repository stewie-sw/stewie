import { useResource } from "../fetchState";
import { useWorkspace } from "../workspace_context";

// [REQ:FR-02] the perception depth-source selector + health/freshness. Binds /perception/depth-sources (the
// real profile registry: each source's kind + health STATUS) and the /rc/eligibility freshness gate. A source
// is usable or DEGRADED for the current source class -- a simulated source cannot back a LIVE command, an
// absent/legacy source is unusable -- and Release/Execute key on that verdict (AuthorityPane).
export interface DepthSource {
  name: string;
  kind: string;
  status: string;
  output_topic: string | null;
}
interface DepthResp { ok: boolean; selected: string; sources: DepthSource[] }
interface Fresh { sensor_fresh: boolean }

// the shared usability rule (reused by the AuthorityPane's Release/Execute degrade). `fresh` folds the
// eligibility sensor-freshness gate in: a stale stream degrades even a healthy source.
export function depthSourceUsable(status: string, sourceClass: string, fresh: boolean):
  { ok: boolean; note: string } {
  if (!fresh) return { ok: false, note: "sensor stream stale" };
  if (status === "absent") return { ok: false, note: "sensor absent" };
  if (status === "legacy") return { ok: false, note: "legacy geometry (provenance only)" };
  if (status === "simulated" && sourceClass === "live") return { ok: false, note: "simulated source, live required" };
  return { ok: true, note: status };
}

export function DepthSourcePane() {
  const { state, patch } = useWorkspace();
  const depth = useResource<DepthResp>("/perception/depth-sources");
  const elig = useResource<Fresh>("/rc/eligibility");
  const fresh = elig.status === "ready" ? elig.data.sensor_fresh : true;

  return (
    <section data-pane="validate" aria-label="Validate">
      <h1>Validate <span className="sysb">LEAP</span></h1>

      <div className="report-block" data-testid="depth-sources" data-state={depth.status}>
        <h2>Perception depth source</h2>
        {depth.status === "loading" && <p className="state-loading">Loading depth sources…</p>}
        {depth.status === "error" && <p className="state-error">Depth sources unavailable ({depth.error}).</p>}
        {depth.status === "ready" && (
          <>
            <div className="signoff-row">
              <select data-testid="ws-depthSource" value={state.depthSource}
                onChange={(e) => patch({ depthSource: e.target.value })}>
                {depth.data.sources.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
              </select>
              <span className="tx-when">source class {state.sourceClass} · sensor {fresh ? "fresh" : "STALE"}</span>
            </div>
            <table className="compat" data-testid="depth-table">
              <thead><tr><th>source</th><th>kind</th><th>health</th><th>usable</th></tr></thead>
              <tbody>
                {depth.data.sources.map((s) => {
                  const u = depthSourceUsable(s.status, state.sourceClass, fresh);
                  return (
                    <tr key={s.name} data-current={s.name === state.depthSource}>
                      <td>{s.name}</td><td>{s.kind}</td><td>{s.status}</td>
                      <td className={u.ok ? "c-ok" : "c-no"} title={u.note}>{u.ok ? "✓" : "✕"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}
      </div>
    </section>
  );
}
