"""Command-line entry point for the runnable UltraBuild research slice."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from stewie.ultrabuild.canonical import canonical_bytes
from stewie.ultrabuild.benchmark import run_benchmarks
from stewie.ultrabuild.experiment import run_controlled_evaluation
from stewie.ultrabuild.faults import run_fault_injection
from stewie.ultrabuild.golden import build_golden_world
from stewie.ultrabuild.identity import build_identity
from stewie.ultrabuild.payloads import ContentAddressedPayloadStore
from stewie.ultrabuild.perturbation import run_perturbation_study
from stewie.ultrabuild.scenario_runner import (
    run_conflict_retention_demo,
    run_multi_robot_closed_loop,
)
from stewie.ultrabuild.store import AuthoritativeStore


def _measured_runs(value: str) -> int:
    parsed = int(value)
    if parsed < 20:
        raise argparse.ArgumentTypeError("--measured-runs must be at least 20")
    return parsed


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def _demo(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    store, ids = build_golden_world(output / "world-state.sqlite3")
    try:
        integrity = store.verify_integrity()
        summary = {
            "schema_version": "stewie.ultrabuild_demo/1.0",
            "status": "complete" if integrity["ok"] else "failed",
            "evidence_level": "reproducible_controlled_demonstration",
            "claim_limit": (
                "The demo exercises persistent semantics and autonomy contracts; "
                "it is not physical deployment validation."
            ),
            "record_ids": ids,
            "accepted_head": store.branch_head("branch.accepted"),
            "integrity": integrity,
            "build_identity": build_identity(),
        }
        _write_json(output / "demo-summary.json", summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if integrity["ok"] else 1
    finally:
        store.close()


def _evaluate(output: Path) -> int:
    report = run_controlled_evaluation(output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _multi_demo(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    store, report = run_multi_robot_closed_loop(output / "world-state.sqlite3")
    try:
        _write_json(output / "multi-robot-summary.json", report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["integrity"]["ok"] else 1
    finally:
        store.close()


def _conflict_demo(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    store, report = run_conflict_retention_demo(output / "world-state.sqlite3")
    try:
        _write_json(output / "conflict-summary.json", report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["integrity"]["ok"] else 1
    finally:
        store.close()


def _verify(database: Path, payloads: Path | None) -> int:
    if payloads is None:
        raise ValueError("complete verification requires --payloads")
    payload_store = ContentAddressedPayloadStore(payloads)
    with AuthoritativeStore(
        database,
        payload_store=payload_store,
        require_local_payloads=True,
    ) as store:
        report = store.verify_integrity()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


def _benchmark(output: Path, measured_runs: int) -> int:
    report = run_benchmarks(output, measured_runs=measured_runs)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["all_measured_targets_pass"] else 1


def _fault_injection(output: Path) -> int:
    report = run_fault_injection(output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["failed"] == 0 else 1


def _perturbation(output: Path) -> int:
    report = run_perturbation_study(output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="stewie-ultrabuild",
        description="Persistent world-state research artifact",
    )
    commands = root.add_subparsers(dest="command", required=True)
    demo = commands.add_parser(
        "demo",
        help="build the closed-loop golden world-state graph",
    )
    demo.add_argument("--output", type=Path, required=True)
    multi_demo = commands.add_parser(
        "multi-demo",
        help="run the persistent multi-robot closed loop",
    )
    multi_demo.add_argument("--output", type=Path, required=True)
    conflict_demo = commands.add_parser(
        "conflict-demo",
        help="persist unresolved competing world-state hypotheses",
    )
    conflict_demo.add_argument("--output", type=Path, required=True)
    evaluate = commands.add_parser(
        "evaluate",
        help="run exploratory controlled baseline/ablation diagnostics",
    )
    evaluate.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser(
        "verify",
        help="verify an existing authority database",
    )
    verify.add_argument("--database", type=Path, required=True)
    verify.add_argument("--payloads", type=Path, required=True)
    benchmark = commands.add_parser(
        "benchmark",
        help="measure implemented Barrier-3 performance paths",
    )
    benchmark.add_argument("--output", type=Path, required=True)
    benchmark.add_argument("--measured-runs", type=_measured_runs, default=200)
    faults = commands.add_parser(
        "fault-inject",
        help="run controlled authority and reconciliation faults",
    )
    faults.add_argument("--output", type=Path, required=True)
    perturbation = commands.add_parser(
        "perturb",
        help="run the exposed exploratory one-factor perturbation grid",
    )
    perturbation.add_argument("--output", type=Path, required=True)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    argument_parser = parser()
    arguments = argument_parser.parse_args(argv)
    if arguments.command == "demo":
        return _demo(arguments.output)
    if arguments.command == "evaluate":
        return _evaluate(arguments.output)
    if arguments.command == "multi-demo":
        return _multi_demo(arguments.output)
    if arguments.command == "conflict-demo":
        return _conflict_demo(arguments.output)
    if arguments.command == "verify":
        return _verify(arguments.database, arguments.payloads)
    if arguments.command == "benchmark":
        try:
            return _benchmark(arguments.output, arguments.measured_runs)
        except FileExistsError as exc:
            argument_parser.error(str(exc))
    if arguments.command == "fault-inject":
        return _fault_injection(arguments.output)
    if arguments.command == "perturb":
        return _perturbation(arguments.output)
    raise AssertionError(f"unhandled command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
