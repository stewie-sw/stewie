"""[REQ:PX-14] AutoDig-equivalent CLOSED-LOOP trench control: the bite is regulated from the drum-current
observable, and the trench terminates on drum-full via the sourced offload trigger.

WHY THIS FILE EXISTS. NASA's AutoDig (the semi-autonomous excavation routine for RASSOR -> IPEx) maintains
ground contact and REGULATES DIGGING DEPTH FROM THE DRUM MOTORS' CURRENT DRAW -- i.e. from how much soil the
drums are actually ingesting. STEWIE had the SENSOR and not the LOOP. `rassor_mass_model` grounds the exact
telemetry AutoDig closes on -- the Free-spinning Drum Current (mass proportional to steady current;
FDC_LINEAR_R2 = (0.989, 0.985), sourced from NTRS 20210022781) -- and can synthesise the current from
conserved drum mass and infer mass back with published error bars. But the live dig was a COMMANDED VERB
(`cmd == "dig"` -> `_apply_dig()`, a fixed depth): no controller, no feedback, no termination. And the runtime
did not even EXPOSE the drum-current reading -- another sourced model with nothing wired to it.

WHAT THIS ROW HONESTLY CAN AND CANNOT CLAIM. The conserved sim's density field is UNIFORM (measured: std
0.000 kg/m^3 over the fine window), so there is NO real density gradient to regulate a 'denser -> shallower
bite' against. Inventing one would be fabricated data. So this row does NOT claim density adaptation. What it
DOES claim is the loop the physics genuinely supports:

  * the bite is REGULATED to a target per-pass ingestion, read through the drum-current OBSERVABLE (with the
    FDC noise band) rather than the true conserved mass -- the point of the sensor is that a real rover has
    no load cell;
  * the trench TERMINATES on the drum-full condition via the sourced `should_offload` trigger, using the
    UPPER confidence bound so it never overfills even under sensor noise;
  * the regulated bite respects every sourced bound already in place -- PX-09 capacity + the <=50%
    anti-bridging cap, PX-10 the arm gate, PX-13 the two-drum reaction.

HONEST SCOPE: the proportional gain is [CALIB] -- AutoDig's gains are not published -- so the acceptance is
on the closed-loop BEHAVIOUR (the achieved ingestion tracks the setpoint through the sensor; a different
setpoint yields a different bite; it stops on full), NEVER on reproducing NASA's specific gains, which would
be fabrication. PRIOR ART, stated so this does not overclaim: NTRS 20210022218 (ICE-RASSOR *learning
excavation*) is NASA replacing the AutoDig PID trencher with deep RL; STEWIE cites the MASS paper (…781),
not that one.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from stewie.physics.rassor_mass_model import FDC_MPE_HALF_FULL
from stewie.runtime.viz2_runtime import Viz2Runtime

_SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "samples", "lunar_dem")
SFS = os.path.join(_SAMPLES, "haworth_sfs_2km_1m")
pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="real Haworth SfS bundle not on disk")


def _spawn() -> tuple[float, float]:
    from stewie.physics.worksite import coarse_base_from_bundle
    base, meta = coarse_base_from_bundle(SFS)
    wb = meta["world_bounds_m"]
    return (float(wb["x0"]) + base.width * meta["grid"]["cell_m"] * 0.5,
            float(wb["y0"]) + base.height * meta["grid"]["cell_m"] * 0.5)


def _rt(tmp: str, drum: str = "small") -> Viz2Runtime:
    return Viz2Runtime(SFS, session_dir=tmp, fine_cell_m=0.05, start_xy=_spawn(), drum=drum)


def test_the_runtime_EXPOSES_the_drum_current_observable() -> None:
    """[REQ:PX-14] The sensor existed in physics and the runtime never surfaced it. Telemetry must carry the
    drum-current reading, the mass inferred back from it, and the offload decision -- the closed-loop's
    inputs. And the reading must RISE as the drum fills (the whole basis of the FDC model)."""
    with tempfile.TemporaryDirectory() as d:
        rt = _rt(d)
        try:
            t0 = rt._sensor_telem()
            for k in ("drum_current_a", "drum_mass_inferred_kg", "should_offload"):
                assert k in t0, f"telemetry is missing {k!r} -- the sensor is still not wired to the runtime"
            i_empty = float(t0["drum_current_a"])
            for _ in range(6):
                rt._arm_front_offset_rad = 0.0
                rt._arm_back_offset_rad = 0.0
                rt._apply_dig()
            i_loaded = float(rt._sensor_telem()["drum_current_a"])
            assert i_loaded > i_empty + 1e-3, (
                f"the drum-current reading did not rise as the drum filled ({i_empty:.3f} -> {i_loaded:.3f} A)")
        finally:
            rt.stop()


def test_the_inferred_mass_tracks_the_true_mass_within_the_published_band() -> None:
    """[REQ:PX-14] Deterministic (noise off): the mass inferred from the drum current must match the true
    conserved drum mass to well within the FDC error band -- otherwise the loop is regulating on a fiction."""
    with tempfile.TemporaryDirectory() as d:
        rt = _rt(d)
        try:
            for _ in range(8):
                rt._arm_front_offset_rad = 0.0
                rt._arm_back_offset_rad = 0.0
                rt._apply_dig()
            t = rt._sensor_telem()
            true_kg = float(rt.ws.inventory_kg)
            inferred = float(t["drum_mass_inferred_kg"])
            assert true_kg > 0.0, "the drum never filled -- test premise broken"
            assert abs(inferred - true_kg) <= FDC_MPE_HALF_FULL * true_kg + 0.05, (
                f"inferred {inferred:.3f} kg vs true {true_kg:.3f} kg exceeds the FDC band")
        finally:
            rt.stop()


def test_the_closed_loop_regulates_the_bite_to_a_target_ingestion() -> None:
    """[REQ:PX-14] THE REQUIREMENT. The open-loop dig cuts the maximum allowed bite every pass. AutoDig
    regulates the bite DOWN to hold a target per-pass ingestion (maintaining consistent contact, not
    over-biting), and it reads that ingestion through the drum-current SENSOR, not the conserved truth."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        # what one open-loop (max-bite) pass ingests -> pick a target well below it, so regulation is DOWN
        rt0 = _rt(a)
        try:
            rt0._arm_front_offset_rad = rt0._arm_back_offset_rad = 0.0
            before = float(rt0.ws.inventory_kg)
            rt0._apply_dig()
            max_bite = float(rt0.ws.inventory_kg) - before
        finally:
            rt0.stop()
        assert max_bite > 0.0, "the open-loop dig moved nothing"
        target = 0.5 * max_bite

        rt = _rt(b)
        try:
            rt._arm_front_offset_rad = rt._arm_back_offset_rad = 0.0
            result = rt.autodig_trench(target_kg_per_pass=target, max_passes=40)
            passes = result["ingested_per_pass_kg"]
            assert len(passes) >= 5, f"the controller barely ran ({len(passes)} passes)"
            # after a few passes to converge, the achieved ingestion tracks the target far better than the
            # open-loop max-bite would (which is 2x the target by construction).
            settled = passes[2:]
            mean = sum(settled) / len(settled)
            assert abs(mean - target) < 0.25 * target, (
                f"the regulated ingestion {mean:.3f} kg/pass did not track the target {target:.3f} "
                f"(open-loop would give {max_bite:.3f})")
        finally:
            rt.stop()


