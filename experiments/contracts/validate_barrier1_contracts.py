"""Validate the additive Barrier-1 research closure packet.

The packet intentionally distinguishes a machine-valid design from an acceptance-ready
preregistration. Validation succeeds when the contracts are internally coherent; the returned
``acceptance_ready`` flag remains false while calibration, materialization, implementation hashes,
runtime isolation, and independent review are pending.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = ROOT / "experiments" / "contracts"
ORACLE_ROOT = CONTRACT_ROOT / "metric_oracles"

REQUIRED_SYSTEM_IDS = {
    "B-LWW",
    "B-TS",
    "B-VERSION",
    "B-REPLACE",
    "B-BITEMP",
    "B-NOPROV",
    "B-PROV",
    "B-SINGLE",
    "B-CRDT",
    "B-CENTRAL",
    "B-LOCAL",
    "B-LIFELONG",
    "B-MRMAP",
    "B-IVF",
    "B-CI",
    "A-NOPHYS",
    "A-INDEP",
    "A-GLOBAL",
    "A-NOUNC",
    "A-NOPROVGATE",
    "P-STEWIE",
}
REQUIRED_MECHANISM_CELLS = {"P0D0", "P1D0", "P0D1", "P1D1"}
REQUIRED_HYPOTHESES = {f"H{index}" for index in range(1, 8)}
OUTCOME_METRICS = {
    "harmful_acceptance_rate",
    "availability",
    "abstention_rate",
    "execution_failure_rate",
    "incorrect_overwrite_rate",
}


class ContractError(ValueError):
    """Raised when a closure contract is internally inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def require_fields(record: Mapping[str, Any], fields: set[str], context: str) -> None:
    missing = sorted(fields - set(record))
    require(not missing, f"{context}: missing fields {missing}")


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path.relative_to(ROOT)}: root must be a mapping")
    return value


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path.relative_to(ROOT)}: root must be an object")
    return value


def close(left: float, right: float, *, tolerance: float = 1e-12) -> bool:
    return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)


def validate_registry(registry: Mapping[str, Any]) -> set[str]:
    require_fields(
        registry,
        {
            "schema_version",
            "artifact_id",
            "status",
            "evidence_level",
            "empirical_results",
            "calibration_state",
            "systems",
            "mechanism_cells",
            "acceptance_blockers",
        },
        "baseline registry",
    )
    require(registry["schema_version"] == "stewie.baseline_registry/1.0", "registry schema")
    require(registry["empirical_results"] is None, "registry must not invent empirical results")
    calibration = registry["calibration_state"]
    require(isinstance(calibration, Mapping), "calibration_state must be a mapping")
    require(
        calibration.get("confirmatory_execution_allowed") is False,
        "provisional baseline registry must forbid confirmatory execution",
    )

    systems = registry["systems"]
    require(isinstance(systems, list), "systems must be a list")
    ids = [system.get("id") for system in systems if isinstance(system, Mapping)]
    require(len(ids) == len(systems), "every system must be a mapping with an ID")
    require(len(ids) == len(set(ids)), "baseline/system IDs must be unique")
    require(REQUIRED_SYSTEM_IDS <= set(ids), f"missing required systems {sorted(REQUIRED_SYSTEM_IDS - set(ids))}")

    required_system_fields = {
        "id",
        "role",
        "owner_node",
        "version",
        "implementation_status",
        "config",
        "license",
        "adapter",
        "input_equivalence",
        "compute_cap",
        "confirmatory_ready",
    }
    for system in systems:
        assert isinstance(system, Mapping)
        system_id = str(system["id"])
        require_fields(system, required_system_fields, system_id)
        require(isinstance(system["version"], str) and system["version"], f"{system_id}: empty version")
        require(isinstance(system["owner_node"], str) and system["owner_node"], f"{system_id}: empty owner")
        config = system["config"]
        require(isinstance(config, Mapping), f"{system_id}: config must be a mapping")
        require_fields(config, {"config_id", "parameters", "content_hash_status"}, f"{system_id}.config")
        require(isinstance(config["parameters"], Mapping), f"{system_id}: config parameters must be exact mapping")
        license_record = system["license"]
        require(isinstance(license_record, Mapping), f"{system_id}: license must be a mapping")
        require_fields(
            license_record,
            {"expression", "source", "redistribution_allowed", "status"},
            f"{system_id}.license",
        )
        adapter = system["adapter"]
        require(isinstance(adapter, Mapping), f"{system_id}: adapter must be a mapping")
        require_fields(adapter, {"adapter_id", "version", "status"}, f"{system_id}.adapter")
        equivalence = system["input_equivalence"]
        require(isinstance(equivalence, Mapping), f"{system_id}: input equivalence must be a mapping")
        require_fields(
            equivalence,
            {"contract_id", "equal_fields", "forbidden_fields", "assertion_status"},
            f"{system_id}.input_equivalence",
        )
        cap = system["compute_cap"]
        require(isinstance(cap, Mapping), f"{system_id}: compute cap must be a mapping")
        require_fields(
            cap,
            {"profile_id", "cpu_cores", "memory_mib", "gpu_count", "wall_time_s_per_trial", "timeout_outcome"},
            f"{system_id}.compute_cap",
        )
        require(system["confirmatory_ready"] is False, f"{system_id}: no implementation is yet confirmatory-ready")

    cells = registry["mechanism_cells"]
    require(isinstance(cells, list), "mechanism_cells must be a list")
    cell_ids = {cell.get("id") for cell in cells if isinstance(cell, Mapping)}
    require(cell_ids == REQUIRED_MECHANISM_CELLS, "mechanism cells must be exactly P0D0/P1D0/P0D1/P1D1")
    for cell in cells:
        assert isinstance(cell, Mapping)
        require(cell.get("parent_system") == "P-STEWIE", f"{cell.get('id')}: wrong parent system")
        require(isinstance(cell.get("provenance_admission"), bool), f"{cell.get('id')}: provenance flag")
        require(isinstance(cell.get("pairwise_dependency"), bool), f"{cell.get('id')}: dependency flag")
    observed_cells = {
        (bool(cell["provenance_admission"]), bool(cell["pairwise_dependency"])) for cell in cells
    }
    require(observed_cells == {(False, False), (True, False), (False, True), (True, True)}, "factorial cells incomplete")
    return set(ids) | cell_ids


