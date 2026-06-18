/* Typed API adapters (FS-15) for the data-light work areas + chrome panels. Each maps a real backend
 * route to a view model; shapes are verbatim from the routers:
 *   GET /events            (director) -> {ok, events:[{ts, actor, action, target}]}   FS-19 audit ledger
 *   GET /admin/operators   (director) -> {ok, operators:[{email, role, status, created_at}]}
 *   GET /healthz                       -> {status, version, uptime_s, audit, revocation}
 *   GET /metrics                       -> {uptime_s, latency, …}
 * UI consumes these view models, never the raw JSON. */

async function getJson(path: string): Promise<{ status: number; json: any }> {
  const r = await fetch(path, { credentials: "same-origin" });
  const json = await r.json().catch(() => null);
  return { status: r.status, json };
}

export interface EventRow {
  ts: number;
  tsLabel: string;
  actor: string;
  action: string;
  target: string;
}

function fmtTs(ts: number): string {
  if (!ts) return "";
  try {
    return new Date(ts * 1000).toISOString().replace("T", " ").slice(0, 19);
  } catch {
    return String(ts);
  }
}

/** GET /events — the FS-19 audit ledger (director-only; 403 for lower roles). */
export async function fetchEvents(n = 50): Promise<EventRow[]> {
  const { status, json } = await getJson(`/events?n=${n}`);
  if (status >= 400 || !json?.ok) return [];
  return (json.events || []).map((e: any): EventRow => ({
    ts: e.ts, tsLabel: fmtTs(e.ts), actor: e.actor || "", action: e.action || "", target: e.target || "",
  }));
}

export interface OperatorRow {
  email: string;
  role: string;
  status: string;
  createdAt: number | null;
}

/** GET /admin/operators — the operator roster (director-only). */
export async function fetchOperators(): Promise<OperatorRow[]> {
  const { status, json } = await getJson("/admin/operators");
  if (status >= 400 || !json?.ok) return [];
  return (json.operators || []).map((o: any): OperatorRow => ({
    email: o.email, role: o.role, status: o.status, createdAt: o.created_at ?? null,
  }));
}

export interface Health {
  status: string;
  version: string;
  uptimeS: number;
  ok: boolean;
}

/** GET /healthz — public health (no auth). */
export async function fetchHealth(): Promise<Health | null> {
  const { status, json } = await getJson("/healthz");
  if (status >= 400 || !json) return null;
  return { status: json.status, version: json.version, uptimeS: json.uptime_s, ok: json.status === "ok" };
}

export interface Metrics {
  uptimeS: number;
  raw: Record<string, unknown>;
}

/** GET /metrics — operations metrics snapshot. */
export async function fetchMetrics(): Promise<Metrics | null> {
  const { status, json } = await getJson("/metrics");
  if (status >= 400 || !json) return null;
  return { uptimeS: json.uptime_s ?? 0, raw: json };
}

export interface NavStage {
  stage: string;
  present: boolean; // wired on this host vs. a gated tier (e.g. the live planner binary)
  seam: string;
  note: string;
}
export interface NavContract {
  version: string;
  onHostComplete: boolean;
  stages: NavStage[];
}

/** GET /nav/contract — the FS-05 auditable navigation contract: each stage self-reports whether its seam
 * is wired on this host; the live Autoware/Nav2 planner binary is the gated tier. */
export async function fetchNavContract(): Promise<NavContract | null> {
  const { status, json } = await getJson("/nav/contract");
  if (status >= 400 || !json?.ok) return null;
  return {
    version: json.version,
    onHostComplete: !!json.on_host_complete,
    stages: (json.stages || []).map((s: any): NavStage => ({
      stage: s.stage, present: !!s.present, seam: s.seam || "", note: s.note || "",
    })),
  };
}
