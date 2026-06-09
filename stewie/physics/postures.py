"""IPEx/RASSOR reconfigurable-morphology postures (data-driven; terrain_authority/data/ipex_postures.json).

The producer owns the vehicle model; the Godot 8-camera rig and the kinematics/stability layer read
these so a posture transform (MEERKAT/IRON_CROSS/COBRA/...) faithfully changes the rendered observation
geometry -- the dissertation P2 hypothesis (posture changes observability). Joint angles + chassis lift
are [ASSUMPTION] geometric calibration targets, NOT measured flight values: edit the JSON to update.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from stewie.physics import posture_kinematics as pk

_PATH = os.path.join(os.path.dirname(__file__), "data", "ipex_postures.json")
# arm angles are the editable source of truth; chassis_lift/camera_vantage are COMPUTED from them by
# posture_kinematics (so the sim angle faithfully drives the height -- they cannot diverge).
_REQUIRED = ("arm_front_pitch_rad", "arm_back_pitch_rad", "stability", "provenance")


@dataclass(frozen=True)
class Posture:
    name: str
    arm_front_pitch_rad: float
    arm_back_pitch_rad: float
    chassis_lift_m: float
    camera_vantage_m: float
    stability: str
    provenance: str
    description: str = ""


def load_postures(path: str = _PATH) -> dict:
    with open(path) as f:
        doc = json.load(f)
    out = {}
    for name, p in doc["postures"].items():
        missing = [k for k in _REQUIRED if k not in p]
        if missing:
            raise ValueError(f"posture {name} missing required fields {missing}")
        af, ab = float(p["arm_front_pitch_rad"]), float(p["arm_back_pitch_rad"])
        lift = pk.chassis_lift_m(af, ab)                  # COMPUTED from arm angles (faithful), not the JSON constant
        for k_json in ("chassis_lift_m", "camera_vantage_m"):
            if k_json in p and abs(float(p[k_json]) - lift) > 0.02:
                # audit M32: the authored constant was silently IGNORED. The FK value is the design
                # truth (see the comment above), so a contradicting JSON field is SURFACED as a
                # warning -- loud enough for the operator, without failing a load on legacy data.
                import warnings
                warnings.warn(f"posture {name}: authored {k_json}={p[k_json]} contradicts the "
                              f"FK-computed {lift:.3f} m (>2 cm); the FK value is used",
                              stacklevel=2)
        out[name] = Posture(name=name, description=str(p.get("description", "")),
                            arm_front_pitch_rad=af, arm_back_pitch_rad=ab,
                            chassis_lift_m=lift, camera_vantage_m=lift,
                            stability=str(p["stability"]), provenance=str(p["provenance"]))
    return out


def get_posture(name: str, path: str = _PATH) -> Posture:
    ps = load_postures(path)
    if name not in ps:
        raise KeyError(f"unknown posture {name!r}; known: {sorted(ps)}")
    return ps[name]
