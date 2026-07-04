"""[REQ:EG-12] Physics/model control: the frozen validated model is the LIVE default; a deprecated or
unvalidated model cannot be selected for LIVE; the LIVE backend is conserved (release authority); LIVE
resolution refuses a body with no validated profile; non-LIVE modes may select a non-deprecated model."""
import pytest

from stewie.contracts.governance import EnvironmentMode
from stewie.contracts.physics_model_control import (
    LIVE_DEFAULT_MODEL_ID,
    MODELS,
    PhysicsModelRefused,
    get_model,
    list_models,
    live_default_model,
    resolve_live_backend,
    select_backend,
)
from stewie.physics.backend import get_backend


def test_eg12_frozen_validated_model_is_the_live_default():  # [REQ:EG-12]
    m = live_default_model()
    assert m.model_id == LIVE_DEFAULT_MODEL_ID
    assert m.validated is True and m.frozen is True and m.deprecated is False
    assert m.live_eligible is True
    # resolves to the conserved Tier-2 authority (identity with the registered backend singleton).
    backend = resolve_live_backend()
    assert backend is get_backend("tier2_numpy")


def test_eg12_live_default_backend_is_conserved_release_authority():  # [REQ:EG-12]
    info = resolve_live_backend().info()
    assert info.authority_class == "conserved" and info.conserves_mass is True


def test_eg12_unvalidated_model_cannot_be_selected_for_live():  # [REQ:EG-12]
    # the PX-03 Chrono geometry-oracle is a REAL registered model that is not release authority.
    chrono = get_model("tier3_chrono@0.0")
    assert chrono.validated is False and chrono.live_eligible is False
    with pytest.raises(PhysicsModelRefused, match="unvalidated"):
        resolve_live_backend("tier3_chrono@0.0")


def test_eg12_deprecated_model_cannot_be_selected_for_live():  # [REQ:EG-12]
    # deprecation refuses even a model that is otherwise validated + frozen (and whose backend resolves).
    dep = get_model("tier2_numpy@0.1")
    assert dep.validated is True and dep.frozen is True and dep.deprecated is True
    assert dep.live_eligible is False
    with pytest.raises(PhysicsModelRefused, match="deprecated"):
        resolve_live_backend("tier2_numpy@0.1")


def test_eg12_per_body_profile_gate_refuses_a_body_without_a_validated_profile():  # [REQ:EG-12]
    # moon is in the gravity-loaded Bekker regime -> validated profile -> resolves.
    assert resolve_live_backend(body="moon") is get_backend("tier2_numpy")
    # bennu is microgravity (Bekker numbers are a flagged analog) -> no validated LIVE profile -> refused.
    with pytest.raises(PhysicsModelRefused, match="no validated LIVE profile"):
        resolve_live_backend(body="bennu")


def test_eg12_select_backend_composes_environment_mode():  # [REQ:EG-12]
    # LIVE delegates to the strict resolver: the deprecated model is refused.
    with pytest.raises(PhysicsModelRefused):
        select_backend(EnvironmentMode.LIVE, "tier2_numpy@0.1")
    # a non-LIVE mode may select a registered, non-deprecated model (the default) for simulation.
    assert select_backend(EnvironmentMode.REHEARSAL) is get_backend("tier2_numpy")
    assert select_backend("dev") is get_backend("tier2_numpy")
    # a deprecated model is withdrawn from selection in every mode, not only LIVE.
    with pytest.raises(PhysicsModelRefused, match="deprecated"):
        select_backend(EnvironmentMode.REHEARSAL, "tier2_numpy@0.1")


def test_eg12_registry_lists_the_real_models_and_rejects_unknown():  # [REQ:EG-12]
    ids = list_models()
    assert "tier2_numpy@1.0" in ids and "tier2_numpy@0.1" in ids and "tier3_chrono@0.0" in ids
    assert set(ids) == set(MODELS)
    with pytest.raises(KeyError):
        get_model("does_not_exist@9.9")
