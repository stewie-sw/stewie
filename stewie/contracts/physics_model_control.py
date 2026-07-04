"""[REQ:EG-12] Physics/model control -- a versioned physics-model registry + the LIVE-default rule
(PRD §29.8 "Physics/Model Control", §7 EG-12).

The control plane over the selectable physics backends (stewie.physics.backend: get_backend / list_backends /
PhysicsBackendInfo). §29.8 requires the platform to track "Forge+Chrono versions / regolith+body profiles /
terramechanics params / calibration / validation / backend selection / freeze / deprecate". This module is that
ledger plus the one rule that keeps LIVE safe:

  the model that drives a LIVE mission (EnvironmentMode.LIVE -- the only mode that commands real robots, EG-01)
  must be the FROZEN, VALIDATED, non-deprecated default, and its backend must be CONSERVED (release authority;
  PhysicsBackendInfo.authority_class == "conserved" / conserves_mass -- the rule the backend PROTOCOL already
  states: a non-mass-conserving backend cannot claim release/execute authority). An UNVALIDATED model (the
  PX-03 Chrono geometry-oracle, deliberately NOT release authority until it conserves mass) or a DEPRECATED
  model (a superseded params version) is REFUSED for LIVE.

Per-body validation is REAL, not a bare flag: the Tier-2 pressure-sinkage model is validated only for bodies IN
the gravity-loaded Bekker regime (moon/mars/ceres/earth/bp1_testbed); at microgravity bodies (bennu/phobos) the
Bekker numbers are only a flagged analog (stewie.specs.bodies.body_in_regime is False), so LIVE resolution for
such a body is refused rather than silently trusted. resolve_live_backend() is the strict LIVE resolver;
select_backend() composes EnvironmentMode so non-LIVE modes (dev/training/rehearsal) may select any registered,
non-deprecated model for simulation.
"""
from __future__ import annotations

from dataclasses import dataclass

from stewie.contracts.governance import EnvironmentMode
from stewie.physics.backend import PhysicsBackend, get_backend
from stewie.specs import bodies as B


class PhysicsModelRefused(PermissionError):
    """Raised when a physics model is selected for LIVE that is not the frozen-validated default: it is
    unvalidated, not frozen, deprecated, backed by a non-conserved backend, or lacks a validated profile for the
    requested body. The single typed refusal the LIVE resolver raises (fail-closed)."""


@dataclass(frozen=True)
class PhysicsModel:
    """A registered, VERSIONED physics model in the control-backend ledger (§29.8). ``backend_id`` selects the
    stewie.physics.backend the model runs on; ``validated`` / ``frozen`` / ``deprecated`` are the governance
    flags the Physics/Model Control admin section toggles; ``calibration`` is the calibration/validation status
    string; and ``validated_bodies`` are the per-body/regolith profiles the model is validated for (a body
    absent here has no validated LIVE profile). LIVE-eligibility of the model STATUS is validated AND frozen AND
    NOT deprecated (``live_eligible``); the conserved-backend + per-body checks are applied at resolution."""
    model_id: str
    backend_id: str
    version: str
    validated: bool
    frozen: bool
    deprecated: bool
    calibration: str
    validated_bodies: tuple[str, ...] = ()
    notes: str = ""

    @property
    def live_eligible(self) -> bool:
        """The §7 EG-12 model-status rule: only a FROZEN, VALIDATED, non-deprecated model may be a LIVE default.
        The backend-conservation + per-body-profile checks are applied separately at resolution."""
        return self.validated and self.frozen and not self.deprecated


#: Bodies whose Tier-2 Bekker pressure-sinkage model is VALIDATED (gravity-loaded regime). Derived from the real
#: stewie.specs.bodies registry -- microgravity bodies (bennu/phobos) are EXCLUDED because there the Bekker
#: numbers are only a flagged analog, not predictive, so LIVE resolution for them is refused.
_TIER2_VALIDATED_BODIES: tuple[str, ...] = tuple(name for name in B.BODIES if B.body_in_regime(name))