def validate_hypotheses(contracts: Mapping[str, Any], known_systems: set[str]) -> None:
    require_fields(
        contracts,
        {
            "schema_version",
            "status",
            "evidence_level",
            "empirical_results",
            "confirmatory_execution_allowed",
            "value_status",
            "common",
            "hypotheses",
        },
        "hypothesis contracts",
    )
    require(contracts["schema_version"] == "stewie.hypothesis_contracts/1.0", "hypothesis schema")
    require(contracts["empirical_results"] is None, "hypothesis packet must not include results")
    require(contracts["confirmatory_execution_allowed"] is False, "provisional hypotheses must block execution")
    hypotheses = contracts["hypotheses"]
    require(isinstance(hypotheses, list), "hypotheses must be a list")
    ids = {item.get("id") for item in hypotheses if isinstance(item, Mapping)}
    require(ids == REQUIRED_HYPOTHESES, f"hypothesis IDs differ: {sorted(ids)}")

    required = {
        "id",
        "research_question",
        "title",
        "domain",
        "scenario_family",
        "candidate_system",
        "comparators",
        "confirmatory_comparators",
        "primary_endpoint",
        "estimand",
        "multiplicity",
        "minimum_effect",
        "bounds",
        "availability",
        "falsification",
    }
    for hypothesis in hypotheses:
        assert isinstance(hypothesis, Mapping)
        hypothesis_id = str(hypothesis["id"])
        require_fields(hypothesis, required, hypothesis_id)
        require(hypothesis["research_question"] == f"RQ{hypothesis_id[1:]}", f"{hypothesis_id}: RQ mismatch")
        candidate = hypothesis["candidate_system"]
        comparators = hypothesis["comparators"]
        require(candidate in known_systems, f"{hypothesis_id}: unknown candidate {candidate}")
        require(isinstance(comparators, list) and comparators, f"{hypothesis_id}: comparators missing")
        unknown = set(comparators) - known_systems
        require(not unknown, f"{hypothesis_id}: unknown comparators {sorted(unknown)}")
        confirmatory = hypothesis["confirmatory_comparators"]
        require(
            isinstance(confirmatory, list) and confirmatory,
            f"{hypothesis_id}: confirmatory comparators missing",
        )
        require(
            set(confirmatory) <= set(comparators),
            f"{hypothesis_id}: confirmatory comparator absent from comparator set",
        )
        require(
            isinstance(hypothesis["multiplicity"], str) and hypothesis["multiplicity"],
            f"{hypothesis_id}: multiplicity rule missing",
        )
        domain = hypothesis["domain"]
        require(isinstance(domain, Mapping), f"{hypothesis_id}: domain must be a mapping")
        require_fields(domain, {"id", "body", "site", "mode", "generality_claim"}, f"{hypothesis_id}.domain")
        require(domain["generality_claim"] is False, f"{hypothesis_id}: bounded packet cannot claim generality")
        endpoint = hypothesis["primary_endpoint"]
        require(isinstance(endpoint, Mapping), f"{hypothesis_id}: endpoint must be a mapping")
        require_fields(endpoint, {"metric", "direction", "aggregation"}, f"{hypothesis_id}.primary_endpoint")
        estimand = hypothesis["estimand"]
        require(isinstance(estimand, Mapping), f"{hypothesis_id}: estimand must be a mapping")
        require_fields(estimand, {"id", "formula", "favorable_direction"}, f"{hypothesis_id}.estimand")
        effect = hypothesis["minimum_effect"]
        require(isinstance(effect, Mapping), f"{hypothesis_id}: minimum effect must be a mapping")
        require_fields(effect, {"value", "units", "basis", "calibration_status"}, f"{hypothesis_id}.minimum_effect")
        require(isinstance(effect["value"], (int, float)) and effect["value"] >= 0, f"{hypothesis_id}: invalid MDE")
        if hypothesis_id == "H6":
            require(effect["value"] == 0.0, "H6 is a conformance threshold, not an improvement MDE")
            require(effect["calibration_status"] == "not_applicable", "H6 calibration label")
        else:
            require(effect["value"] > 0.0, f"{hypothesis_id}: provisional MDE must be positive")
            require(
                effect["basis"] == "provisional_operational_assumption"
                and effect["calibration_status"] == "not_calibrated",
                f"{hypothesis_id}: provisional MDE is overclaimed",
            )
        bounds = hypothesis["bounds"]
        require(isinstance(bounds, Mapping), f"{hypothesis_id}: bounds must be a mapping")
        require(bounds.get("status") in {"provisional_exact_levels", "fixed_from_performance_budget"}, f"{hypothesis_id}: bound status")
        for name, levels in bounds.items():
            if name == "status":
                continue
            require(isinstance(levels, list) and levels, f"{hypothesis_id}.bounds.{name}: levels required")
        availability = hypothesis["availability"]
        require(isinstance(availability, Mapping), f"{hypothesis_id}: availability must be a mapping")
        require_fields(
            availability,
            {"metric", "comparator", "max_absolute_decrease", "decision"},
            f"{hypothesis_id}.availability",
        )
        require(
            isinstance(availability["max_absolute_decrease"], (int, float))
            and 0 <= availability["max_absolute_decrease"] <= 1,
            f"{hypothesis_id}: invalid availability margin",
        )
        require(isinstance(hypothesis["falsification"], list) and hypothesis["falsification"], f"{hypothesis_id}: falsification missing")

    h7 = next(item for item in hypotheses if item["id"] == "H7")
    require(set(h7["comparators"]) == REQUIRED_MECHANISM_CELLS, "H7 must use all four factorial cells")
    require(
        h7["estimand"]["formula"] == "-((Y_P1D1 - Y_P1D0) - (Y_P0D1 - Y_P0D0))",
        "H7 interaction formula changed",
    )
    h3 = next(item for item in hypotheses if item["id"] == "H3")
    gates = h3.get("structural_gates", [])
    require(any("arbitrary physics-predicted bytes" in gate for gate in gates), "H3 noninterference gate missing")


