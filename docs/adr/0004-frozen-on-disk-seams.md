# ADR-0004: Engines meet at frozen on-disk artifact contracts

- **Status**: Accepted
- **Boundary**: cross-engine (FORGE ↔ render ↔ ROS2)
- **Date**: 2026-06 (recorded 2026-07-04)

## Context
Three stages (physics authority → render/sensor → perception/ROS2) are written in different languages and
runtimes. Sharing memory or types across them would couple their release cycles and make each stage
un-testable in isolation.

## Decision
Stages agree only on **frozen on-disk artifact contracts**, never shared memory or types:
- **Seam 1 (state-field contract)** — the authority writes texture-encoded state fields (heightmap, density,
  disturbance, dust, ice); the renderer samples them in shaders. Frozen as `INTERFACE.md`.
- **Seam 2 (sensor-bridge contract)** — the renderer writes `sensors.json` + PNGs; the containerized ROS2
  stack reads them. Frozen as the sensor-bridge contract (REP-103 conventions).

## Consequences
- Each stage is independently testable against the contract with fixtures — no live neighbor required.
- A stage can be reimplemented (or run offline/replayed) as long as it honors the artifact bytes.
- The interop converters (BA-06) are the typed, tested realizations of moving data across these seams.