#: The §29.8 physics-model ledger. REAL entries only: the conserved Tier-2 authority (the LIVE default), the
#: superseded pre-load-bearing baseline (deprecated), and the PX-03 Chrono geometry-oracle (unvalidated for
#: release). Multiple model VERSIONS may map to one backend id -- versioning is a params/calibration property,
#: independent of which engine resolves the terramechanics.
MODELS: dict[str, PhysicsModel] = {
    "tier2_numpy@1.0": PhysicsModel(
        model_id="tier2_numpy@1.0", backend_id="tier2_numpy", version="1.0",
        validated=True, frozen=True, deprecated=False, calibration="sourced-analog",
        validated_bodies=_TIER2_VALIDATED_BODIES,
        notes="Load-bearing Bekker/Wong-Reece + slip + mass-conserving compaction; the conserved sim authority "
              "(roversim Phase 1-2, 636f062/49c06bf/418858e). Body params sourced (Apollo/ChaSTE, MER/InSight, "
              "NASA LTV); microgravity bodies carry only a flagged analog and are excluded from LIVE."),
    "tier2_numpy@0.1": PhysicsModel(
        model_id="tier2_numpy@0.1", backend_id="tier2_numpy", version="0.1",
        validated=True, frozen=True, deprecated=True, calibration="superseded",
        validated_bodies=("moon",),
        notes="DEPRECATED: the pre-load-bearing baseline (hardcoded 0.12 compaction; the Bekker moduli were "
              "decorative, read by nothing). Superseded 2026-06-01 by the load-bearing solve (636f062/49c06bf). "
              "Kept as a ledger record; validated+frozen but deprecated -> never a LIVE default."),
    "tier3_chrono@0.0": PhysicsModel(
        model_id="tier3_chrono@0.0", backend_id="tier2_chrono", version="0.0",
        validated=False, frozen=False, deprecated=False, calibration="uncalibrated",
        validated_bodies=(),
        notes="PX-03 Chrono/hybrid geometry oracle: a Tier-3 engine that does NOT yet conserve mass, so it is "
              "NOT release authority (deliberately unvalidated for LIVE until the euclid PyChrono oracle "
              "calibration, FIX-1/FIX-2, lands). Selectable for rehearsal/sim, never for LIVE."),
}

#: The frozen-validated LIVE default (§7 EG-12: "the frozen validated model is the LIVE default").
LIVE_DEFAULT_MODEL_ID = "tier2_numpy@1.0"


def list_models() -> list[str]:
    """Every registered physics-model id (the §29.8 ledger keys), sorted."""
    return sorted(MODELS)


def get_model(model_id: str) -> PhysicsModel:
    """Resolve a registered physics model by id. Raises KeyError on an unknown model."""
    m = MODELS.get(model_id)
    if m is None:
        raise KeyError(f"unknown physics model {model_id!r}; registered: {sorted(MODELS)}")
    return m


def live_default_model() -> PhysicsModel:
    """The frozen-validated LIVE-default model (§7 EG-12). Its live-eligibility is re-checked at resolution."""
    return get_model(LIVE_DEFAULT_MODEL_ID)


def resolve_live_backend(model_id: str | None = None, *, body: str | None = None) -> PhysicsBackend:
    """Resolve the PhysicsBackend a LIVE mission may run on. Returns ONLY a frozen-validated, non-deprecated
    model's CONSERVED backend; RAISES PhysicsModelRefused on any other selection (unvalidated, not frozen,
    deprecated, a non-conserved backend, or a body without a validated profile). ``model_id=None`` -> the LIVE
    default. This is the §7 EG-12 acceptance rule: the frozen validated model is the LIVE default; a
    deprecated/unvalidated model cannot be selected for LIVE."""
    model = get_model(model_id) if model_id is not None else live_default_model()

    # 1) model-status gate (the EG-12 rule): validated AND not deprecated AND frozen. Checked BEFORE resolving
    #    the backend, so an unvalidated/deprecated model is refused by GOVERNANCE, not merely by a missing engine.
    if not model.validated:
        raise PhysicsModelRefused(
            f"model {model.model_id!r} is unvalidated (calibration {model.calibration!r}) "
            f"-- cannot be selected for LIVE")
    if model.deprecated:
        raise PhysicsModelRefused(f"model {model.model_id!r} is deprecated -- cannot be selected for LIVE")
    if not model.frozen:
        raise PhysicsModelRefused(f"model {model.model_id!r} is not frozen -- cannot be selected for LIVE")

    # 2) backend-conservation gate: compose the conserved-mass / authority_class the backend already exposes.
    backend = get_backend(model.backend_id)
    info = backend.info()
    if info.authority_class != "conserved" or not backend.conserves_mass():
        raise PhysicsModelRefused(
            f"model {model.model_id!r} backend {model.backend_id!r} is not conserved "
            f"(authority_class={info.authority_class!r}) -- cannot drive LIVE execution")

    # 3) per-body/regolith-profile gate: the model must carry a validated profile for the requested body.
    if body is not None and body not in model.validated_bodies:
        raise PhysicsModelRefused(
            f"model {model.model_id!r} has no validated LIVE profile for body {body!r} "
            f"(validated for {list(model.validated_bodies)})")
    return backend


def select_backend(mode: EnvironmentMode | str, model_id: str | None = None, *,
                   body: str | None = None) -> PhysicsBackend:
    """Select a physics backend for an environment MODE (composes EG-01 governance). In LIVE this is the strict
    resolve_live_backend (frozen-validated default only). In any non-LIVE mode (dev/training/rehearsal/replay/
    archive) a registered, non-deprecated model may be selected for simulation; a deprecated model is refused
    everywhere (it is withdrawn), and an unimplemented backend raises honestly at get_backend (never stubbed)."""
    if EnvironmentMode(mode) is EnvironmentMode.LIVE:
        return resolve_live_backend(model_id, body=body)
    model = get_model(model_id) if model_id is not None else live_default_model()
    if model.deprecated:
        raise PhysicsModelRefused(f"model {model.model_id!r} is deprecated -- withdrawn from selection")
    return get_backend(model.backend_id)
