"""Operator/director training sessions (STEWIE P22 / beta B3).

A session runs the REAL closed-loop executive (lode.autonomy.run_closed_loop) once, records the
per-leg execution, and serves two views of the same record:

  OPERATOR  -- open URL; every leg passes through the telemetry layer (stewie.bridge.telemetry):
               legs whose status packet is dropped by the link simply never reach the operator,
               and TRUTH fields (slip, slope, true energy) are denylisted by construction.
  DIRECTOR  -- API-key gated; the full record plus the seen-vs-actual divergence (the debrief).

Fast-forward is a VIEW concern: replaying faster never re-runs the link, so the link accounting is
immutable after execution (B3.4).
"""
from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass, field

from stewie.bridge import telemetry as tl

_PROFILES = os.path.join(os.path.dirname(tl.__file__), "profiles")
# fields the operator must NEVER see (truth telemetry; I3 carries into training sessions)
TRUTH_FIELDS = ("true_J", "slip", "slope_deg", "true_energy_J")
_LEG_PERIOD_S = 1.0          # one status packet per leg on the sim clock
_LEG_PACKET_BYTES = 256      # status packet size [ASSUMPTION: CCSDS-class housekeeping frame]


@dataclass
class Session:
    session_id: str
    profile_name: str
    record: dict                      # the full closed-loop output (director truth)
    link: tl.TelemetryLink
    operator_legs: list = field(default_factory=list)
    mission_t0_s: float = 0.0         # T4.2: the session's mission epoch -- ONE sun for all views
    created_monotonic_s: float = 0.0  # M-09: store-eviction stamp; set by start() at insert time
    mission: object = None            # TR-01: retained so makespan-vs-optimal can re-sim alternatives
    objective: str = "time"           # TR-01: the objective the run optimised (ranks forward_compare)

    def sun_state(self) -> dict:
        from stewie.specs.solar import sun_az_el
        az, el = sun_az_el(-87.45, float(self.mission_t0_s))
        return {"mission_t0_s": self.mission_t0_s, "az_deg": az, "el_deg": el,
                "authority": "stewie.specs.solar @ Haworth -87.45"}

    @classmethod
    def run(cls, mission, *, profile: str = "ideal", dem=None, dem_origin=(0.0, 0.0),
            algorithm: str = "auto", objective: str = "time", seed: int = 0,
            mission_t0_s: float = 0.0) -> "Session":
        from lode import autonomy as AUT
        prof = tl.load_profile(os.path.join(_PROFILES, f"{profile}.json"))
        out = AUT.run_closed_loop(mission, dem=dem, dem_origin=dem_origin,
                                  algorithm=algorithm, objective=objective)
        link = tl.TelemetryLink(prof, seed=seed)
        sess = cls(session_id=secrets.token_hex(8), profile_name=profile, record=out, link=link,
                   mission_t0_s=float(mission_t0_s), mission=mission, objective=objective)
        for i, leg in enumerate(out["legs"]):
            visible_at = link.deliver_at(_LEG_PACKET_BYTES, t_s=i * _LEG_PERIOD_S)
            if visible_at is not None:                     # mypy-narrowed (the bool indirection wasn't)
                shaped = {k: v for k, v in leg.items() if k not in TRUTH_FIELDS}
                shaped["sent_at_s"] = round(i * _LEG_PERIOD_S, 3)
                shaped["visible_at_s"] = round(visible_at, 3)   # #67 [REQ:PO-03]: sent + downlink latency
                sess.operator_legs.append(shaped)
        return sess

    def operator_view(self) -> dict:
        return {
            "session_id": self.session_id,
            "legs": self.operator_legs,                       # only what the link delivered
            "n_legs_total": len(self.record["legs"]),
            "completed": self.record["completed"],
            "recharges": self.record["recharges"],
            "link": {"profile": self.profile_name, "stats": dict(self.link.stats)},
            "sun": self.sun_state(),
        }

    def scorecard(self) -> dict:
        """#80 trainer A-board: the autonomy-run KPIs from this session. ``public`` is what a trainee
        sees (objectives, link reality, energy budget); ``truth`` (believed-vs-actual divergence) is
        director-only -- the seen-vs-actual gap is exactly the truth-denylisted signal (UI-11)."""
        rec = self.record
        legs = rec["legs"]
        nominal = sum(float(l_["nominal_J"]) for l_ in legs)
        true = sum(float(l_["true_J"]) for l_ in legs)
        seen = {l_["leg"] for l_ in self.operator_legs}
        missed = [l_["leg"] for l_ in legs if l_["leg"] not in seen]
        n = max(1, len(legs))
        stats = dict(self.link.stats)
        public = {
            "completed": bool(rec["completed"]),
            "objectives_total": int(rec.get("n_trips", len(legs))),
            "recharges": int(rec["recharges"]),
            "replans": int(rec["replans"]),
            "legs_total": len(legs),
            "legs_delivered": len(self.operator_legs),
            "legs_missed": len(missed),
            "comm_delivered_frac": round(len(self.operator_legs) / n, 3),
            "stranded_packets": int(stats.get("stranded", 0)),
            "dropped_packets": int(stats.get("dropped", 0)),
            "energy_MJ": round(nominal / 1e6, 3),
            "link_profile": self.profile_name,
        }
        public.update(self.makespan_vs_optimal())
        truth = {"energy_divergence_J": round(abs(true - nominal), 1),
                 "true_energy_MJ": round(true / 1e6, 3),
                 "operator_missed_legs": missed}
        return {"public": public, "truth": truth}

    def makespan_vs_optimal(self) -> dict:
        """TR-01: score the run's makespan against the best alternative the planner can find.
        ``makespan_s`` is THIS run's canonical plant time; ``optimal_s`` is the head of the ranked
        candidate futures that ``lode.resync.forward_compare`` re-simulates over the same mission
        (same conserved authority -- no second simulator, no authored numbers). ``makespan_ratio`` =
        run / optimal (>= 1.0 when the chosen plan was not the fastest). When the mission was not
        retained (a structural fixture), the run is its own reference (ratio 1.0)."""
        makespan_s = float(self.record.get("plant_time_s", 0.0))
        optimal_s = makespan_s
        if self.mission is not None and makespan_s > 0.0:
            from lode import resync as RES
            fc = RES.forward_compare(self.mission, objective=self.objective,
                                     stem=f"scorecard_{self.session_id}")
            futures = fc.get("futures") or []
            cand = [float(f["time_s"]) for f in futures if float(f.get("time_s", 0.0)) > 0.0]
            # the optimal is the fastest candidate; never claim faster than the run actually achieved
            if cand:
                optimal_s = min([makespan_s, *cand])
        ratio = makespan_s / optimal_s if optimal_s > 0.0 else 1.0
        return {"makespan_s": round(makespan_s, 3), "optimal_s": round(optimal_s, 3),
                "makespan_ratio": round(ratio, 4)}

    def debrief_view(self, fast_forward: float = 1.0) -> dict:
        legs = self.record["legs"]
        divergence = sum(abs(float(leg["true_J"]) - float(leg["nominal_J"])) for leg in legs)
        seen_labels = {leg_rec["leg"] for leg_rec in self.operator_legs}
        return {
            "session_id": self.session_id,
            "fast_forward": float(fast_forward),              # view-rate only; link stats untouched
            "legs": legs,
            "n_legs_total": len(legs),
            "operator_received": len(self.operator_legs),
            "operator_missed_legs": [l_["leg"] for l_ in legs if l_["leg"] not in seen_labels],
            "energy_divergence_J": float(divergence),
            "completed": self.record["completed"],
            "map_channel": self.record.get("map_channel"),
            "sun": self.sun_state(),
        }


