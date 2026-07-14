"""[REQ:PX-13] The live dig engages BOTH counter-rotating drums, so the net chassis reaction is ~0.

WHY THIS FILE EXISTS. The sim modelled HALF THE MACHINE. `_drum_rc()` resolves only the FRONT drum, so
`_apply_dig` cut at one footprint and billed the chassis the FULL draft (`F = tau/r`) -- which is the CORRECT
answer for a single-front-drum dig, and the WRONG vehicle. The real RASSOR/IPEx digs with BOTH bucket drums
counter-rotating; that is *why* it has two of them. Per KSC-TOPS-7 the two horizontal reactions are equal and
opposite, so the pair nets ~0 -- and in 1/6 g that cancellation is not an optimisation, it is the only way the
rover can react the digging force at all. A 30 kg-class vehicle simply does not have the weight to shove back.

So today's sim pushes the rover backward with a force the real machine is BUILT to cancel, and that false
force flows into traction, slip and energy on EVERY dig tick. It is a prerequisite for the training rows
(PX-14 closed-loop trenching, TR-02 the distilled policy), not a polish item: a policy trained against it
learns to compensate for a reaction that does not exist on the real vehicle.

The back drum was a DEAD DOF. `_arm_back_offset_rad` was set, INGESTED from the operator, and published as
telemetry -- and never reached physics. That is PX-10's cosmetic-arm bug again, on the other arm. Here the
back arm becomes authoritative exactly as PX-10 made the front arm authoritative: it gates its own drum's cut,
so stowing it removes that drum's mass AND breaks the cancellation. The reaction must go to ~0 for the RIGHT
REASON (two drums are actually cutting), never because a term was zeroed.

WHAT DOUBLES AND WHAT DOES NOT (the arithmetic that is easy to get backwards -- I did, at first):
`DRUM_CAPACITY_KG` is PER DRUM ("Avg total regolith collected per drum", Schuler 2022 Table 3 [BDSCALE]).
Two drums cut two footprints, so mass-in doubles -- but the vehicle also holds twice as much, so
PASSES-TO-FULL IS UNCHANGED. What actually doubles is THROUGHPUT: every haul carries 2x the regolith. That
is the real reason the vehicle has two drums, and it is self-consistent with PX-12 (a dump pass discharges
through both drums' scoops, so the quantum doubles too and passes-to-empty is likewise unchanged).

A SOURCED TENSION THIS SURFACES, DELIBERATELY UNCLAMPED. With two drums the vehicle hold is 2x per-drum:
small 7.60 / medium 14.60 / large 49.96 kg. PX-09 asserts every hold sits inside the 30 kg/cycle RDS
envelope "by construction" -- and for the LARGE drum that is now FALSE. It is also a category error that
predates this row: `ipex_specs` says plainly "IPEx uses the small..medium range; the large drum is the
RASSOR 2.0 drum", so the IPEx RDS envelope never applied to it. The test below ASSERTS the breach rather than
hiding it behind a silent clamp, because a spec mismatch you can see is worth more than one you cannot.
"""
from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest

from stewie.runtime.viz2_runtime import Viz2Runtime
from stewie.specs.arm_state import ARM_DIG_DOWN_RAD, net_dig_reaction_n
from stewie.specs.ipex_specs import DRUM_CAPACITY_KG, REGOLITH_PER_CYCLE_KG

_SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "samples", "lunar_dem")
SFS = os.path.join(_SAMPLES, "haworth_sfs_2km_1m")
pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="real Haworth SfS bundle not on disk")

STOW = -ARM_DIG_DOWN_RAD          # the offset that returns the arm to stowed (engagement 0)


def _spawn() -> tuple[float, float]:
    from stewie.physics.worksite import coarse_base_from_bundle
    base, meta = coarse_base_from_bundle(SFS)
    wb = meta["world_bounds_m"]
    return (float(wb["x0"]) + base.width * meta["grid"]["cell_m"] * 0.5,
            float(wb["y0"]) + base.height * meta["grid"]["cell_m"] * 0.5)


def _runtime(tmp: str, drum: str = "small") -> Viz2Runtime:
    return Viz2Runtime(SFS, session_dir=tmp, fine_cell_m=0.05, start_xy=_spawn(), drum=drum)


