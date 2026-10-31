"""Arm geometry and command wiring; no native-terrain excavation claim."""
from __future__ import annotations


import pytest


from stewie.specs.arm_state import ARM_DIG_DOWN_RAD, dig_engagement

def test_engagement_is_full_at_the_dig_posture_and_zero_when_stowed() -> None:
    """[REQ:PX-10] offset 0 == the dig posture (full bite); raising the arm to horizontal or beyond == no bite."""
    assert dig_engagement(0.0) == pytest.approx(1.0)              # the default posture digs, unchanged
    assert dig_engagement(-ARM_DIG_DOWN_RAD) == 0.0               # raised to stowed-horizontal -> off the ground
    assert dig_engagement(1.0) == 0.0                             # raised past stowed -> still no cut
    assert dig_engagement(-0.4) == pytest.approx(1.0)             # pushed further down -> still capped at full
    mid = dig_engagement(0.275)                                   # halfway up from the dig posture
    assert 0.0 < mid < 1.0 and mid == pytest.approx(0.5, abs=1e-6)
    assert dig_engagement(float("nan")) == 0.0                    # a poisoned command never licenses a cut


def test_godot_rig_mirrors_the_python_arm_constants() -> None:
    """[REQ:PX-10] The arm numbers now live in BOTH `stewie/specs/arm_state.py` (the authority, which the
    dig gate reads) and `stewie/godot/viz2_root.gd` (the render rig, which poses the joint and clamps the
    operator's deltas). If those drift, the pictured arm and the arm the physics gates on stop being the
    same arm -- and a rover would appear stowed while still cutting. Exactly the class of contradiction
    that produced the double-Lyasko bug (PX-08), so pin it."""
    import re
    from pathlib import Path

    from stewie.specs.arm_state import ARM_DIG_DOWN_RAD, ARM_OFFSET_MAX_RAD, ARM_OFFSET_MIN_RAD

    gd = (Path(__file__).resolve().parents[1] / "godot" / "viz2_root.gd").read_text(encoding="utf-8")

    def _const(name: str) -> float:
        m = re.search(rf"^const {name} *:= *(-?[\d.]+)", gd, re.M)
        assert m, f"{name} is missing from viz2_root.gd -- the rig no longer declares the arm band"
        return float(m.group(1))

    assert _const("ARM_DIG_DOWN") == pytest.approx(ARM_DIG_DOWN_RAD), \
        "the render rig's dig posture drifted from arm_state.ARM_DIG_DOWN_RAD (the gate's reference)"
    assert _const("ARM_OFFSET_MIN") == pytest.approx(ARM_OFFSET_MIN_RAD)
    assert _const("ARM_OFFSET_MAX") == pytest.approx(ARM_OFFSET_MAX_RAD)


def test_the_rig_actually_forwards_the_arm_pose_to_the_authority() -> None:
    """[REQ:PX-10] The gate is worthless if the rig never tells the runtime where the arm is -- which was
    precisely the bug (the offsets never left Godot). Pin the wiring: the rig calls send_arm, and the
    client speaks the `arm` command the runtime ingests."""
    from pathlib import Path
    gdir = Path(__file__).resolve().parents[1] / "godot"
    root = (gdir / "viz2_root.gd").read_text(encoding="utf-8")
    client = (gdir / "viz2_drive_client.gd").read_text(encoding="utf-8")
    assert "send_arm(" in root, "viz2_root.gd no longer forwards the arm pose to the runtime"
    assert 'func send_arm(' in client and '"cmd": "arm"' in client, \
        "the drive client no longer speaks the `arm` command the runtime gates the dig on"
