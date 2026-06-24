"""siteplan.py -- the site-plan validate-and-advise analyzer (Gap B core, 2026-06-23).

The per-structure decomposition (``structures.py``) already turns a dropped structure into mass-balanced
cut/fill orders. This module is the layer ABOVE it: it reasons across the WHOLE set of placed structures
-- the operator's authored base layout -- and, WITHOUT moving anything, reports:

  * the base-wide MASS economy (total cut vs fill, net surplus/deficit);
  * a base-wide source<->sink ROUTING that pairs each fill with its nearest available cut (so one borrow
    pit can feed several fills instead of one pit per structure), with the total haul work;
  * inter-structure CLEARANCES (footprint overlaps / sub-minimum gaps);
  * a BUILD ORDER in which each fill's paired source cut precedes it;
  * human-readable ADVISORIES.

Design choice (user, 2026-06-23): **validate-and-advise** -- the operator keeps placement authority; the
solver checks + advises, it does not auto-place. See docs/siteplan_structure_first_design_2026-06-23.md.

Mass is the conserved quantity: a CUT yields BANK material (rho_bank = RHO_DEEP); a FILL demands LOOSE
material (rho_loose = RHO_SPOIL). structures.py sizes a consuming structure's borrow so bank mass == loose
mass (swell-corrected), so a self-balanced structure nets ~0 here by construction.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from leap import structures as S
from stewie.specs import constants as K

RHO_BANK = K.RHO_DEEP     # in-situ density of cut material [kg/m^3]
RHO_LOOSE = K.RHO_SPOIL   # placed-loose density of fill material [kg/m^3]


@dataclass
class PlacedStructure:
    """One structure the operator dropped on the map: a template name + a site coordinate (local metres)
    + optional template params. The footprint/decomposition come from ``structures.py``."""
    name: str
    x: float
    y: float
    params: dict = field(default_factory=dict)


@dataclass
class _Order:
    order_idx: int
    struct_idx: int
    struct_name: str
    action: str
    kind: str          # "cut" (source) | "fill" (sink)
    x: float
    y: float
    footprint_m2: float
    depth_m: float
    mass_kg: float     # bank mass yielded (cut) or loose mass demanded (fill)


@dataclass
class Pairing:
    """A routed flow of material from a source cut to a sink fill."""
    source_order_idx: int
    sink_order_idx: int
    source_x: float
    source_y: float
    sink_x: float
    sink_y: float
    mass_kg: float
    haul_dist_m: float


@dataclass
class Clearance:
    """The footprint relationship between two placed structures (disk approximation)."""
    i: int
    j: int
    gap_m: float        # centre distance minus the two bounding radii (< 0 = overlap)
    overlap: bool


@dataclass
class SitePlanReport:
    total_cut_mass_kg: float
    total_fill_mass_kg: float
    net_mass_kg: float                       # cut - fill: > 0 surplus to spoil, < 0 deficit to import
    pairings: list[Pairing]
    total_haul_work_kg_m: float
    clearances: list[Clearance]
    build_order: list[int]                   # order indices, each source before the fill it feeds
    advisories: list[str]

    def to_dict(self) -> dict:
        return {
            "total_cut_mass_kg": self.total_cut_mass_kg,
            "total_fill_mass_kg": self.total_fill_mass_kg,
            "net_mass_kg": self.net_mass_kg,
            "total_haul_work_kg_m": self.total_haul_work_kg_m,
            "pairings": [vars(p) for p in self.pairings],
            "clearances": [vars(c) for c in self.clearances],
            "build_order": list(self.build_order),
            "advisories": list(self.advisories),
        }


def _order_mass(kind: str, footprint_m2: float, depth_m: float) -> float:
    rho = RHO_BANK if kind == "cut" else RHO_LOOSE
    return rho * footprint_m2 * depth_m


def _decompose_all(placements: list[PlacedStructure]) -> list[_Order]:
    orders: list[_Order] = []
    k = 0
    for s_idx, ps in enumerate(placements):
        # S.decompose raises ValueError on an unknown structure name -- propagate it (honest failure).
        for od in S.decompose(ps.name, ps.x, ps.y, **(ps.params or {})):
            orders.append(_Order(
                order_idx=k, struct_idx=s_idx, struct_name=ps.name,
                action=od["action"], kind=od["kind"], x=od["x"], y=od["y"],
                footprint_m2=od["footprint_m2"], depth_m=od["depth_m"],
                mass_kg=_order_mass(od["kind"], od["footprint_m2"], od["depth_m"]),
            ))
            k += 1
    return orders


def _route(orders: list[_Order]) -> tuple[list[Pairing], float]:
    """Greedy base-wide routing: each fill (sink) draws from the nearest cut (source) with remaining
    supply until its demand is met. Largest demand is routed first so big fills claim near sources. Pure
    advisory -- it does NOT mutate the orders, it reports the cheaper base-wide pairing."""
    sources = [o for o in orders if o.kind == "cut"]
    sinks = [o for o in orders if o.kind == "fill"]
    remaining = {o.order_idx: o.mass_kg for o in sources}
    pairings: list[Pairing] = []
    total_work = 0.0
    for sink in sorted(sinks, key=lambda o: -o.mass_kg):
        demand = sink.mass_kg
        # nearest sources first
        for src in sorted(sources, key=lambda o: math.dist((o.x, o.y), (sink.x, sink.y))):
            if demand <= 1e-12:
                break
            avail = remaining[src.order_idx]
            if avail <= 1e-12:
                continue
            take = min(avail, demand)
            dist = math.dist((src.x, src.y), (sink.x, sink.y))
            pairings.append(Pairing(
                source_order_idx=src.order_idx, sink_order_idx=sink.order_idx,
                source_x=src.x, source_y=src.y, sink_x=sink.x, sink_y=sink.y,
                mass_kg=take, haul_dist_m=dist,
            ))
            remaining[src.order_idx] -= take
            demand -= take
            total_work += take * dist
    return pairings, total_work


def _struct_radius(orders_of_struct: list[_Order]) -> float:
    """Bounding-disk radius for a structure: from the SUM of its order footprints (disk approximation)."""
    total_fp = sum(o.footprint_m2 for o in orders_of_struct)
    return math.sqrt(total_fp / math.pi) if total_fp > 0 else 0.0


def _clearances(placements: list[PlacedStructure], orders: list[_Order], min_gap_m: float) -> list[Clearance]:
    by_struct: dict[int, list[_Order]] = {}
    for o in orders:
        by_struct.setdefault(o.struct_idx, []).append(o)
    radii = {i: _struct_radius(by_struct.get(i, [])) for i in range(len(placements))}
    out: list[Clearance] = []
    for i in range(len(placements)):
        for j in range(i + 1, len(placements)):
            d = math.dist((placements[i].x, placements[i].y), (placements[j].x, placements[j].y))
            gap = d - radii[i] - radii[j]
            out.append(Clearance(i=i, j=j, gap_m=gap, overlap=gap < 0.0))
    return out


def _build_order(orders: list[_Order]) -> list[int]:
    """Sources before sinks: every cut precedes every fill, so each fill's paired source cut is already
    built when the fill runs. Within a class, preserve authored order (stable)."""
    cuts = [o.order_idx for o in orders if o.kind == "cut"]
    fills = [o.order_idx for o in orders if o.kind != "cut"]
    return cuts + fills


def analyze_siteplan(placements: list[PlacedStructure], *, min_gap_m: float = 2.0) -> SitePlanReport:
    """Validate-and-advise over a set of placed structures. Raises ValueError on an unknown structure."""
    orders = _decompose_all(placements)
    total_cut = sum(o.mass_kg for o in orders if o.kind == "cut")
    total_fill = sum(o.mass_kg for o in orders if o.kind != "cut")
    net = total_cut - total_fill
    pairings, haul_work = _route(orders)
    clearances = _clearances(placements, orders, min_gap_m)
    border = _build_order(orders)

    advisories: list[str] = []
    n_sources = sum(1 for o in orders if o.kind == "cut")
    n_sinks = sum(1 for o in orders if o.kind != "cut")
    tol = 1e-6 * max(total_cut, 1.0)
    if net > tol:
        advisories.append(
            f"base has a {net:,.0f} kg material surplus -- route the surplus cut to a spoil pile or an "
            f"export sink (it is not consumed by any fill).")
    elif net < -tol:
        advisories.append(
            f"base has a {-net:,.0f} kg material deficit -- the fills demand more than the cuts yield; "
            f"add a borrow pit or import material.")
    if n_sources >= 2 and n_sinks >= 1:
        advisories.append(
            f"{n_sources} cut sources feed {n_sinks} fill(s) -- route base-wide (one borrow pit can feed "
            f"several fills) to cut total haul rather than one pit per structure.")
    overlaps = [c for c in clearances if c.overlap]
    for c in overlaps:
        advisories.append(
            f"structures #{c.i} ({placements[c.i].name}) and #{c.j} ({placements[c.j].name}) overlap "
            f"(gap {c.gap_m:.1f} m) -- adjust placement so footprints clear by >= {min_gap_m:.1f} m.")

    return SitePlanReport(
        total_cut_mass_kg=total_cut, total_fill_mass_kg=total_fill, net_mass_kg=net,
        pairings=pairings, total_haul_work_kg_m=haul_work,
        clearances=clearances, build_order=border, advisories=advisories,
    )
