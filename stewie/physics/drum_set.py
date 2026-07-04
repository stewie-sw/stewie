"""drum_set.py -- per-drum regolith fill state for the IPEx four-drum bucket-drum excavator (VT-04).

The conserved authority (``ColumnState``) books drum-held regolith as ONE scalar ``drum_inventory``
[kg] -- correct for total-mass conservation, but it hides that IPEx physically carries FOUR
counter-rotating bucket drums (two drum halves per RDS arm; ``system_profile.IPEX.n_drums == 4``).
Per-drum fill matters for capacity limits (a single drum saturates independently of the platform
total), CG / static stability (VT-05: the load is distributed, not lumped), and the offload trigger
(a single drum reads full before the platform total does).

``DrumSet`` is the per-drum decomposition of that scalar: a fixed set of drums, each with its own
capacity and current fill, whose sum equals the platform drum mass. It does NOT own the grid -- cut
and dump stay on ``ColumnState`` (the single mass authority); ``DrumSet`` mirrors those transfers per
drum so ``drum_set.total_fill == column_state.drum_inventory`` is the binding invariant a caller
maintains. This keeps existing scalar callers byte-identical while adding four-drum resolution on top
(the VT-04 note: "keep the scalar total as sum(per_drum) so existing callers stay byte-identical").

Capacities are COMPOSED from the sourced platform hold, never fabricated: the IPEx per-cycle regolith
capacity (``ipex_specs.REGOLITH_PER_CYCLE_KG == 30`` kg, surfaced as
``vehicles.get_vehicle("ipex").drum_capacity_kg``) split equally across the four identical drums ->
7.5 kg/drum. The equal split is a stated modeling choice (the four bucket drums are identical by
design); it preserves the sourced total exactly (4 x 7.5 == 30) rather than replacing it. Independent
corroboration: Schuler et al. 2022 BD-scaling reports ~7.30 kg average collected for the MEDIUM drum
class (``ipex_specs.DRUM_CAPACITY_KG["medium"]``), which brackets the 7.5 kg equal share -- the split
is a derivation from two sourced quantities (30 kg total, 4 drums), not an invented per-drum number.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from stewie.physics import validation as _val
from stewie.specs import system_profile as _sp
from stewie.specs import vehicles as _veh

# Float tolerance for "a drum still has room / still holds mass" tests in the water-fill loops. Far
# below any physically meaningful regolith mass (1e-12 kg = 1 nanogram) so it only absorbs float noise.
_EPS = 1e-12


@dataclass
class DrumSet:
    """Per-drum fill state for a multi-drum excavator (IPEx: four bucket drums).

    ``capacities`` [kg] is fixed at construction (one entry per drum, each > 0); ``fills`` [kg] is the
    mutable per-drum held mass, each bounded to ``0 <= fill <= capacity``. ``total_fill`` is the sum --
    the quantity ``ColumnState`` books as the scalar ``drum_inventory``. All transfers conserve mass:
    ``add`` returns the kg ACCEPTED (a full-drum shortfall is reported to the caller, never silently
    absorbed) and ``remove`` returns the kg WITHDRAWN (bounded by what the drums hold).
    """

    capacities: tuple[float, ...]
    fills: list[float] = field(default_factory=list)   # empty -> all-zero (empty drums) in __post_init__

    def __post_init__(self) -> None:
        if len(self.capacities) < 1:
            raise ValueError("DrumSet needs at least one drum")
        caps = tuple(_val.ensure_positive_scalar(float(c), f"capacity[{i}]")
                     for i, c in enumerate(self.capacities))
        self.capacities = caps
        if not self.fills:
            self.fills = [0.0 for _ in caps]
        elif len(self.fills) != len(caps):
            raise ValueError(f"fills length {len(self.fills)} != n_drums {len(caps)}")
        norm: list[float] = []
        for i, f_kg in enumerate(self.fills):
            v = _val.ensure_nonneg_scalar(float(f_kg), f"fill[{i}]")
            if v > caps[i] + _EPS:
                raise ValueError(f"drum {i} fill {v:.6g} kg exceeds capacity {caps[i]:.6g} kg")
            norm.append(min(v, caps[i]))
        self.fills = norm

    # -- geometry / totals -------------------------------------------------

    @property
    def n_drums(self) -> int:
        return len(self.capacities)

    @property
    def total_fill(self) -> float:
        """Total regolith held across all drums [kg] -- equals ColumnState.drum_inventory when bound."""
        return float(sum(self.fills))

    @property
    def total_capacity(self) -> float:
        return float(sum(self.capacities))

    @property
    def total_remaining(self) -> float:
        return self.total_capacity - self.total_fill

    @property
    def per_drum_fill(self) -> tuple[float, ...]:
        """Immutable snapshot of the per-drum fills [kg]; ``sum(per_drum_fill) == total_fill`` exactly."""
        return tuple(self.fills)

    def remaining(self, drum: int) -> float:
        """Free capacity [kg] in one drum."""
        return self.capacities[drum] - self.fills[drum]

    # -- transfers (mass-conserving) ---------------------------------------

    def add(self, kg: float, drum: int | None = None) -> float:
        """Route ``kg`` of regolith into the drums, capacity-bounded, conserving mass.

        ``drum`` targets one specific drum (excavation routes cut mass to the arm/drum doing the
        digging); ``None`` distributes across every drum that has room, leveling the fills. Returns the
        kg ACCEPTED -- if the drums cannot hold all of ``kg`` (saturation) the shortfall
        ``kg - accepted`` is returned to the caller to handle (e.g. force an offload), never dropped.
        """
        want = _val.ensure_nonneg_scalar(float(kg), "kg")
        if drum is not None:
            take = min(self.capacities[drum] - self.fills[drum], want)
            self.fills[drum] += take
            return take
        return self._level(want, fill=True)

    def remove(self, kg: float, drum: int | None = None) -> float:
        """Withdraw ``kg`` of regolith from the drums (deposit / offload), conserving mass.

        ``drum`` empties one specific drum; ``None`` draws evenly from all non-empty drums. Per-drum
        fill never goes negative. Returns the kg actually WITHDRAWN (bounded by the mass the drums
        hold); a deposit request larger than the load leaves the drums empty and returns less.
        """
        want = _val.ensure_nonneg_scalar(float(kg), "kg")
        if drum is not None:
            take = min(self.fills[drum], want)
            self.fills[drum] -= take
            return take
        return self._level(want, fill=False)

    def _level(self, kg: float, *, fill: bool) -> float:
        """Water-fill ``kg`` into (``fill=True``) or out of (``fill=False``) the drums, leveling.

        Each round gives every drum with room/mass an equal share; a round that does not exhaust ``kg``
        must have saturated (or emptied) at least one drum, so the open set shrinks -- at most
        ``n_drums`` rounds. Returns the kg actually moved (``kg`` minus any un-placeable remainder).
        """
        remaining = kg
        for _ in range(self.n_drums):
            if remaining <= _EPS:
                break
            if fill:
                open_idx = [i for i in range(self.n_drums)
                            if self.capacities[i] - self.fills[i] > _EPS]
            else:
                open_idx = [i for i in range(self.n_drums) if self.fills[i] > _EPS]
            if not open_idx:
                break
            share = remaining / len(open_idx)
            for i in open_idx:
                headroom = (self.capacities[i] - self.fills[i]) if fill else self.fills[i]
                take = min(headroom, share)
                self.fills[i] += take if fill else -take
                remaining -= take
        return kg - remaining

    # -- guards ------------------------------------------------------------

    def check_capacity_bounds(self) -> None:
        """Guard the per-drum domain (callable in CI): every fill finite and ``0 <= fill <= capacity``."""
        for i, f_kg in enumerate(self.fills):
            _val.ensure_nonneg_scalar(float(f_kg), f"fill[{i}]")
            if f_kg > self.capacities[i] + _EPS:
                raise ValueError(
                    f"drum {i} fill {f_kg:.6g} kg exceeds capacity {self.capacities[i]:.6g} kg")

    # -- constructors from the sourced registries --------------------------

    @classmethod
    def split_total(cls, total_capacity_kg: float, n_drums: int) -> "DrumSet":
        """A set of ``n_drums`` identical (empty) drums sharing ``total_capacity_kg`` equally."""
        n = int(n_drums)
        if n < 1:
            raise ValueError(f"n_drums must be >= 1 (got {n_drums})")
        total = _val.ensure_positive_scalar(float(total_capacity_kg), "total_capacity_kg")
        per = total / n
        return cls(capacities=tuple(per for _ in range(n)))

    @classmethod
    def for_vehicle(cls, vehicle: str, n_drums: int) -> "DrumSet":
        """Compose per-drum capacity from a registry vehicle's sourced total drum hold.

        ``vehicles.get_vehicle(vehicle).drum_capacity_kg`` is the sourced PLATFORM hold; it is split
        equally across ``n_drums`` identical drums. A non-excavator (``drum_capacity_kg == 0``) raises.
        """
        veh = _veh.get_vehicle(vehicle)
        if veh.drum_capacity_kg <= 0.0:
            raise ValueError(
                f"vehicle {veh.name!r} is not an excavator (drum_capacity_kg=0); no drums to model")
        return cls.split_total(veh.drum_capacity_kg, n_drums)

    @classmethod
    def for_ipex(cls) -> "DrumSet":
        """The IPEx four-drum set: the sourced 30 kg/cycle platform hold
        (``ipex_specs.REGOLITH_PER_CYCLE_KG`` via ``vehicles`` "ipex") split equally across
        ``system_profile.IPEX.n_drums == 4`` identical bucket drums (7.5 kg/drum). See the module
        docstring for the equal-split rationale + BD-scaling corroboration."""
        return cls.for_vehicle("ipex", int(_sp.IPEX.n_drums))
