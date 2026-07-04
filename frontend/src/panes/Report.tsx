import { useResource } from "../fetchState";

// [REQ:RF-03] first migrated pane: Report binds the REAL backend evidence (/world state + /world/transactions
// timeline) via the useResource state convention (loading/error/empty/ready). It mirrors the vanilla Report
// (cockpit.js loadReport: world state + recent transactions); the vanilla pane stays authoritative at / until
// this pane's parity gate passes (ADR-0007).

interface WorldResp {
  ok: boolean;
  world?: Record<string, unknown>;
  layer_manifest?: { layers?: { layer_id?: string }[] } | Record<string, unknown>;
}
interface TxListResp {
  ok?: boolean;
  transactions?: Array<Record<string, unknown>>;
}

function layerNames(m: WorldResp["layer_manifest"]): string[] {
  const layers = (m as { layers?: { layer_id?: string }[] } | undefined)?.layers;
  return Array.isArray(layers) ? layers.map((l) => l.layer_id ?? "?") : [];
}

export function ReportPane() {
  const world = useResource<WorldResp>("/world");
  const txs = useResource<TxListResp>(
    "/world/transactions?limit=20",
    (d) => !d.transactions || d.transactions.length === 0,
  );

  return (
    <section data-pane="report" aria-label="Report">
      <h1>Report <span className="sysb">FORGE</span></h1>

      <div className="report-block" data-testid="report-world" data-state={world.status}>
        <h2>World state</h2>
        {world.status === "loading" && <p className="state-loading">Loading world state…</p>}
        {world.status === "error" && (
          <p className="state-error">World state unavailable ({world.error}) — sign in to view live evidence.</p>
        )}
        {world.status === "empty" && <p className="state-empty">No world state yet.</p>}
        {world.status === "ready" && (
          <dl className="kv">
            <dt>fields</dt><dd>{Object.keys(world.data.world ?? {}).join(", ") || "—"}</dd>
            <dt>layers</dt><dd>{layerNames(world.data.layer_manifest).join(", ") || "—"}</dd>
          </dl>
        )}
      </div>

      <div className="report-block" data-testid="report-timeline" data-state={txs.status}>
        <h2>Execution timeline</h2>
        {txs.status === "loading" && <p className="state-loading">Loading transactions…</p>}
        {txs.status === "error" && <p className="state-error">No transaction evidence ({txs.error}).</p>}
        {txs.status === "empty" && <p className="state-empty">No world transactions recorded yet.</p>}
        {txs.status === "ready" && (
          <ol className="timeline">
            {txs.data.transactions!.slice(0, 20).map((t, i) => (
              <li key={i}>
                <span className="tx-kind">{String(t.kind ?? t.action ?? t.op ?? "transaction")}</span>
                <span className="tx-when">{String(t.timestamp ?? t.time ?? t.at ?? "")}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
