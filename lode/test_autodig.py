"""[REQ:AD-01] The AUTODIG behavior layer -- a torque-regulating autonomous-excavation controller
that sequences one dig cycle (traverse -> dig/bite/drum-speed -> lift -> offload) beneath the
berm-building FSM (lode.berm_fsm).

These gates screen the behaviour the physics genuinely supports, grounded in docs/vehicle_ipex.md
(the [BUCKLES] auto-dig loop): drum TORQUE is the process variable and the arm/bite depth the control
variable. The torque is the McKyes/Reece earthmoving DRAFT (stewie.physics.excavation.draft_force) x
the drum radius -- density-RESPONSIVE, so the SAME setpoint yields a SHALLOWER bite in denser regolith
(the adaptation PX-14's uniform-field drum-CURRENT loop explicitly could not claim). The bite is
bounded by the anti-bridging cut-per-pass cap (ipex_specs.max_cut_per_pass_m); a rock >= 10 cm or a
drum-overload torque aborts to STALL; drum-full (rassor_mass_model.should_offload upper bound) fires
the offload handoff to berm_fsm; and every dig pass emits a conserved-EFFORT record (torque, specific
dig energy, mass, mechanical work) -- the AD-02 effort log.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

from lode import autodig as AD
from lode.berm_fsm import step as berm_step
from stewie.physics import rassor_mass_model as RM

# real, sourced operating points (NOT fabricated data): the material model spans phi 30-50 deg /
# cohesion 0.1-1.0 kPa over the relative-density range; loose vs dense are two real densities.
LOOSE = 1400.0
BP1 = 1750.0        # BP-1 lunar simulant in-situ density (ipex_specs.BP1_BULK_DENSITY_KG_M3)
DENSE = 1900.0


def _sensor() -> RM.DrumSensor:
    """A deterministic (noise-off) drum sensor calibrated on the conserved drum signal."""
    return RM.DrumSensor.calibrated([0.0, 10.0, 20.0, 30.0])


# ---- G1: torque = PV, bite = CV -------------------------------------------------------------------

def test_torque_regulates_to_setpoint():
    """[REQ:AD-01] The controller drives the CONTROL variable (bite depth) until the PROCESS variable
    (drum torque) sits on the setpoint."""
    c = AD.AutoDigController(torque_setpoint_nm=1.0)
    sol = c.regulate_bite(BP1)
    assert sol.torque_nm == pytest.approx(1.0, abs=1e-3)
    assert 0.0 < sol.depth_m <= c.max_cut_m
    assert not sol.saturated


# ---- G2: regulates ACROSS regolith densities (the PX-14 gap) --------------------------------------

def test_denser_regolith_takes_shallower_bite():
    """[REQ:AD-01] The SAME torque setpoint converges at BOTH densities, and the denser regolith is
    cut with a STRICTLY shallower bite -- the density adaptation PX-14's uniform field could not test."""
    c = AD.AutoDigController(torque_setpoint_nm=1.0)
    loose = c.regulate_bite(LOOSE)
    dense = c.regulate_bite(DENSE)
    assert loose.torque_nm == pytest.approx(1.0, abs=1e-3)
    assert dense.torque_nm == pytest.approx(1.0, abs=1e-3)
    assert dense.depth_m < loose.depth_m          # denser -> shallower bite to hold the same torque


# ---- G3: cut-depth bound respected ----------------------------------------------------------------

def test_cut_depth_bound_respected():
    """[REQ:AD-01] A setpoint too high to reach within the anti-bridging cap saturates the bite AT the
    cap and never exceeds it, at every density."""
    c = AD.AutoDigController(torque_setpoint_nm=50.0)   # unreachable within max_cut at these densities
    for rho in (LOOSE, BP1, DENSE):
        sol = c.regulate_bite(rho)
        assert sol.depth_m <= c.max_cut_m + 1e-12
        assert sol.depth_m == pytest.approx(c.max_cut_m, abs=1e-9)
        assert sol.saturated


# ---- G4: a stall aborts ---------------------------------------------------------------------------

