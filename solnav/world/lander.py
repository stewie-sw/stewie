"""Lander geometry + TO-SCALE map icon.

The rover returns to / docks with a delivery lander (the charging base). On the navigation map the lander
must be placed at its ACTUAL location and drawn TO SCALE -- not a fixed-pixel glyph -- so its footprint,
keep-out, and dock approach are spatially correct relative to the terrain.

Reference dimensions (real, CLPS-class). Default = Intuitive Machines Nova-C: hexagonal body 1.57 m wide
and ~4.0 m tall on 6 landing legs (the body width + height are documented; the leg-span / ground footprint
is an APPROXIMATE ~4.6 m -- the tall, comparatively narrow stance). A larger Griffin-class cargo lander is
provided for an IPEx-scale delivery scenario; its footprint is approximate pending a documented figure.
Sources: en.wikipedia.org/wiki/Intuitive_Machines_Nova-C; intuitivemachines.com/nova-c.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanderSpec:
    name: str
    body_width_m: float          # documented body width (hexagonal flat-to-flat)
    height_m: float              # documented height
    footprint_diameter_m: float  # landing-gear span = the ground footprint (approximate)
    n_legs: int
    footprint_is_estimate: bool = True


# Documented body + height; footprint (leg span) approximate.
NOVA_C = LanderSpec("Nova-C", body_width_m=1.57, height_m=4.0, footprint_diameter_m=4.6, n_legs=6)
GRIFFIN = LanderSpec("Griffin-class", body_width_m=2.5, height_m=3.8, footprint_diameter_m=5.5, n_legs=4)

LANDERS = {s.name: s for s in (NOVA_C, GRIFFIN)}


def icon_radius_px(spec: LanderSpec, meters_per_pixel: float) -> float:
    """Half the footprint in PIXELS at the map's current scale -> a to-scale icon (grows when you zoom)."""
    return 0.5 * spec.footprint_diameter_m / meters_per_pixel


def footprint_cells(spec: LanderSpec, cell_m: float) -> float:
    """Footprint diameter in DEM cells (e.g. ~0.9 cell on a 5 m/px Haworth tile, ~9 cells on a 0.5 m map)."""
    return spec.footprint_diameter_m / cell_m


def keepout_radius_m(spec: LanderSpec, margin_m: float = 2.0) -> float:
    """No-go / no-excavate radius around the lander = footprint radius + safety margin. Feed to a
    PROTECTED zone so the rover neither drives under nor digs beside the lander."""
    return 0.5 * spec.footprint_diameter_m + margin_m


def place_on_map(spec: LanderSpec, x: float, y: float, *, meters_per_pixel: float) -> dict:
    """To-scale map-icon descriptor for the renderer: world position + footprint in pixels + a hexagon/leg
    glyph spec. The renderer draws an n-leg hexagon of radius_px so the lander appears at true size."""
    return {
        "name": spec.name,
        "x": x, "y": y,
        "radius_px": icon_radius_px(spec, meters_per_pixel),
        "footprint_diameter_m": spec.footprint_diameter_m,
        "footprint_is_estimate": spec.footprint_is_estimate,
        "body_width_m": spec.body_width_m,
        "height_m": spec.height_m,
        "n_legs": spec.n_legs,
        "keepout_radius_m": keepout_radius_m(spec),
        "glyph": "hexagon-legs",
    }
