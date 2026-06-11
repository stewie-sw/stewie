"""Excavation-aware shadow prediction.

Predicted shadows = f(L0 orbital DEM + L4 excavation events + Sun), NOT f(static DEM + Sun). When the
rover builds a berm or digs a trench, the NEW terrain casts NEW predicted shadows -- so a changed shadow
is recognized as TERRAIN CHANGE, not a localization error. This resolves the shadow-vs-localization
ambiguity that breaks naive shadow cues at the poles. Cast-shadow ray-march over the (possibly excavated)
terrain from the WorldModel's derived current_terrain. Real DEM only.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import math

import numpy as np


def cast_shadow_mask(terrain, sun_az_deg: float, sun_el_deg: float, *, max_range_m: float = 500.0):
    """Boolean cast-shadow mask: a cell is shadowed if, marching toward the Sun (azimuth az), any terrain
    rises above the Sun-elevation ray from that cell. sun_el<=0 -> everything is shadowed (sun down)."""
    z = np.asarray(terrain[0], dtype=float)
    cell = float(terrain[1])
    h, w = z.shape
    if sun_el_deg <= 0:
        return np.ones((h, w), dtype=bool)
    az = math.radians(sun_az_deg)
    dx, dy = math.cos(az), math.sin(az)
    tan_el = math.tan(math.radians(sun_el_deg))
    n = max(1, int(max_range_m / cell))
    shadow = np.zeros((h, w), dtype=bool)
    for r in range(h):
        for c in range(w):
            z0 = z[r, c]
            for k in range(1, n + 1):
                ci = int(round(c + dx * k))
                ri = int(round(r + dy * k))
                if not (0 <= ri < h and 0 <= ci < w):
                    break
                if z[ri, ci] > z0 + (k * cell) * tan_el:
                    shadow[r, c] = True
                    break
    return shadow


def predict_shadows_world(world_model, sun_az_deg: float, sun_el_deg: float, **kw):
    """Cast shadows over the DERIVED current terrain (L0 + L4 events) -- excavation-aware."""
    cur, cell = world_model.current_terrain()
    return cast_shadow_mask((cur, cell), sun_az_deg, sun_el_deg, **kw)


def excavation_shadow_delta(world_model, sun_az_deg: float, sun_el_deg: float, **kw):
    """Shadows that APPEARED/DISAPPEARED purely because of excavation: compare the cast-shadow mask over
    L0 alone vs over L0+L4. Returns (newly_shadowed, newly_lit) boolean masks. A newly-shadowed region is
    a recognized terrain change (e.g. a fresh berm), NOT a localization error."""
    base = cast_shadow_mask((world_model.Z0, world_model.cell), sun_az_deg, sun_el_deg, **kw)
    cur = predict_shadows_world(world_model, sun_az_deg, sun_el_deg, **kw)
    return (cur & ~base), (base & ~cur)