_SESSIONS: dict[str, Session] = {}
_SESSION_TTL_S = 6 * 3600.0          # M-09: live-session TTL (~one training shift)
_SESSION_MAX = 256                   # M-09: hard cap on concurrently-held sessions
_now = time.monotonic                # injectable elapsed-time source (test-pinnable)


def _evict(now: float) -> None:
    """M-09: drop expired sessions, then enforce the cap oldest-first (clock-driven). The durable
    record is the on-demand debrief/summary markdown, so eviction never loses the trainer's record."""
    for sid in [k for k, v in _SESSIONS.items()
                if now - v.created_monotonic_s > _SESSION_TTL_S]:
        _SESSIONS.pop(sid, None)
    while len(_SESSIONS) > _SESSION_MAX:
        oldest = min(_SESSIONS, key=lambda k: _SESSIONS[k].created_monotonic_s)
        _SESSIONS.pop(oldest, None)


def start(mission, **kw) -> Session:
    s = Session.run(mission, **kw)
    now = _now()
    _evict(now)                      # clear the expired/over-cap backlog before inserting
    s.created_monotonic_s = now
    _SESSIONS[s.session_id] = s
    if len(_SESSIONS) > _SESSION_MAX:   # the just-inserted session itself may put us at cap+1
        _evict(now)
    return s


def get(session_id: str) -> Session | None:
    return _SESSIONS.get(session_id)


def _route_drive_m(record: dict) -> float:
    """Total routed drive distance [m]: the GoTo waypoint polylines from the canonical plan IR.
    This is the EXECUTED route geometry (it includes any keep-out detour), not the crow-flies."""
    import math
    total = 0.0
    for a in record.get("plan_ir", {}).get("actions", ()):
        wp = a.get("waypoints") or []
        total += sum(math.dist(wp[i], wp[i + 1]) for i in range(len(wp) - 1))
    return total


