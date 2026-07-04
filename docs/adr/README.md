# Architecture Decision Records (ADRs)

[REQ:MT-05] One record per load-bearing subsystem-boundary decision in STEWIE (DART / LODE / LEAP / FORGE /
stewie core). Each ADR is immutable once accepted: to change a decision, add a new ADR that supersedes it
(never rewrite history). Format is MADR-lite — Status · Context · Decision · Consequences.

These are not aspirational; every ADR here records a decision already realized in the code and cited to its
enforcing test or module. The continuity-governance gate (`scripts/continuity_gate.py`) checks this set stays
present + checked in.

| ADR | Boundary | Decision |
|-----|----------|----------|
| [0001](0001-single-physics-authority.md) | FORGE ↔ render | One physics authority owns all dynamics; render is a separate consumer |
| [0002](0002-conserved-authority-mutates-terrain.md) | FORGE ↔ DART | The conserved authority mutates terrain; autonomy only commands |
| [0003](0003-terrain-memory-authoritative-world-model.md) | LEAP ↔ LODE | STEWIE keeps an authoritative world model (Terrain Memory), not rover-centric SLAM |
| [0004](0004-frozen-on-disk-seams.md) | cross-engine | Engines agree on frozen on-disk artifact contracts, never shared memory/types |
| [0005](0005-fail-closed-physics-backend-registry.md) | FORGE ↔ stewie | The physics-backend registry fails closed on a not-yet-conserving backend |
| [0006](0006-import-boundaries-and-lean-server.md) | stewie packaging | Citable packages carry no heavy/contaminated imports; the server boots lean |
| [0007](0007-strangler-fig-frontend.md) | stewie frontend | The cockpit migrates strangler-fig behind parity gates — no big-bang rewrite |
