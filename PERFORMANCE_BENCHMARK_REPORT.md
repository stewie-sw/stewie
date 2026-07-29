# Performance benchmark report

**Artifact ID:** `ART-PERFORMANCE-REPORT`
**Producer node:** `PERF-010`
**Consumers:** `REV-010`, `DISS-010`
**Machine report:** `reports/ultrabuild/performance/performance-report.json`
**Environment:** `reports/ultrabuild/performance/environment.json`
**Status:** all measured targets passed; the budget remains partially measured.

On the recorded 32-CPU Linux host, using Python 3.11.2 and NumPy 2.4.6, 200 measured warm runs
produced:

| Path | Observed | Target |
|---|---:|---:|
| Evidence validation p95 | 0.621 ms | ≤100 ms |
| WAL/FULL durable append p95 | 57.283 ms | ≤100 ms |
| 256×256, four-source reconcile p95 | 2.236 ms | ≤500 ms |
| Reconcile p99 | 2.251 ms | ≤1000 ms |
| Full-history integrity-gated revision query p95 | 55.279 ms | ≤100 ms |
| Deterministic replay mismatches | 0 | 0 |

The query now verifies the complete stored graph, upstream payload lineage, receipts, and projections
before returning authoritative state; that fail-closed scope explains the material increase from the
earlier payload-only query timing.

This is a warm in-process microbenchmark. Full bitemporal joins, indexed provenance tracing,
1,000-version
replay, metadata growth, cold cache, concurrency levels two/four, scaling grids, and distributed
synchronization remain unmeasured. H6 is not established.
