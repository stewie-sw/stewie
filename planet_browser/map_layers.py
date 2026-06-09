"""Map layer registry for the navigation / mapping UI -- select, load, and unload overlays.

Layers (selectable, independently loaded/unloaded):
  imagery     base orbital imagery (Cesium Trek tiles)
  dem         work-area DEM hillshade
  topology    slope / contour shading derived from the DEM
  hazard      slope-gate + keep-out + negative-obstacle hazard overlay
  excavation  placed cut/fill structures + excavation history (artifacts)
  lander      the delivery lander, drawn TO SCALE at its actual location

Raster layers derive from the work-area DEM; vector layers are feature lists the browser draws on the
plan canvas. The lander footprint is Nova-C class (documented body 1.57 m x 4.0 m on 6 legs; the ground
footprint / leg span is an approximate ~4.6 m) and is scaled to the map GSD so it appears at true size.
"""
from __future__ import annotations

import math

# Nova-C class delivery lander. Body width + height are documented; the leg-span footprint is approximate.
LANDER_BODY_W_M = 1.57
LANDER_HEIGHT_M = 4.0
LANDER_FOOTPRINT_M = 4.6
LANDER_LEGS = 6
LANDER_KEEPOUT_MARGIN_M = 2.0

LAYERS = [
    {"id": "imagery", "name": "Imagery", "kind": "raster", "group": "base", "default": True},
    {"id": "dem", "name": "DEM (hillshade)", "kind": "raster", "group": "terrain", "default": True},
    {"id": "topology", "name": "Topology (slope)", "kind": "raster", "group": "terrain", "default": False},
    {"id": "hazard", "name": "Hazard / keep-outs", "kind": "vector", "group": "nav", "default": True},
    {"id": "excavation", "name": "Excavation history", "kind": "vector", "group": "ops", "default": True},
    {"id": "lander", "name": "Lander", "kind": "vector", "group": "ops", "default": True},
]
LAYER_IDS = {d["id"] for d in LAYERS}


def layer_defs() -> list:
    """The selectable layers for the UI panel (id, name, kind, group, default load state)."""
    return [dict(d) for d in LAYERS]


def lander_marker(x: float, y: float, *, meters_per_pixel: float, name: str = "Nova-C",
                  footprint_m: float = LANDER_FOOTPRINT_M) -> dict:
    """To-scale lander icon descriptor: world position + footprint in PIXELS at the current map scale +
    a keep-out radius (feed it to a no-excavation zone so the rover neither drives under nor digs beside
    the lander). radius_px grows when you zoom in -> the icon stays true-size, not a fixed glyph."""
    return {
        "id": "lander", "name": name, "x": float(x), "y": float(y),
        "radius_px": 0.5 * footprint_m / meters_per_pixel,
        "footprint_m": footprint_m, "body_width_m": LANDER_BODY_W_M, "height_m": LANDER_HEIGHT_M,
        "keepout_radius_m": 0.5 * footprint_m + LANDER_KEEPOUT_MARGIN_M,
        "n_legs": LANDER_LEGS, "glyph": "hexagon-legs", "footprint_is_estimate": True,
    }


def excavation_features(ops) -> list:
    """Excavation-history overlay from placed cut/fill ops (structures.decompose / the build queue):
    [{action,kind,x,y,footprint_m2,depth_m,note}] -> drawable discs {kind,x,y,radius_m,depth_m,note}."""
    feats = []
    for o in ops:
        area = max(float(o.get("footprint_m2", 1.0)), 0.0)
        feats.append({
            "kind": o.get("kind", "cut"), "x": float(o["x"]), "y": float(o["y"]),
            "radius_m": math.sqrt(area / math.pi), "depth_m": float(o.get("depth_m", 0.0)),
            "note": o.get("note", ""),
        })
    return feats


def zone_features(zones) -> list:
    """Designated keep-out / hazard / no-excavation zones -> drawable overlay {x,y,radius_m,zone_type,label}."""
    out = []
    for z in zones:
        out.append({
            "x": float(z["x"]), "y": float(z["y"]),
            "radius_m": float(z.get("radius_m", z.get("r", 0.0))),
            "zone_type": z.get("zone_type", "no_go"), "label": z.get("label", ""),
        })
    return out
