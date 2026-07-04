"""VT-06: the support polygon and the static stability margin are POSTURE-DEPENDENT.

Where ``test_dynamic_cg.py`` proves the vehicle-twin CG *moves* with arm posture and drum fill
(VT-05), this file binds that moving CG to the VT-06 acceptance: feeding it through the static
tip-over model (``stability.stability`` via ``DynamicCG.stability``) makes BOTH the effective
support polygon (the per-axis static-stability angle, ``ssa_pitch_deg``/``ssa_roll_deg``) AND the
tip margin (``margin_deg``) change with posture and load -- exactly what "compute posture-dependent
support polygon and static stability margin each step" asks for.

Two mechanisms are exercised, both already implemented (no new source -- this is the citing test):

  * ``dynamic_cg.dynamic_cg`` (VT-05) composes the VT-03 ``ArmJointState`` angles and the VT-04
    ``DrumSet`` per-drum fill into an absolute mass-weighted CG (``cg_z_m`` height, ``cg_x_m`` fore/aft
    offset), then ``DynamicCG.stability`` feeds ``cg_z_m -> cg_height_m`` and ``cg_x_m -> cg_dx_m`` into
    ``stability.stability``;
  * ``stability.stability`` turns those into a posture-dependent support polygon: a taller CG shrinks
    every SSA (the ``atan(half/cg_height)`` denominator grows), and a fore/aft offset shrinks the
    binding PITCH lever ``wheelbase/2 - |cg_dx|`` -- so the pitch-axis support extent narrows while the
    roll extent is untouched, and the remaining tip margin drops.

No synthetic data: masses/geometry are the sourced IPEx registry values (``vehicles``/``ipex_specs``:
dry 30 kg, stowed cg_height 0.21 m, 30 kg/cycle drum hold) composed with the real VT-03/VT-04 records;
the reference numbers below are computed from that same real path, not hand-fabricated.
"""
from __future__ import annotations

import pytest

from stewie.physics import stability as ST
from stewie.physics.drum_set import DrumSet
from stewie.physics.dynamic_cg import dynamic_cg
from stewie.specs import vehicles as V
from stewie.specs.arm_joint import JOINT_FRONT, JOINT_REAR, ArmJointState


def _joints(front_deg: float, rear_deg: float) -> tuple[ArmJointState, ArmJointState]:
    return (ArmJointState(joint=JOINT_FRONT, angle_deg=front_deg),
            ArmJointState(joint=JOINT_REAR, angle_deg=rear_deg))


# A fixed terrain attitude held constant across postures, so any change in the reported margin comes
# purely from the posture-driven CG (the support polygon), not from a changed tilt.
_PITCH_DEG = 8.0
_ROLL_DEG = 6.0