def _allocation_ids(allocation: Mapping[str, Any]) -> tuple[set[str], set[str], set[int]]:
    units = allocation.get("units", [])
    require(isinstance(units, list) and units, f"{allocation.get('phase')}: units missing")
    unit_ids = [unit.get("unit_id") for unit in units if isinstance(unit, Mapping)]
    window_ids = [unit.get("window_id") for unit in units if isinstance(unit, Mapping)]
    require(len(unit_ids) == len(units), f"{allocation.get('phase')}: malformed units")
    require(len(unit_ids) == len(set(unit_ids)), f"{allocation.get('phase')}: duplicate unit IDs")
    seeds = allocation.get("seeds", [])
    require(isinstance(seeds, list) and seeds, f"{allocation.get('phase')}: seeds missing")
    require(len(seeds) == len(set(seeds)), f"{allocation.get('phase')}: duplicate seeds")
    return set(unit_ids), set(window_ids), set(seeds)


def validate_allocations(pilot: Mapping[str, Any], evaluation: Mapping[str, Any]) -> None:
    for allocation, expected_phase, expected_units in (
        (pilot, "pilot", 4),
        (evaluation, "evaluation", 24),
    ):
        require(allocation.get("schema_version") == "stewie.unit_seed_allocation/1.0", f"{expected_phase}: schema")
        require(allocation.get("phase") == expected_phase, f"{expected_phase}: phase")
        require(allocation.get("executed") is False, f"{expected_phase}: execution must not be claimed")
        require(allocation.get("empirical_results") is None, f"{expected_phase}: results must be null")
        require(allocation.get("execution_allowed") is False, f"{expected_phase}: execution must remain blocked")
        require(allocation.get("spatial_disjointness_verified") is False, f"{expected_phase}: spatial proof is pending")
        units = allocation.get("units", [])
        seeds = allocation.get("seeds", [])
        require(allocation.get("unit_count") == expected_units == len(units), f"{expected_phase}: unit count")
        require(allocation.get("seeds_per_unit") == len(seeds), f"{expected_phase}: seeds per unit")
        require(
            allocation.get("unit_seed_pair_count") == len(units) * len(seeds),
            f"{expected_phase}: unit-seed pair count",
        )
        _allocation_ids(allocation)

    pilot_units, pilot_windows, pilot_seeds = _allocation_ids(pilot)
    eval_units, eval_windows, eval_seeds = _allocation_ids(evaluation)
    require(not (pilot_units & eval_units), "pilot/evaluation unit IDs overlap")
    require(not (pilot_windows & eval_windows), "pilot/evaluation window IDs overlap")
    require(not (pilot_seeds & eval_seeds), "pilot/evaluation seeds overlap")
    require(evaluation.get("unique_window_count") == len(eval_windows) == 8, "evaluation window count")
    window_action_counts = Counter(
        unit["window_id"] for unit in evaluation["units"] if isinstance(unit, Mapping)
    )
    require(set(window_action_counts.values()) == {3}, "each evaluation window must have three action geometries")


