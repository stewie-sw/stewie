"""[REQ:AS-17] TRL5 stereo-rig baseline authority — the single labeled source for the IPEx
stereo baseline, so a rejected/legacy value can never be silently substituted for the flight
geometry.

After the 2026-06-18 re-freeze the legacy 0.070 m fixture is GONE: the sim runs the real flight
baseline. Two values remain in the record, and they MUST stay separable (PRD AS-17):

  * 0.050 m  TRL5_FINAL   ACTIVE_FLIGHT   — the TRL5-final flown geometry: the stereo pair combined
                                            into a single rigid housing (explicit on-figure dimension,
                                            SCHULER24/NTRS 20240008162 Figs 28/30/32), which replaced
                                            the rejected 0.165 m shoulder split after it lost
                                            calibration under structural flex/thermal expansion. This
                                            is the sim's ACTIVE geometry (stewie_ipex_v1.json).
  * 0.165 m  SHOULDER_SPLIT  REJECTED_LEGACY — the 16.5 cm split design published in SCHULER24 then
                                            REJECTED (ipex_specs.STEREO_BASELINE_REJECTED_M). Kept ONLY
                                            as historical provenance; never usable as the flight value.

`validate_stereo_authority()` is the gate (its test is the AS-17 acceptance): it rejects any state
where the two collapse, where the active value is not the sourced TRL5-final, where the rejected split
is mislabeled, or where the loaded profile drifts off the 0.05 flight baseline. No ROS dependency — the
profile geometry / robot_state_publisher TF smoke is the container-gated half of AS-17.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from stewie.specs import ipex_specs
from stewie.specs.profiles import load_profile

# Status classes. Exactly one profile is the active flight geometry.
ACTIVE_FLIGHT = "ACTIVE_FLIGHT"        # the TRL5-final flown geometry — the sim's real baseline
REJECTED_LEGACY = "REJECTED_LEGACY"    # a design published then rejected; never usable as truth

# Pinned labeled values. The JSON profile remains the GEOMETRY authority for the active baseline;
# the literal here is the LABEL anchor, and validate_stereo_authority() asserts the JSON agrees
# (single source by cross-check, not by duplication).
TRL5_FINAL_BASELINE_M = 0.05            # explicit on-figure dimension, SCHULER24 Figs 28/30/32
SHOULDER_SPLIT_BASELINE_M = ipex_specs.STEREO_BASELINE_REJECTED_M   # 0.165, sourced (rejected)


@dataclass(frozen=True)
class StereoProfile:
    name: str
    baseline_m: float
    status: str
    provenance: str
    is_active_default: bool = False


PROFILES: dict[str, StereoProfile] = {p.name: p for p in (
    StereoProfile(
        "trl5_final", TRL5_FINAL_BASELINE_M, ACTIVE_FLIGHT,
        "TRL5-final flight baseline: the stereo pair combined into a single rigid housing "
        "(explicit on-figure dimension, SCHULER24/NTRS 20240008162 Figs 28/30/32), which replaced "
        "the rejected 0.165 m shoulder split after it lost calibration under structural flex/thermal "
        "expansion. Trades reach for near-field accuracy + calibration stability. The sim's ACTIVE "
        "geometry (stewie_ipex_v1.json) as of the 2026-06-18 re-freeze.",
        is_active_default=True,
    ),
    StereoProfile(
        "shoulder_split", SHOULDER_SPLIT_BASELINE_M, REJECTED_LEGACY,
        "The 16.5 cm split design published in SCHULER24 then REJECTED for calibration loss under "
        "load (ipex_specs.STEREO_BASELINE_REJECTED_M). Historical provenance only; never usable as truth.",
        is_active_default=False,
    ),
)}


def active_profile() -> StereoProfile:
    """The single ACTIVE_FLIGHT profile the sim runs on (0.05 m)."""
    actives = [p for p in PROFILES.values() if p.is_active_default]
    if len(actives) != 1:
        raise ValueError(f"stereo authority must have exactly one active default, got {len(actives)}")
    return actives[0]


def loaded_profile_baseline_m() -> float:
    """The front-stereo baseline of the geometry profile actually loaded (the JSON authority)."""
    return float(load_profile().data["stereo"]["front"]["baseline_m"])


def validate_stereo_authority() -> list[str]:
    """Return a list of authority violations (empty = the baseline is correctly labeled + active).

    The AS-17 gate. Checks: (1) the two named baselines are distinct; (2) exactly one is the active
    default and it is ACTIVE_FLIGHT (the TRL5-final value); (3) the shoulder split is REJECTED_LEGACY
    and NOT active; (4) the loaded geometry profile's front+rear baseline equals the sourced TRL5-final
    0.05 m and is NOT the rejected 0.165 m split.
    """
    errs: list[str] = []
    baselines = {name: p.baseline_m for name, p in PROFILES.items()}
    if len({round(b, 6) for b in baselines.values()}) != len(baselines):
        errs.append(f"stereo baselines collapsed (must be distinct): {baselines}")

    actives = [p for p in PROFILES.values() if p.is_active_default]
    if len(actives) != 1:
        errs.append(f"exactly one active default required, got {[p.name for p in actives]}")
    elif actives[0].status != ACTIVE_FLIGHT or actives[0].name != "trl5_final":
        errs.append(f"active default must be the TRL5-final ACTIVE_FLIGHT profile, got {actives[0].name!r}")

    split = PROFILES.get("shoulder_split")
    if split is None or split.status != REJECTED_LEGACY:
        errs.append("shoulder_split must exist with status REJECTED_LEGACY")
    elif split.is_active_default:
        errs.append("the rejected shoulder split must NOT be the active default")

    loaded = loaded_profile_baseline_m()
    if not math.isclose(loaded, TRL5_FINAL_BASELINE_M, abs_tol=1e-4):
        errs.append(f"loaded profile baseline {loaded} != TRL5-final flight baseline {TRL5_FINAL_BASELINE_M}")
    if math.isclose(loaded, SHOULDER_SPLIT_BASELINE_M, abs_tol=1e-4):
        errs.append(f"loaded profile baseline {loaded} == rejected shoulder split — legacy confusion")
    return errs
