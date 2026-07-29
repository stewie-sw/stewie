# Ablation report

**Artifact ID:** `ART-ABLATION-REPORT`
**Producer node:** `EXP-020`
**Consumers:** `REV-010`, `DISS-010`
**Source:** `reports/ultrabuild/evaluation/evaluation_report.json`
**Status:** negative/neutral exposed exploratory result retained.

| Ablation | Harmful-plan rate | Mean available RMSE | RMSE difference from full |
|---|---:|---:|---:|
| Full STEWIE | 0.000 | 0.012133 m | — |
| No physics gate | 0.000 | 0.011957 m | −0.000176 m |
| No dependency correction | 0.000 | 0.012133 m | 0.000000 m |
| No uncertainty weighting | 0.000 | 0.012154 m | +0.000021 m |
| Provenance-free fusion | 0.000 | 0.011785 m | −0.000348 m |

The current scenario does not demonstrate necessity of physics, dependency correction, uncertainty
weighting, or provenance gating on the harmful-plan endpoint. The paired
`STEWIE − no_physics` contrast is exactly `0.000`, with descriptive interval `[0.000, 0.000]`.
Physics changes admissibility in the controlled multi-robot graph and passes a state-byte
noninterference test, but that is structural evidence rather than an outcome benefit.

H2, H3, H4, and the H7 provenance-by-dependency interaction remain unsupported by this diagnostic.
The negative result is retained so architecture complexity cannot be mistaken for scientific
contribution.