def summary_markdown(s: Session) -> str:
    """The per-run mission summary (beta B4.2): route, energy, comm drops, slip events, and the
    seen-vs-actual divergence. A director/debrief artifact (it carries truth fields), built only
    from the closed-loop record -- no authored numbers."""
    d = s.debrief_view()
    rec = s.record
    legs = rec["legs"]
    nominal_J = sum(float(l_["nominal_J"]) for l_ in legs)
    true_J = sum(float(l_["true_J"]) for l_ in legs)
    drive_m = _route_drive_m(rec)
    stats = dict(s.link.stats)
    # a "slip event" leg = one whose drive actually slipped (slope-driven; dig legs do not slip)
    slipped = sorted((l_ for l_ in legs if float(l_["slip"]) > 0.0),
                     key=lambda l_: float(l_["slip"]), reverse=True)

    lines = [f"# Mission summary — session {s.session_id}",
             "",
             f"- completed: {d['completed']} · legs: {d['n_legs_total']} "
             f"(operator received {d['operator_received']})",
             f"- recharges: {rec['recharges']} · replans: {rec['replans']}",
             "",
             "## Route",
             f"- routed drive distance: {drive_m:.1f} m (executed path incl. any detour)",
             "", "| leg | believed → true pose | SoC |", "|---|---|---|"]
    for leg in legs:
        lines.append(f"| {leg['leg']} | ({leg['bx']:.1f}, {leg['by']:.1f}) → "
                     f"({leg['tx']:.1f}, {leg['ty']:.1f}) | {leg['soc']:.2f} |")

    lines += ["",
              "## Energy",
              f"- nominal (planned): {nominal_J / 1e6:.3f} MJ · "
              f"true (slip/grade physics): {true_J / 1e6:.3f} MJ",
              "", "| leg | nominal J | true J |", "|---|---|---|"]
    for leg in legs:
        lines.append(f"| {leg['leg']} | {leg['nominal_J']:.0f} | {leg['true_J']:.0f} |")

    lines += ["",
              "## Link (comm drops)",
              f"- link profile: {s.profile_name} · stats: {stats}",
              f"- operator received {d['operator_received']} / {d['n_legs_total']} legs · "
              f"missed: {d['operator_missed_legs'] or 'none'}"]

    lines += ["", "## Slip events"]
    if slipped:
        lines += [f"- {len(slipped)} drive leg(s) slipped on the real DEM grade",
                  "", "| leg | slip | slope° |", "|---|---|---|"]
        for leg in slipped:
            lines.append(f"| {leg['leg']} | {leg['slip']:.3f} | {leg['slope_deg']:.2f} |")
    else:
        lines.append("- none (every drive leg held traction on this route)")

    lines += ["",
              "## Divergence (seen vs actual)",
              f"- energy divergence (true vs nominal): {d['energy_divergence_J']:.1f} J"]
    mc = d.get("map_channel")
    if mc:
        lines.append(f"- map channel: coverage {mc.get('coverage', 0):.2f}, "
                     f"mean uncertainty {mc.get('mean_uncertainty_m', 0):.2f} m")
    return "\n".join(lines)


def persist_summary(s: Session) -> str:
    from stewie.specs import config as CFG
    d = os.path.join(CFG.data_dir(), "sessions")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"summary_{s.session_id}.md")
    open(path, "w").write(summary_markdown(s))
    return path


def scorecard_record(s: Session) -> dict:
    """TR-01: the durable per-session scorecard record (PRD §27.2.E A-board). One JSON object that
    carries the public trainee board, the director-only truth divergence, and the makespan-vs-optimal
    block, keyed by session id. This is the artifact that OUTLIVES the in-memory session (M-09
    eviction), so a trainer can review a finished run after the live store has dropped it."""
    sc = s.scorecard()
    mk = sc["public"]
    return {
        "session_id": s.session_id,
        "profile": s.profile_name,
        "objective": s.objective,
        "public": sc["public"],
        "truth": sc["truth"],
        "makespan": {"makespan_s": mk["makespan_s"], "optimal_s": mk["optimal_s"],
                     "makespan_ratio": mk["makespan_ratio"]},
    }


def persist_scorecard(s: Session) -> str:
    """Write the scorecard record atomically to data_dir/sessions/scorecard_{sid}.json."""
    from stewie.server import atomicio
    from stewie.specs import config as CFG
    d = os.path.join(CFG.data_dir(), "sessions")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"scorecard_{s.session_id}.json")
    atomicio.write_json_atomic(path, scorecard_record(s), indent=2)
    return path


def load_scorecard_record(session_id: str) -> dict | None:
    """Read a persisted scorecard record by session id, or None if no record exists. The durable
    read path: serves a finished session's A-board even after live eviction (M-09)."""
    import json
    from stewie.specs import config as CFG
    path = os.path.join(CFG.data_dir(), "sessions", f"scorecard_{session_id}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)
