"""Designated zones -- HARD, non-overridable spatial constraints for navigation + excavation.

An operator (or a safety authority) designates an area as NO_GO / NO_EXCAVATION / HAZARD / PROTECTED.
These are LOCKED constraints the autonomy and the optimizer CANNOT relax: they are enforced as REFUSAL
gates (raise on violation), never as soft cost that a planner could trade away. There is NO API to remove,
disable, or override a designated zone, and the zone records are immutable (frozen) -- non-overridable by
construction. The planner consumes them as hard keep-outs; the excavator refuses any dig that touches one.
"""
# PROVENANCE: SolNav dissertation (A. Storey) -- moved from solnav/world/zones.py, 2026-06-09 (M2)
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class ZoneType(str, Enum):
    NO_GO = "no_go"                  # no traverse AND no excavation
    NO_EXCAVATION = "no_excavation"  # traverse permitted, NO digging
    HAZARD = "hazard"                # known hazard -> no traverse (hard)
    PROTECTED = "protected"          # e.g. the charger -- no excavation, terrain must stay stable


@dataclass(frozen=True)
class DesignatedZone:
    """An immutable designated area. frozen -> cannot be mutated; the registry exposes no removal."""
    x: float
    y: float
    radius_m: float
    zone_type: ZoneType
    label: str = ""
    designated_by: str = "operator"

    def contains(self, x, y) -> bool:
        return math.hypot(x - self.x, y - self.y) <= self.radius_m

    def overlaps(self, x, y, r) -> bool:
        return math.hypot(x - self.x, y - self.y) <= self.radius_m + r

    @property
    def forbids_traverse(self) -> bool:
        return self.zone_type in (ZoneType.NO_GO, ZoneType.HAZARD)

    @property
    def forbids_excavation(self) -> bool:
        return True                  # every designated zone forbids excavation

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "radius_m": self.radius_m, "zone_type": self.zone_type.value,
                "label": self.label, "designated_by": self.designated_by,
                "forbids_traverse": self.forbids_traverse, "forbids_excavation": self.forbids_excavation}


class ZoneViolation(Exception):
    """Raised when an action would enter/dig a designated zone -- a HARD stop, not overridable."""


class ZoneRegistry:
    """The set of designated zones. Append-only + immutable entries -> non-overridable by construction."""

    def __init__(self):
        self._zones: list[DesignatedZone] = []

    def designate(self, x, y, radius_m, zone_type, label="", by="operator") -> DesignatedZone:
        if not all(math.isfinite(float(v)) for v in (x, y, radius_m)) or float(radius_m) <= 0.0:
            raise ValueError(f"zone needs finite x/y and radius_m > 0 (got {x},{y},r={radius_m}): a "
                             "non-positive radius silently forbids nothing (audit M05)")
        z = DesignatedZone(float(x), float(y), float(radius_m), ZoneType(zone_type), label, by)
        self._zones.append(z)
        return z

    @property
    def zones(self) -> tuple:
        return tuple(self._zones)            # read-only view; no setter, no remove

    # --- queries -----------------------------------------------------------
    def forbids_traverse(self, x, y) -> bool:
        return any(z.forbids_traverse and z.contains(x, y) for z in self._zones)

    def forbids_excavation(self, x, y, r=0.0) -> bool:
        return any(z.forbids_excavation and z.overlaps(x, y, r) for z in self._zones)

    # --- HARD enforcement gates (raise; cannot be overridden; fail CLOSED) --
    @staticmethod
    def _require_finite(*vals) -> None:
        """A NaN/Inf position must REFUSE, not silently pass: hypot(NaN) compares False against every
        radius, which would fail the gate OPEN (audit 2026-06-09)."""
        if not all(math.isfinite(float(v)) for v in vals):
            raise ZoneViolation(f"non-finite position {vals} -- refusing (zone gates fail closed)")

    def check_traverse(self, x, y) -> None:
        self._require_finite(x, y)
        for z in self._zones:
            if z.forbids_traverse and z.contains(x, y):
                raise ZoneViolation(f"traverse blocked: ({x:.1f},{y:.1f}) is in {z.zone_type.value} "
                                    f"zone {z.label!r}")

    def check_excavation(self, x, y, r=0.0) -> None:
        self._require_finite(x, y, r)
        for z in self._zones:
            if z.forbids_excavation and z.overlaps(x, y, r):
                raise ZoneViolation(f"excavation blocked: ({x:.1f},{y:.1f},r={r:.1f}) touches "
                                    f"{z.zone_type.value} zone {z.label!r}")

    # --- planner interface -------------------------------------------------
    def keepouts_for_planner(self, *, margin_m: float = 0.0) -> list:
        """Hard keep-outs {x,y,r} for route_leg/hazard_map (traverse-forbidding zones)."""
        return [{"x": z.x, "y": z.y, "r": z.radius_m + margin_m}
                for z in self._zones if z.forbids_traverse]

    def as_list(self) -> list:
        return [z.as_dict() for z in self._zones]
