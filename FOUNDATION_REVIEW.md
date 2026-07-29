# UltraBuild foundation independent review

**Artifact ID:** `ART-FOUNDATION-REVIEW`
**Producer node:** `REV-010`
**Consumers:** `ORCH-001`, all Barrier-1/Barrier-2 nodes, `DISS-010`
**Status:** active defect record; Barrier 1 and Barrier 2 are not accepted.

## Decision

Three independent reviews examined the clean-start artifacts from research/method, world-state/
database, and platform-integration perspectives. The unanimous decision is:

- **Barrier 1 — BLOCKED:** novelty, baseline, preregistration, construct, and sampling contracts are
  incomplete.
- **Barrier 2 — BLOCKED:** the conceptual separation is credible, but no integrated store, promotion
  compare-and-swap, reference firewall, cross-record resolver, or historical query implementation
  exists.
- **Barrier 3 — NOT STARTED:** implementation remains gated by both decisions above.

This decision is evidence of review activity, not evidence that any research hypothesis or runtime
mechanism is correct.

## Defect ledger

| ID | Severity | Owner | Finding | Current disposition |
|---|---|---|---|---|
| FND-001 | critical | `RES-020` | Nearest temporal DB, GIS, provenance, event-sourcing, CRDT, belief-revision, replication, and robotics literature is not yet covered by a completed novelty matrix. | Open |
| FND-002 | critical | `RES-010` / `EXP-010` | The claimed mechanism interaction is not identified by component-only ablations. | Open; add a registered interaction contrast or narrow the claim |
| FND-003 | critical | `EXP-010` | MDEs, sample size, independent units, seeds, thresholds, stopping/exclusion rules, and scenario manifests are not frozen after disjoint pilots. | Open; schema now requires these fields |
| FND-004 | critical | `EXP-010` | Version-only, credible bitemporal/event-sourced, provenance-free, no-uncertainty, centralized, and local-only baseline assignments are incomplete. | Open |
| FND-005 | critical | `EXP-010` | Dependency attribution can be circular if action overlap generates both the fault and the oracle. | Open; scenario contract now records oracle independence |
| FND-006 | major | `RES-010` | RQ3 says arbitrary model bias although only a bounded grid can be tested. | Open; split structural noninterference from bounded empirical harm |
| FND-007 | major | `EXP-010` | Explanation fidelity, correction time, human evaluation, endpoint hierarchy, and harm/availability frontier lack complete executable definitions. | Open |
| FND-008 | critical | `EXP-010` / `ARCH-020` | Candidate-visible action reports and withheld execution truth shared an untyped manifest/firewall. | Contract revised; executable isolation and poison attestation still open |
| FND-009 | critical | `EXP-010` | One terrain/action with many cell/noise samples would not support generality. | Open; scenario contract now requires independent units and resampling level |
| FND-010 | critical | `ARCH-020` / `WS-040` | Branch kind, accepted-head compare-and-swap, and promotion linkage were unenforced. | Contract revised; authoritative store/CAS tests remain open |
| FND-011 | critical | `WS-020` | Mutating `closed_at` contradicted immutable transaction history. | Contract revised to append supersession events; store/query oracle open |
| FND-012 | critical | `WS-040` | Durable candidate, conflict, and hypothesis contracts were missing; invalid decision combinations passed. | Schemas/negative fixtures added; persistence remains open |
| FND-013 | critical | `WS-040` / `PHY-010` | Physics evidence could be mislabeled/admitted as observation or directly underpin authority. | Local/cross-record guards added; mutation noninterference test remains open |
| FND-014 | critical | `WS-030` / `WS-050` | Provenance was opaque and uncertainty accepted arbitrary/null components. | Barrier-3 subset schemas added; store, resolution, completeness, and calibration tests open |
| FND-015 | critical | `ARCH-020` | Cross-site evidence/revision linkage was not enforceable. | `site_id` and cross-record negative fixture added; cold-store test open |
| FND-016 | critical | `ORCH-001` | Validator accepted malformed schemas and accepted barriers ahead of nodes/review evidence. | Meta-schema, fixture, DAG, registry, and barrier guards added |
| FND-017 | critical | `EXP-010` | A boolean/process-name firewall could be vacuous. | Distinct identities/mounts/processes and freeze protocol required; runtime proof open |
| FND-018 | critical | `ORCH-001` / `ARCH-020` | Graph allowed unregistered outputs/inputs, duplicate producers, dangling edge payloads, cycles, and self-version ambiguity. | Resolved for the control graph: all dependencies have producer-matching typed edges and inverse consumers |
| FND-019 | major | `ORCH-001` | Barrier 4 required integration that depended on Barrier-5 work. | Resolved by limiting Barrier 4 to its single-robot contract/review |
| FND-020 | critical | `ORCH-001` | `jsonschema` was absent from the locked clean environment. | Resolved for the foundation gate: minimal JSON Schema/RFC-3339 dependencies are hash-locked and installed in a new branch-local environment; full experiment reproduction remains future work |
| FND-021 | critical | `ARCH-020` | Query lenses could resolve a revision from a different branch/policy. | Cross-record guard added; planner persistence test open |
| FND-022 | major | `EXP-010` | Scenario RQ/commit fields and evidence/perturbation records admitted semantically empty values. | Schema tightened; frozen scenario instances remain open |
| FND-023 | critical | `ARCH-030` | The development DAG had no distinct runtime job graph with pre/postconditions, retry, isolation, evidence, and mutation authority. | Typed runtime graph and closure/loop validator added; implementation and fault evidence remain open |
| FND-024 | critical | `ORCH-001` | Critical risks were prose-only and could not block a barrier decision. | Machine-readable dispositions and validator coupling added; all listed open Critical risks still block their barriers |
| FND-025 | critical | `ARCH-020` / `ARCH-030` / `WS-020` | Stored-record schemas require and hash source-supplied transaction time, while the temporal/runtime contracts say the store assigns it after ingest. | Open; split submission from stored-record contracts or make the store perform final normalization, validation, hashing, and append |
| FND-026 | critical | `ARCH-030` | Reconciliation/planning append outside the declared append gateway, while append/projection receipts are untyped names. | Open; one store primitive and machine-readable durability/head/lag receipts required |
| FND-027 | critical | `ARCH-020` | The cross-record resolver crashed when a resolved query had a revision but no branch. | Resolved at draft level with a null guard; missing-reference mutation fixtures still required |
| FND-028 | critical | `WS-040` / `ARCH-020` | Promotion can reuse candidate payload hashes under a different spatial frame, extent, time, or aggregate uncertainty contract. | Open; bind candidate spatial/temporal/uncertainty descriptors through decision and revision |
| FND-029 | critical | `WS-040` / `EXP-010` | Evaluator-only dependency-oracle knowledge could enter candidate support. | Contract revised with dependency visibility and candidate rejection; executable poison test remains open |
| FND-030 | critical | `ARCH-020` | No valid closed record graph proves all reference joins are simultaneously satisfiable. | Open; add golden promotion/query/plan/action and conflict/supersession graphs, then derive missing/type/site/policy/time mutations |
| FND-031 | critical | `WS-030` | A claim can name an existing provenance bundle that contains no matching claim/payload/source/transform/calibration activity. | Open; typed PROV endpoint and claim-to-bundle closure checks required |
| FND-032 | major | `ARCH-030` / `WS-020` | Stale-CAS retry, partial-query semantics, immutable status evolution, and schema migration/retention contracts are incomplete. | Open; specify before Barrier 2 acceptance |