def validate_dependency_oracle(record: Mapping[str, Any]) -> None:
    require(record.get("schema_version") == "stewie.dependency_oracle_design/1.0", "dependency schema")
    require(record.get("empirical_results") is None, "dependency design cannot contain results")
    require(record.get("confirmatory_execution_allowed") is False, "dependency design must block execution")
    generator = record.get("generator", {})
    require(generator.get("candidate_visible") is False, "dependency generator must be evaluator-only")
    require(generator.get("estimator_import_allowed") is False, "estimator cannot import oracle generator")
    require(generator.get("generated_after_candidate_action_report_freeze") is True, "oracle generation ordering")
    oracle = record.get("oracle", {})
    require(oracle.get("visibility") == "evaluator_only", "dependency oracle visibility")
    require(oracle.get("candidate_mount") == "absent", "candidate must have no dependency-oracle mount")
    cells = record.get("factorial_cells", [])
    require(isinstance(cells, list) and len(cells) == 4, "dependency factorial requires four cells")
    observed = {
        (
            bool(cell.get("candidate_reported_action_overlap")),
            bool(cell.get("evaluator_error_correlation")),
        )
        for cell in cells
        if isinstance(cell, Mapping)
    }
    require(observed == {(False, False), (True, False), (False, True), (True, True)}, "dependency negative controls incomplete")
    perturbations = record.get("action_report_perturbations", {})
    require(perturbations.get("application_order") == "after_error_oracle_generation", "circular dependency generation")
    poison_tests = record.get("required_poison_tests", [])
    require(len(poison_tests) >= 3, "dependency oracle poison tests missing")


