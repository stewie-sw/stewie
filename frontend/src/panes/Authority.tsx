import { useState } from "react";

import { csrfHeader } from "../csrf";
import { useResource } from "../fetchState";
import type { Pane } from "../panes";
import { useWorkspace } from "../workspace_context";
import { depthSourceUsable } from "./DepthSource";

// [REQ:FR-03] the Release + Execute complete authority-evidence panel (extends FS-28). It binds the REAL
// /rc/eligibility gate set (all 11 fields) and surfaces, per pane, the full authority evidence + refusal
// reason. Release adds the director sign-off flow: pick a prepared mission -> POST /executive/release-plan ->
// the frozen 7-field command-authority card (plan hash, sign-off, runtime + sensor profile, namespace,
// authorization, SF-01 watchdog). Acceptance: a released revision shows every field (clause 1); an ineligible
// command surfaces its refusal reason (clause 2).
interface Eligibility {
  eligible: boolean;
  reason: string;
  profile: string;
  mode_ok: boolean;
  released: boolean;
  sensor_fresh: boolean;
  map_fresh: boolean;
  covariance_ok: boolean;
  watchdog_alive: boolean;
  link_ack: boolean;
  safe_inactive: boolean;
}
interface CommandAuthority {
  plan_hash: string;
  signed_by: string;
  runtime_profile: string;
  sensor_profile: string;
  namespace: string;
  authorized: boolean;
  watchdog_deadline_s: number;
}
interface SampleList { samples: { name: string; url: string }[] }

type GateKey = keyof Eligibility;
const RELEASE_GATES: [GateKey, string][] = [
  ["mode_ok", "namespace / mode authorized"],
  ["released", "released (director sign-off)"],
  ["watchdog_alive", "SF-01 watchdog alive"],
];
const EXECUTE_GATES: [GateKey, string][] = [
  ["sensor_fresh", "sensor stream fresh"],
  ["map_fresh", "map fresh"],
  ["covariance_ok", "pose covariance ok"],
  ["watchdog_alive", "watchdog alive"],
  ["link_ack", "link acknowledged"],
  ["safe_inactive", "SAFE not tripped"],
];
const AUTHORITY_FIELDS: [keyof CommandAuthority, string][] = [
  ["plan_hash", "plan hash"], ["signed_by", "signed by"], ["runtime_profile", "runtime profile"],
  ["sensor_profile", "sensor profile"], ["namespace", "namespace"], ["authorized", "AG-08 authorized"],
  ["watchdog_deadline_s", "SF-01 watchdog deadline (s)"],
];

function Gate({ ok, label }: { ok: boolean; label: string }) {
  return <li className={ok ? "gate-ok" : "gate-no"} data-gate={label} data-ok={ok}><span>{ok ? "✓" : "✕"}</span> {label}</li>;
}

