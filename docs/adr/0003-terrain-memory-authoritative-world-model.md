# ADR-0003: Terrain Memory — an authoritative world model, not rover-centric SLAM

- **Status**: Accepted
- **Boundary**: LEAP ↔ LODE
- **Date**: 2026-06 (recorded 2026-07-04)

## Context
The rover physically reshapes the terrain it must then perceive (dig a pit, build a berm). A purely
rover-centric SLAM map — rebuilt from scratch each pass — cannot express "the terrain at time t changed
because the rover changed it," which is exactly the path-dependent behavior STEWIE exists to capture.

## Decision
STEWIE (LODE) maintains an **authoritative, persistent world model** — Terrain Memory — keyed by site. LEAP
(localization/estimation) registers observations *into* that model (e.g. scan-to-DEM against the known LOLA
prior) rather than building a fresh rover-frame map. A completed run folds its terrain back into Terrain
Memory; belief/authority divergence is recorded per (site, source).

## Consequences
- Localization is map-relative (we have the prior DEM), not SLAM-from-scratch — a smaller, better-posed problem.
- The observed-map-vs-truth-at-time-t comparison (the LAC-style mapping objective) is well-defined.
- The world model is the shared substrate for the costmap, the perception scorer, and any future RL reward.
