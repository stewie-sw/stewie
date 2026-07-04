# ADR-0005: The physics-backend registry fails closed on a not-yet-conserving backend

- **Status**: Accepted
- **Boundary**: FORGE ↔ stewie (mission config)
- **Date**: 2026-07 (recorded 2026-07-04)

## Context
STEWIE supports more than one physics backend (the conserved Tier-2 numpy authority today; a live Chrono
oracle later). A mission that silently ran on a backend whose conservation is unproven would produce numbers
that look authoritative but are not — the worst kind of failure for a digital twin.

## Decision
Missions carry an explicit `physics_backend_id`, validated against a registry (`/physics/backends`, PX-02).
The registry **fails closed**: only backends whose conservation is validated are selectable as the default;
a not-yet-conserving backend (the Chrono oracle) is registered but must be opted into explicitly and is
flagged. An unknown or unvalidated id is rejected at mission construction, not at run time.

## Consequences
- A twin result always names the backend that produced it; an unproven backend cannot masquerade as default.
- Adding a backend is a governed act (it enters the ledger validated/frozen/deprecated), not an import.
- The body registry (BD-02) applies the same fail-closed discipline at the data-ingest boundary.