## Reviewer acceptance criteria

Barrier 1 cannot advance until:

1. `NOVELTY_REVIEW.md` contains a primary-source, claim-by-claim nearest-work matrix and is independently
   reviewed;
2. the hypothesis/design artifacts freeze one primary endpoint per comparison family, interaction
   estimands where claimed, credible baselines, bounded domains, and independent experimental units;
3. valid scenario manifests pass the schema and are frozen only after disjoint pilots; and
4. all critical research defects above are closed with evidence links.

Barrier 2 cannot advance until:

1. all JSON schemas and adversarial fixtures pass in the locked clean environment;
2. a record-set resolver rejects cross-world/site/type/branch/policy references;
3. accepted head mutation is compare-and-swap from a matching durable `PROMOTE` decision;
4. bitemporal correction preserves every prior `known_at` result without mutating old records;
5. conflict hypotheses, provenance, and query lenses survive cold restart; and
6. simulation, resync, physics changes, and withheld references cannot alter candidate/accepted bytes
   outside their declared policy effects;
7. submission and stored-record contracts prove store-assigned transaction ordering and immutable
   content hashes without trusting source transaction metadata;
8. every immutable record uses the same typed durable append boundary, with typed projection
   freshness and compare-and-swap receipts; and
9. valid closed record graphs plus adversarial mutations pass without validator crashes.

## Review limitations

The review inspected specifications, schemas, existing code/tests, and targeted adversarial payloads.
It did not validate a Barrier-3 implementation because none has been authorized by the preceding
barriers. “Resolved” above means the draft control-surface defect is corrected, not that the runtime
mechanism is experimentally validated.
