# ADR-0002: The conserved authority mutates terrain; autonomy only commands

- **Status**: Accepted
- **Boundary**: FORGE ↔ DART
- **Date**: 2026-06 (recorded 2026-07-04)

## Context
STEWIE hosts learned/planned autonomy (DART) that decides where to dig, haul, and build. If a learned policy
could write terrain directly, its reward would be hackable (it could "wish" mass into existence) and the
world model would drift from physical reality.

## Decision
Learned and planned components **only command**; the conserved-physics authority (FORGE) is the only thing
that mutates terrain. Every terrain change flows through the mass-conserving cut/fill/deposit primitives.
Reward is defined against the true conserved fields, so it is unhackable by construction.

## Consequences
- Mass conservation holds regardless of policy behavior; a bad policy wastes energy, it cannot fabricate mass.
- Autonomy is portable across bodies (the authority is g-parameterized) without re-validating conservation.
- Single-objective tasks have a feasibility floor (dig energy is mass-fixed); RL headroom lives in the
  multi-objective scheduling layer, not in the physics.
