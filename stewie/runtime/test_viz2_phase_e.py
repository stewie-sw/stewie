"""[REQ:] viz2 PRD Phase E through the Viz2Runtime — dig energy debit (E1), the signed diff drape
streamed as a patch field (E2), and the RegolithVolumeEstimate evidence tie-in (E3), on the REAL
Haworth SfS 1 m bundle. Single-threaded (the runtime is constructed but its actor loop is NOT
started), so the conserved world is mutated deterministically off the test thread — no synthetic
terrain, no faked timing.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.contracts import RegolithVolumeEstimate
from stewie.runtime.viz2_runtime import Viz2Runtime, apply_manifest
from stewie.specs.ipex_specs import dig_energy_per_kg

_SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "samples", "lunar_dem")
SFS = os.path.join(_SAMPLES, "haworth_sfs_2km_1m")

pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="real Haworth SfS bundle not on disk")


def _runtime(tmp_path) -> Viz2Runtime:
    """A constructed-but-UNSTARTED runtime centered deep-interior on the real SfS bundle (its __init__
    recenters the WorkSite + sets the pose, so _apply_dig/_apply_dump have a seated footprint)."""
    from stewie.physics.worksite import coarse_base_from_bundle
    _base, meta = coarse_base_from_bundle(SFS)
    wb = meta["world_bounds_m"]
    cx = float(wb["x0"]) + _base.width * meta["grid"]["cell_m"] * 0.5
    cy = float(wb["y0"]) + _base.height * meta["grid"]["cell_m"] * 0.5
    return Viz2Runtime(SFS, session_dir=str(tmp_path), fine_cell_m=0.05, start_xy=(cx, cy))


def _box(H, W, r, c, hc=8):
    m = np.zeros((H, W), dtype=bool)
    m[max(0, r - hc):min(H, r + hc + 1), max(0, c - hc):min(W, c + hc + 1)] = True
    return m


# -- E1: dig debits the grounded excavation energy -------------------------------------------

def test_apply_dig_debits_grounded_dig_energy(tmp_path):
    rt = _runtime(tmp_path)
    try:
        assert rt._dig_energy_j == 0.0
        dirty = rt._apply_dig()                           # conserved dig at the seated pose
        assert dirty, "dig produced no dirty region"
        assert rt.ws.cut_total_kg > 0.0
        # council #1: the debit is now the FEE-modulated per-kg cost of THIS pass, not a flat constant.
        # WIRING: the accumulated energy == mass cut * the last pass's grounded J/kg.
        assert rt._dig_energy_j == pytest.approx(rt._last_dig_moved_kg * rt._last_dig_j_per_kg, rel=1e-9)
        assert rt._last_dig_j_per_kg > 0.0
        # the flat electrical figure remains the ANCHOR; the modulated per-kg is a physical fraction of it
        # (this real SfS bundle is looser + shallower than the BP-1 representative dig, so cost < anchor).
        assert 0.0 < rt._last_dig_j_per_kg < dig_energy_per_kg()
        assert rt._dig_energy_per_kg == pytest.approx(dig_energy_per_kg(), rel=1e-12)
    finally:
        rt.stop()


# -- E1b: the dig cost is FEE-grounded (depth^2 / density dependent), not a flat constant ------

def test_dig_specific_energy_rises_with_bite_depth_and_density(tmp_path):
    """council #1: excavation.earthmoving_report (McKyes/Reece FEE) is wired into the live dig so the
    per-kg cost RISES with cut-bite depth and in-situ density -- the terramechanics the old flat 4151 J/kg
    erased. Unit-tests the helper directly so the monotonicity does not depend on the real terrain relief."""
    rt = _runtime(tmp_path)
    try:
        f = rt.ws._require_fine()
        H, W = rt.window_shape()
        r0, r1, c0, c1 = 20, 36, 20, 36                       # a fixed 16x16-cell footprint
        area = float((r1 - r0) * (c1 - c0)) * (rt.ws.fine_cell_m ** 2)
        rho = float(np.mean(np.asarray(f.density[r0:r1, c0:c1], dtype=float)))
        # deeper bite = more mass removed over the same footprint -> strictly higher J/kg (FEE depth term)
        shallow = 0.25 * rt._max_cut_per_pass_m * rho * area
        deep = 1.00 * rt._max_cut_per_pass_m * rho * area
        e_shallow = rt._dig_specific_energy(r0, r1, c0, c1, shallow, f)
        e_deep = rt._dig_specific_energy(r0, r1, c0, c1, deep, f)
        assert e_deep > e_shallow > 0.0, (e_shallow, e_deep)
        # a zero-bite pass falls back to the flat grounded anchor (no negative / NaN cost)
        assert rt._dig_specific_energy(r0, r1, c0, c1, 0.0, f) == pytest.approx(dig_energy_per_kg())
    finally:
        rt.stop()


# -- #2: a single-front-drum dig arms an unbalanced draft reaction that feeds the drive -------

def test_apply_dig_arms_reaction_that_reaches_the_drive(tmp_path):
    """council #2: a single-front-drum dig arms a NONZERO unbalanced draft reaction (a counter-rotating
    pair would net ~0); feeding it through the runtime's own WorkSite.step carries it into the drive
    telemetry -- the excavation reaction now enters the wheel-soil traction budget."""
    rt = _runtime(tmp_path)
    try:
        assert rt._active_dig_reaction_n == 0.0
        rt._apply_dig()
        react = rt._active_dig_reaction_n
        assert react > 0.0                                # single drum => uncancelled FEE draft on the chassis
        assert rt._last_dig_reaction_n == react
        telem, _ = rt.ws.step(0.1, 0.0, rt.dt, dig_reaction_n=react)   # the drive resists the reaction
        assert telem["dig_reaction_n"] == react           # reaction reached the drive step
    finally:
        rt.stop()


# -- #31: aggregate execution metrics — wheel odometry over-reads the ground truth by slip ----

def test_aggregate_metrics_wheel_odometry_over_reads_ground_truth(tmp_path):
    """council/metrics #31: drive the REAL conserved physics and accumulate the deterministic aggregate
    metrics. The slip-blind wheel odometry integrates the COMMANDED speed and the ground truth the ACHIEVED
    speed, so under real slip the wheel odometry >= the actual distance and the odometry_error (drift) >= 0."""
    rt = _runtime(tmp_path)
    try:
        assert rt._dist_actual_m == 0.0 and rt._dist_wheel_m == 0.0 and rt._slope_n == 0
        for _ in range(12):
            telem, _ = rt.ws.step(0.2, 0.0, rt.dt)        # commanded 0.2 m/s over the real Haworth DEM
            rt._accumulate_metrics(telem, rt.dt)
        assert rt._dist_actual_m > 0.0                    # the rover really moved (ground truth)
        assert rt._dist_wheel_m >= rt._dist_actual_m      # slip-blind encoder over-reads
        assert rt._dist_wheel_m - rt._dist_actual_m >= 0.0  # dead-reckoning drift is non-negative
        assert 0.0 <= rt._slope_sum_deg / rt._slope_n < 90.0  # a real mean grade from the traversed terrain
    finally:
        rt.stop()


# -- E2: the signed diff drape is streamed as an absolute-value patch field ------------------

def test_diff_field_is_streamed_and_matches_the_authority(tmp_path):
    rt = _runtime(tmp_path)
    try:
        dig_dirty = rt._apply_dig()
        assert dig_dirty
        # a keyframe generation covers the whole window; write it and read the diff crop back
        gen = rt._advance_generation(dig_dirty, keyframe=True)
        assert gen >= 1
        manifest = rt.latest_manifest_path()
        import json
        m = json.load(open(manifest))
        assert "diff" in m["fields"], f"manifest missing the diff field: {sorted(m['fields'])}"
        H, W = rt.window_shape()
        dst = {"diff": np.zeros((H, W), dtype="<f4")}
        apply_manifest(dst, manifest)                     # digest-verified blit (the client's role)
        authority = rt.ws.diff_field()
        # the streamed drape equals the authority's signed diff (rf32 precision)
        assert np.allclose(dst["diff"], authority, atol=1e-3)
        # the cut region reads negative; the MAX CUT DEPTH in the drape == the authority min at that cell.
        # The cut is at least the shallow-pass dig depth (~dig_depth_m below the box min, deeper over relief);
        # the pre-shallow-pass -0.05 threshold is stale since dig_depth_m dropped to 0.02 (commit cc8e4461).
        assert float(dst["diff"].min()) < -0.9 * rt.dig_depth_m
        assert float(dst["diff"].min()) == pytest.approx(float(authority.min()), abs=1e-3)
    finally:
        rt.stop()


# -- E3: the RegolithVolumeEstimate evidence tie-in (round-3 conserved-mass contract) --------

def test_emit_volume_evidence_agrees_on_cut_total_only(tmp_path):
    """A dig-then-dump run (spoil placed as a SEPARATE berm) — the conserved cross-check is
    ``cut_total_kg`` ALONE, so observed == cut_total and agreement_conserved is True. placed_total_kg
    and the drum residual inventory_kg are reported SEPARATELY. Summing them (the OLD cut+placed
    argument) would FALSELY fail — the round-3 regression this contract fixes."""
    rt = _runtime(tmp_path)
    try:
        ws = rt.ws
        f = ws.fine
        H, W = f.height, f.width
        mA = _box(H, W, H // 2, W // 3)
        ws.flatten(mA, float(f.derive_height()[mA].min()) - 0.12)      # dig region A
        mB = _box(H, W, H // 2, 2 * W // 3)
        ws.dump(mB)                                                    # dump onto a SEPARATE berm
        ev = rt.emit_volume_evidence()
        e = ev["estimate"]
        assert isinstance(e, RegolithVolumeEstimate)
        # observed (cut-volume mass) agrees with the cumulative CUT mass, within the contract tolerance
        assert e.observed_mass_kg == pytest.approx(ev["cut_total_kg"], rel=1e-6)
        assert e.agreement_conserved is True
        assert e.acceptance == "accepted"
        # placed_total_kg and inventory_kg are SEPARATE quantities, never summed into conserved_mass_kg
        assert ev["placed_total_kg"] > 0.0
        assert ev["inventory_kg"] == pytest.approx(0.0, abs=1e-6)
        assert ev["placed_total_kg"] != pytest.approx(0.0, abs=1e-6)
        # the round-3 regression: conserved_mass_kg = cut + placed would FALSELY fail agreement
        before = ws.window_virgin_height()
        after = f.derive_height()
        bad = RegolithVolumeEstimate.from_delta(
            before, after, ws.fine_cell_m, work_order_id="x", before_source="v", after_source="a",
            transaction_id="t", density_kg_m3=ev["density_kg_m3"],
            conserved_mass_kg=ev["cut_total_kg"] + ev["placed_total_kg"])
        assert bad.agreement_conserved is False
    finally:
        rt.stop()


def test_emit_volume_evidence_dig_only_agrees(tmp_path):
    rt = _runtime(tmp_path)
    try:
        ws = rt.ws
        f = ws.fine
        mA = _box(f.height, f.width, f.height // 2, f.width // 2)
        ws.flatten(mA, float(f.derive_height()[mA].min()) - 0.12)
        ev = rt.emit_volume_evidence()
        e = ev["estimate"]
        assert e.observed_mass_kg == pytest.approx(ev["cut_total_kg"], rel=1e-6)
        assert e.agreement_conserved is True
        assert ev["placed_total_kg"] == 0.0
        assert ev["dig_energy_j"] == 0.0                  # energy is debited by _apply_dig, not ws.flatten
    finally:
        rt.stop()
