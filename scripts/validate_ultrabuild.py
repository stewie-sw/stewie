"""Validate the UltraBuild research/architecture control surface and draft contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from scripts.ultrabuild_contract_fixtures import fixtures, record_set_fixtures
from scripts.validate_ultrabuild_contracts import validate_record, validate_record_set
from scripts.validate_ultrabuild_requirements import validate_requirements

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "GRAPH_MANIFEST.yaml"

REQUIRED_INITIAL = {
    "PROJECT_CHARTER.md",
    "DISSERTATION_ALIGNMENT.md",
    "PROBLEM_DEFINITION.md",
    "SYSTEM_REQUIREMENTS.md",
    "RESEARCH_QUESTIONS.md",
    "HYPOTHESES.md",
    "SYSTEM_ARCHITECTURE.md",
    "GRAPH_MANIFEST.yaml",
    "DATA_MODEL.md",
    "WORLD_STATE_ONTOLOGY.md",
    "PROVENANCE_MODEL.md",
    "TEMPORAL_MODEL.md",
    "EXPERIMENTAL_DESIGN.md",
    "QUALITY_RUBRIC.md",
    "PERFORMANCE_BUDGET.json",
    "EVALUATION_METRICS.md",
    "RISK_REGISTER.md",
    "TASK_LEDGER.md",
    "ASSUMPTION_REGISTER.md",
    "KNOWN_LIMITATIONS.md",
    "REPRODUCIBILITY_PLAN.md",
    "DATA_AND_ASSET_PROVENANCE.md",
}

NODE_FIELDS = {
    "id",
    "name",
    "purpose",
    "owning_specialist",
    "independent_reviewers",
    "required_inputs",
    "expected_outputs",
    "artifact_schemas",
    "upstream_dependencies",
    "downstream_consumers",
    "assumptions",
    "known_risks",
    "acceptance_tests",
    "evaluation_metrics",
    "computational_budget",
    "performance_budget",
    "max_local_revision_cycles",
    "integration_conditions",
    "scientific_claims_supported",
    "scientific_claims_not_supported",
    "lifecycle_evidence",
    "lifecycle_state",
}

EXPECTED_LIFECYCLE = [
    "UNPLANNED",
    "SPECIFIED",
    "READY",
    "ACTIVE",
    "SELF_TEST",
    "INDEPENDENT_REVIEW",
    "REWORK",
    "ACCEPTED",
    "INTEGRATED",
    "REGRESSION_VERIFIED",
    "EXPERIMENTALLY_VALIDATED",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_manifest() -> dict[str, Any]:
    raw = MANIFEST_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError("GRAPH_MANIFEST.yaml must contain a mapping")
    return data


def validate_required_files() -> None:
    missing = sorted(path for path in REQUIRED_INITIAL if not (ROOT / path).is_file())
    require(not missing, f"missing required initial artifacts: {missing}")


def validate_json_files() -> None:
    paths = [ROOT / "PERFORMANCE_BUDGET.json", *sorted((ROOT / "schemas/ultrabuild").glob("*.json"))]
    require(len(paths) >= 16, "expected performance budget plus the complete UltraBuild schema set")
    schemas: dict[str, dict[str, Any]] = {}
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        require(isinstance(value, dict), f"{path.relative_to(ROOT)} must contain a JSON object")
        if path.name.endswith(".schema.json"):
            require(value.get("$schema") == "https://json-schema.org/draft/2020-12/schema",
                    f"{path.relative_to(ROOT)} must use JSON Schema draft 2020-12")
            require("$id" in value and value.get("type") == "object",
                    f"{path.relative_to(ROOT)} needs $id and object root type")
            Draft202012Validator.check_schema(value)
            schemas[path.name] = value

    graph = load_manifest()
    graph_errors = sorted(
        Draft202012Validator(
            schemas["graph_manifest.schema.json"],
            format_checker=FormatChecker(),
        ).iter_errors(graph),
        key=lambda error: list(error.absolute_path),
    )
    if graph_errors:
        raise ValueError(f"GRAPH_MANIFEST.yaml schema error: {graph_errors[0].message}")

    performance = json.loads((ROOT / "PERFORMANCE_BUDGET.json").read_text(encoding="utf-8"))
    performance_errors = sorted(
        Draft202012Validator(
            schemas["performance_budget.schema.json"],
            format_checker=FormatChecker(),
        ).iter_errors(performance),
        key=lambda error: list(error.absolute_path),
    )
    if performance_errors:
        raise ValueError(f"PERFORMANCE_BUDGET.json schema error: {performance_errors[0].message}")


def validate_contract_fixtures() -> None:
    for fixture in fixtures():
        errors = validate_record(fixture["schema"], fixture["record"])
        expect_valid = bool(fixture["expect_valid"])
        require(
            bool(errors) is not expect_valid,
            f"{fixture['id']}: expected {'valid' if expect_valid else 'invalid'}, errors={errors}",
        )
    for fixture in record_set_fixtures():
        errors = validate_record_set(fixture["records"])
        expect_valid = bool(fixture["expect_valid"])
        require(
            bool(errors) is not expect_valid,
            f"{fixture['id']}: expected {'valid' if expect_valid else 'invalid'}, errors={errors}",
        )


def validate_manifest(data: dict[str, Any]) -> None:
    require(data.get("schema_version") == "stewie.graph_manifest/1.0", "unexpected manifest schema")
    require(data.get("lifecycle") == EXPECTED_LIFECYCLE, "node lifecycle differs from the execution contract")

    schemas = data.get("artifact_schemas")
    if not isinstance(schemas, dict) or not schemas:
        raise ValueError("artifact_schemas must be a non-empty mapping")
    for schema_id, schema in schemas.items():
        if not isinstance(schema_id, str) or not isinstance(schema, dict):
            raise ValueError("each artifact schema must be a named mapping")
        schema_path = schema.get("path")
        if schema_path is not None:
            require(isinstance(schema_path, str) and (ROOT / schema_path).is_file(),
                    f"{schema_id}: schema path does not exist")

    raw_roles = data.get("roles")
    if not isinstance(raw_roles, list) or not raw_roles:
        raise ValueError("roles must be a non-empty list")
    role_ids: list[str] = []
    for index, role in enumerate(raw_roles):
        if not isinstance(role, dict):
            raise ValueError(f"role {index} must be a mapping")
        role_id = role.get("id")
        if not isinstance(role_id, str) or not role_id:
            raise ValueError(f"role {index} needs a non-empty string ID")
        role_ids.append(role_id)
    require(len(role_ids) == len(set(role_ids)), "role IDs must be unique")
    role_id_set = set(role_ids)

    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("nodes must be a non-empty list")
    nodes: list[dict[str, Any]] = []
    node_ids: list[str] = []
    for index, node in enumerate(raw_nodes):
        if not isinstance(node, dict):
            raise ValueError(f"node {index} must be a mapping")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError(f"node {index} needs a non-empty string ID")
        nodes.append(node)
        node_ids.append(node_id)
    require(len(node_ids) == len(set(node_ids)), "node IDs must be unique")
    node_id_set = set(node_ids)
    node_by_id = {node["id"]: node for node in nodes}

    for node in nodes:
        missing = sorted(NODE_FIELDS - set(node))
        require(not missing, f"{node.get('id')}: missing required fields {missing}")
        require(node["owning_specialist"] in role_id_set,
                f"{node['id']}: owner is not a declared role")
        unknown_reviewers = sorted(set(node["independent_reviewers"]) - role_id_set)
        require(not unknown_reviewers, f"{node['id']}: unknown reviewer roles {unknown_reviewers}")
        require(node["lifecycle_state"] in EXPECTED_LIFECYCLE,
                f"{node['id']}: invalid lifecycle state {node['lifecycle_state']}")
        require(node["owning_specialist"] not in set(node["independent_reviewers"]),
                f"{node['id']}: owner cannot independently review its own node")
        unknown_deps = sorted(set(node["upstream_dependencies"]) - node_id_set)
        require(not unknown_deps, f"{node['id']}: unknown upstream nodes {unknown_deps}")
        require(node["max_local_revision_cycles"] >= 1,
                f"{node['id']}: revision-cycle budget must be positive")

    inverse_dependencies: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for node in nodes:
        for upstream_id in node["upstream_dependencies"]:
            inverse_dependencies[upstream_id].append(node["id"])
    for node in nodes:
        require(
            node["downstream_consumers"] == inverse_dependencies[node["id"]],
            f"{node['id']}: downstream_consumers is not the exact upstream inverse",
        )

    dependency_graph = {
        node["id"]: set(node["upstream_dependencies"])
        for node in nodes
    }
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(node_id: str) -> None:
        require(node_id not in temporary, f"node dependency cycle includes {node_id}")
        if node_id in permanent:
            return
        temporary.add(node_id)
        for upstream_id in dependency_graph[node_id]:
            visit(upstream_id)
        temporary.remove(node_id)
        permanent.add(node_id)

    for node_id in node_ids:
        visit(node_id)

    raw_artifacts = data.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise ValueError("artifacts must be a non-empty list")
    artifacts: list[dict[str, Any]] = []
    artifact_ids: list[str] = []
    artifact_paths: list[str] = []
    for index, artifact in enumerate(raw_artifacts):
        if not isinstance(artifact, dict):
            raise ValueError(f"artifact {index} must be a mapping")
        artifact_id = artifact.get("id")
        artifact_path = artifact.get("path")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError(f"artifact {index} needs a non-empty string ID")
        if not isinstance(artifact_path, str) or not artifact_path:
            raise ValueError(f"{artifact_id}: path must be a non-empty string")
        artifacts.append(artifact)
        artifact_ids.append(artifact_id)
        artifact_paths.append(artifact_path)
    require(len(artifact_ids) == len(set(artifact_ids)), "artifact IDs must be unique")
    require(len(artifact_paths) == len(set(artifact_paths)), "artifact paths must be unique")
    registered_required = set(artifact_paths) & REQUIRED_INITIAL
    require(registered_required == REQUIRED_INITIAL,
            f"required artifact registry mismatch: {sorted(REQUIRED_INITIAL - registered_required)}")

    for artifact in artifacts:
        producer = artifact.get("producer")
        require(producer in node_id_set,
                f"{artifact.get('id')}: producer is not a graph node")
        require(artifact.get("schema") in schemas,
                f"{artifact.get('id')}: unknown artifact schema {artifact.get('schema')}")
        consumers = artifact.get("consumers")
        if not isinstance(consumers, list) or not consumers:
            raise ValueError(f"{artifact.get('id')}: consumers must be a non-empty list")
        unknown_consumers = sorted(set(consumers) - node_id_set - {"all"})
        require(not unknown_consumers,
                f"{artifact.get('id')}: unknown consumer nodes {unknown_consumers}")
        producer_node = next(node for node in nodes if node["id"] == producer)
        require(artifact["id"] in producer_node["expected_outputs"],
                f"{artifact['id']}: absent from producer {producer}'s expected outputs")
        path = ROOT / str(artifact.get("path"))
        require(path.is_file(), f"{artifact.get('id')}: registered path does not exist: {path}")
        if path.suffix == ".md":
            text = path.read_text(encoding="utf-8")
            for marker in ("**Artifact ID:**", "**Producer node:**", "**Consumers:**", "**Status:**"):
                require(marker in text, f"{artifact.get('id')}: markdown metadata missing {marker}")

    raw_planned = data.get("planned_artifacts")
    if not isinstance(raw_planned, list):
        raise ValueError("planned_artifacts must be a list")
    planned_ids: list[str] = []
    for index, artifact in enumerate(raw_planned):
        if not isinstance(artifact, dict):
            raise ValueError(f"planned artifact {index} must be a mapping")
        artifact_id = artifact.get("id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError(f"planned artifact {index} needs an ID")
        require(artifact.get("producer") in node_id_set,
                f"{artifact_id}: planned producer is not a node")
        require(artifact.get("schema") in schemas,
                f"{artifact_id}: planned artifact schema is unknown")
        consumers = artifact.get("consumers")
        if not isinstance(consumers, list) or not consumers:
            raise ValueError(f"{artifact_id}: planned consumers must be non-empty")
        require(not (set(consumers) - node_id_set - {"all"}),
                f"{artifact_id}: planned artifact has unknown consumers")
        planned_ids.append(artifact_id)
    require(len(planned_ids) == len(set(planned_ids)), "planned artifact IDs must be unique")
    require(not (set(planned_ids) & set(artifact_ids)),
            "materialized and planned artifact IDs must be disjoint")

    declared_outputs = set(artifact_ids) | set(planned_ids)
    output_producers: dict[str, list[str]] = {}
    for node in nodes:
        for output in node["expected_outputs"]:
            output_producers.setdefault(output, []).append(node["id"])
            require(output in declared_outputs,
                    f"{node['id']}: unregistered expected output {output}")
    for output, producers in output_producers.items():
        require(len(producers) == 1, f"{output}: multiple producing nodes {producers}")
    for artifact in [*artifacts, *raw_planned]:
        require(output_producers.get(artifact["id"]) == [artifact["producer"]],
                f"{artifact['id']}: registry producer differs from node output producer")

    external_inputs = data.get("external_inputs")
    if not isinstance(external_inputs, list) or not all(isinstance(value, str) for value in external_inputs):
        raise ValueError("external_inputs must be a string list")
    known_inputs = declared_outputs | set(schemas) | set(external_inputs)
    for node in nodes:
        unknown_inputs = sorted(set(node["required_inputs"]) - known_inputs)
        require(not unknown_inputs, f"{node['id']}: undeclared required inputs {unknown_inputs}")
        unknown_evidence = sorted(set(node["lifecycle_evidence"]) - declared_outputs)
        require(not unknown_evidence,
                f"{node['id']}: unknown lifecycle evidence {unknown_evidence}")

    accepted_index = EXPECTED_LIFECYCLE.index("ACCEPTED")
    advancement_states = {
        "ACTIVE",
        "SELF_TEST",
        "INDEPENDENT_REVIEW",
        "ACCEPTED",
        "INTEGRATED",
        "REGRESSION_VERIFIED",
        "EXPERIMENTALLY_VALIDATED",
    }
    for node in nodes:
        if node["lifecycle_state"] in advancement_states:
            require(bool(node["lifecycle_evidence"]),
                    f"{node['id']}: advanced lifecycle lacks evidence")
            require(not (set(node["lifecycle_evidence"]) - set(artifact_ids)),
                    f"{node['id']}: advanced lifecycle evidence must be materialized")
            lagging_upstream = [
                upstream_id
                for upstream_id in node["upstream_dependencies"]
                if upstream_id != "ORCH-001"
                and EXPECTED_LIFECYCLE.index(node_by_id[upstream_id]["lifecycle_state"]) < accepted_index
            ]
            require(not lagging_upstream,
                    f"{node['id']}: advanced ahead of upstream nodes {lagging_upstream}")
        if node["lifecycle_state"] == "REWORK":
            require(bool(node["lifecycle_evidence"]),
                    f"{node['id']}: REWORK lacks review evidence")

    risk_path = ROOT / "RISK_DISPOSITIONS.yaml"
    risks = yaml.safe_load(risk_path.read_text(encoding="utf-8"))
    risk_schema = json.loads(
        (ROOT / "schemas/ultrabuild/risk_register.schema.json").read_text(encoding="utf-8")
    )
    risk_errors = sorted(
        Draft202012Validator(risk_schema).iter_errors(risks),
        key=lambda error: list(error.absolute_path),
    )
    if risk_errors:
        raise ValueError(f"RISK_DISPOSITIONS.yaml schema error: {risk_errors[0].message}")
    risk_records = risks["risks"]
    risk_by_id = {risk["id"]: risk for risk in risk_records}
    require(len(risk_by_id) == len(risk_records), "risk disposition IDs must be unique")

    markdown_risks: dict[str, dict[str, str]] = {}
    for line in (ROOT / "RISK_REGISTER.md").read_text(encoding="utf-8").splitlines():
        if not line.startswith("| R-"):
            continue
        columns = [column.strip() for column in line.strip("|").split("|")]
        require(len(columns) == 7, f"malformed risk register row: {line}")
        markdown_risks[columns[0]] = {
            "impact": columns[3],
            "owner_node": columns[4].strip("`"),
        }
    require(set(risk_by_id) == set(markdown_risks),
            "markdown and machine-readable risk IDs differ")
    require(len(risk_by_id) == 25, "expected 25 inventoried risks")
    for risk_id, risk in risk_by_id.items():
        require(risk["owner_node"] in node_id_set,
                f"{risk_id}: owner node is unknown")
        require(risk["impact"] == markdown_risks[risk_id]["impact"],
                f"{risk_id}: impact differs from markdown register")
        require(risk["owner_node"] == markdown_risks[risk_id]["owner_node"],
                f"{risk_id}: owner differs from markdown register")
        require(risk_id in node_by_id[risk["owner_node"]]["known_risks"],
                f"{risk_id}: absent from owner node known_risks")
        require(not (set(risk["barrier_ids"]) - {f"BARRIER-{index}" for index in range(1, 9)}),
                f"{risk_id}: unknown associated barrier")
        require(not (set(risk["evidence_artifact_ids"]) - set(artifact_ids)),
                f"{risk_id}: evidence must be materialized")
    declared_risk_ids = {
        risk_id
        for node in nodes
        for risk_id in node["known_risks"]
    }
    require(not (declared_risk_ids - set(risk_by_id)),
            f"nodes reference unknown risks {sorted(declared_risk_ids - set(risk_by_id))}")

    runtime_graph = yaml.safe_load((ROOT / "RUNTIME_GRAPH.yaml").read_text(encoding="utf-8"))
    runtime_schema = json.loads(
        (ROOT / "schemas/ultrabuild/runtime_graph.schema.json").read_text(encoding="utf-8")
    )
    runtime_errors = sorted(
        Draft202012Validator(runtime_schema).iter_errors(runtime_graph),
        key=lambda error: list(error.absolute_path),
    )
    if runtime_errors:
        raise ValueError(f"RUNTIME_GRAPH.yaml schema error: {runtime_errors[0].message}")
    runtime_nodes = runtime_graph["nodes"]
    runtime_node_by_id = {node["id"]: node for node in runtime_nodes}
    require(len(runtime_node_by_id) == len(runtime_nodes), "runtime node IDs must be unique")
    runtime_edges = runtime_graph["edges"]
    runtime_edge_ids = [edge["id"] for edge in runtime_edges]
    require(len(runtime_edge_ids) == len(set(runtime_edge_ids)), "runtime edge IDs must be unique")
    known_runtime_contracts = set(schemas) | set(runtime_graph["internal_contracts"])
    for node in runtime_nodes:
        unknown_contracts = (
            set(node["input_contracts"]) | set(node["output_contracts"])
        ) - known_runtime_contracts
        require(not unknown_contracts,
                f"{node['id']}: unknown runtime contracts {sorted(unknown_contracts)}")
    forward_without_back_edges: dict[str, set[str]] = {
        node_id: set() for node_id in runtime_node_by_id
    }
    loop_edges = []
    for edge in runtime_edges:
        require(edge["producer"] in runtime_node_by_id and edge["consumer"] in runtime_node_by_id,
                f"{edge['id']}: runtime endpoint does not exist")
        producer_outputs = set(runtime_node_by_id[edge["producer"]]["output_contracts"])
        consumer_inputs = set(runtime_node_by_id[edge["consumer"]]["input_contracts"])
        require(not (set(edge["artifacts"]) - producer_outputs),
                f"{edge['id']}: producer does not emit every edge artifact")
        require(not (set(edge["artifacts"]) - consumer_inputs),
                f"{edge['id']}: consumer does not accept every edge artifact")
        if "loop_policy" in edge:
            loop_edges.append(edge)
        else:
            forward_without_back_edges[edge["producer"]].add(edge["consumer"])

    runtime_temporary: set[str] = set()
    runtime_permanent: set[str] = set()

    def visit_runtime(node_id: str) -> None:
        require(node_id not in runtime_temporary,
                f"runtime cycle lacks an explicit loop_policy near {node_id}")
        if node_id in runtime_permanent:
            return
        runtime_temporary.add(node_id)
        for consumer_id in forward_without_back_edges[node_id]:
            visit_runtime(consumer_id)
        runtime_temporary.remove(node_id)
        runtime_permanent.add(node_id)

    for runtime_node_id in runtime_node_by_id:
        visit_runtime(runtime_node_id)
    for edge in loop_edges:
        frontier = [edge["consumer"]]
        reachable: set[str] = set()
        while frontier:
            candidate = frontier.pop()
            if candidate in reachable:
                continue
            reachable.add(candidate)
            frontier.extend(forward_without_back_edges[candidate])
        require(edge["producer"] in reachable,
                f"{edge['id']}: loop_policy edge does not close a declared forward path")

    raw_edges = data.get("edge_contracts")
    if not isinstance(raw_edges, list) or not raw_edges:
        raise ValueError("edge contracts must be a non-empty list")
    edge_ids: list[str] = []
    edge_pairs: set[tuple[str, str]] = set()
    for index, edge in enumerate(raw_edges):
        if not isinstance(edge, dict):
            raise ValueError(f"edge contract {index} must be a mapping")
        edge_id = edge.get("id")
        if not isinstance(edge_id, str) or not edge_id:
            raise ValueError(f"edge contract {index} needs a non-empty string ID")
        require(edge.get("producer") in node_id_set,
                f"{edge_id}: producer is not a graph node")
        edge_consumers = edge.get("consumers")
        if not isinstance(edge_consumers, list) or not edge_consumers:
            raise ValueError(f"{edge_id}: consumers must be a non-empty list")
        unknown_edge_consumers = sorted(set(edge_consumers) - node_id_set)
        require(not unknown_edge_consumers,
                f"{edge_id}: unknown consumers {unknown_edge_consumers}")
        edge_schema = edge.get("schema")
        if edge_schema is not None:
            require(edge_schema in schemas, f"{edge_id}: unknown schema {edge_schema}")
        acceptance = edge.get("acceptance")
        require(isinstance(acceptance, str) and bool(acceptance.strip()),
                f"{edge_id}: acceptance must be non-empty")
        payloads = edge.get("payloads", [])
        require(isinstance(payloads, list), f"{edge_id}: payloads must be a list")
        unknown_payloads = sorted(set(payloads) - declared_outputs)
        require(not unknown_payloads, f"{edge_id}: unregistered payloads {unknown_payloads}")
        wrong_producers = sorted(
            payload
            for payload in payloads
            if output_producers.get(payload) != [edge["producer"]]
        )
        require(not wrong_producers,
                f"{edge_id}: payloads not produced by edge producer {wrong_producers}")
        edge_pairs.update((edge["producer"], consumer) for consumer in edge_consumers)
        edge_ids.append(edge_id)
    require(len(edge_ids) == len(set(edge_ids)), "edge contract IDs must be unique")
    dependency_pairs = {
        (upstream_id, node["id"])
        for node in nodes
        for upstream_id in node["upstream_dependencies"]
    }
    require(edge_pairs == dependency_pairs,
            f"typed edge/dependency mismatch: missing={sorted(dependency_pairs - edge_pairs)}, "
            f"extra={sorted(edge_pairs - dependency_pairs)}")

    raw_barriers = data.get("barriers")
    if not isinstance(raw_barriers, list):
        raise ValueError("barriers must be a list")
    barriers: list[dict[str, Any]] = []
    for index, barrier in enumerate(raw_barriers):
        if not isinstance(barrier, dict):
            raise ValueError(f"barrier {index} must be a mapping")
        barriers.append(barrier)
    require([barrier.get("id") for barrier in barriers] == [f"BARRIER-{i}" for i in range(1, 9)],
            "all eight ordered barriers must be declared")
    for barrier in barriers:
        unknown = sorted(set(barrier.get("required_nodes", [])) - node_id_set)
        require(not unknown, f"{barrier['id']}: unknown required nodes {unknown}")
        if barrier.get("status") == "accepted":
            lagging = [
                node_id
                for node_id in barrier.get("required_nodes", [])
                if EXPECTED_LIFECYCLE.index(node_by_id[node_id]["lifecycle_state"]) < accepted_index
            ]
            require(not lagging, f"{barrier['id']}: accepted ahead of nodes {lagging}")
            evidence = barrier.get("evidence_artifact_ids")
            if not isinstance(evidence, list) or not evidence:
                raise ValueError(f"{barrier['id']}: accepted without review evidence")
            require(not (set(evidence) - set(artifact_ids)),
                    f"{barrier['id']}: review evidence must be materialized")
            review_ids = {
                artifact["id"]
                for artifact in artifacts
                if artifact["producer"] == "REV-010"
                and artifact["schema"] == "json.barrier_decision.v1"
            }
            decision_ids = set(evidence) & review_ids
            require(bool(decision_ids),
                    f"{barrier['id']}: lacks typed independent barrier decision evidence")
            for decision_id in decision_ids:
                artifact = next(item for item in artifacts if item["id"] == decision_id)
                decision = json.loads((ROOT / artifact["path"]).read_text(encoding="utf-8"))
                errors = validate_record("barrier_decision.schema.json", decision)
                require(not errors, f"{decision_id}: invalid barrier decision {errors}")
                require(decision.get("barrier_id") == barrier["id"],
                        f"{decision_id}: decision targets another barrier")
                require(decision.get("decision") == "ACCEPT",
                        f"{decision_id}: barrier evidence is not an ACCEPT decision")
                require(data.get("reviewed_artifact_commit") is not None,
                        f"{decision_id}: manifest has no reviewed_artifact_commit")
                require(decision.get("target_commit") == data.get("reviewed_artifact_commit"),
                        f"{decision_id}: decision targets another reviewed artifact commit")
                require(set(decision.get("reviewed_node_ids", [])) == set(barrier["required_nodes"]),
                        f"{decision_id}: reviewed nodes do not match barrier")
                reviewer_ids = decision.get("reviewer_ids", [])
                reviewer_groups = decision.get("reviewer_independence_groups", [])
                role_by_id = {role["id"]: role for role in raw_roles}
                require(not (set(reviewer_ids) - set(role_by_id)),
                        f"{decision_id}: unknown reviewer roles")
                expected_groups = {
                    role_by_id[reviewer_id]["independence_group"]
                    for reviewer_id in reviewer_ids
                }
                require(set(reviewer_groups) == expected_groups,
                        f"{decision_id}: reviewer independence groups do not match roles")
                owner_roles = {
                    node_by_id[node_id]["owning_specialist"]
                    for node_id in barrier["required_nodes"]
                }
                require(not (set(reviewer_ids) & owner_roles),
                        f"{decision_id}: a producing owner reviews its own barrier")
                evidence_records = decision.get("evidence_artifacts", [])
                evidence_ids = [item.get("artifact_id") for item in evidence_records]
                require(len(evidence_ids) == len(set(evidence_ids)),
                        f"{decision_id}: duplicate evidence artifacts")
                materialized_by_id = {item["id"]: item for item in artifacts}
                require(not (set(evidence_ids) - set(materialized_by_id)),
                        f"{decision_id}: evidence artifact is not materialized")
                for evidence_record in evidence_records:
                    evidence_artifact = materialized_by_id[evidence_record["artifact_id"]]
                    observed_hash = hashlib.sha256(
                        (ROOT / evidence_artifact["path"]).read_bytes()
                    ).hexdigest()
                    require(observed_hash == evidence_record["sha256"],
                            f"{decision_id}: evidence hash mismatch for "
                            f"{evidence_record['artifact_id']}")
            blocking_risks = [
                risk["id"]
                for risk in risk_records
                if barrier["id"] in risk["barrier_ids"]
                and risk["impact"] == "Critical"
                and risk["status"] not in {"closed", "accepted_limitation"}
            ]
            require(not blocking_risks,
                    f"{barrier['id']}: unresolved critical risks {blocking_risks}")
            accepted_risks = [
                risk
                for risk in risk_records
                if barrier["id"] in risk["barrier_ids"]
                and risk["status"] == "accepted_limitation"
            ]
            for risk in accepted_risks:
                require(risk["acceptance_decision_artifact_id"] in decision_ids,
                        f"{barrier['id']}: {risk['id']} limitation was not accepted by this decision")


def main() -> int:
    validate_required_files()
    validate_json_files()
    validate_contract_fixtures()
    validate_manifest(load_manifest())
    validate_requirements()
    print("UltraBuild manifest, requirements, artifacts, schemas, semantic fixtures, and barrier guards: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
