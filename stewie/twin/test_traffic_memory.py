"""TrafficMemory (TW-11) -- the per-cell traversal-hardening accumulator that folds real drive telemetry
(cell-visits + wheel load) into a CUMULATIVE-LOAD densification that approaches the EXISTING conserved
equilibrium exponentially, is H-09-safe (re-applying the same telemetry is idempotent), and persists +
hash-chains exactly like TerrainMemory.

No synthetic data: the wheel load is the REAL sourced IPEx static per-wheel load (terramechanics.
static_wheel_load_n), the reference areal mass is a REAL regolith column's areal mass, and the equilibrium
is the SAME physical_compaction_target_density the conserved drive loop uses -- no fabricated distribution.

Run: <venv>/bin/python -m pytest stewie/twin/test_traffic_memory.py -q
"""
import numpy as np
import pytest

from stewie.physics import material
from stewie.physics import terramechanics as tm
from stewie.specs import constants as K
from stewie.twin.traffic_memory import TrafficMemory


def _straight_corridor(rows: int, cols: int, r: int) -> list[tuple[int, int]]:
    """A REAL driven corridor: the cells of a straight haul road along row ``r`` (a rover drives a line)."""
    return [(r, c) for c in range(cols)]


def _real_wheel_load() -> float:
    """The REAL sourced IPEx static per-wheel normal load [N] (dry 30 kg-class), not a made-up number."""
    return tm.static_wheel_load_n(payload_kg=0.0)


# --- (a) cumulative load -> Dr rises toward the existing equilibrium (monotone, exp approach, asymptote) --

def test_cumulative_load_approaches_the_conserved_equilibrium_monotonically():
    tmem = TrafficMemory(site="s", rows=3, cols=6, cell_m=0.5)
    load = _real_wheel_load()
    corridor = _straight_corridor(3, 6, 1)
    # the SAME corridor driven again and again -> cumulative load rises, peak load is constant
    drs = []
    for i in range(12):
        tmem.apply_path(corridor, load, mission=f"haul-{i}", event_id=f"haul:{i}")
        drs.append(float(tmem.relative_density()[1, 1]))
    # equilibrium the conserved drive loop would reach at THIS peak load (the SAME function, not re-invented)
    rho_eq = float(min(tm.physical_compaction_target_density(
        np.array([tmem.mass_areal]), load, contact_width_m=tmem.contact_width_m)[0], K.RHO_DEEP))
    dr_eq = float(material.relative_density(np.array([rho_eq]))[0])
    # MONOTONE non-decreasing, strictly rising while sub-equilibrium
    assert all(b >= a - 1e-12 for a, b in zip(drs, drs[1:]))
    assert drs[3] > drs[0] > 0.0
    # ASYMPTOTES AT the equilibrium and NEVER EXCEEDS it. Dr is linear in density, so Dr(Sigma) is EXACTLY
    # dr_eq * (1 - exp(-Sigma/Sigma_c)): after 12 dry passes (Sigma ~ 146 N, Sigma_c = 60) the approach is
    # ~91% of the asymptote -- substantially firmed, still strictly sub-equilibrium (never overshoots).
    sigma = 12.0 * load
    expect = dr_eq * (1.0 - np.exp(-sigma / tmem.sigma_c_n))
    assert drs[-1] < dr_eq                                    # never reaches/exceeds the asymptote in finite load
    assert drs[-1] == pytest.approx(expect, rel=1e-6)         # matches the closed-form exponential approach
    assert 0.85 * dr_eq < drs[-1]                             # a dozen haul passes firm most of the way there
    # unvisited cells stay pristine (Dr = 0) -- only the driven corridor hardens
    assert float(tmem.relative_density()[0, 0]) == 0.0


