from __future__ import annotations

from copy import deepcopy

import pytest

from experiments.contracts import validate_barrier1_contracts as contracts


def test_closure_packet_is_machine_valid_but_not_acceptance_ready() -> None:
    summary = contracts.validate_all()
    assert summary["valid"] is True
    assert summary["acceptance_ready"] is False
    assert summary["hypotheses"] == 7
    assert summary["pilot_units"] == 4
    assert summary["evaluation_units"] == 24
    assert summary["metric_oracles"] == 6
    assert summary["blocking_items"]


def test_pilot_and_evaluation_units_windows_and_seeds_are_disjoint() -> None:
    pilot = contracts.load_yaml(contracts.CONTRACT_ROOT / "pilot_allocation.yaml")
    evaluation = contracts.load_yaml(contracts.CONTRACT_ROOT / "evaluation_allocation.yaml")
    contracts.validate_allocations(pilot, evaluation)

    pilot_units, pilot_windows, pilot_seeds = contracts._allocation_ids(pilot)
    eval_units, eval_windows, eval_seeds = contracts._allocation_ids(evaluation)
    assert pilot_units.isdisjoint(eval_units)
    assert pilot_windows.isdisjoint(eval_windows)
    assert pilot_seeds.isdisjoint(eval_seeds)


def test_registry_rejects_a_missing_required_baseline() -> None:
    registry = contracts.load_yaml(contracts.ROOT / "BASELINE_REGISTRY.yaml")
    mutated = deepcopy(registry)
    mutated["systems"] = [system for system in mutated["systems"] if system["id"] != "B-BITEMP"]
    with pytest.raises(contracts.ContractError, match="missing required systems"):
        contracts.validate_registry(mutated)


def test_allocation_rejects_seed_leakage_between_pilot_and_evaluation() -> None:
    pilot = contracts.load_yaml(contracts.CONTRACT_ROOT / "pilot_allocation.yaml")
    evaluation = contracts.load_yaml(contracts.CONTRACT_ROOT / "evaluation_allocation.yaml")
    mutated = deepcopy(evaluation)
    mutated["seeds"][0] = pilot["seeds"][0]
    with pytest.raises(contracts.ContractError, match="pilot/evaluation seeds overlap"):
        contracts.validate_allocations(pilot, mutated)


def test_dependency_design_requires_all_four_negative_control_cells() -> None:
    design = contracts.load_yaml(
        contracts.CONTRACT_ROOT / "dependency_oracle_negative_controls.yaml"
    )
    mutated = deepcopy(design)
    mutated["factorial_cells"] = mutated["factorial_cells"][:-1]
    with pytest.raises(contracts.ContractError, match="requires four cells"):
        contracts.validate_dependency_oracle(mutated)


def test_reference_firewall_rejects_shared_candidate_evaluator_identity() -> None:
    firewall = contracts.load_yaml(contracts.CONTRACT_ROOT / "reference_firewall.yaml")
    mutated = deepcopy(firewall)
    mutated["processes"]["evaluator"]["identity"] = mutated["processes"]["candidate"]["identity"]
    with pytest.raises(contracts.ContractError, match="identity must differ"):
        contracts.validate_firewall(mutated)


def test_metric_oracle_formulas_and_task_tolerance_contract() -> None:
    contracts.validate_metric_oracles()
    fixture = contracts.load_json(
        contracts.ORACLE_ROOT / "reconciliation_metrics.json"
    )
    assert fixture["harm_tolerance"]["metric"] not in contracts.OUTCOME_METRICS
    assert fixture["harm_tolerance"]["unit"] == "m"
    assert fixture["harm_tolerance"]["basis"].startswith("provisional_")