// [REQ:FR-03] the director sign-off flow: pick a prepared mission's REAL orders -> release -> the card.
function ReleaseSignOff() {
  const missions = useResource<SampleList>("/sample_missions");
  const [pick, setPick] = useState("");
  const [card, setCard] = useState<CommandAuthority | null>(null);
  const [err, setErr] = useState("");

  async function release(name: string) {
    setErr(""); setCard(null);
    try {
      const m = await fetch(`/sample_mission/${name}`, { credentials: "same-origin" }).then((r) => r.json());
      const res = await fetch("/executive/release-plan", {
        method: "POST", credentials: "same-origin",
        headers: { "content-type": "application/json", ...csrfHeader() },   // [R7a] SEC-01 double-submit CSRF
        body: JSON.stringify({ orders: m.orders ?? [], mission_id: `release:${name}`, body: m.body ?? "moon" }),
      });
      const j = await res.json();
      if (!res.ok || !j.command_authority) throw new Error(j.error || `release ${res.status}`);
      setCard(j.command_authority);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }

  const samples = missions.status === "ready" ? missions.data.samples : [];
  return (
    <div className="report-block" data-testid="release-signoff">
      <h2>Director sign-off</h2>
      <div className="signoff-row">
        <select data-testid="release-mission" value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">select a prepared mission…</option>
          {samples.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
        </select>
        <button data-testid="release-btn" disabled={!pick} onClick={() => release(pick)}>Release + sign</button>
      </div>
      {err && <p className="state-error">Release refused — {err}</p>}
      {card && (
        <dl className="kv authority-card" data-testid="command-authority">
          {AUTHORITY_FIELDS.map(([k, label]) => <><dt key={`${k}t`}>{label}</dt><dd key={`${k}d`}>{String(card[k])}</dd></>)}
        </dl>
      )}
    </div>
  );
}

// [REQ:AU-01] the GLOBAL command-authority chrome: a compact, always-present element in the App shell that
// binds the SAME /rc/eligibility gate set as the AuthorityPane and surfaces the current command authority
// (AUTHORIZED / REFUSED + the refusal reason) from EVERY command-capable view -- so authority is never out of
// sight on any pane. The full per-pane AuthorityPane (evidence + sign-off) stays on Release/Execute.
export function AuthorityChrome() {
  const elig = useResource<Eligibility>("/rc/eligibility");
  if (elig.status !== "ready") {
    return (
      <span className="authority-chrome" data-testid="authority-chrome" data-eligible="unknown"
            data-state={elig.status} title="command authority">
        AUTH {elig.status === "error" ? "—" : "…"}
      </span>
    );
  }
  const ok = elig.data.eligible;
  return (
    <span className={`authority-chrome ${ok ? "auth-ok" : "auth-no"}`} data-testid="authority-chrome"
          data-eligible={ok} data-state="ready"
          title={ok ? "command authorized" : `command refused — ${elig.data.reason}`}>
      <strong>AUTH {ok ? "✓" : "✗"}</strong> {ok ? "authorized" : `refused — ${elig.data.reason}`}
    </span>
  );
}

export function AuthorityPane({ pane }: { pane: Pane }) {
  const { state } = useWorkspace();
  // [dispatch-audit R7c] the per-pane verdict must reflect the SELECTED mission: the backend /rc/eligibility
  // keys its released-live gate on ?mission=, so a bare fetch judged a mission-LESS command (always refused).
  // A mission-less workspace still fetches the bare path (the generic no-mission verdict, unchanged).
  const eligUrl = state.mission
    ? `/rc/eligibility?mission=${encodeURIComponent(state.mission)}`
    : "/rc/eligibility";
  const elig = useResource<Eligibility>(eligUrl);
  const depth = useResource<{ sources: { name: string; status: string }[] }>("/perception/depth-sources");
  const isRelease = pane.id === "release";
  const gates = isRelease ? RELEASE_GATES : EXECUTE_GATES;

  return (
    <section data-pane={pane.id} aria-label={pane.label}>
      <h1>{pane.label}{pane.system ? <span className="sysb"> {pane.system}</span> : null}</h1>

      <div className="report-block" data-testid={`authority-${pane.id}`} data-state={elig.status}>
        {elig.status === "loading" && <p className="state-loading">Loading command authority…</p>}
        {elig.status === "error" && <p className="state-error">Authority evidence unavailable ({elig.error}).</p>}
        {elig.status === "ready" && (
          <>
            <p className={elig.data.eligible ? "verdict-ok" : "verdict-no"}
               data-testid={`verdict-${pane.id}`} data-eligible={elig.data.eligible} data-blocked={!elig.data.eligible}>
              <strong>{elig.data.eligible ? "ELIGIBLE" : "REFUSED"}</strong>
              {!elig.data.eligible && <> — {elig.data.reason}</>}
            </p>
            {/* [REQ:FR-01] command authority KEYS on the runnable profile: if the operator's selected profile
                differs from the system's active profile, {pane.label} is DEGRADED (it would run under the
                system profile, not the selection) -- surfaced, never silently mismatched. */}
            {state.runnableProfile !== elig.data.profile && (
              <p className="verdict-no" data-testid={`profile-mismatch-${pane.id}`} data-mismatch="true">
                ⚠ profile mismatch — {pane.label} degraded: selected <strong>{state.runnableProfile}</strong>,
                but command authority runs under the system profile <strong>{elig.data.profile}</strong>.
              </p>
            )}
            {/* [REQ:FR-02] the depth source gates command authority too: a stale / simulated-when-live /
                absent source blocks Release/Execute with a legible reason. */}
            {depth.status === "ready" && (() => {
              const sel = depth.data.sources.find((s) => s.name === state.depthSource);
              const u = sel ? depthSourceUsable(sel.status, state.sourceClass, elig.data.sensor_fresh)
                            : { ok: false, note: "unknown depth source" };
              return u.ok ? null : (
                <p className="verdict-no" data-testid={`depth-degraded-${pane.id}`} data-degraded="true">
                  ⚠ depth source degraded — {pane.label} blocked: <strong>{state.depthSource}</strong> ({u.note}).
                </p>
              );
            })()}
            <dl className="kv">
              <dt>profile</dt><dd>{elig.data.profile}</dd>
              <dt>namespace</dt><dd>{state.commandNamespace}</dd>
              <dt>source class</dt><dd>{state.sourceClass}</dd>
            </dl>
            <ul className="gates" data-testid={`gates-${pane.id}`}>
              {gates.map(([k, label]) => <Gate key={k} ok={Boolean(elig.data[k])} label={label} />)}
            </ul>
          </>
        )}
      </div>

      {isRelease && <ReleaseSignOff />}
    </section>
  );
}
