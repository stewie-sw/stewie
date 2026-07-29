# Reviewer defect history and revision evidence

**Artifact ID:** `ART-REVIEWER-DEFECT-HISTORY`
**Producer node:** `REV-010`
**Consumers:** `ORCH-001`, `DISS-010`
**Reviewed source:** `608c6881e9be5754ac801a7833ee1f8217c238a0`
**Status:** final for this bounded build.

No implementation node certified itself. Research, database/world-state, and systems/package reviews
were conducted independently against pinned clean trees.

| Review target | Independent finding before revision | Owning change | Evidence after revision | Disposition |
|---|---|---|---|---|
| `8f38832b` | caller-controlled transaction metadata, promotion bypass, incomplete provenance closure, and non-authoritative payload identity | `cb9532b2` | untrusted submissions separated from completed records; one append authority; observation-only candidate values; atomic promotion/provenance/revision CAS; payload-gated authoritative query | resolved in bounded prototype |
| `cb9532b2` | snapshot DB/CAS race; rebuild admitted corrupt immutable inputs; environment SHA described as verified; stale runtime docs; benchmark reuse traceback | `6bc682bb` | backup-first exact-cut snapshot; full-integrity rebuild gate; externally-declared identity label; corrected docs; usage error without traceback | resolved |
| `cb9532b2` | deleted transaction sequence undetected; corrupt admitted evidence did not block query; extreme numeric time escaped; Barrier-3 graph lacked real prior/new discrepancy | `6bc682bb`, `c28a74f3`, `a67b287c` | sequence-contiguity check; complete lineage/payload query gate; signed-64-bit numeric profile and atomic rejection | engineering defects resolved; Barrier 3 still blocked |
| `6bc682bb` | indexed record shadow fields were not checked; missing append or applied-promotion receipt rows were invisible | `c28a74f3` | six shadow-field mutation probes fail integrity; each durable record/promotion requires one receipt path; rebuild refuses missing registry evidence | resolved |
| `c28a74f3` | `10**100` still overflowed SQLite; malformed receipt raised `KeyError`; well-formed operation-hash mutation was invisible | `a67b287c` | storage-safe integer bound; malformed receipt reported; CAS receipt binds operation hash and canonical receipt content | resolved |
| `a67b287c` | idempotent replay changed `reason_code` without resealing returned receipt | `effdc94d` | replay receipt is resealed; durable original remains byte-identical and `applied`; sequence/head unchanged; integrity remains true | resolved |
| `effdc94d` | signed-64-bit temporal integers beyond exact binary64 range made a newly appended `REAL` shadow differ from immutable bytes | `e6d4e89e` | non-exact temporal integers, including `2**53 + 1`, fail atomically before persistence | resolved |
| `e6d4e89e` | output-reuse CLI regression also required a 20-run latency benchmark to pass under full-suite host saturation | `608c6881` | first-run exit is checked against the emitted budget result; second-run output reuse must still fail as a usage error | resolved |
| `608c6881` | replacement allocation, power/MDE, materialized terrain hashes, executable firewalls/oracles, strong baseline attestations, and confirmatory packet absent | none—scientific redesign required | final scientific review remains `BLOCK`; exploratory results retain explicit labels | open critical research blockers |
| `608c6881` | Barrier-3 fixture is a generated 2×2 raster with one root revision, no real-terrain prior/new reconstruction, and no integrated discrepancy artifact | none—new vertical slice required | final database review remains `BLOCK` for Barrier 3 | open barrier blocker |

## Bounded-loop record

Three ordinary local rework cycles were followed by two narrow additional closures. The
orchestrator allowed the additional cycles because independent reviewers supplied reproducible,
contract-bound defects with deterministic acceptance tests; each revision improved the same
fail-closed integrity metric. No cycle was used to manufacture a scientific effect.

The final authority-query p95 is `55.279 ms` against a `100 ms` registered target. All six measured
performance/replay targets pass. The stronger integrity checks increased the scope of every
authoritative query but did not breach the budget.

The unresolved research and real-terrain findings were not iterated away with more code because they
require a new evaluator-controlled allocation and new evidence, not a local implementation repair.
