"""[REQ:BD-01] The BODIES constants become versioned, migratable BodyProfile records with NO value changes.

Proves: every one of the 7 registry bodies (moon/mars/ceres/bennu/phobos/earth/bp1_testbed) has a BodyProfile;
each profile is a version-stamped Contract subclass that round-trips through JSON losslessly; ``to_body``
reconstructs the exact original ``Body`` (value-for-value, so nothing was mutated); and ``params_for_body``
compatibility is preserved -- params built from the profile-reconstructed body equal params_for_body(name),
including the microgravity fail-closed behaviour. Numpy-only (no gymnasium) -> runs in the core suite.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from stewie.contracts import Contract
from stewie.contracts.body_profile import BODY_PROFILES, BodyProfile, body_profile
from stewie.specs.bodies import BODIES, get_body, params_for_body

EXPECTED = {"moon", "mars", "ceres", "bennu", "phobos", "earth", "bp1_testbed"}


def test_bd01_every_body_has_a_profile():  # [REQ:BD-01]
    assert set(BODY_PROFILES) == set(BODIES) == EXPECTED
    for key in BODIES:
        prof = body_profile(key)
        assert isinstance(prof, BodyProfile)
        assert prof.id == key


def test_bd01_profile_is_a_versioned_contract():  # [REQ:BD-01]
    prof = body_profile("moon")
    assert isinstance(prof, Contract)
    assert prof.schema_version  # inherited from Contract -> migratable
    # frozen: a snapshot is immutable
    with pytest.raises(ValidationError):
        prof.g = 9.81  # type: ignore[misc]
    # extra='forbid': unknown fields are rejected at the boundary
    with pytest.raises(ValidationError):
        BodyProfile(id="x", name="x", label="X", g=1.0, bekker_regime="gravity-loaded", made_up=1)


def test_bd01_to_body_reconstructs_the_exact_body_no_value_changes():  # [REQ:BD-01]
    # the core acceptance: converting to a profile and back is value-for-value identical to the original.
    for key, body in BODIES.items():
        assert body_profile(key).to_body() == body


def test_bd01_profile_json_round_trip_is_lossless():  # [REQ:BD-01]
    # migratable: serialize -> deserialize yields an equal profile (schema_version + all fields preserved).
    for key in BODIES:
        prof = body_profile(key)
        back = BodyProfile.model_validate_json(prof.model_dump_json())
        assert back == prof
        assert back.to_body() == BODIES[key]


def test_bd01_params_for_body_compat_is_preserved():  # [REQ:BD-01]
    # params built from the profile-reconstructed body match params_for_body(name) -- unchanged behaviour,
    # including the microgravity fail-closed contract (Bennu/Phobos refuse unless allow_analog).
    for key, body in BODIES.items():
        prof_body = body_profile(key).to_body()
        if body.bekker_regime == "microgravity":
            with pytest.raises(ValueError):
                params_for_body(prof_body)
            assert params_for_body(prof_body, allow_analog=True) == params_for_body(key, allow_analog=True)
        else:
            assert params_for_body(prof_body) == params_for_body(key)


def test_bd01_key_soil_constants_carried_verbatim():  # [REQ:BD-01]
    # spot-check the sourced values ride through the profile unchanged (no silent rescaling).
    moon = body_profile("moon")
    assert moon.g == 1.62
    assert moon.bekker == (1400.0, 820000.0, 1.0)   # NASA LTV lunar moduli
    assert moon.cohesion_pa == 170.0
    assert body_profile("mars").bekker == (23200.0, 606700.0, 1.0)   # GRC-3 simulant
    assert body_profile("ceres").bekker is None     # unsourced -> stays None (not fabricated)
    assert body_profile("bennu").bekker_regime == "microgravity"


def test_bd01_body_profile_accepts_a_body_and_is_case_insensitive():  # [REQ:BD-01]
    assert body_profile("MOON").id == "moon"
    assert body_profile(get_body("mars")).id == "mars"
    with pytest.raises(KeyError):
        body_profile("pluto")   # unknown -> same error contract as get_body
