"""[REQ:PX-10] The front-arm DOF is PHYSICAL: where the operator puts the arm gates what the drum can cut.
On the REAL Haworth SfS 1 m bundle, through the real Viz2Runtime (constructed, actor loop not started).

WHY THIS FILE EXISTS. The arm was a cosmetic render offset. `viz2_root.gd` kept `_arm_front_offset` purely
to pose the render joint, never told the runtime about it, and `_apply_dig` cut its full `dig_depth_m`
regardless -- so a rover driving with its drum RAISED FOR TRANSPORT still carved a trench under itself, and
the operator's arm control was a lie: it moved the picture and nothing else. For a HITL command surface
(now publicly reachable via RT-06) that is the wrong kind of wrong -- the displayed vehicle state and the
world state disagreed.

The gate: effective pitch = ARM_DIG_DOWN_RAD + the operator's offset (exactly what the render rig poses),
engagement 1.0 at the dig posture and 0.0 at/above stowed. So:
  * offset 0 IS the dig posture -> engagement 1.0 -> the DEFAULT dig is byte-for-byte unchanged (this gate
    cannot silently break every existing dig, and a test below pins that);
  * arm raised for transport -> engagement 0 -> the dig moves NO mass at all.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.runtime.viz2_runtime import Viz2Runtime
from stewie.specs.arm_state import ARM_DIG_DOWN_RAD, dig_engagement

_SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "samples", "lunar_dem")
SFS = os.path.join(_SAMPLES, "haworth_sfs_2km_1m")
pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="real Haworth SfS bundle not on disk")


def _runtime(tmp_path) -> Viz2Runtime:
    from stewie.physics.worksite import coarse_base_from_bundle
    _base, meta = coarse_base_from_bundle(SFS)
    wb = meta["world_bounds_m"]
    cx = float(wb["x0"]) + _base.width * meta["grid"]["cell_m"] * 0.5
    cy = float(wb["y0"]) + _base.height * meta["grid"]["cell_m"] * 0.5
    return Viz2Runtime(SFS, session_dir=str(tmp_path), fine_cell_m=0.05, start_xy=(cx, cy))


def _grid_kg(rt: Viz2Runtime) -> float:
    return float(rt.ws._require_fine().grid_mass())


# ── the engagement model itself ───────────────────────────────────────────────────────────────────
def test_engagement_is_full_at_the_dig_posture_and_zero_when_stowed() -> None:
    """[REQ:PX-10] offset 0 == the dig posture (full bite); raising the arm to horizontal or beyond == no bite."""
    assert dig_engagement(0.0) == pytest.approx(1.0)              # the default posture digs, unchanged
    assert dig_engagement(-ARM_DIG_DOWN_RAD) == 0.0               # raised to stowed-horizontal -> off the ground
    assert dig_engagement(1.0) == 0.0                             # raised past stowed -> still no cut
    assert dig_engagement(-0.4) == pytest.approx(1.0)             # pushed further down -> still capped at full
    mid = dig_engagement(0.275)                                   # halfway up from the dig posture
    assert 0.0 < mid < 1.0 and mid == pytest.approx(0.5, abs=1e-6)
    assert dig_engagement(float("nan")) == 0.0                    # a poisoned command never licenses a cut


# ── the gate, on the real runtime + real terrain ──────────────────────────────────────────────────
def test_arm_raised_for_transport_cuts_nothing(tmp_path) -> None:
    """[REQ:PX-10/PX-13] THE REQUIREMENT: drums up for transport => the dig removes NO mass from the world.

    UPDATED BY PX-13, and the change is the point. This test used to raise only the FRONT arm and expect a
    zero cut -- which was right for a sim that modelled ONE drum, and wrong for the vehicle. The real
    RASSOR/IPEx has TWO bucket drums on independent arms, and PX-13 made each arm gate its own drum. So a
    hauling rover stows BOTH: raising the front alone leaves the BACK drum in the ground, still carving.
    That is not a regression, it is the machine. Loosening the assertion would have hidden a real drum."""
    rt = _runtime(tmp_path)
    rt._ingest_arm({"front": -ARM_DIG_DOWN_RAD, "back": -ARM_DIG_DOWN_RAD})   # BOTH arms -> stowed-horizontal
    assert rt._arm_engagement("front") == 0.0
    assert rt._arm_engagement("back") == 0.0

    before = _grid_kg(rt)
    dirty = rt._apply_dig()
    after = _grid_kg(rt)
    assert dirty == [], "a transport-posture rover still carved the terrain"
    assert after == pytest.approx(before, abs=1e-9), "mass left the grid with the drums out of the ground"
    assert float(rt.ws.inventory_kg) == 0.0, "the drums booked regolith while raised for transport"


def test_stowing_only_ONE_arm_still_digs_with_the_other(tmp_path) -> None:
    """[REQ:PX-13] The corollary, asserted so nobody 'fixes' the test above by re-collapsing the two drums
    into one: with the FRONT arm stowed the BACK drum is still in the ground and MUST still cut. Two arms,
    two drums, two independent gates."""
    rt = _runtime(tmp_path)
    rt._ingest_arm({"front": -ARM_DIG_DOWN_RAD, "back": 0.0})      # front stowed, back at the dig posture
    assert rt._arm_engagement("front") == 0.0
    assert rt._arm_engagement("back") > 0.0

    before = _grid_kg(rt)
    dirty = rt._apply_dig()
    after = _grid_kg(rt)
    assert dirty, "the back drum is in the ground and cut nothing -- its arm gate is not wired"
    assert after < before - 1e-9, "the back drum reported a dirty region but removed no mass"
    assert float(rt.ws.inventory_kg) > 0.0, "the back drum cut terrain but booked no regolith"
    # exactly ONE drum cut -> exactly one dirty box (the front is stowed and must contribute nothing)
    assert len(dirty) == 1, f"one arm is stowed, so only one drum may cut; got {len(dirty)} boxes"


def test_default_posture_digs_exactly_as_before(tmp_path) -> None:
    """[REQ:PX-10] The gate must not silently break the normal dig: with no arm command the offset is 0,
    which IS the dig posture, so a default dig still cuts (engagement 1.0)."""
    rt = _runtime(tmp_path)
    assert rt._arm_engagement() == pytest.approx(1.0)             # untouched arm == dig posture
    before = _grid_kg(rt)
    dirty = rt._apply_dig()
    assert dirty, "the default dig stopped working"
    assert _grid_kg(rt) < before, "the default dig moved no mass"
    assert float(rt.ws.inventory_kg) > 0.0


def test_partly_raised_arm_takes_a_proportionally_shallower_bite(tmp_path) -> None:
    """[REQ:PX-10] Between the two postures the arm MODULATES the cut: a half-raised arm takes a shallower
    bite than a fully-lowered one (and both are still bounded by the PX-09 caps)."""
    rt_full = _runtime(tmp_path / "full")
    rt_half = _runtime(tmp_path / "half")
    rt_half._ingest_arm({"front": 0.275})                         # half-way up -> engagement 0.5

    d_full = _grid_kg(rt_full) - (rt_full._apply_dig(), _grid_kg(rt_full))[1]
    d_half = _grid_kg(rt_half) - (rt_half._apply_dig(), _grid_kg(rt_half))[1]

    assert d_full > 0.0 and d_half > 0.0, "one of the digs moved nothing"
    assert d_half < d_full, (
        f"a half-raised arm cut {d_half:.3f} kg, no less than the fully-lowered {d_full:.3f} kg -- "
        "the arm is not modulating the bite")


def test_arm_command_is_bounded_and_poison_resistant(tmp_path) -> None:
    """[REQ:PX-10/PX-13] The arm command comes off a PUBLIC console (RT-06). A non-finite or wildly
    out-of-range angle must never license a deeper cut -- it clamps to the rig's travel, and NaN refuses to
    dig. Both arms are commandable, so both must be bounded (PX-13 made the back arm PHYSICAL; an unbounded
    back arm would be exactly the hole the front one no longer has)."""
    rt = _runtime(tmp_path)
    rt._ingest_arm({"front": 1e9, "back": 1e9})                   # absurd raise on BOTH -> clamps, no cut
    assert rt._arm_engagement("front") == 0.0
    assert rt._arm_engagement("back") == 0.0
    assert rt._apply_dig() == []

    rt2 = _runtime(tmp_path / "nan")
    rt2._ingest_arm({"front": float("nan"), "back": float("nan")})   # poisoned -> refused, arms unchanged
    assert np.isfinite(rt2._arm_front_offset_rad)
    assert np.isfinite(rt2._arm_back_offset_rad)
    assert rt2._arm_engagement("front") == pytest.approx(1.0)     # the bad command was ignored, not applied
    assert rt2._arm_engagement("back") == pytest.approx(1.0)


# ── the render rig and the physics authority must agree on the arm ────────────────────────────────
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
