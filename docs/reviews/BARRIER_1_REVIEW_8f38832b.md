# Barrier 1 independent scientific-method review — `8f38832b`

- **Reviewed commit:** `8f38832b0a6e7b5a1ac2a7a5c3b15c8c422108c6`
- **Review type:** independent, read-only Barrier-1 and scientific-method review
- **System mode reviewed:** controlled simulation/replay and engineering prototype; no live or
  physical deployment claim
- **Evidence boundary:** structural tests and deterministic synthetic diagnostics only; no H1–H7
  empirical result is accepted by this review

## Verdict

| Decision target | Decision | Scope |
|---|---|---|
| Barrier 1 fan-in | **BLOCK** | The packet is internally structured but is not a frozen, executable preregistration. |
| Research problem and H1–H7 definitions | **ACCEPT — provisional design only** | The questions are bounded, falsifiable, and appropriately distinguish conformance from effectiveness. |
| Novelty boundary | **ACCEPT — conservative working boundary** | Established mechanisms are not presented as novel; this is not a novelty conclusion. |
| Registered pilot execution | **BLOCK** | Pilot terrain/actions are not materialized, hashed, spatially verified, or connected to an executable firewall. |
| Confirmatory H1–H7 execution | **BLOCK** | Baselines, allocation, scoring, isolation, power, and implementation attestations are incomplete. |
| Current controlled harness | **ACCEPT — exploratory engineering diagnostic only** | It demonstrates deterministic code behavior on synthetic arrays, not dissertation effectiveness. |
| Current evaluation allocation | **RETIRE from confirmatory use** | Reserved evaluation seeds and expected outcomes are exercised by development tests. |

This decision does not change the repository's barrier state. It records why Barrier 1 must remain
blocked.

## Highest-risk findings

### 1. The machine contract packet does not govern execution

The controlled evaluation, perturbation runner, and CLI hard-code methods, seeds, thresholds, and
factor levels. They do not load or enforce `BASELINE_REGISTRY.yaml`,
`research/hypothesis_contracts.yaml`, the pilot/evaluation allocation manifests, the metric-oracle
fixtures, or `execution_allowed`.

The CLI labels the trials “frozen” and can execute them while
`experiments/contracts/validate_barrier1_contracts.py` correctly returns
`acceptance_ready: false`. A declarative block that the executor can bypass is not an experiment
gate.

Evidence:

- `8f38832b:stewie/ultrabuild/cli.py:53-56`
- `8f38832b:stewie/ultrabuild/cli.py:138-164`
- `8f38832b:experiments/contracts/validate_barrier1_contracts.py:521-566`

### 2. The reserved evaluation allocation is exposed to development

Seeds `3001..3008` are hard-coded in the experiment and perturbation implementations. Tests execute
the evaluation grid and assert that STEWIE avoids a harmful plan while latest-write and
timestamp-only baselines commit one. The same seeds are also used by the benchmark, fault probes, and
closed-loop demonstration.

Because these are development tests with expected outcomes, this allocation is not an unseen
confirmatory holdout. It may remain as regression or exploratory data, but a new evaluator-owned
allocation is required after candidate freeze.

Evidence:

- `8f38832b:stewie/ultrabuild/experiment.py:22-24`
- `8f38832b:stewie/ultrabuild/perturbation.py:22-29`
- `8f38832b:stewie/ultrabuild/test_experiment.py:43-54`
- `8f38832b:stewie/ultrabuild/test_experiment.py:208-222`

### 3. The claimed 24 independent units are pseudoreplicated

The implementation creates eight synthetic `12 × 12` windows and crosses each with nominal,
partial, and failed outcomes. The three outcome conditions for a window reuse the same random stream
and spatial support, yet `_paired_unit_bootstrap` resamples all 24
`terrain_window × action_kind` identifiers as independent units.

A direct mask check found four overlapping pairs among the eight generated spatial envelopes. The
allocation contract also declares only eight unique windows while treating three actions per window
as 24 independent `terrain_action_pair` units.

The valid choices are:

1. define terrain window as the independent cluster and treat action conditions as repeated
   measures; or
2. materialize 24 genuinely separated terrain/action windows.

Power and intervals must then be recalibrated at that independent level. Seeds remain repeated
measures and cannot increase the independent sample size.

Evidence:

- `8f38832b:stewie/ultrabuild/experiment.py:22-45`
- `8f38832b:stewie/ultrabuild/experiment.py:79-140`
- `8f38832b:stewie/ultrabuild/experiment.py:371-412`
- `8f38832b:experiments/contracts/evaluation_allocation.yaml:32-63`

### 4. The executable scenario is not the registered Haworth experiment

The preregistration requires a content-addressed Haworth LOLA-derived crop and cut, deposit, and grade
actions. The runner instead starts from an all-zero synthetic raster and uses nominal, partial, and
failed execution outcomes. Runtime unit identifiers do not match the registered allocation, and no
terrain/action hashes are carried into the result.

This is a useful unit-test domain if labelled as such. It cannot be represented as evidence from the
registered Haworth domain.

Evidence:

- `8f38832b:EXPERIMENTAL_DESIGN.md:34-42`
- `8f38832b:stewie/ultrabuild/experiment.py:92-123`
- `8f38832b:stewie/ultrabuild/experiment.py:210-228`
- `8f38832b:experiments/contracts/evaluation_allocation.yaml:26-63`

### 5. Baselines are incomplete, confounded, or do not implement their registry contracts

The registry contains 21 systems plus four H7 mechanism cells. The controlled harness exposes nine
local method names that can only be tentatively mapped to nine registry IDs; no runtime adapter,
configuration hash, implementation hash, or same-input attestation binds those names to the registry.
Twelve registered systems and all four H7 cells are absent.

Confirmed method defects:

- `map_replacement` is the same implementation as latest transaction overwrite;
- `provenance_free_fusion` disables physics as well as provenance admission, confounding H4;
- `single_authoritative_map` selects lexically by robot/claim, while the registry specifies LWW;
- `no_uncertainty` changes fusion weighting rather than implementing the registered fixed-threshold
  rule;
- the generated stale claim is both last by transaction sequence and latest by source timestamp,
  making the two weakest baselines fail by construction; and
- the pure reconciliation path does not implement P-STEWIE's registered transaction history,
  durable conflict retention, or accepted-head semantics.

Evidence:

- `8f38832b:BASELINE_REGISTRY.yaml:77-483`
- `8f38832b:stewie/ultrabuild/experiment.py:25-35`
- `8f38832b:stewie/ultrabuild/reconciliation.py:14-24`
- `8f38832b:stewie/ultrabuild/reconciliation.py:250-293`

### 6. Reference and dependency isolation are not executable

Both generator paths declared by the firewall and dependency-oracle manifests are absent. Candidate
and evaluator execute in one process without a canonical output freeze. `CandidateScenario` exposes
`action_kind`, whose nominal/partial/failed value determines executed truth, to the candidate object
and output.

The reference poison test changes the reference after candidate-view generation, so it cannot detect
truth-derived fields already present in that view. The fault probe creates a poisoned array and
intentionally never passes it anywhere. These checks show that the current function signature does
not directly consume the returned reference object; they do not attest the specified firewall.

Evidence:

- `8f38832b:experiments/contracts/reference_firewall.yaml:10-105`
- `8f38832b:experiments/contracts/dependency_oracle_negative_controls.yaml:14-41`
- `8f38832b:stewie/ultrabuild/experiment.py:48-65`
- `8f38832b:stewie/ultrabuild/experiment.py:92-228`
- `8f38832b:stewie/ultrabuild/test_experiment.py:23-40`
- `8f38832b:stewie/ultrabuild/faults.py:151-163`

### 7. Actual scoring diverges from the metric contracts

The metric-oracle fixtures validate arithmetic on synthetic fixture inputs, but the experiment runner
does not use a shared scorer derived from them. The runtime evaluator:

- computes RMSE over the full array rather than explicit joint coverage;
- treats any non-`None` state as available, including partially covered states containing NaNs;
- does not implement the registered execution-failure/abstention/valid-promotion partition;
- reports stale rejection rather than stale-overwrite rate;
- implements a threshold proxy rather than the registered planner/query-lens commitment endpoint;
- computes `candidate − baseline` contrasts, opposite the positive favorable direction in the H5
  estimand; and
- executes no multiplicity or availability decision gate.

The allocation manifest's `fixed_sequence_within_family` setting also conflicts with the
intersection-union rules declared by several hypothesis contracts.

Evidence:

- `8f38832b:EVALUATION_METRICS.md:7-131`
- `8f38832b:research/hypothesis_contracts.yaml:37-384`
- `8f38832b:experiments/contracts/evaluation_allocation.yaml:74-82`
- `8f38832b:stewie/ultrabuild/experiment.py:260-306`
- `8f38832b:stewie/ultrabuild/experiment.py:336-449`

### 8. Perturbation and performance packages are exploratory or partial

The perturbation runner varies seven factors one at a time and uses reserved evaluation seeds. Its
levels do not match the registered H1–H4 grids: robot count is `1/2/3`, “physics mismatch” truncates
the action envelope instead of biasing a physical prediction, and no joint sensor-fault × model-bias
grid is executed. A review run found nine STEWIE failure cells, including zero availability in
several localization, noise, delay, and envelope conditions. Recording these failures is useful
exploratory evidence, not hypothesis validation.

The microbenchmark is appropriately labelled `measured_partial_budget`. It does not execute the H6
scaling grid, cold-cache protocol, concurrency levels, resource-cap enforcement, provenance trace,
or 1,000-version replay.

Evidence:

- `8f38832b:stewie/ultrabuild/perturbation.py:22-28`
- `8f38832b:stewie/ultrabuild/perturbation.py:159-278`
- `8f38832b:stewie/ultrabuild/benchmark.py:214-303`
- `8f38832b:PERFORMANCE_BUDGET.json:14-91`

### 9. The novelty boundary is conservative, but one citation was misattributed

Primary-source spot checks support the document's conservative conclusion that the component
mechanisms are established:

- valid time and transaction time are established bitemporal concepts:
  [Bliujutė et al., 1998](https://www.vldb.org/conf/1998/p345.pdf);
- provenance entities, activities, agents, derivation, revision, and qualified relationships are
  standardized by [W3C PROV-O](https://www.w3.org/TR/prov-o/);
- layered real-time 3-D scene graphs are implemented by
  [Hydra](https://www.roboticsproceedings.org/rss18/p050.html);
- distributed dense metric-semantic multi-robot mapping is implemented by
  [Kimera-Multi](https://arxiv.org/abs/2106.14386); and
- probabilistic change detection and volumetric maintenance in changing scenes are demonstrated by
  [POCD](https://www.roboticsproceedings.org/rss18/p013.html).

The linked VLDB paper had been attributed to Nascimento and Dunham, but the linked paper is by Rasa
Bliujutė, Christian S. Jensen, Simonas Šaltenis, and Giedrius Slivinskas. Correcting that attribution
does not change the conservative novelty conclusion.

## H1–H7 disposition

| Hypothesis | Research definition | Confirmatory dissertation evidence |
|---|---|---|
| H1 — bitemporal correctness | **ACCEPT — provisional** | **BLOCK** — no registered B-VERSION/B-BITEMP adapters or temporal-oracle experiment |
| H2 — dependency-aware support | **ACCEPT — provisional** | **BLOCK** — independent dependency oracle is absent and the current no-dependency scenario does not activate a measurable mechanism effect |
| H3 — contestable physics veto | **ACCEPT — provisional** | **BLOCK** — no joint fault × model-bias grid, IVF comparator, or arbitrary-byte noninterference attestation |
| H4 — provenance/conflict | **ACCEPT — provisional** | **BLOCK** — the implemented provenance-free comparator is confounded and mandatory replay/explanation metrics are absent |
| H5 — downstream decision value | **ACCEPT — provisional** | **BLOCK** — the threshold proxy is not the registered planner/query-lens experiment |
| H6 — bounded operational cost | **ACCEPT — provisional** | **BLOCK** — only a partial in-process microbenchmark exists |
| H7 — provenance × dependency | **ACCEPT — provisional** | **BLOCK** — P0D0/P1D0/P0D1/P1D1 are not executable |

## Synthetic diagnostic results

The following are deterministic implementation diagnostics, not empirical or dissertation results:

- 192 trials per method were generated from eight synthetic windows, three action outcomes, and eight
  repeated seeds;
- STEWIE produced `0/192` harmful-plan flags;
- latest overwrite and timestamp-only each produced `128/192`;
- no-physics produced `0/192`, so the current endpoint does not distinguish STEWIE from that
  ablation;
- the no-dependency state differed from STEWIE only at floating-point roundoff
  (`maximum absolute delta <= 3.33e-16`); and
- the apparent latest-overwrite contrast is driven by deterministic action labels and weak-baseline
  construction, not independent terrain variation.

These observations are useful for diagnosing the harness. They support no H1–H7 conclusion.

## Minimal closure work

1. **Create one manifest-driven executor.** It must refuse execution unless phase, reviewed commit,
   configuration hashes, system adapters, allocation hashes, and `execution_allowed` permit the run.
2. **Separate development from research allocations.** Retain the current arrays/seeds as regression
   fixtures; materialize real, hashed pilot windows using the pilot allocation; create a new
   evaluator-owned confirmatory allocation only after candidate freeze.
3. **Correct the independent-unit model.** Cluster all action conditions by terrain window or allocate
   24 separated windows, then calibrate sample size and minimum effects at that level.
4. **Implement exact mandatory comparators.** For the smallest dissertation core, freeze H1–H3 and
   their confirmatory comparators first; explicitly defer H4–H7 and external-system claims rather
   than leaving them nominally registered but unavailable.
5. **Make truth isolation executable.** Implement the candidate-view projection, separate evaluator
   identity, output freeze, dependency generator, permission probes, and non-vacuous poison tests.
   Remove executed-outcome labels from candidate-visible inputs.
6. **Use one executable metric scorer.** Bind it to the oracle fixtures and enforce coverage,
   invalid-output treatment, contrast direction, availability, multiplicity, and exclusions.
7. **Run and independently review a disjoint pilot.** Freeze tolerances, perturbations, MDEs, sample
   size, and stopping rules before unblinding the replacement confirmatory allocation.
8. **Complete evidence hygiene.** Bind implementation/configuration hashes, repair citation metadata,
   and obtain independent method, novelty, and data-provenance review.

## Verification performed

All commands were run against an isolated archive of
`8f38832b0a6e7b5a1ac2a7a5c3b15c8c422108c6`.

```text
.venv/bin/python scripts/validate_ultrabuild.py
  PASS — manifest, requirements, artifacts, schemas, semantic fixtures, and barrier guards

.venv/bin/python scripts/validate_ultrabuild_contracts.py
  PASS

.venv/bin/python scripts/validate_ultrabuild_requirements.py
  PASS — 51 requirements; 11 test-cited; 40 pending implementation evidence

.venv/bin/python experiments/contracts/validate_barrier1_contracts.py
  PASS structurally — valid=true, acceptance_ready=false

.venv/bin/python experiments/contracts/validate_barrier1_contracts.py --require-acceptance-ready
  EXPECTED BLOCK — exit 2

.venv/bin/pytest -q -p no:cacheprovider \
  experiments/contracts/test_barrier1_contracts.py \
  stewie/ultrabuild scripts/test_ultrabuild_artifacts.py
  PASS — 54 tests

.venv/bin/ruff check stewie/ultrabuild experiments/contracts \
  scripts/validate_ultrabuild.py scripts/validate_ultrabuild_contracts.py \
  scripts/validate_ultrabuild_requirements.py
  PASS
```

Passing these checks establishes internal structural consistency and deterministic prototype behavior.
It does not establish Barrier-1 acceptance or validate any dissertation hypothesis.