def _dig_once(tmp: str, front: float, back: float) -> dict:
    rt = _runtime(tmp)
    try:
        rt._arm_front_offset_rad, rt._arm_back_offset_rad = front, back
        dirty = rt._apply_dig()
        return {"reaction": float(rt._last_dig_reaction_n), "moved": float(rt._last_dig_moved_kg),
                "dirty": dirty}
    finally:
        rt.stop()


def test_counter_rotating_drums_cancel_and_the_RESIDUAL_IS_EXACTLY_THE_DRAFT_DIFFERENCE() -> None:
    """[REQ:PX-13] THE REQUIREMENT, and the strongest form it can take.

    Both drums cutting -> the horizontal reactions are equal and OPPOSITE (KSC-TOPS-7), so the pair nets
    ~0 instead of dumping the full draft on the chassis. On a REAL, uneven lunar surface it does NOT cancel
    to exactly zero, and pretending it does would be the lie: the two drums bite different material, so the
    leftover is a genuine force the chassis feels. That gives an EXACT prediction we can gate on:

        reaction(both)  ==  | draft(front only)  -  draft(back only) |

    If the signs were wrong (or a term were simply zeroed to make a test pass), this identity would not
    hold -- it is much harder to fake than `< epsilon`. Measured on the real Haworth SfS bundle:
        front only 1.970 N | back only 1.691 N | both 0.279 N  ==  |1.970 - 1.691|   -> an 86% cancellation
    and the mass adds: 0.387 + 0.335 = 0.722 kg (two drums cut two footprints)."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b, \
            tempfile.TemporaryDirectory() as c:
        both = _dig_once(a, 0.0, 0.0)
        front = _dig_once(b, 0.0, STOW)
        back = _dig_once(c, STOW, 0.0)

    assert both["dirty"], "the symmetric dig moved nothing -- the test premise is broken"
    assert front["reaction"] > 1.0 and back["reaction"] > 1.0, "a lone drum must feel a real draft"

    # THE IDENTITY: the counter-rotating pair leaves exactly the DIFFERENCE of the two drafts.
    assert both["reaction"] == pytest.approx(abs(front["reaction"] - back["reaction"]), rel=1e-6, abs=1e-6), (
        f"both-drum reaction {both['reaction']:.4f} N is not the signed sum of the two drafts "
        f"(front {front['reaction']:.4f}, back {back['reaction']:.4f}) -- the counter-rotation is wrong")

    # AND THE CANCELLATION IS REAL, not a rounding artefact: the chassis feels a small fraction of a lone
    # drum's draft. (This is the whole reason IPEx has two drums: in 1/6 g it cannot react the full draft.)
    assert both["reaction"] < 0.25 * front["reaction"], (
        f"the pair left {both['reaction']:.3f} N against a lone drum's {front['reaction']:.3f} N -- that is "
        "not a cancellation")

    # and BOTH drums genuinely cut: the mass is the sum of the two single-drum passes.
    assert both["moved"] == pytest.approx(front["moved"] + back["moved"], rel=1e-6), (
        f"both-drum dig moved {both['moved']:.4f} kg, not the sum of front {front['moved']:.4f} + back "
        f"{back['moved']:.4f} -- one of the drums is not really cutting")


def test_a_single_engaged_drum_still_nets_the_full_draft() -> None:
    """[REQ:PX-13] The cancellation must happen for the RIGHT REASON. Stow the BACK arm: only the front
    drum cuts, so there is nothing to cancel against and the chassis takes the full F = tau/r. If this
    passes trivially, the implementation merely zeroed a term instead of modelling two drums."""
    with tempfile.TemporaryDirectory() as d:
        rt = _runtime(d)
        try:
            rt._arm_front_offset_rad = 0.0     # front digs
            rt._arm_back_offset_rad = STOW     # back stowed -> engagement 0 -> does not cut
            assert rt._apply_dig(), "the front-only dig moved nothing -- the test premise is broken"
            assert rt._last_dig_reaction_n > 1.0, (
                f"a front-only dig netted {rt._last_dig_reaction_n:.3f} N; with one drum cutting there is "
                "no counter-rotation to cancel it, so the chassis must take the full draft")
        finally:
            rt.stop()


def test_the_back_arm_is_physical_and_gates_its_own_drum() -> None:
    """[REQ:PX-13] The back arm was a DEAD DOF (set, ingested, telemetered -- and never read by physics).
    Stowing it must remove ITS drum's mass, exactly as PX-10 made the front arm authoritative."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        both, front_only = _runtime(a), _runtime(b)
        try:
            both._arm_front_offset_rad = 0.0
            both._arm_back_offset_rad = 0.0
            both._apply_dig()

            front_only._arm_front_offset_rad = 0.0
            front_only._arm_back_offset_rad = STOW
            front_only._apply_dig()

            assert float(both.ws.inventory_kg) > float(front_only.ws.inventory_kg) + 1e-6, (
                f"both-drum dig booked {both.ws.inventory_kg:.3f} kg vs front-only "
                f"{front_only.ws.inventory_kg:.3f} kg -- the back arm still does not gate its own cut")
        finally:
            both.stop(); front_only.stop()


