# ADR-0001: A single physics authority owns all dynamics

- **Status**: Accepted
- **Boundary**: FORGE ↔ render/sensor
- **Date**: 2026-06 (recorded 2026-07-04)

## Context
The simulator couples a terramechanics/dynamics solver with a renderer + sensor model. A recurring failure
mode in coupled sims is splitting rigid-body authority across two engines (e.g. letting the renderer also
integrate motion), which desynchronizes state and makes conservation unprovable.

## Decision
FORGE (the conserved terramechanics core) is the **sole** authority for all dynamics — rover, terramechanics,
and clasts. The render/sensor layer (Godot) is a pure consumer: it reads authority state and produces frames,
never integrating motion or mutating terrain. Dust is render-only ballistic particles, never in the mass
balance.

## Consequences
- Mass conservation is provable at the authority (rel-drift ~1e-16; `height == datum + mass/(area·ρ)`).
- The render layer can be swapped or run offline without touching dynamics.
- The two sides never share memory or types — they meet only at the frozen seams (see ADR-0004).
