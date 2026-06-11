"""ARGUS vs Stanford NAV Lab vs ShadowNav: the comparison framework + head-to-head fix."""
import sys
sys.path.insert(0, "/mnt/projects/Dissertation/projects/argus/notebooks")  # for the haworth DEM helper

import numpy as np

from dart import comparison as CMP
from stewie.specs import ipex_specs as S


def test_capability_matrix_positions_all_three_grounded():
    m = CMP.nav_capability_matrix()
    assert set(m) == {"Stanford NAV Lab (LAC)", "ShadowNav (JPL)", "ARGUS"}
    # the grounded differentiation: only ARGUS uses shadow as GEOMETRY + active morphology
    assert m["ARGUS"]["active_reconfiguration"] is True
    assert m["Stanford NAV Lab (LAC)"]["active_reconfiguration"] is False
    assert m["ShadowNav (JPL)"]["active_reconfiguration"] is False
    assert "GEOMETRIC" in m["ARGUS"]["shadow_role"]
    # only ShadowNav requires the orbital prior; ARGUS local fix is map-free
    assert m["ShadowNav (JPL)"]["needs_orbital_prior"] is True
    assert m["ARGUS"]["needs_orbital_prior"] is False
    # every entry cites a paper
    assert all("arXiv" in v["paper"] or v["paper"] == "this work" for v in m.values())


def test_head_to_head_position_fix_on_real_dem():
    """Both representatives recover the rover position on the SAME real Haworth scene; report errors.
    ARGUS is map-free + heading-free, the map-match needs the orbital DEM."""
    from lode.mission_planner import load_site_dem
    Z, cell = load_site_dem("haworth")
    Z = np.asarray(Z, float)
    tr, tc = 1000, 1000
    true_xy = np.array([tc * cell, tr * cell])
    L = np.array([[true_xy[0] + 6, true_xy[1]], [true_xy[0], true_xy[1] + 5],
                  [true_xy[0] - 5, true_xy[1] - 4]])
    res = CMP.compare_position_fix(Z, (tr, tc), L, cell_m=cell, dh_m=0.1743,
                                   fx_px=S.flight_fx_px(6.0), guess_offset_cells=3)
    assert res["ARGUS (articulation parallax)"] < 0.5          # sub-meter standstill fix
    assert res["ShadowNav-class (map-match)"] is not None       # the map-match returns a fix
    assert res["Stanford-class (passive VO)"] is None           # relative VO -> no standalone abs fix


def test_operational_cost_grounded_and_regime_distinct():
    """Operational comparison: the ARGUS standstill fix is energetically cheap + zero-distance
    (grounded lift work); ShadowNav burns continuous illumination in darkness; Stanford is passive."""
    from dart import comparison as CMP
    c = CMP.operational_cost(n_fixes=10, traverse_m=100.0, dark=True)
    a = c["ARGUS"]
    assert a["per_fix_distance_m"] == 0.0                       # standstill
    assert 5.0 < a["per_fix_energy_J"] < 40.0                   # ~17 J chassis lift (grounded)
    assert a["equiv_drive_m"] < 3.0                             # ~the energy of driving ~1 m
    assert a["per_fix_time_s"] > 0                              # but it costs a stop
    # in darkness ShadowNav's own-illumination dwarfs the ARGUS fixes
    assert c["ShadowNav (JPL)"]["extra_mission_energy_J"] > a["extra_mission_energy_J"]
    # Stanford accuracy is EARNED by a coverage + loop-closure driving PATTERN (not free)
    st = c["Stanford NAV Lab (LAC)"]
    assert st["pattern_distance_m"] > 100.0                     # spiral over the 27x27 m region
    assert st["pattern_energy_J"] > a["extra_mission_energy_J"]  # the pattern dwarfs ARGUS's standstill fixes
