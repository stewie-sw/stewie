# World-state ontology

**Artifact ID:** `ART-ONTOLOGY`
**Producer node:** `WS-010`
**Consumers:** `ARCH-020`, `WS-020`, `WS-030`, `WS-040`, `WS-050`, `VERT-010`
**Status:** specified vocabulary v0.1; pending Barrier-2 review.

## Principle

A value is not “the map.” It is a claim about a spatial entity under a state kind, time lens,
authority scope, uncertainty model, and provenance bundle. Two numerically equal rasters may have
different meanings and may not be interchangeable.

## Entities

- `World`: a named physical or simulated environment.
- `Region`: a spatial extent in a declared CRS/frame.
- `WorldObject`: terrain patch, material volume, robot, hazard, structure, work zone, or derived layer.
- `StateClaim`: an assertion about an object/region.
- `WorldStateVersion`: an immutable collection of claims on a named branch.
- `Evidence`: observation, action record, physical prediction, or human assertion.
- `Agent`: robot, sensor, software process, operator, reviewer, or organization.
- `Activity`: observe, transform, calibrate, reconcile, verify, plan, execute, review, or archive.
- `Decision`: a policy outcome and the exact version/lens it consumed.
- `HypothesisSet`: mutually compatible or competing claims retained without forced collapse.

## State kinds

| Kind | Meaning | May directly become accepted? |
|---|---|---|
| `planned` | Intended future state or action effect | No |
| `predicted` | Model-produced possible state | No; evidence only |
| `simulated` | State realized in a named simulation branch | Only within that simulation branch |
| `observed` | Immutable report from a sensor/pipeline/source | No; must be reconciled |
| `proposed` | Candidate constructed from admissible observations | No |
| `reconciled` | Policy decision accepted for a named belief branch | Yes, on that branch |
| `verified` | Reconciled claim that passed a declared independent procedure | Yes; procedure remains explicit |
| `authoritative` | Current governing claim within an explicit scope | Yes; scope and lens required |
| `superseded` | Previously governing claim replaced by a linked correction | Historical only |
| `archived` | Frozen terminal record retained for audit/replay | No mutation |
| `reference` | Withheld evaluation-only state | Never visible to evaluated code |

`verified` does not mean physically true. `authoritative` does not mean globally true. Both require a
scope such as `simulation:run-17`, `reconciled-policy:v2`, or `evaluation-only`.

## Relations

- `wasGeneratedBy(claim, activity)`
- `wasAttributedTo(claim, agent)`
- `used(activity, evidence_or_version)`
- `wasDerivedFrom(claim, evidence_or_claim)`
- `specializationOf(claim, broader_claim)`
- `alternateOf(claim_a, claim_b)`
- `supersedes(new_claim, old_claim)`
- `invalidates(event, derived_artifact)`
- `competesWith(claim_a, claim_b)`
- `corroborates(evidence_a, evidence_b)`
- `mayDependOn(evidence_a, evidence_b, region, time)`
- `describes(claim, world_object)`
- `validDuring(claim, interval)`
- `knownDuring(claim, transaction_interval)`
- `informed(decision, version_and_lens)`

The first six align with W3C PROV concepts; STEWIE-specific relations specialize them.

## Authority scopes

Authority is the tuple:

`(world_id, branch_id, state_kind, policy_id, valid_at, known_at, region, representation)`.

An API or UI that says only “authoritative” is underspecified. Simulation, operator proposal,
reconciled belief, and evaluation reference must occupy different branches/scopes.

## Conflict semantics

Claims conflict when their extents and valid intervals overlap, their values are incompatible under
the declared uncertainty/tolerance, and neither is a specialization or explicit supersession of the
other. Conflict creates a `HypothesisSet`; it does not select the newest claim.

A hypothesis set closes only through a recorded decision whose evidence discriminates the claims or
through an explicit human policy decision. The losing claim becomes rejected or superseded, never
deleted.

## Verification levels

1. `unverified`: source record only;
2. `schema_valid`: contract checks passed;
3. `cross_checked`: compared with independent evidence;
4. `reconciled`: policy decision recorded;
5. `experiment_verified`: evaluated against withheld reference in a named experiment;
6. `operationally_verified`: independent real-world procedure passed.

These levels are not the graph-node lifecycle and must not be confused with it.
