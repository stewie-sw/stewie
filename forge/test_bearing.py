"""FORGE bearing-capacity model — sourced-value unit tests (TDD for the CP-06 berm/pad bearing slice).

Anchors the Terzaghi/Vesic shallow-foundation factors against standard textbook values so the model can
never silently drift. No synthetic data: the lunar inputs are the body-sourced regolith params
(constants.py / bodies.py: c=170 Pa, phi=35 deg)."""
import math

from forge import bearing as B


def test_factors_phi0_are_the_prandtl_cohesive_limit():
    nc, nq, ng = B.bearing_capacity_factors(0.0)
    assert abs(nc - 5.14) < 0.01      # Prandtl Nc at phi=0
    assert nq == 1.0 and ng == 0.0    # no surcharge/self-weight gain in a frictionless soil


def test_factors_phi35_match_textbook_tables():
    # Standard tables (Terzaghi/Vesic): for phi=35 deg, Nq~=33.3, Nc~=46.1, Ngamma(Vesic)~=48.0.
    nc, nq, ng = B.bearing_capacity_factors(math.radians(35.0))
    assert abs(nq - 33.30) < 0.4
    assert abs(nc - 46.13) < 0.6
    assert abs(ng - 48.03) < 0.8


def test_qult_monotonic_in_cohesion_and_width():
    base = B.ultimate_bearing_capacity_pa(170.0, math.radians(35.0), 2106.0, 2.0)
    assert B.ultimate_bearing_capacity_pa(340.0, math.radians(35.0), 2106.0, 2.0) > base  # more cohesion
    assert B.ultimate_bearing_capacity_pa(170.0, math.radians(35.0), 2106.0, 4.0) > base  # wider footing


def test_allowable_is_ultimate_over_factor_of_safety():
    q = B.ultimate_bearing_capacity_pa(170.0, math.radians(35.0), 2106.0, 2.0)
    a = B.allowable_bearing_pa(170.0, math.radians(35.0), 2106.0, 2.0, factor_of_safety=3.0)
    assert abs(a - q / 3.0) < 1e-6


def test_surcharge_term_raises_capacity():
    surface = B.ultimate_bearing_capacity_pa(170.0, math.radians(35.0), 2106.0, 2.0, surcharge_depth_m=0.0)
    buried = B.ultimate_bearing_capacity_pa(170.0, math.radians(35.0), 2106.0, 2.0, surcharge_depth_m=0.5)
    assert buried > surface
