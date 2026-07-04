# ADR-0006: Citable packages carry no heavy imports; the server boots lean

- **Status**: Accepted
- **Boundary**: stewie packaging / import graph
- **Date**: 2026-07 (recorded 2026-07-04)

## Context
Parts of the monorepo are extracted as independently citable packages (`stewie-bodies`, `stewie-forge`).
If those packages, or the server's import path, pulled in heavy CV/GIS/ML libraries (opencv, rasterio,
torch, matplotlib), every install and every server boot would drag the whole dependency surface — slow,
fragile, and a supply-chain liability.

## Decision
Enforce import boundaries: the citable packages depend only on numpy/stdlib and never import application or
heavy modules; the lean `core` profile boots `stewie-serve` + `/healthz` with **zero** heavy CV/GIS libs
(MT-04). Heavy libraries are opt-in dependency profiles, lazy-imported at their use site. A CI import-boundary
test + a clean-subprocess lean-boot test pin this.

## Consequences
- `stewie-bodies` / `stewie-forge` are publishable and citable without the app's baggage.
- `pip install stewie[server]` still resolves the full runtime (the `server` profile composes the parts).
- A new heavy import at the wrong layer fails CI, not production.
