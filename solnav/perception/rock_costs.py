"""Unified planner cost from the classified-rock world model.

Each Rock contributes a NAVIGATION cost by its operational nav class -- A/B are traversable (enter the
regolith model, ~free), C is a soft penalty (prefer to route around), D/E are hard keep-outs the route
must bend around. This is the rock term of the planner's cost (terrain/slope cost already lives in the
dustgym route_leg; energy in the planner). Localization value (loc class) is a routing BONUS, not a cost:
a persistent landmark (L2) kept in view lowers localization uncertainty.

The keep-outs this emits feed mission_planner.route_leg directly, so a boulder the playthrough classifies
as D/E automatically becomes an obstacle the route avoids -- closing detect -> size -> classify -> AVOID.
"""
from __future__ import annotations

import math

# relative per-cell traverse penalty by nav class (E = impassable -> keep-out)
NAV_COST = {"A": 0.0, "B": 0.2, "C": 1.0, "D": 5.0, "E": math.inf}
HARD_CLASSES = ("D", "E")                       # become hard keep-outs
# localization value (negative cost / bonus) by loc class -- a persistent landmark is worth keeping in view
LOC_VALUE = {"L0": 0.0, "L1": 0.5, "L2": 1.5}


def nav_cost(nav_class: str) -> float:
    """Per-cell navigation penalty for traversing near a rock of this class."""
    return NAV_COST.get(nav_class, 1.0)


def localization_value(loc_class: str) -> float:
    """Routing bonus for keeping a landmark of this class in view (lowers localization uncertainty)."""
    return LOC_VALUE.get(loc_class, 0.0)


def rock_keepouts(rocks_world, *, hard_classes=HARD_CLASSES, margin_m: float = 0.3) -> list:
    """Keep-outs {x, y, r} for the hazard-class rocks -> route_leg routes around them. ``rocks_world`` is
    an iterable of (x_m, y_m, Rock); only D/E (no-go) become keep-outs (A/B/C stay traversable/soft)."""
    out = []
    for x, y, rk in rocks_world:
        if rk.nav_class in hard_classes:
            out.append({"x": float(x), "y": float(y), "r": float(rk.diameter_m / 2.0 + margin_m)})
    return out


def traverse_cost(rocks_world, x: float, y: float, *, radius_m: float = 1.0) -> float:
    """Soft rock cost a planner adds for a cell at (x, y): sum of nav penalties of nearby non-hard rocks
    (A/B/C). D/E are handled as keep-outs, not soft cost, so they're excluded here."""
    total = 0.0
    for rx, ry, rk in rocks_world:
        if rk.nav_class in HARD_CLASSES:
            continue
        if (rx - x) ** 2 + (ry - y) ** 2 <= radius_m ** 2:
            total += nav_cost(rk.nav_class)
    return total