def test_vt06_working_posture_shrinks_support_polygon_and_margin():  # [REQ:VT-06]
    """Raising AND loading the front arm (a real DIG->carry posture) lifts the CG and leans it fore.
    Against the same terrain tilt this shrinks the pitch-axis support polygon (``ssa_pitch_deg``) and
    the static stability margin (``margin_deg``) versus the stowed, empty reference -- the posture
    dependence VT-06 requires. At the stowed/centred reference the pitch SSA equals the naive
    half-wheelbase SSA (the support polygon is un-shifted), giving the comparison a sourced anchor."""
    ipex = V.get_vehicle("ipex")

    stowed = dynamic_cg(*_joints(0.0, 0.0), DrumSet.for_ipex())
    s_stowed = stowed.stability(_PITCH_DEG, _ROLL_DEG)

    # anchor: the centred lumped CG reproduces the naive centred support polygon (no fore/aft shrink).
    naive_ssa_pitch = ST.ssa_deg(ipex.wheelbase_m / 2.0, ipex.cg_height_m)
    assert stowed.cg_dx_m == pytest.approx(0.0, abs=1e-9)
    assert s_stowed["ssa_pitch_deg"] == pytest.approx(naive_ssa_pitch)

    # the working posture: front arm high (70 deg) with both front drums full (the sourced 7.5 kg each).
    loaded = DrumSet.for_ipex()
    loaded.add(loaded.capacities[0], drum=0)
    loaded.add(loaded.capacities[1], drum=1)
    working = dynamic_cg(*_joints(70.0, 0.0), loaded)
    s_work = working.stability(_PITCH_DEG, _ROLL_DEG)

    # the CG genuinely moved (VT-05 substance): higher and offset fore/aft.
    assert working.cg_z_m > stowed.cg_z_m + 0.05
    assert abs(working.cg_dx_m) > abs(stowed.cg_dx_m) + 1e-3

    # posture-dependent SUPPORT POLYGON: the pitch-axis static-stability angle narrowed materially.
    assert s_work["ssa_pitch_deg"] < s_stowed["ssa_pitch_deg"] - 5.0
    # posture-dependent STATIC STABILITY MARGIN: fewer degrees of tilt remain before tip-over.
    assert float(s_work["margin_deg"]) < float(s_stowed["margin_deg"]) - 5.0
    # pitch binds on the IPEx gauge>wheelbase geometry, and the margin is still a real finite number.
    assert s_work["binding_axis"] == "pitch"
    assert float(s_work["margin_deg"]) > 0.0


def test_vt06_posture_alone_shrinks_margin_without_any_load():  # [REQ:VT-06]
    """Isolate POSTURE from LOAD: raise the front arm with the drums EMPTY. The arm-link mass alone
    lifts the CG (and offsets it fore/aft), so the support polygon (``ssa_pitch_deg``) and the margin
    both shrink versus stowed -- proving the dependence is on arm posture, not merely on carried mass."""
    empty = DrumSet.for_ipex()

    stowed = dynamic_cg(*_joints(0.0, 0.0), empty)
    raised = dynamic_cg(*_joints(70.0, 0.0), empty)

    s_stowed = stowed.stability(_PITCH_DEG, _ROLL_DEG)
    s_raised = raised.stability(_PITCH_DEG, _ROLL_DEG)

    assert raised.total_mass_kg == pytest.approx(stowed.total_mass_kg)   # no load added
    assert raised.cg_z_m > stowed.cg_z_m + 0.01                          # posture alone raised the CG
    assert s_raised["ssa_pitch_deg"] < s_stowed["ssa_pitch_deg"] - 2.0   # support polygon narrowed
    assert float(s_raised["margin_deg"]) < float(s_stowed["margin_deg"]) - 2.0


def test_vt06_foreaft_offset_narrows_only_the_pitch_support_polygon():  # [REQ:VT-06]
    """The support-polygon mechanism in ``stability.stability``: a fore/aft CG offset (``cg_dx_m``,
    what ``DynamicCG`` feeds from ``cg_x_m``) shortens the binding PITCH lever ``wheelbase/2 - |cg_dx|``
    and therefore the pitch SSA, while leaving the ROLL SSA untouched -- the support polygon shrinks
    anisotropically, exactly along the axis the offset acts on, and the margin follows."""
    ipex = V.get_vehicle("ipex")
    kw = dict(gauge_m=ipex.gauge_m, wheelbase_m=ipex.wheelbase_m, cg_height_m=ipex.cg_height_m)

    centred = ST.stability(_PITCH_DEG, _ROLL_DEG, cg_dx_m=0.0, **kw)
    offset = ST.stability(_PITCH_DEG, _ROLL_DEG, cg_dx_m=0.10, **kw)

    assert offset["ssa_pitch_deg"] < centred["ssa_pitch_deg"]            # pitch support extent shrank
    assert offset["ssa_roll_deg"] == pytest.approx(centred["ssa_roll_deg"])  # roll extent unchanged
    assert float(offset["margin_deg"]) < float(centred["margin_deg"])   # margin tightened with it
