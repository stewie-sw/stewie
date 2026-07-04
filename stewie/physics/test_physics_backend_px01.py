"""[REQ:PX-01] PhysicsBackend protocol + tier2_numpy adapter, exercised over the Moon Tier-2 planner-context
path. PX-01 (the §7.A frontend-rewrite lane) is the same seam PX-04 (§7.B) already builds and verifies; this
adds the acceptance PX-01 names explicitly: (a) the Moon plan-context functions the adapter exposes
(static_wheel_load_n -> wheel_static_sinkage -> allowable_bearing_pa) are BYTE-IDENTICAL to calling the real
conserved FORGE functions directly (so `/plan` output is byte-compatible via the adapter, not diff-reviewed),
and (b) the microgravity refusal stays fail-closed (a microgravity body is refused unless an explicit analog
is requested). No synthetic data: every input is a real SOURCED body constant from the registry.
"""
import math

import pytest

from forge.bearing import allowable_bearing_pa
from stewie.physics import terramechanics as TM
from stewie.physics.backend import PhysicsBackend, get_backend
from stewie.physics.body_params import params_for_body
from stewie.specs.bodies import body_in_regime, get_body


def test_moon_plan_context_is_byte_identical_through_the_adapter():  # [REQ:PX-01]
    """The Moon Tier-2 planner-context chain resolved THROUGH get_backend('tier2_numpy') equals calling the
    real conserved functions directly, value-for-value -- the byte-compatible arm of the acceptance."""
    b = get_backend("tier2_numpy")
    assert isinstance(b, PhysicsBackend)                 # satisfies the runtime_checkable protocol
    moon = get_body("moon")
    assert body_in_regime("moon") is True                # Moon is a gravity-loaded Bekker body

    # Soil params: adapter resolution == the direct body_params path (config-overlaid, sourced constants).
    p = b.resolve_soil_params("moon")
    assert p == params_for_body("moon")

    # Per-wheel static load at lunar g with a full 30 kg drum payload (ascend24 "30 kg-class").
    load = b.static_wheel_load_n(payload_kg=30.0, g=moon.g)
    assert load == TM.static_wheel_load_n(payload_kg=30.0, g=moon.g)
    assert load > 0.0

    # Bekker static sinkage under that load -> the adapter delegates VERBATIM to the FORGE authority.
    z = b.wheel_static_sinkage(load, params=p)
    assert z == TM.wheel_static_sinkage(load, params=p)
    assert z > 0.0                                       # a real gravity-loaded sinkage, not a stubbed 0

    # Allowable bearing from the SAME sourced Moon soil (cohesion / friction / unit-weight, 0.15 m footprint).
    args = (moon.cohesion_pa, math.radians(moon.friction_deg), moon.bulk_density * moon.g, 0.15)
    assert b.allowable_bearing_pa(*args) == allowable_bearing_pa(*args)


def test_microgravity_refusal_is_fail_closed_through_the_adapter():  # [REQ:PX-01]
    """resolve_soil_params for a microgravity body (Bennu) is REFUSED by default (the gravity-loaded Bekker
    model is out of regime); the flagged lunar analog is available only when explicitly requested."""
    b = get_backend("tier2_numpy")
    assert body_in_regime("bennu") is False              # microgravity: quantitative sinkage out of regime
    with pytest.raises(ValueError, match="OUT OF REGIME"):
        b.resolve_soil_params("bennu")                   # default fails closed -- no silent microgravity result
    assert b.resolve_soil_params("bennu", allow_analog=True) is not None   # explicit flagged analog allowed