def validate_firewall(record: Mapping[str, Any]) -> None:
    require(record.get("schema_version") == "stewie.reference_firewall_design/1.0", "firewall schema")
    require(record.get("empirical_results") is None, "firewall design cannot contain results")
    require(record.get("confirmatory_execution_allowed") is False, "firewall must block confirmatory execution")
    processes = record.get("processes", {})
    candidate = processes.get("candidate", {})
    evaluator = processes.get("evaluator", {})
    for field in ("process_id", "identity", "credential_id", "network_namespace"):
        require(candidate.get(field) != evaluator.get(field), f"firewall: {field} must differ")
    isolation = record.get("isolation", {})
    require(isolation.get("candidate_reference_access") is False, "candidate reference access")
    require(isolation.get("evaluator_reference_access") is True, "evaluator reference access")
    require(isolation.get("evaluator_mount_time") == "after_candidate_exit_and_output_freeze", "mount ordering")
    projection = record.get("candidate_view_projection", {})
    excluded = set(projection.get("exclude", []))
    required_exclusions = {
        "withheld_execution_truth_manifest_id",
        "withheld_execution_truth_content_hash",
        "evaluator_dependency_oracle_id",
        "unavailable_claim_ids",
        "unavailable_claim_count",
        "poison_variant_id",
    }
    require(required_exclusions <= excluded, "candidate projection leaks evaluator metadata")
    require(record.get("attestation", {}).get("status") == "not_executed", "firewall attestation overclaimed")
    require(record.get("attestation", {}).get("poison_test_results") is None, "firewall results must be null")
    require(len(record.get("permission_probes", [])) >= 4, "firewall permission probes missing")
    require(len(record.get("poison_tests", [])) >= 4, "firewall poison tests missing")


def validate_metric_oracles() -> None:
    fixtures = {path.stem: load_json(path) for path in sorted(ORACLE_ROOT.glob("*.json"))}
    require(
        set(fixtures) == {
            "temporal_metrics",
            "reconciliation_metrics",
            "provenance_metrics",
            "decision_metrics",
            "interaction_metrics",
            "performance_metrics",
        },
        "metric oracle fixture set changed",
    )
    for name, fixture in fixtures.items():
        require(
            fixture.get("status") == "synthetic_oracle_fixture_not_empirical_result",
            f"{name}: fixture status overclaims evidence",
        )

    temporal = fixtures["temporal_metrics"]
    values = temporal["inputs"]
    observed = {
        "stale_overwrite_rate": values["stale_promotions"] / values["promotion_opportunities"],
        "valid_time_query_accuracy": values["valid_time_exact_matches"] / values["valid_time_queries"],
        "transaction_time_query_accuracy": (
            values["transaction_time_exact_matches"] / values["transaction_time_queries"]
        ),
    }
    for metric, value in observed.items():
        require(close(value, temporal["expected"][metric]), f"temporal oracle mismatch: {metric}")

    reconciliation = fixtures["reconciliation_metrics"]
    tolerance = reconciliation["harm_tolerance"]
    require(tolerance["metric"] not in OUTCOME_METRICS, "task harm tolerance cannot be an outcome rate")
    require(isinstance(tolerance.get("unit"), str) and tolerance["unit"], "task harm tolerance requires units")
    trials = reconciliation["trials"]
    total = len(trials)
    promoted = [trial for trial in trials if trial["outcome"] == "PROMOTE"]
    harmful = [trial for trial in promoted if trial["state_error"] > tolerance["tau"]]
    abstained = [trial for trial in trials if trial["outcome"] == "ABSTAIN"]
    failed = [trial for trial in trials if trial["outcome"] == "EXECUTION_FAILURE"]
    conflicts = reconciliation["conflicts"]
    overwrites = reconciliation["overwrites"]
    rec_observed = {
        "harmful_acceptance_rate": len(harmful) / total,
        "availability": len(promoted) / total,
        "abstention_rate": len(abstained) / total,
        "execution_failure_rate": len(failed) / total,
        "conflict_retention_recall": conflicts["true_conflicts_retained"] / conflicts["true_conflicts"],
        "conflict_retention_precision": conflicts["true_conflicts_retained"] / conflicts["all_retained_conflicts"],
        "incorrect_overwrite_rate": overwrites["incorrect_advances"] / overwrites["advance_opportunities"],
    }
    require(
        close(
            rec_observed["availability"]
            + rec_observed["abstention_rate"]
            + rec_observed["execution_failure_rate"],
            1.0,
        ),
        "availability/abstention/failure partition",
    )
    for metric, value in rec_observed.items():
        require(close(value, reconciliation["expected"][metric]), f"reconciliation oracle mismatch: {metric}")

    provenance = fixtures["provenance_metrics"]
    values = provenance["inputs"]
    prov_observed = {
        "explanation_edge_precision": values["correct_predicted_typed_edges"] / values["predicted_typed_edges"],
        "explanation_edge_recall": values["correct_predicted_typed_edges"] / values["oracle_typed_edges"],
        "decision_replay_rate": values["successful_replays"] / values["replay_attempts"],
        "automated_correction_latency_sequences": (
            values["durable_corrected_head_sequence"] - values["first_corrective_evidence_sequence"]
        ),
    }
    for metric, value in prov_observed.items():
        require(close(value, provenance["expected"][metric]), f"provenance oracle mismatch: {metric}")

    decision = fixtures["decision_metrics"]
    value = decision["inputs"]["unique_harmful_plan_commits"] / decision["inputs"]["plan_commit_opportunities"]
    require(close(value, decision["expected"]["harmful_plan_commitment_rate"]), "decision oracle mismatch")

    interaction = fixtures["interaction_metrics"]
    harm = interaction["inputs"]["harmful_acceptance_rate"]
    value = -((harm["P1D1"] - harm["P1D0"]) - (harm["P0D1"] - harm["P0D0"]))
    require(
        close(value, interaction["expected"]["normalized_provenance_dependency_interaction"]),
        "interaction oracle mismatch",
    )
    availability = interaction["inputs"]["availability"]
    margin = interaction["inputs"]["availability_max_absolute_decrease"]
    guard = all(availability["P0D0"] - cell_value <= margin for cell_value in availability.values())
    require(guard is interaction["expected"]["availability_guard_passes"], "interaction availability guard")

    performance = fixtures["performance_metrics"]
    budgets = performance["inputs"]["budgets"]
    observed_values = performance["inputs"]["observed_fixture_values"]
    violations = sum(observed_values[name] > budget for name, budget in budgets.items())
    completion = (
        performance["inputs"]["completed_workloads"]
        / performance["inputs"]["required_workloads"]
    )
    require(
        violations == performance["expected"]["mandatory_budget_violation_count"],
        "performance budget oracle mismatch",
    )
    require(
        close(completion, performance["expected"]["required_run_completion_rate"]),
        "performance completion oracle mismatch",
    )


