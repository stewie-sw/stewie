"""[REQ:PX-04] The PhysicsBackend seam. Tier2NumpyBackend is a byte-identical passthrough over the existing
terramechanics / FORGE bearing / body-params functions, behind a self-describing interface (authority_class +
conserves_mass). The conserved authority stays the only terrain mutator; a backend that does not conserve mass
cannot claim release authority."""
import math

import pytest

from forge.bearing import allowable_bearing_pa
from stewie.physics import terramechanics as TM
from stewie.physics.backend import (
    PhysicsBackend,
    get_backend,
    list_backends,
)
from stewie.physics.body_params import params_for_body


def test_tier2_info_reports_conserved_authority():  # [REQ:PX-04]
    b = get_backend("tier2_numpy")
    assert isinstance(b, PhysicsBackend)                 # satisfies the runtime_checkable protocol
    info = b.info()
    assert info.authority_class == "conserved"
    assert info.conserves_mass is True and b.conserves_mass() is True
    assert info.fidelity_tier == 2


def test_resolve_soil_params_matches_params_for_body():  # [REQ:PX-04]
    b = get_backend()
    assert b.resolve_soil_params("moon") == params_for_body("moon")     # byte-compatible with the direct path
    with pytest.raises(ValueError):
        b.resolve_soil_params("bennu")                                  # microgravity fail-closed carries through
    b.resolve_soil_params("bennu", allow_analog=True)                   # explicit analog allowed


def test_delegations_are_byte_identical():  # [REQ:PX-04]
    b = get_backend()
    p = b.resolve_soil_params("moon")
    assert b.wheel_static_sinkage(1200.0, params=p) == TM.wheel_static_sinkage(1200.0, params=p)
    args = (170.0, math.radians(35.0), 1500.0 * 1.62, 0.15)
    assert b.allowable_bearing_pa(*args) == allowable_bearing_pa(*args)


def test_registry():  # [REQ:PX-04]
    assert "tier2_numpy" in list_backends()
    with pytest.raises(ValueError):
        get_backend("chrono")                                           # unknown / not registered (PX-03 gated)
