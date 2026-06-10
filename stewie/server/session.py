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

    @classmethod
    def run(cls, mission, *, profile: str = "ideal", dem=None, dem_origin=(0.0, 0.0),
            algorithm: str = "auto", objective: str = "time", seed: int = 0) -> "Session":
        from lode import autonomy as AUT
        prof = tl.load_profile(os.path.join(_PROFILES, f"{profile}.json"))
        out = AUT.run_closed_loop(mission, dem=dem, dem_origin=dem_origin,
                                  algorithm=algorithm, objective=objective)
        link = tl.TelemetryLink(prof, seed=seed)
        sess = cls(session_id=secrets.token_hex(8), profile_name=profile, record=out, link=link)
        for i, leg in enumerate(out["legs"]):
            delivered = link.try_send(_LEG_PACKET_BYTES, t_s=i * _LEG_PERIOD_S)
            if delivered:
                sess.operator_legs.append(
                    {k: v for k, v in leg.items() if k not in TRUTH_FIELDS})
        return sess

    def operator_view(self) -> dict:
        return {
            "session_id": self.session_id,
            "legs": self.operator_legs,                       # only what the link delivered
            "n_legs_total": len(self.record["legs"]),
            "completed": self.record["completed"],
            "recharges": self.record["recharges"],
            "link": {"profile": self.profile_name, "stats": dict(self.link.stats)},
        }

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
        }


_SESSIONS: dict[str, Session] = {}


def start(mission, **kw) -> Session:
    s = Session.run(mission, **kw)
    _SESSIONS[s.session_id] = s
    return s


def get(session_id: str) -> Session | None:
    return _SESSIONS.get(session_id)


def summary_markdown(s: Session) -> str:
    """The per-run mission summary (beta B4.2): route, energy, link behaviour, divergence."""
    d = s.debrief_view()
    lines = [f"# Mission summary — session {s.session_id}",
             "",
             f"- completed: {d['completed']} · legs: {d['n_legs_total']} "
             f"(operator received {d['operator_received']})",
             f"- recharges: {s.record['recharges']} · replans: {s.record['replans']}",
             f"- energy divergence (true vs nominal): {d['energy_divergence_J']:.1f} J",
             f"- link profile: {s.profile_name} · stats: {dict(s.link.stats)}",
             f"- operator missed legs: {d['operator_missed_legs'] or 'none'}",
             "", "| leg | nominal J | true J | SoC |", "|---|---|---|---|"]
    for leg in s.record["legs"]:
        lines.append(f"| {leg['leg']} | {leg['nominal_J']:.0f} | {leg['true_J']:.0f} "
                     f"| {leg['soc']:.2f} |")
    mc = d.get("map_channel")
    if mc:
        lines += ["", f"map channel: coverage {mc.get('coverage', 0):.2f}, "
                       f"mean uncertainty {mc.get('mean_uncertainty_m', 0):.2f} m"]
    return "\n".join(lines)


def persist_summary(s: Session) -> str:
    from stewie.specs import config as CFG
    d = os.path.join(CFG.data_dir(), "sessions")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"summary_{s.session_id}.md")
    open(path, "w").write(summary_markdown(s))
    return path