def test_both_drums_cut_two_separate_footprints() -> None:
    """[REQ:PX-13] Two drums means TWO contact patches (front ~+0.40 m ahead, back ~-0.40 m behind), not one
    box counted twice. Assert the terrain is disturbed in two disjoint regions straddling the pose."""
    with tempfile.TemporaryDirectory() as d:
        rt = _runtime(d)
        try:
            rt._arm_front_offset_rad = 0.0
            rt._arm_back_offset_rad = 0.0
            before = rt.ws._require_fine().derive_height().copy()
            rt._apply_dig()
            after = rt.ws._require_fine().derive_height()

            cut = (before - after) > 1e-6                      # cells that lost material
            assert cut.any(), "nothing was cut"
            rows = np.flatnonzero(cut.any(axis=1))
            cols = np.flatnonzero(cut.any(axis=0))
            # the two boxes are ~0.80 m apart centre-to-centre; at 5 cm cells that is ~16 cells, so the
            # disturbed extent along the travel axis must span well beyond one drum-width box.
            span = max(rows.max() - rows.min(), cols.max() - cols.min()) + 1
            one_box = 2 * rt.dig_half_cells + 1
            assert span > one_box + 2, (
                f"the cut spans only {span} cells (one drum box is {one_box}); a two-drum dig must disturb "
                "two separate patches straddling the pose, not a single footprint")
        finally:
            rt.stop()


def test_the_two_drum_vehicle_holds_twice_a_drum_and_the_large_drum_breaches_the_rds_envelope() -> None:
    """[REQ:PX-13] DRUM_CAPACITY_KG is PER DRUM [BDSCALE], so a two-drum vehicle holds 2x. Passes-to-full is
    therefore UNCHANGED (mass-in doubles AND the tank doubles); what doubles is THROUGHPUT.

    And the consequence we refuse to hide: at 2x, the LARGE drum's vehicle hold (49.96 kg) EXCEEDS the 30
    kg/cycle RDS envelope that PX-09 claims holds 'by construction'. That envelope is an IPEx spec and the
    large drum is RASSOR 2.0's ('IPEx uses the small..medium range'), so applying it was always a category
    error. Assert the mismatch so it stays visible instead of being silently clamped."""
    with tempfile.TemporaryDirectory() as d:
        rt = _runtime(d, drum="small")
        try:
            assert rt._vehicle_capacity_kg == pytest.approx(2.0 * DRUM_CAPACITY_KG["small"])
        finally:
            rt.stop()

    within = {k: 2.0 * v for k, v in DRUM_CAPACITY_KG.items() if 2.0 * v <= REGOLITH_PER_CYCLE_KG}
    breaches = {k: 2.0 * v for k, v in DRUM_CAPACITY_KG.items() if 2.0 * v > REGOLITH_PER_CYCLE_KG}
    assert set(within) == {"small", "medium"}, f"IPEx's own drums must sit inside the RDS envelope: {within}"
    assert set(breaches) == {"large"}, (
        "the large (RASSOR 2.0) drum is the ONLY one that breaches the 30 kg/cycle IPEx RDS envelope at two "
        f"drums; if this changed, the sourced premise moved: {breaches}")


def test_the_reaction_model_itself_still_distinguishes_one_drum_from_two() -> None:
    """[REQ:PX-13] Pin the seam the runtime leans on. `net_dig_reaction_n` is the ONE authority for the
    cancellation; if it ever stopped distinguishing the configurations, every gate above would pass
    vacuously while the physics silently went wrong."""
    f_one = abs(net_dig_reaction_n(100.0 * 0.25, 0.25, drums=("front",)))
    f_two = abs(net_dig_reaction_n(100.0 * 0.25, 0.25, drums=("front", "back")))
    assert f_one == pytest.approx(100.0), "a single drum must net the full F = tau/r"
    assert f_two == pytest.approx(0.0, abs=1e-9), "counter-rotating drums must cancel"
