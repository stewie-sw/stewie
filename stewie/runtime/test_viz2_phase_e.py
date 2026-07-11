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
        # HUD energy decreased by the grounded J/kg (Schuler et al 2024, ~4151 J/kg)
        assert rt._dig_energy_j == pytest.approx(rt.ws.cut_total_kg * dig_energy_per_kg(), rel=1e-12)
        assert rt._dig_energy_per_kg == pytest.approx(dig_energy_per_kg(), rel=1e-12)
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
        # the cut region reads negative; the MAX CUT DEPTH in the drape == the authority min at that cell
        assert float(dst["diff"].min()) < -0.05
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
