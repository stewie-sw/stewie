# ADR-0007: The cockpit migrates strangler-fig, not big-bang

- **Status**: Accepted
- **Boundary**: stewie frontend
- **Date**: 2026-06 (recorded 2026-07-04)

## Context
The operator cockpit is a working vanilla-JS application served by the FastAPI backend. A previous full React
rewrite was attempted and **reverted** (`55c44c6`) after it black-screened on a map-engine init — a big-bang
replacement put the entire operational surface at risk at once.

## Decision
Evolve the cockpit **strangler-fig**: the vanilla cockpit stays live and authoritative; any React/GeoLibre
migration lands behind explicit parity gates (MG-01/02), pane by pane, with the new surface proven at parity
before it replaces the old one. A generated TypeScript API client + route registry (AC-01/02) is the typed
contract the new panes bind to. No pane is cut over until its parity gate passes.

## Consequences
- The operational UI never goes dark on a rewrite; regressions are caught per-pane, not all at once.
- The migration is resumable and reviewable; it can pause indefinitely without leaving the app broken.
- Frontend scope stays an explicit human decision (route/state and shell choices are reviewed, not inferred).