def test_densification_is_an_exponential_approach_keyed_on_cumulative_load():
    tmem = TrafficMemory(site="s", rows=1, cols=1, cell_m=0.5)
    load = _real_wheel_load()
    rho_eq = float(min(tm.physical_compaction_target_density(
        np.array([tmem.mass_areal]), load, contact_width_m=tmem.contact_width_m)[0], K.RHO_DEEP))
    # fold cumulative load in equal increments; the REMAINING gap to equilibrium must decay by a
    # CONSTANT ratio each equal-load step (the signature of exp(-Sigma/Sigma_c)), NOT a linear/pass-count law
    gaps = []
    for i in range(5):
        tmem.apply_path([(0, 0)], load, mission=f"m{i}", event_id=f"m:{i}")
        gaps.append(rho_eq - float(tmem.densified_density()[0, 0]))
    ratios = [gaps[i + 1] / gaps[i] for i in range(len(gaps) - 1)]
    assert all(g > 0 for g in gaps)                          # always sub-equilibrium (never overshoots)
    assert max(ratios) - min(ratios) < 1e-6                  # constant decay ratio == exponential in Sigma


def test_a_heavier_pass_raises_the_equilibrium_ceiling():
    # peak load sets the asymptote (H-09: a heavier pass firms further); cumulative load sets the approach
    light = TrafficMemory(site="a", rows=1, cols=1, cell_m=0.5)
    heavy = TrafficMemory(site="b", rows=1, cols=1, cell_m=0.5)
    for i in range(20):
        light.apply_path([(0, 0)], tm.static_wheel_load_n(payload_kg=0.0), mission=f"l{i}", event_id=f"l:{i}")
        heavy.apply_path([(0, 0)], tm.static_wheel_load_n(payload_kg=30.0), mission=f"h{i}", event_id=f"h:{i}")
    assert float(heavy.relative_density()[0, 0]) > float(light.relative_density()[0, 0])


# --- (b) H-09-safe idempotence: same telemetry batch twice == once -----------------------------------

def test_reapplying_the_same_telemetry_is_idempotent():
    tmem = TrafficMemory(site="s", rows=2, cols=4, cell_m=0.5)
    load = _real_wheel_load()
    corridor = _straight_corridor(2, 4, 0)
    v1 = tmem.apply_path(corridor, load, mission="haul", event_id="haul:0")
    dr1 = tmem.relative_density().copy()
    sig1 = tmem._load_cycles.copy()
    # the EXACT same telemetry batch, folded again -> no double-count, no version bump, no chain append
    v2 = tmem.apply_path(corridor, load, mission="haul", event_id="haul:0")
    assert v2 == v1                                          # version did NOT advance on a repeat
    assert np.allclose(tmem._load_cycles, sig1)              # cumulative load did NOT double
    assert np.allclose(tmem.relative_density(), dr1)         # Dr unchanged
    assert len(tmem.chain) == 1
    # a genuinely NEW event (new cumulative load) DOES harden further and advances the chain
    v3 = tmem.apply_path(corridor, load, mission="haul", event_id="haul:1")
    assert v3 == v2 + 1
    assert float(tmem.relative_density()[0, 0]) > float(dr1[0, 0])
    assert len(tmem.chain) == 2


def test_dr_never_exceeds_the_equilibrium_under_unbounded_repeats():
    tmem = TrafficMemory(site="s", rows=1, cols=1, cell_m=0.5)
    load = _real_wheel_load()
    rho_eq = float(min(tm.physical_compaction_target_density(
        np.array([tmem.mass_areal]), load, contact_width_m=tmem.contact_width_m)[0], K.RHO_DEEP))
    for i in range(200):
        tmem.apply_path([(0, 0)], load, mission=f"m{i}", event_id=f"m:{i}")
        assert float(tmem.densified_density()[0, 0]) <= rho_eq + 1e-6


# --- (c) bearing uplift follows Dr -------------------------------------------------------------------

