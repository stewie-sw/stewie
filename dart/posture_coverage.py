"""SN-08b: the full posture x load feasibility matrix (every posture, loaded AND unloaded).

The coverage the single-posture selector skipped: evaluate EVERY named posture under unloaded,
front-drum-loaded, rear-drum-loaded, and both-loaded conditions. The honest finding it surfaces:
one-sided postures (COBRA / REVERSE_COBRA / MEERKAT_1S) that are feasible UNLOADED become
INFEASIBLE when the OPPOSING drum is loaded -- the cross-load tip. Symmetric raises (IRON_CROSS)
are load-robust but have the smallest unloaded margin. Real posture_a3 kinematics + stability.
"""
from __future__ import annotations

from stewie.physics import posture_a3 as P

#: a meaningful drum load to stress stability -- ~2/3 of the 30 kg/cycle capacity per end.
LOAD_KG = 20.0
LOAD_CONDITIONS = ("unloaded", "front_loaded", "rear_loaded", "both_loaded")


def _fills(condition: str, load_kg: float):
    return {"unloaded": (0.0, 0.0), "front_loaded": (load_kg, 0.0),
            "rear_loaded": (0.0, load_kg), "both_loaded": (load_kg, load_kg)}[condition]


def posture_load_matrix(*, load_kg: float = LOAD_KG, min_margin_m: float = 0.05) -> dict:
    """{posture: {condition: {margin_m, feasible, lift_m, parallax_m}}} over ALL postures x ALL
    load conditions. parallax_m is the vertical baseline vs TRANSIT (the active-morphology gain)."""
    transit = P.posture("TRANSIT")
    out: dict = {}
    for name in P.POSTURES:
        ps = P.posture(name)
        row = {}
        for cond in LOAD_CONDITIONS:
            ff, fr = _fills(cond, load_kg)
            margin = P.stability_margin_m(ps, fill_front_kg=ff, fill_rear_kg=fr)
            row[cond] = {"margin_m": round(margin, 4),
                         "feasible": bool(ps.within_mech_limit and margin >= min_margin_m),
                         "lift_m": round(ps.chassis_lift_m, 4),
                         "parallax_m": round(P.parallax_baseline_m(transit, ps), 4)}
        out[name] = row
    return out


def feasible_postures(condition: str, *, load_kg: float = LOAD_KG, min_margin_m: float = 0.05) -> list:
    """The postures that stay feasible under one load condition (the usable viewpoint set)."""
    m = posture_load_matrix(load_kg=load_kg, min_margin_m=min_margin_m)
    return [name for name, row in m.items() if row[condition]["feasible"]]