def test_rock_hazard_aborts_to_stall():
    """[REQ:AD-01] A rock >= 10 cm in the cut path (docs [BUCKLES]) drives the FSM to STALL."""
    c = AD.AutoDigController()
    s = _sensor()
    obs = AD.AutoDigObs(at_face=True, drum_kg=5.0, bulk_density_kg_m3=BP1, stable=True,
                        rock_m=AD.ROCK_HAZARD_M + 0.05)
    nxt, reason = AD.step(AD.DIG, obs, c, s)
    assert nxt == AD.STALL and "rock" in reason.lower()


def test_drum_overload_torque_aborts_to_stall():
    """[REQ:AD-01] A buried-rock surcharge that spikes the min-bite torque past the drum-overload
    ceiling stalls even the shallowest productive bite -> STALL."""
    c = AD.AutoDigController()
    s = _sensor()
    stalled, why = c.is_stalled(BP1, surcharge_pa=200_000.0)
    assert stalled and "overload" in why.lower()
    nxt, _ = AD.step(AD.DIG, AD.AutoDigObs(at_face=True, drum_kg=5.0, bulk_density_kg_m3=BP1,
                                           stable=True, surcharge_pa=200_000.0), c, s)
    assert nxt == AD.STALL


def test_stability_gate_aborts():
    """[REQ:AD-01] Tip margin <= 0 aborts the dig -- never excavate while unstable (the #59 gate)."""
    c = AD.AutoDigController()
    s = _sensor()
    nxt, reason = AD.step(AD.DIG, AD.AutoDigObs(at_face=True, drum_kg=5.0, bulk_density_kg_m3=BP1,
                                                stable=False), c, s)
    assert nxt == AD.STALL and "tip" in reason.lower()


# ---- G5: the offload handoff fires ----------------------------------------------------------------

def test_offload_handoff_fires_and_hands_to_berm_fsm():
    """[REQ:AD-01] Drum-full (should_offload upper bound) walks DIG -> LIFT -> OFFLOAD -> DONE, and the
    handoff drum drives berm_fsm LOAD -> HAUL (AutoDig sits BENEATH the berm FSM)."""
    c = AD.AutoDigController(torque_setpoint_nm=1.0)
    s = _sensor()
    obs = [AD.AutoDigObs(at_face=False, drum_kg=0.0, bulk_density_kg_m3=BP1, stable=True),
           AD.AutoDigObs(at_face=True, drum_kg=0.0, bulk_density_kg_m3=BP1, stable=True),
           AD.AutoDigObs(at_face=True, drum_kg=10.0, bulk_density_kg_m3=BP1, stable=True),
           AD.AutoDigObs(at_face=True, drum_kg=20.0, bulk_density_kg_m3=BP1, stable=True),
           AD.AutoDigObs(at_face=True, drum_kg=30.5, bulk_density_kg_m3=BP1, stable=True)]
    out = AD.run(obs, c, s, target_kg=25.0)
    assert out["final"] == AD.DONE and out["offloaded"] is True
    assert [t["to"] for t in out["trace"]] == [AD.DIG, AD.LIFT, AD.OFFLOAD, AD.DONE]
    # the offload handoff -> berm_fsm: a full drum, berm under target -> HAUL to the build site
    hand = out["handoff"]
    assert hand is not None
    nxt, _ = berm_step("LOAD", hand)
    assert nxt == "HAUL"


# ---- G6: emits the AD-02 effort log ---------------------------------------------------------------

def test_effort_log_emitted_and_energy_reconciles():
    """[REQ:AD-01] Each dig pass emits a conserved-effort record (torque, specific energy, mass, work);
    mechanical work == specific dig energy x mass ingested, and the torque is a real positive draft."""
    c = AD.AutoDigController(torque_setpoint_nm=1.0)
    s = _sensor()
    obs = [AD.AutoDigObs(at_face=True, drum_kg=0.0, bulk_density_kg_m3=BP1, stable=True),
           AD.AutoDigObs(at_face=True, drum_kg=2.0, bulk_density_kg_m3=BP1, stable=True),
           AD.AutoDigObs(at_face=True, drum_kg=4.5, bulk_density_kg_m3=BP1, stable=True)]
    out = AD.run(obs, c, s)
    log = out["effort_log"]
    assert len(log) >= 2
    for rec in log:
        assert rec.drum_torque_nm > 0.0
        assert rec.specific_energy_j_per_kg > 0.0
        assert rec.mechanical_work_j == pytest.approx(rec.specific_energy_j_per_kg * rec.mass_kg, rel=1e-9)
        assert rec.bite_depth_m <= c.max_cut_m + 1e-12
    assert sum(r.mass_kg for r in log) == pytest.approx(4.5, abs=1e-9)   # conserved: total ingest


