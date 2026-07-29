# Perturbation study report

**Artifact ID:** `ART-PERTURBATION-REPORT`
**Producer node:** `EXP-030`
**Consumers:** `REV-010`, `DISS-010`
**Machine report:** `reports/ultrabuild/perturbation/perturbation-report.json`
**Status:** exposed exploratory one-factor diagnostic with explicit failure boundaries.

Seven factors were varied at three levels for four methods, producing 84 aggregate cells over eight
synthetic development windows and eight exposed seeds. STEWIE registered nine failure cells:

- one- and two-cell localization drift: availability `0`;
- added sensor noise `0.05 m`: availability `0.875`; at `0.2 m`: availability `0`;
- ten-sequence observation delay: availability `0`;
- image dropout `0.25` and `0.75`: partial outputs were not consumable as finite full-state maps;
- physics-envelope fractions `0.5` and `0`: availability `0`.

These are fail-closed outcomes rather than unsafe commitments, but they are still operational
failures. Partial-coverage query semantics need a coverage-aware planner before dropout claims can
advance.

Wheel slip, bandwidth/partition duration, map scaling, run-time clock drift, terrain collapse, and
physical material-model mismatch remain unmeasured. Factor interactions were not studied. The
exposed arrays and seeds prohibit confirmatory interpretation.
