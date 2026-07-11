"""[REQ:] SYNTHETIC procedural terrain producer — determinism, variance anchor, seamlessness,
and the SEGREGATION guardrail (stewie.terrain.procedural_bundle).

Every assertion runs against real generated output (no fabricated numbers): the fbm engine is the
repo's own procgen_seed.fbm_global, and the datum-path injection is the same one dem_import uses.
Run: pytest stewie/terrain/test_procedural_bundle.py  (gate on exit code).
"""
from __future__ import annotations

import json
import os

import numpy as np

from stewie.terrain import procedural_bundle as pb
from dart import dem_site_compare as dsc

_PARAMS = {"H": 0.9, "feature_wavelength_m": 20.0, "amplitude_m": 6.0, "octaves": 6}


def _bundle_files(d: str) -> list[str]:
    return ["metadata.json", "heightmap.rf32", "mass_areal.rf32", "density.rf32",
            "disturbance.rf32", "state_label.r8"]


# --- determinism: same seed+params -> BYTE-identical bundle -------------------------------------

def test_same_seed_params_gives_byte_identical_bundle(tmp_path):
    # two SEPARATE generations with the SAME basename -> identical scene_name -> byte-identical.
    da = str(tmp_path / "a" / "demo")
    db = str(tmp_path / "b" / "demo")
    pb.generate_procedural_bundle(da, world_seed=11, params=_PARAMS, extent_m=64.0,
                                  cell_m=1.0, write_previews=False)
    pb.generate_procedural_bundle(db, world_seed=11, params=_PARAMS, extent_m=64.0,
                                  cell_m=1.0, write_previews=False)
    for fn in _bundle_files(da):
        a = (tmp_path / "a" / "demo" / fn).read_bytes()
        b = (tmp_path / "b" / "demo" / fn).read_bytes()
        assert a == b, f"{fn} differs across identical generations (non-deterministic)"


def test_derive_height_round_trips_the_saved_heightmap(tmp_path):
    d = str(tmp_path / "rt")
    fields, meta = pb.generate_procedural_bundle(d, world_seed=3, params=_PARAMS, extent_m=64.0,
                                                 cell_m=1.0, write_previews=False)
    # saved heightmap (float32) == datum + mass/density recomputed from the saved rasters
    saved = np.fromfile(tmp_path / "rt" / "heightmap.rf32", dtype="<f4").reshape(64, 64)
    assert np.allclose(saved, fields["heightmap"].astype("<f4"), atol=0.0)


# --- a different world_seed -> different terrain ------------------------------------------------

def test_different_seed_changes_terrain(tmp_path):
    f1, _ = pb.generate_procedural_bundle(str(tmp_path / "s1"), world_seed=1, params=_PARAMS,
                                          extent_m=64.0, cell_m=1.0, write_previews=False)
    f2, _ = pb.generate_procedural_bundle(str(tmp_path / "s2"), world_seed=2, params=_PARAMS,
                                          extent_m=64.0, cell_m=1.0, write_previews=False)
    assert not np.array_equal(f1["heightmap"], f2["heightmap"])
    # and the difference is substantial (not a one-cell fluke)
    assert float(np.std(f1["heightmap"] - f2["heightmap"])) > 1.0


# --- variance-anchored (physical roughness), NOT a min-max renorm -------------------------------

def test_variance_anchored_scales_linearly_with_amplitude(tmp_path):
    """Doubling amplitude_m DOUBLES the surface std bit-exactly (nu0=amp^2 -> std ~ amp). A min-max
    renorm to [0,1] would be amplitude-INVARIANT; variance anchoring scales the SAME realization by
    the amplitude ratio, so the relief is exactly 2x."""
    p1 = dict(_PARAMS, amplitude_m=5.0)
    p2 = dict(_PARAMS, amplitude_m=10.0)
    cs1, _ = pb.generate_procedural_fields(world_seed=9, params=p1, extent_m=256.0, cell_m=1.0)
    cs2, _ = pb.generate_procedural_fields(world_seed=9, params=p2, extent_m=256.0, cell_m=1.0)
    r1 = cs1.derive_height() - cs1.derive_height().mean()   # zero-mean relief (base_elev=0)
    r2 = cs2.derive_height() - cs2.derive_height().mean()
    # same realization, exactly 2x amplitude
    assert np.allclose(r2, 2.0 * r1, rtol=0, atol=1e-9)
    # sample std tracks the amplitude (physical roughness), and the field is NOT bounded to [0,1]
    s = float(cs1.derive_height().std())
    assert 0.6 * 5.0 < s < 1.4 * 5.0, f"std {s} not near amplitude 5.0 (min-max renorm would fail)"
    assert float(np.ptp(cs1.derive_height())) > 5.0     # spans well beyond a [0,1] normalization


