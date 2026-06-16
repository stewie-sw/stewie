"""Fleet shared-resource reservations (FL-03, PRD §7.10). Chargers, pits, dumps, observation vantages,
and constrained corridors are SHARED RESOURCES with finite simultaneous capacity. A ReservationLedger
admits a time-windowed reservation only if it never pushes an instant on that resource over its
capacity -- turning the after-the-fact conflict DETECTORS (mission_planner._vehicle_conflicts /
_charger_conflicts) into PREVENTIVE admission control the fleet coordinator (FL-04) plans against. A
same-exclusive site or a single charger is just a capacity-1 resource; a pit that fits k loaders is
capacity-k; a one-way corridor is capacity-1. Windows are half-open [t_start, t_end), so two adjacent
reservations (one ends exactly as the next begins) do NOT conflict."""
from __future__ import annotations

from dataclasses import dataclass

_KINDS = ("charger", "pit", "dump", "vantage", "corridor")


@dataclass(frozen=True)
class SharedResource:
    """A shared fleet resource. `capacity` is the max number of vehicles that may occupy it at once."""
    id: str
    kind: str
    capacity: int = 1


@dataclass(frozen=True)
class Reservation:
    """A vehicle's claim on a resource over the half-open window [t_start, t_end)."""
    resource_id: str
    vehicle: str
    t_start: float
    t_end: float


class ReservationLedger:
    def __init__(self, resources) -> None:
        self._res: dict[str, SharedResource] = {}
        for r in resources:
            if r.kind not in _KINDS:
                raise ValueError(f"unknown shared-resource kind {r.kind!r}; known: {_KINDS}")
            if int(r.capacity) < 1:
                raise ValueError(f"resource {r.id!r} capacity must be >= 1 (got {r.capacity})")
            self._res[r.id] = r
        self._held: list[Reservation] = []

    def _peak_occupancy(self, resource_id: str, extra: Reservation | None = None) -> int:
        """Peak simultaneous occupancy on a resource over the held reservations (+ optional `extra`).
        Sweep endpoints; at equal times a release (-1) is processed before an acquire (+1) so half-open
        adjacency does not double-count."""
        ivs = [r for r in self._held if r.resource_id == resource_id]
        if extra is not None:
            ivs = ivs + [extra]
        events: list[tuple[float, int]] = []
        for r in ivs:
            events.append((float(r.t_start), 1))
            events.append((float(r.t_end), -1))
        events.sort(key=lambda e: (e[0], e[1]))      # -1 before +1 at the same instant (half-open)
        cur = peak = 0
        for _t, delta in events:
            cur += delta
            peak = max(peak, cur)
        return peak

    def would_admit(self, req: Reservation) -> bool:
        """True iff `req` could be reserved now without exceeding the resource's capacity. Pure (no
        state change). Raises KeyError on an unknown resource, ValueError on an empty/negative window."""
        r = self._res.get(req.resource_id)
        if r is None:
            raise KeyError(f"unknown resource {req.resource_id!r}; known: {list(self._res)}")
        if req.t_end <= req.t_start:
            raise ValueError(f"empty/negative reservation window [{req.t_start}, {req.t_end})")
        return self._peak_occupancy(req.resource_id, extra=req) <= r.capacity

    def reserve(self, req: Reservation) -> bool:
        """Admit `req` iff it fits the capacity; returns True (and records it) on success, False if it
        would conflict."""
        if self.would_admit(req):
            self._held.append(req)
            return True
        return False

    def release(self, resource_id: str, vehicle: str) -> int:
        """Drop all of `vehicle`'s reservations on `resource_id`; returns how many were released."""
        before = len(self._held)
        self._held = [r for r in self._held
                      if not (r.resource_id == resource_id and r.vehicle == vehicle)]
        return before - len(self._held)

    def occupancy(self, resource_id: str, t: float) -> int:
        """How many vehicles occupy `resource_id` at instant `t` (half-open: the end is not occupied)."""
        if resource_id not in self._res:
            raise KeyError(f"unknown resource {resource_id!r}; known: {list(self._res)}")
        return sum(1 for r in self._held
                   if r.resource_id == resource_id and r.t_start <= t < r.t_end)

    def held(self) -> list[Reservation]:
        return list(self._held)