def test_bearing_uplift_follows_dr():
    tmem = TrafficMemory(site="s", rows=1, cols=3, cell_m=0.5)
    load = _real_wheel_load()
    # cell 0 heavily trafficked, cell 1 lightly, cell 2 never
    for i in range(15):
        tmem.apply_path([(0, 0)], load, mission=f"a{i}", event_id=f"a:{i}")
    for i in range(2):
        tmem.apply_path([(0, 1)], load, mission=f"b{i}", event_id=f"b:{i}")
    uplift = tmem.bearing_uplift_pa()
    dr = tmem.relative_density()
    assert dr[0, 0] > dr[0, 1] > dr[0, 2] == 0.0
    assert uplift[0, 0] > uplift[0, 1] > 0.0                 # a firmer road bears more
    assert uplift[0, 2] == pytest.approx(0.0, abs=1e-6)      # pristine cell -> no uplift


# --- (d) persistence round-trips through .npz + folds into the DT-01 chain ----------------------------

def test_persistence_roundtrips_and_hash_chain_verifies(tmp_path):
    tmem = TrafficMemory(site="haworth", rows=2, cols=4, cell_m=0.5, origin=(3.0, 7.0))
    load = _real_wheel_load()
    tmem.apply_path(_straight_corridor(2, 4, 1), load, mission="haul-A", event_id="A:0")
    tmem.apply_path(_straight_corridor(2, 4, 1), load, mission="haul-A", event_id="A:1")
    assert tmem.verify_chain()
    p = str(tmp_path / "traffic.npz")
    tmem.save(p)
    back = TrafficMemory.load(p)
    assert back.site == "haworth" and back.version == tmem.version == 2 and back.origin == (3.0, 7.0)
    assert np.allclose(back._load_cycles, tmem._load_cycles)
    assert np.allclose(back._peak_load, tmem._peak_load)
    assert np.allclose(back.relative_density(), tmem.relative_density())
    assert back.verify_chain()
    assert list(back._applied) == ["A:0", "A:1"]             # the folded event-ids persist (idempotence survives reload)


def test_hash_chain_advances_only_on_new_load(tmp_path):
    tmem = TrafficMemory(site="s", rows=1, cols=2, cell_m=0.5)
    load = _real_wheel_load()
    tmem.apply_path([(0, 0)], load, mission="m", event_id="e:0")
    h1 = tmem.chain[-1]["hash"]
    tmem.apply_path([(0, 0)], load, mission="m", event_id="e:0")   # REPEAT -> no new chain link
    assert tmem.chain[-1]["hash"] == h1 and len(tmem.chain) == 1
    tmem.apply_path([(0, 0)], load, mission="m", event_id="e:1")   # NEW load -> chain advances
    assert tmem.chain[-1]["hash"] != h1 and len(tmem.chain) == 2
    # tamper detection: editing a committed record breaks verify_chain
    tmem.chain[0]["mission"] = "forged"
    assert tmem.verify_chain() is False


def test_apply_rejects_nonfinite_and_shape_mismatch():
    tmem = TrafficMemory(site="s", rows=2, cols=2, cell_m=0.5)
    with pytest.raises(ValueError):
        tmem.apply(np.array([[np.nan, 0.0], [0.0, 0.0]]), mission="m", event_id="x")
    with pytest.raises(ValueError):
        tmem.apply(np.zeros((3, 3)), mission="m", event_id="y")


def test_load_site_store_roundtrip(tmp_path):
    from stewie.twin import traffic_memory as TW
    assert TW.load_site(str(tmp_path), "haworth") is None      # nothing recorded yet
    tmem = TrafficMemory(site="haworth", rows=2, cols=3, cell_m=0.5)
    tmem.apply_path([(0, 0), (0, 1)], _real_wheel_load(), mission="m", event_id="e:0")
    TW.save_site(str(tmp_path), tmem)
    back = TW.load_site(str(tmp_path), "haworth")
    assert back is not None and back.version == 1
    assert np.allclose(back.relative_density(), tmem.relative_density())