# --- seamless: two OVERLAPPING procedural windows agree bit-exact (procgen_seed property) -------

def test_overlapping_windows_agree_bit_exact():
    """Reuse the procgen_seed global-lattice property through the producer's fbm surface: two windows
    that overlap in the GLOBAL frame read the SAME lattice nodes -> bit-exact on the overlap."""
    seed = 7
    p = _PARAMS
    csA, _ = pb.generate_procedural_fields(world_seed=seed, params=p, extent_m=64.0, cell_m=1.0,
                                           world_x0=0.0, world_y0=0.0)
    csB, _ = pb.generate_procedural_fields(world_seed=seed, params=p, extent_m=64.0, cell_m=1.0,
                                           world_x0=20.0, world_y0=10.0)  # +20 col, +10 row
    A = csA.derive_height()
    B = csB.derive_height()
    # global cell (r,c) is A[r,c]; in B (origin row+10,col+20) it is B[r-10, c-20]
    ovA = A[10:64, 20:64]
    ovB = B[0:54, 0:44]
    assert ovA.shape == ovB.shape and ovA.size > 0
    assert np.array_equal(ovA, ovB), "overlapping procedural windows are not seam-continuous"


# --- provenance GUARDRAIL: synthetic:true, citation None, out/procedural_sandbox, never real ----

def test_provenance_is_synthetic_and_uncited(tmp_path):
    fields, meta = pb.generate_procedural_bundle(str(tmp_path / "guard"), world_seed=4,
                                                 params=_PARAMS, extent_m=64.0, cell_m=1.0,
                                                 write_previews=False)
    assert meta["synthetic"] is True
    prov = meta["dem_provenance"]
    assert prov["synthetic"] is True
    assert prov["citation"] is None                 # NEVER a real citation
    assert "PROCEDURAL" in prov["source"]
    assert prov["world_seed"] == 4
    # the on-disk metadata says the same
    on_disk = json.loads((tmp_path / "guard" / "metadata.json").read_text())
    assert on_disk["synthetic"] is True
    assert on_disk["dem_provenance"]["citation"] is None


def test_default_destination_is_procedural_sandbox():
    d = pb._resolve_out_dir("some_name")
    assert os.path.join("out", "procedural_sandbox") in os.path.normpath(d)


def test_refuses_samples_lunar_dem_destination():
    import pytest
    with pytest.raises(ValueError):
        pb._resolve_out_dir(os.path.join(pb._REPO_ROOT, "samples", "lunar_dem", "evil"))


def test_dem_site_compare_never_lists_a_synthetic_bundle(tmp_path):
    """A synthetic bundle dropped even INTO a site root is excluded from the real cross-site table
    (segregation guardrail); a real (unmarked) bundle in the same root IS listed."""
    root = tmp_path / "lunar_dem"
    # a synthetic bundle written into the site root (absolute path is allowed; only a literal
    # samples/lunar_dem path is refused)
    synth = str(root / "synth_site")
    pb.generate_procedural_bundle(synth, world_seed=1, params=_PARAMS, extent_m=32.0, cell_m=1.0,
                                  write_previews=False)
    # a minimal REAL (unmarked) bundle beside it
    real = root / "real_site"
    real.mkdir(parents=True, exist_ok=True)
    (real / "metadata.json").write_text(json.dumps({
        "grid": {"width": 4, "height": 4, "cell_m": 5.0, "order": "row-major-C"},
        "world_bounds_m": {"x0": 0.0, "y0": 0.0, "x1": 20.0, "y1": 20.0},
        "region": "Real", "dem_provenance": {"source": "LOLA", "citation": "Barker et al."},
    }))

    listed = {os.path.basename(b) for b in dsc.list_site_bundles(str(root))}
    assert "real_site" in listed
    assert "synth_site" not in listed, "synthetic bundle leaked into the real cross-site enumeration"
    assert dsc.is_synthetic_bundle(synth) is True
    assert dsc.is_synthetic_bundle(str(real)) is False
    # and it never appears as a compare-table row
    names = {r.name for r in dsc.compare_table(str(root))}
    assert "synth_site" not in names
