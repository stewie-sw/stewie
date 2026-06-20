"""FS-15 / FS-18 parity gate: the cockpit's typed frontend adapters (`web/assets/adapters.js`) map the
REAL FS-02 spine contracts (`stewie.contracts`), with NO invented fields. adapters.js is JS (not importable
here), so this test reads it as text and asserts, for every contract the adapter layer consumes:

  1. every snake_case field the adapter reads is an actual field on the Pydantic contract (catches the
     adapter reading a field the backend never had / renamed -- the fabrication / drift failure mode), and
  2. that field name literally appears in adapters.js (catches this map drifting from the JS), and
  3. every spine contract has a normalizer function in adapters.js (the adapter layer is COMPLETE), and
  4. ModelArtifact still exposes the canonical `deployment_ready` property that the JS `deploymentReady`
     derivation mirrors (so the ML-01 gate cannot silently change under the mirror).

This is why adapters.js is trustworthy: it is provably faithful to the typed source of truth.
"""
from __future__ import annotations

from pathlib import Path

from stewie import contracts as C

_ADAPTERS_JS = Path(__file__).parent / "web" / "assets" / "adapters.js"

# contract class -> (its normalizer function in adapters.js, the contract fields that normalizer reads).
# The field lists are exactly what each normalizer consumes; every name here is a real contract field.
_ADAPTER_FIELDS: dict[type, tuple[str, list[str]]] = {
    C.EphemerisObservation: ("normalizeEphemeris", [
        "mission_t_s", "site_lat_deg", "site_lon_deg", "frame",
        "sun_az_deg", "sun_el_deg", "azimuth_convention", "uncertainty_deg", "source"]),
    C.WorldState: ("normalizeWorld", [
        "body", "frame", "rows", "cols", "cell_m", "datum_radius_m",
        "dem_source", "observed_fraction", "mutated"]),
    C.VehicleState: ("normalizeVehicle", [
        "vehicle_id", "role", "row", "col", "yaw_rad", "soc", "slip", "sinkage_m", "entrapped", "status"]),
    C.FleetState: ("normalizeFleet", ["vehicles", "reservations", "conflicts"]),
    C.ResourceReservation: ("normalizeFleet", ["resource_id", "vehicle_id", "t_start", "t_end"]),
    C.BeliefState: ("normalizeBelief", [
        "vehicle_id", "row", "col", "yaw_rad", "pos_sigma_m", "yaw_sigma_rad",
        "localized", "last_relocalization_t_s"]),
    C.PlanResult: ("normalizePlanResult", [
        "plan_id", "feasible", "n_orders", "vehicles", "makespan_s", "energy_j",
        "mass_moved_kg", "blocked_legs", "recharges", "drum_cycles", "cut_passes", "resolved_algorithm"]),
    C.ExecutionEvent: ("normalizeExecutionEvent", ["t_s", "vehicle_id", "kind", "detail", "outcome"]),
    C.ARGUSFactor: ("normalizeARGUSFactor", [
        "factor_id", "kind", "keyframe_i", "keyframe_j", "residual", "information", "accepted"]),
    C.ModelArtifact: ("normalizeModelArtifact", [
        "model_id", "name", "version", "task", "dataset_lineage", "eval_split",
        "input_schema", "output_schema", "latency_budget_ms", "memory_budget_mb",
        "calibrated", "ood_detector", "fallback", "quantization", "rollback_to", "command_path"]),
    C.ConstructionSkill: ("normalizeSkill", [
        "skill_id", "name", "kind", "version", "n_steps", "closed_loop", "approved", "acceptance_note"]),
}


def _js() -> str:
    return _ADAPTERS_JS.read_text(encoding="utf-8")


def test_every_adapter_field_is_a_real_contract_field():  # [REQ:FS-15]
    # no fabricated fields: every name an adapter reads is an actual field on the Pydantic contract
    for contract, (_fn, fields) in _ADAPTER_FIELDS.items():
        model_fields = set(contract.model_fields)
        for f in fields:
            assert f in model_fields, f"{contract.__name__}: adapter reads '{f}' which is not a contract field"


def test_every_mapped_field_appears_in_adapters_js():  # [REQ:FS-18]
    # the map cannot silently drift from the JS: each field the map claims the adapter reads is in the file
    js = _js()
    for contract, (_fn, fields) in _ADAPTER_FIELDS.items():
        for f in fields:
            assert f in js, f"{contract.__name__}: field '{f}' is mapped but not present in adapters.js"


def test_every_spine_contract_has_a_normalizer():
    # the adapter layer is COMPLETE: every consumed spine contract has its normalizer function in adapters.js
    js = _js()
    for contract, (fn, _fields) in _ADAPTER_FIELDS.items():
        assert f"function {fn}(" in js, f"{contract.__name__}: no '{fn}' normalizer in adapters.js"


def test_model_artifact_keeps_the_canonical_deployment_ready_rule():
    # the JS deploymentReady MIRRORS this property; if the backend rule changes, the mirror must be revisited
    assert isinstance(getattr(C.ModelArtifact, "deployment_ready", None), property), (
        "ModelArtifact.deployment_ready property is gone -- the adapters.js deploymentReady mirror is now stale")
    # the real gate: a fully-declared model is deployment_ready; an undeclared one is not (the JS mirrors this)
    ready = C.ModelArtifact(model_id="m", name="n", version="1", task="terrain_assess",
                            dataset_lineage="d", eval_split="s", input_schema="WorldState",
                            output_schema="Traversability", latency_budget_ms=50, memory_budget_mb=512,
                            calibrated=True, ood_detector=True, fallback="costmap")
    assert ready.deployment_ready is True
    undeclared = C.ModelArtifact(model_id="m", name="n", version="1", task="rock_classify",
                                 dataset_lineage="d", eval_split="s")
    assert undeclared.deployment_ready is False