def validate_all() -> dict[str, Any]:
    registry = load_yaml(ROOT / "BASELINE_REGISTRY.yaml")
    known_systems = validate_registry(registry)
    hypotheses = load_yaml(ROOT / "research" / "hypothesis_contracts.yaml")
    validate_hypotheses(hypotheses, known_systems)
    pilot = load_yaml(CONTRACT_ROOT / "pilot_allocation.yaml")
    evaluation = load_yaml(CONTRACT_ROOT / "evaluation_allocation.yaml")
    validate_allocations(pilot, evaluation)
    dependency = load_yaml(CONTRACT_ROOT / "dependency_oracle_negative_controls.yaml")
    validate_dependency_oracle(dependency)
    firewall = load_yaml(CONTRACT_ROOT / "reference_firewall.yaml")
    validate_firewall(firewall)
    validate_metric_oracles()
    blockers = [
        "minimum effects and perturbation bounds are provisional and not pilot-calibrated",
        "terrain windows and action geometries lack content hashes and spatial-disjointness proof",
        "baseline implementations/configuration hashes and external selections are pending",
        "dependency generator/oracle and poison attestations are not implemented",
        "reference firewall permission and poison attestations are not executed",
        "independent Barrier-1 review has not accepted the frozen packet",
    ]
    return {
        "valid": True,
        "acceptance_ready": False,
        "hypotheses": 7,
        "registered_systems": len(registry["systems"]),
        "pilot_units": pilot["unit_count"],
        "evaluation_units": evaluation["unit_count"],
        "metric_oracles": len(list(ORACLE_ROOT.glob("*.json"))),
        "blocking_items": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-acceptance-ready",
        action="store_true",
        help="return nonzero while provisional/calibration/review blockers remain",
    )
    args = parser.parse_args()
    summary = validate_all()
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.require_acceptance_ready and not summary["acceptance_ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
