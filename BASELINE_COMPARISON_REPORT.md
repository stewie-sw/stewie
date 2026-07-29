# Baseline comparison report

**Artifact ID:** `ART-BASELINE-COMPARISON`
**Producer node:** `EXP-020`
**Consumers:** `REV-010`, `DISS-010`
**Raw evidence:** `reports/ultrabuild/evaluation/trials.jsonl`
**Aggregate:** `reports/ultrabuild/evaluation/evaluation_report.json`
**Status:** exposed exploratory synthetic diagnostic, not confirmatory dissertation validation.

The diagnostic uses eight synthetic terrain windows. Three action kinds, eight development seeds, and
nine methods are repeated measures within each window. There are 192 rows per method and 1,728 rows
overall; those rows must not be described as 1,728 independent trials.

| Method | Availability | Harmful-plan rate | Incorrect states | Mean RMSE when available |
|---|---:|---:|---:|---:|
| STEWIE | 1.000 | 0.000 | 0 | 0.01213 m |
| Latest overwrite | 1.000 | 0.667 | 64 | 0.12142 m |
| Timestamp only | 1.000 | 0.667 | 64 | 0.12142 m |
| Full-map replacement | 1.000 | 0.667 | 64 | 0.12142 m |
| Provenance-free fusion | 1.000 | 0.000 | 0 | 0.01179 m |
| Single lexical authority | 1.000 | 0.000 | 0 | 0.01244 m |

The paired terrain-window contrast `STEWIE − latest overwrite` for harmful-plan commitment is
`−0.667`, with a descriptive cluster-bootstrap 95% interval of `[-0.667, -0.667]`. The zero-width
interval occurs because every generated window has the same constructed effect; it is a warning about
generator homogeneity, not exceptional inferential precision.

Four pairs among the eight generated spatial envelopes overlap. The terrain-window accounting fixes
the earlier action-level pseudoreplication, but these development fixtures still do not constitute a
spatially independent research allocation.

The delayed-observation scenario makes latest/timestamp baselines vulnerable by construction.
External lifelong- and multi-robot-mapping baselines in `BASELINE_REGISTRY.yaml` remain unselected and
unexecuted. The original evaluation seed/window allocation is retired because this harness exposed
it. Consequently, no H1–H7 hypothesis is a confirmatory success.