def test_a_higher_setpoint_takes_a_deeper_bite_and_fewer_passes() -> None:
    """[REQ:PX-14] Setpoint control: raise the target ingestion and the controller takes bigger bites, so it
    fills the drum in fewer passes. A loop that ignored the setpoint would fill in the same count."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        rt_lo = _rt(a)
        rt_hi = _rt(b)
        try:
            for rt in (rt_lo, rt_hi):
                rt._arm_front_offset_rad = rt._arm_back_offset_rad = 0.0
            lo = rt_lo.autodig_trench(target_kg_per_pass=0.10, max_passes=300)
            hi = rt_hi.autodig_trench(target_kg_per_pass=0.40, max_passes=300)
            assert lo["terminated_on_offload"] and hi["terminated_on_offload"], \
                "a trench that never fills is not exercising the loop"
            assert hi["n_passes"] < lo["n_passes"], (
                f"a higher ingestion target ({hi['n_passes']} passes) did not fill faster than a lower one "
                f"({lo['n_passes']} passes) -- the setpoint is not controlling the bite")
        finally:
            rt_lo.stop(); rt_hi.stop()


def test_it_terminates_on_drum_full_without_overfilling_even_under_sensor_noise() -> None:
    """[REQ:PX-14] The offload trigger is the point of the FDC model: plan against IMPERFECT fill knowledge.
    With the sensor NOISY at the paper's half-full error, the loop must still stop at capacity and never
    overfill, because `should_offload` decides on the UPPER confidence bound."""
    with tempfile.TemporaryDirectory() as d:
        rt = _rt(d)
        try:
            rt._arm_front_offset_rad = rt._arm_back_offset_rad = 0.0
            result = rt.autodig_trench(target_kg_per_pass=0.30, max_passes=300,
                                       noise_frac=FDC_MPE_HALF_FULL, seed=7)
            assert result["terminated_on_offload"], "the noisy loop never decided to offload"
            assert float(rt.ws.inventory_kg) <= rt._vehicle_capacity_kg + 1e-6, (
                f"the drum overfilled ({rt.ws.inventory_kg:.3f} kg > {rt._vehicle_capacity_kg:.3f}) -- the "
                "offload trigger did not respect its uncertainty band")
        finally:
            rt.stop()


def test_the_regulated_bite_still_respects_the_sourced_bounds() -> None:
    """[REQ:PX-14] AutoDig regulates WITHIN the existing physics, it does not replace it. No pass may exceed
    the PX-09 <=50% anti-bridging cap, and a stowed arm still cuts nothing (PX-10)."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        rt = _rt(a)
        try:
            rt._arm_front_offset_rad = rt._arm_back_offset_rad = 0.0
            result = rt.autodig_trench(target_kg_per_pass=999.0, max_passes=30)  # ask for the impossible
            # even with an absurd target the bite cannot exceed the anti-bridging max-bite pass
            assert result["max_pass_kg"] <= result["max_bite_kg"] + 1e-6, (
                "a regulated pass exceeded the anti-bridging bound -- the controller broke PX-09")
        finally:
            rt.stop()

        rt2 = _rt(b)
        try:
            from stewie.specs.arm_state import ARM_DIG_DOWN_RAD
            rt2._arm_front_offset_rad = rt2._arm_back_offset_rad = -ARM_DIG_DOWN_RAD  # both stowed
            grid0 = float(rt2.ws._require_fine().grid_mass())
            result = rt2.autodig_trench(target_kg_per_pass=0.3, max_passes=10)
            assert result["n_passes"] == 0 or float(rt2.ws.inventory_kg) == 0.0, \
                "a stowed-arm AutoDig still dug -- the arm gate was bypassed"
            assert float(rt2.ws._require_fine().grid_mass()) == pytest.approx(grid0, abs=1e-6)
        finally:
            rt2.stop()