# ---- G8: NON-VACUITY -- neutering the feedback breaks regulation + adaptation ----------------------

def test_open_loop_neuter_breaks_regulation():
    """[REQ:AD-01] Proof the loop is load-bearing: an open-loop controller (always the max bite) neither
    holds the setpoint NOR adapts to density -- both densities cut the identical max bite."""
    closed = AD.AutoDigController(torque_setpoint_nm=1.0, open_loop=False)
    opened = AD.AutoDigController(torque_setpoint_nm=1.0, open_loop=True)
    # closed loop: distinct, setpoint-holding bites
    assert closed.regulate_bite(LOOSE).depth_m != closed.regulate_bite(DENSE).depth_m
    # open loop: identical max bites, torque OFF the setpoint
    o_loose = opened.regulate_bite(LOOSE)
    o_dense = opened.regulate_bite(DENSE)
    assert o_loose.depth_m == pytest.approx(opened.max_cut_m, abs=1e-12)
    assert o_dense.depth_m == pytest.approx(opened.max_cut_m, abs=1e-12)
    assert abs(o_loose.torque_nm - 1.0) > 0.1     # not regulated to the setpoint


# ---- integration: extends WorkSite over the REAL committed Haworth bundle --------------------------

_BUNDLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "samples", "lunar_dem", "haworth_10km_5m")


@pytest.mark.skipif(not os.path.isdir(_BUNDLE), reason="committed Haworth bundle absent")
def test_extends_worksite_real_haworth():
    """[REQ:AD-01] The behaviour layer drives a REAL WorkSite over the committed Haworth SfS bundle:
    each dig pass cuts a drum-footprint bite at the regulated depth, and the effort log carries the
    REAL ingested mass with the FEE torque + energy reconciling."""
    from stewie.physics.worksite import WorkSite

    site = WorkSite.from_haworth_bundle(_BUNDLE, fine_cell_m=0.05, tile_base_cells=2)
    site.open_window((1101, 1101), radius_m=4.0)
    f = site.fine
    c = AD.AutoDigController(torque_setpoint_nm=1.0)
    s = _sensor()

    # a drum-footprint mask (~0.35 m wide x ~0.10 m along-track) at the window centre
    H, W = f.height, f.width
    mask = np.zeros((H, W), bool)
    r0, c0 = H // 2, W // 2
    mask[r0 - 1:r0 + 1, c0 - 4:c0 + 3] = True          # ~2 x 7 fine cells
    area_m2 = int(mask.sum()) * site.fine_cell_m ** 2

    obs = []
    cum = 0.0
    for _ in range(4):
        rho = float(f.density[mask].mean())            # REAL in-situ density from the conserved field
        sol = c.regulate_bite(rho)
        before = float(f.derive_height()[mask].mean())
        moved = site.flatten(mask, before - sol.depth_m)   # REAL conserved cut -> kg into the drum
        assert moved > 0.0
        cum += moved
        obs.append(AD.AutoDigObs(at_face=True, drum_kg=cum, bulk_density_kg_m3=rho, stable=True))

    out = AD.run(obs, c, s, start=AD.DIG)          # already at the cut face (open_window placed us)
    log = out["effort_log"]
    assert len(log) == 4
    assert sum(r.mass_kg for r in log) == pytest.approx(cum, abs=1e-9)   # real conserved ingest
    for rec in log:
        assert rec.mass_kg > 0.0
        assert rec.drum_torque_nm > 0.0
        assert rec.mechanical_work_j == pytest.approx(rec.specific_energy_j_per_kg * rec.mass_kg, rel=1e-9)
        assert 0.0 < rec.bite_depth_m <= c.max_cut_m + 1e-12
    assert area_m2 > 0.0
