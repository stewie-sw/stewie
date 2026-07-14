"""[REQ:PX-09] The live dig is BOUNDED by the sourced bucket-drum limits: the anti-bridging bite cap and
the drum's own hold. On the REAL Haworth SfS 1 m bundle; the runtime is constructed but not started, so
the conserved world is mutated deterministically off the test thread (no synthetic terrain, no fake timing).

WHY THIS FILE EXISTS. `_apply_dig` cut a fixed `dig_depth_m` box and booked whatever mass came out, which
broke the excavation model in two ways:

  1. THE ENERGY AND THE TERRAIN DESCRIBED DIFFERENT BITES. `_dig_fee` already clamped its characteristic
     bite depth to `max_cut_per_pass_m(drum)` (= MAX_CUT_DEPTH_FRAC 0.50 x the drum's scoop-opening
     height -- the [BDSCALE] anti-bridging limit), but the CUT itself ignored that cap. So an over-deep
     cut removed more mass than a legal pass while being billed at the shallower legal depth -- and the
     McKyes/Reece FEE rises with depth^2, so dig energy was UNDERSTATED exactly when the cut was worst.
     The cap must bind on the terrain, not just on the invoice.
  2. THE DRUM HAD NO CAPACITY. `DRUM_CAPACITY_KG` (small 3.80 / medium 7.30 / large 24.98 kg [BDSCALE])
     was never consulted, so the drum filled without bound -- there was no fill -> stop -> haul quantum,
     and (now that the Drive 3D console is publicly reachable) an anonymous operator could book unbounded
     regolith into a 30 kg-class vehicle's drum.

Both limits are SOURCED (Schuler et al., "ISRU Pilot Excavator: Bucket Drum Scaling", [BDSCALE]); nothing
here is invented. Note the default drum is `large` with a 23.9 mm cap, so the shipped 20 mm `dig_depth_m`
is already legal -- the bite cap bites for the small/medium drums and any deeper `dig_depth_m`, while the
capacity cap bites for every drum.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.runtime.viz2_runtime import Viz2Runtime
from stewie.specs.ipex_specs import (
    DRUM_CAPACITY_KG,
    REGOLITH_PER_CYCLE_KG,
    max_cut_per_pass_m,
)

_SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "samples", "lunar_dem")
SFS = os.path.join(_SAMPLES, "haworth_sfs_2km_1m")
pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="real Haworth SfS bundle not on disk")


def _runtime(tmp_path, *, drum: str = "large", dig_depth_m: float = 0.02) -> Viz2Runtime:
    """A constructed-but-UNSTARTED runtime seated deep-interior on the real SfS bundle."""
    from stewie.physics.worksite import coarse_base_from_bundle
    _base, meta = coarse_base_from_bundle(SFS)
    wb = meta["world_bounds_m"]
    cx = float(wb["x0"]) + _base.width * meta["grid"]["cell_m"] * 0.5
    cy = float(wb["y0"]) + _base.height * meta["grid"]["cell_m"] * 0.5
    return Viz2Runtime(SFS, session_dir=str(tmp_path), fine_cell_m=0.05, start_xy=(cx, cy),
                       drum=drum, dig_depth_m=dig_depth_m)


def _drum_kg(rt: Viz2Runtime) -> float:
    """What the drum actually holds. NOTE: the FINE ColumnState's ``drum_inventory`` is only a transient
    register -- ``WorkSite.flatten`` sweeps it into the GLOBAL ledger and zeroes it -- so the drum's real
    contents are ``WorkSite.inventory_kg``. That is the quantity the capacity cap must bound."""
    return float(rt.ws.inventory_kg)


def test_cut_bite_respects_the_scoop_anti_bridging_limit(tmp_path) -> None:
    """[REQ:PX-09] A single pass may not cut deeper than 50% of the drum's scoop opening, even when
    `dig_depth_m` asks for more. Small drum: cap = 0.5 * 26.4 mm = 13.2 mm; we ask for 50 mm."""
    cap = max_cut_per_pass_m("small")
    rt = _runtime(tmp_path, drum="small", dig_depth_m=0.05)      # deliberately ~4x the legal bite
    assert 0.05 > cap, "test premise: the requested depth must exceed the anti-bridging cap"

    f = rt.ws._require_fine()
    before = f.derive_height().copy()
    dirty = rt._apply_dig()
    assert dirty, "the dig did not seat on the real bundle"
    after = rt.ws._require_fine().derive_height()

    drop = float(np.max(before - after))
    assert drop <= cap + 1e-9, (
        f"one pass cut {drop*1000:.1f} mm, deeper than the {cap*1000:.1f} mm anti-bridging limit for the "
        "'small' drum -- the terrain ignored the cap that the energy model already applies")


def test_energy_is_billed_for_the_bite_actually_taken(tmp_path) -> None:
    """[REQ:PX-09] `_dig_fee` clamps its characteristic depth to the anti-bridging cap. That clamp must be
    a no-op consequence of a legal cut -- never a mask over an over-deep one (which would UNDERSTATE the
    depth^2 FEE energy). Equivalent statement: the mean bite the terrain actually gave up is <= the cap."""
    rt = _runtime(tmp_path, drum="small", dig_depth_m=0.05)
    cap = max_cut_per_pass_m("small")
    f = rt.ws._require_fine()
    before = f.derive_height().copy()
    dirty = rt._apply_dig()
    assert dirty
    fine = rt.ws._require_fine()
    after = fine.derive_height()

    r0, c0, r1, c1 = dirty[0]
    cut = before[r0:r1, c0:c1] - after[r0:r1, c0:c1]
    mean_bite = float(cut[cut > 0].mean()) if np.any(cut > 0) else 0.0
    assert mean_bite <= cap + 1e-9, (
        f"the FEE clamps its depth at {cap*1000:.1f} mm but the terrain gave up a {mean_bite*1000:.1f} mm "
        "mean bite -- energy is being billed for a shallower pass than was actually cut")


def test_drum_never_exceeds_its_sourced_capacity_and_stops_when_full(tmp_path) -> None:
    """[REQ:PX-09/PX-13] The VEHICLE holds 2 x DRUM_CAPACITY_KG. Digging repeatedly must never book more than
    that, and once full a further dig must move NOTHING -- that refusal is the fill -> stop -> haul quantum.

    UPDATED BY PX-13. [BDSCALE] DRUM_CAPACITY_KG is the hold of ONE drum ("Avg total regolith collected PER
    DRUM", Schuler 2022 Table 3), and the vehicle carries TWO. So the cap is 2x. Note what does NOT change:
    two drums cut two footprints, so mass-in doubles AND the tank doubles -- PASSES-TO-FULL IS UNCHANGED.
    What doubles is THROUGHPUT (every haul carries twice the regolith), which is the actual reason the
    machine has two drums. Raising this bound is not a loosening: the refusal below still binds, exactly."""
    rt = _runtime(tmp_path, drum="small", dig_depth_m=0.02)
    cap_kg = 2.0 * float(DRUM_CAPACITY_KG["small"])          # the VEHICLE hold: two drums

    for _ in range(60):                       # far more passes than the vehicle can possibly hold
        rt._apply_dig()
        assert _drum_kg(rt) <= cap_kg + 1e-6, (
            f"vehicle holds {_drum_kg(rt):.2f} kg > its sourced {cap_kg:.2f} kg (2 x per-drum) capacity")

    assert _drum_kg(rt) > 0.0, "the test never actually dug"
    # Full -> the next pass is refused (no mass leaves the grid): the haul quantum exists.
    held = _drum_kg(rt)
    grid_before = float(rt.ws._require_fine().grid_mass())
    rt._apply_dig()
    assert _drum_kg(rt) == pytest.approx(held, abs=1e-9), "a full drum kept accepting regolith"
    assert float(rt.ws._require_fine().grid_mass()) == pytest.approx(grid_before, abs=1e-6), \
        "a refused dig still removed mass from the terrain"


def test_mass_is_conserved_across_a_capacity_limited_dig(tmp_path) -> None:
    """[REQ:PX-09] Capping the bite must not break conservation: grid mass lost == drum mass gained."""
    rt = _runtime(tmp_path, drum="small", dig_depth_m=0.05)
    f = rt.ws._require_fine()
    grid0, drum0 = float(f.grid_mass()), _drum_kg(rt)
    rt._apply_dig()
    fine = rt.ws._require_fine()
    grid1, drum1 = float(fine.grid_mass()), _drum_kg(rt)
    assert (grid0 - grid1) == pytest.approx(drum1 - drum0, rel=1e-9, abs=1e-6), \
        "the capped cut is not mass-conserving"


def test_drum_capacity_keeps_a_cycle_inside_the_rds_envelope() -> None:
    """[REQ:PX-09] The RDS spec collects <=30 kg/cycle. With the drum hold enforced, that envelope now
    holds BY CONSTRUCTION for every drum rather than being flagged after the fact."""
    for drum, cap in DRUM_CAPACITY_KG.items():
        assert float(cap) <= REGOLITH_PER_CYCLE_KG, (
            f"the {drum} drum's {cap} kg hold exceeds the {REGOLITH_PER_CYCLE_KG} kg/cycle RDS envelope")
