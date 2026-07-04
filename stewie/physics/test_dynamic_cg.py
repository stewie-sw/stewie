"""Tests for the posture- and fill-dependent centre of gravity (dynamic_cg.py) -- VT-05.

Analytic ground truth from the real sourced IPEx geometry/masses (vehicles/ipex_specs -> dry 30 kg,
stowed cg_height 0.21 m) composed with the VT-03 ArmJointState angles and the VT-04 DrumSet per-drum
fill. No synthetic data: the drum masses are the sourced 30 kg/cycle hold split across the four
bucket drums. The acceptance is that the CG MOVES with arm posture and with drum fill (a distributed
CG, not a static lumped one), and that it feeds the static tip-over model.
"""
from __future__ import annotations

import pytest

from stewie.physics import stability as ST
from stewie.physics.drum_set import DrumSet
from stewie.physics.dynamic_cg import DynamicCG, dynamic_cg
from stewie.specs import vehicles as V
from stewie.specs.arm_joint import JOINT_FRONT, JOINT_REAR, ArmJointState
from stewie.specs.arm_state import ArmState


def _joints(front_deg: float, rear_deg: float) -> tuple[ArmJointState, ArmJointState]:
    return (ArmJointState(joint=JOINT_FRONT, angle_deg=front_deg),
            ArmJointState(joint=JOINT_REAR, angle_deg=rear_deg))


def test_vt05_cg_moves_with_arm_posture_and_drum_fill():  # [REQ:VT-05]
    """VT-05: the vehicle-twin CG shifts with arm posture (VT-03) AND with per-drum fill (VT-04); it
    is NOT a static lumped CG. Stowed + empty reproduces the classic lumped CG (fore/aft centred at
    the sourced cg_height_m); raising an arm and filling a drum each move it."""
    ipex = V.get_vehicle("ipex")
    empty = DrumSet.for_ipex()

    base = dynamic_cg(*_joints(0.0, 0.0), empty)
    # stowed + empty == the static lumped CG: centred fore/aft, at the sourced stowed height.
    assert base.cg_x_m == pytest.approx(0.0, abs=1e-9)
    assert base.cg_z_m == pytest.approx(ipex.cg_height_m)
    assert base.total_mass_kg == pytest.approx(ipex.dry_mass_kg)

    # raise the FRONT arm (drums still empty): the arm-link mass moves -> CG shifts on BOTH axes.
    raised = dynamic_cg(*_joints(55.0, 0.0), empty)
    assert abs(raised.cg_x_m - base.cg_x_m) > 1e-3          # fore/aft moved
    assert raised.cg_z_m > base.cg_z_m + 1e-3              # and the CG rose

    # fill the FRONT drums at the stowed posture: the added regolith leans the CG fore/aft.
    loaded = DrumSet.for_ipex()
    loaded.add(loaded.capacities[0], drum=0)
    loaded.add(loaded.capacities[1], drum=1)
    filled = dynamic_cg(*_joints(0.0, 0.0), loaded)
    assert filled.front_drum_kg == pytest.approx(loaded.per_drum_fill[0] + loaded.per_drum_fill[1])
    assert filled.rear_drum_kg == pytest.approx(0.0)
    assert filled.cg_x_m > base.cg_x_m + 1e-2              # drum fill shifts the CG toward the front
    assert filled.total_mass_kg == pytest.approx(ipex.dry_mass_kg + loaded.total_fill)


def test_vt05_loaded_raised_arm_lifts_and_leans_the_cg():  # [REQ:VT-05]
    """A loaded drum RAISED on the front arm pulls the CG up and toward the front pivot -- strictly
    more than the same raised arm empty. This is the drum-as-ballast manoeuvre physics, now on the
    typed VT-03/VT-04 records."""
    empty = DrumSet.for_ipex()
    loaded = DrumSet.for_ipex()
    loaded.add(loaded.capacities[0], drum=0)
    loaded.add(loaded.capacities[1], drum=1)

    raised_empty = dynamic_cg(*_joints(55.0, 0.0), empty)
    raised_loaded = dynamic_cg(*_joints(55.0, 0.0), loaded)

    assert raised_loaded.cg_z_m > raised_empty.cg_z_m + 1e-2   # the raised load lifts the CG
    assert raised_loaded.cg_x_m > raised_empty.cg_x_m          # and leans it toward the front pivot


def test_vt05_reuses_arm_state_moment_engine():  # [REQ:VT-05]
    """The dynamic CG is the tested ArmState.cg_offset_m shift added to the stowed lumped reference --
    one moment model, not a divergent re-implementation. The shift (dynamic - stowed) must reproduce
    cg_offset_m exactly for the same angles + per-arm loads."""
    ipex = V.get_vehicle("ipex")
    drums = DrumSet.for_ipex()
    drums.add(drums.capacities[0], drum=0)          # front load only
    front_deg, rear_deg = 40.0, -25.0

    cg = dynamic_cg(*_joints(front_deg, rear_deg), drums)

    arm = ArmState(front_deg=front_deg, back_deg=rear_deg)
    dx, dz = arm.cg_offset_m(front_drum_kg=cg.front_drum_kg, back_drum_kg=cg.rear_drum_kg,
                             dry_mass_kg=ipex.dry_mass_kg)
    assert cg.cg_x_m == pytest.approx(dx)
    assert cg.cg_z_m - ipex.cg_height_m == pytest.approx(dz)


def test_vt05_feeds_static_stability_margin():  # [REQ:VT-05]
    """The payoff: the dynamic CG feeds stability.py (VT-06), so a loaded, raised, ASYMMETRIC posture
    reports a materially TIGHTER tip margin than the static lumped CG would -- the failure a lumped CG
    hides. Reuses stability.stability with this CG's height + fore/aft offset."""
    ipex = V.get_vehicle("ipex")
    loaded = DrumSet.for_ipex()
    loaded.add(loaded.capacities[0], drum=0)
    loaded.add(loaded.capacities[1], drum=1)
    cg = dynamic_cg(*_joints(70.0, 0.0), loaded)     # front drums full, front arm high, rear stowed

    static = ST.stability(0.0, 0.0, gauge_m=ipex.gauge_m, wheelbase_m=ipex.wheelbase_m,
                          cg_height_m=ipex.cg_height_m, cg_dx_m=0.0)
    dyn = cg.stability(0.0, 0.0)

    assert isinstance(cg, DynamicCG)
    assert cg.cg_dx_m == cg.cg_x_m                    # the stability-vocabulary alias
    # a high, front-heavy, loaded CG is closer to tipping than the centred lumped one.
    assert float(dyn["margin_deg"]) < float(static["margin_deg"]) - 1.0


def test_vt05_drum_split_and_joint_guards():  # [REQ:VT-05]
    """Four drums map two-per-arm (front {0,1}, rear {2,3}); the per-arm loads sum the right halves,
    and swapped joint roles are rejected loudly rather than silently mis-composed."""
    drums = DrumSet.for_ipex()
    drums.add(drums.capacities[2], drum=2)           # a REAR drum
    cg = dynamic_cg(*_joints(0.0, 0.0), drums)
    assert cg.rear_drum_kg == pytest.approx(drums.per_drum_fill[2])
    assert cg.front_drum_kg == pytest.approx(0.0)
    assert cg.cg_x_m < 0.0                            # a rear load leans the CG aft

    front = ArmJointState(joint=JOINT_FRONT, angle_deg=0.0)
    rear = ArmJointState(joint=JOINT_REAR, angle_deg=0.0)
    with pytest.raises(ValueError):
        dynamic_cg(rear, front, drums)               # front/rear swapped