def test_open_loop_does_NOT_track_an_arbitrary_target_the_closed_loop_earns_its_keep() -> None:
    """[REQ:PX-14] NON-VACUITY. The whole value is the feedback. Fixed-depth open-loop passes ingest the
    MAX bite regardless of the target, so their achieved ingestion is far from an arbitrary lower setpoint;
    the closed loop's is not. If this failed, the loop would be decorative."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        rt0 = _rt(a)
        try:
            rt0._arm_front_offset_rad = rt0._arm_back_offset_rad = 0.0
            before = float(rt0.ws.inventory_kg)
            rt0._apply_dig()
            max_bite = float(rt0.ws.inventory_kg) - before
        finally:
            rt0.stop()
        target = 0.4 * max_bite

        rt = _rt(b)
        try:
            rt._arm_front_offset_rad = rt._arm_back_offset_rad = 0.0
            closed = rt.autodig_trench(target_kg_per_pass=target, max_passes=40)
            settled = closed["ingested_per_pass_kg"][2:]
            closed_err = abs(sum(settled) / len(settled) - target)
            open_err = abs(max_bite - target)   # open loop always ingests the max, ignoring the target
            assert closed_err < 0.5 * open_err, (
                f"the closed loop ({closed_err:.3f}) is no closer to the target than open-loop "
                f"({open_err:.3f}) -- the feedback is doing nothing")
        finally:
            rt.stop()
