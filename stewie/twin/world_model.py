"""terrain_authority.world_model: the dustgym package's coherent world-model surface.

Ties the five world-model layers (see docs/world_model.md) to their package modules, so one import
gives you the whole model for terrain *transformation*. The physics-side layers (Geometry, Material,
Physics, Task) ship in this package; the perception-side layers (the map-channel scorer and the
per-cell Uncertainty field) live in the app layer (scripts/ros2_bridge, planet_browser) because they
need the Godot render and the planner, and are referenced here rather than imported.

The design call (docs/world_model.md): conserved physics for the DYNAMICS (exact, sub-ms, unhackable;
model-based search beats model-free RL) + a thin learned model only for PERCEPTION. So the package
exposes the conserved model directly; learning is reserved for the observation branch.
"""
from __future__ import annotations

import numpy as np

from stewie.physics import material

from stewie.specs import constants  # noqa: F401  (surface re-exports)

#: layer -> where it lives (package module, or the app layer that uses the package).
LAYERS = {
    "geometry": "column_state (heightmap + slope) + real LOLA DEM ingest (dem_import)",
    "material": "material (per-cell friction/cohesion + cut/slip maps; threaded into drive.drive_step)",
    "physics": "terramechanics (Bekker sinkage) + slip (traction + slip ladder); the conserved transition S(t+1)=f(S,a)",
    "task": "target heightmap + conserved cut/fill (app: planet_browser/mission_planner + structures)",
    "uncertainty": "autonomy Belief (pose/energy/drum sigma) + the map-channel per-cell sigma (app: scripts/ros2_bridge)",
}


def geometry(cs) -> tuple[np.ndarray, np.ndarray]:
    """Geometry layer: (heightmap [m], slope [deg]) for a ColumnState."""
    h = cs.derive_height()
    gy, gx = np.gradient(h, cs.cell_m)
    return h, np.degrees(np.arctan(np.hypot(gx, gy)))


def material_layer(cs) -> dict:
    """Material layer: per-cell strength + trafficability from the ColumnState's conserved density."""
    return material.material_fields(cs.density)


def earthwork(cs, target_height) -> dict:
    """Task layer: the cut/fill volume to reach a target surface (positive = cut, negative = fill) [m^3]."""
    h = cs.derive_height()
    diff = h - np.asarray(target_height, dtype=float)
    area = cs.cell_m ** 2
    return {"cut_m3": float(np.clip(diff, 0.0, None).sum() * area),
            "fill_m3": float(np.clip(-diff, 0.0, None).sum() * area)}


def describe() -> dict:
    """The five-layer map (layer -> package/app module). The world model at a glance."""
    return dict(LAYERS)


# ==============================================================================
# MERGE-1: event-sourced layered twin (L0 orbital base + L4 events -> derived terrain)
# (absorbed from stewie/twin/world_model_events.py in M3; original docstring follows)
# 
# PROVENANCE: SolNav dissertation (A. Storey) -- moved from solnav/world/world_model.py, 2026-06-09 (M2)

import math
from dataclasses import dataclass



@dataclass(frozen=True)
class ExcavationEvent:
    """One terrain-change event (L4). dheight_m: +fill / -cut at the cell; applied over a disc of radius_m."""
    id: int
    x: float
    y: float
    radius_m: float
    dheight_m: float
    t_s: float
    robot_id: str
    kind: str = "cut"            # cut | fill | compact

    @property
    def volume_m3(self) -> float:
        return math.pi * self.radius_m ** 2 * abs(self.dheight_m)


@dataclass
class ProtectedZone:
    """A no-excavate keep-out (e.g., the charger area) -- terrain here must stay stable + repeatable."""
    x: float
    y: float
    radius_m: float
    label: str = "charger"


class WorldModel:
    """L0 orbital base + L4 event log -> derived current terrain (L2/L3). L5 task log + protected zones."""

    def __init__(self, orbital_dem, dem_origin=(0.0, 0.0)):
        self.Z0 = np.asarray(orbital_dem[0], dtype=float)   # L0 immutable
        self.cell = float(orbital_dem[1])
        self.origin = (float(dem_origin[0]), float(dem_origin[1]))
        self.events: list[ExcavationEvent] = []             # L4
        self.tasks: list[dict] = []                         # L5
        self.protected: list[ProtectedZone] = []
        self._next_id = 0

    # --- frame -------------------------------------------------------------
    def world_to_rc(self, x, y):
        return (int(round((y - self.origin[1]) / self.cell)),
                int(round((x - self.origin[0]) / self.cell)))

    # --- L4 events ---------------------------------------------------------
    def add_event(self, x, y, radius_m, dheight_m, *, t_s=0.0, robot_id="ipex", kind="cut") -> ExcavationEvent:
        e = ExcavationEvent(self._next_id, float(x), float(y), float(radius_m), float(dheight_m),
                            float(t_s), robot_id, kind)
        self._next_id += 1
        self.events.append(e)
        return e

    def excavated_near(self, x, y, radius_m) -> list:
        """Events whose disc overlaps a query disc -- e.g. 'has the terrain near the charger changed?'."""
        return [e for e in self.events
                if math.hypot(e.x - x, e.y - y) <= radius_m + e.radius_m]

    # --- L3 / L2 derived terrain ------------------------------------------
    def delta_field(self) -> np.ndarray:
        """L3: per-cell height change accumulated from all L4 events (a derived view, not stored truth)."""
        d = np.zeros_like(self.Z0)
        h, w = d.shape
        rr = np.arange(h)[:, None]
        cc = np.arange(w)[None, :]
        for e in self.events:
            r0, c0 = self.world_to_rc(e.x, e.y)
            # exact radius in cells -- the old max(1, ...) floor painted a sub-cell event over a 5-cell
            # plus-shape, so reconcile_observation never converged (each pass re-painted neighbours and
            # spawned compensating events; audit 2026-06-09). radius < ~0.7 cell -> the centre cell only.
            rad_c = e.radius_m / self.cell
            mask = (rr - r0) ** 2 + (cc - c0) ** 2 <= max(rad_c, 0.5) ** 2
            d[mask] += e.dheight_m
        return d

    def current_terrain(self):
        """L2 = L0 (+) reduce(L4). The terrain the rover currently sees, DERIVED -- never stored."""
        return self.Z0 + self.delta_field(), self.cell

    def delta_at(self, x, y) -> float:
        r, c = self.world_to_rc(x, y)
        if 0 <= r < self.Z0.shape[0] and 0 <= c < self.Z0.shape[1]:
            return float(self.delta_field()[r, c])
        return 0.0

    def reconcile_observation(self, observed_dem, *, t_s=0.0, robot_id="ipex", min_dheight_m=0.05):
        """L2 observation -> L4 events: where the observed terrain differs from the current derived terrain
        by > min_dheight_m, log a change event (the rover INFERS what changed). Returns the new events."""
        cur, _ = self.current_terrain()
        obs = np.asarray(observed_dem, dtype=float)
        resid = obs - cur
        new = []
        sig = np.abs(resid) >= min_dheight_m
        if sig.any():
            rs, cs = np.where(sig)
            # one event per significant cell, with an AREA-EQUIVALENT radius (pi*r^2 = cell^2 ->
            # r = cell/sqrt(pi) ~ 0.56 cell) so delta_field paints exactly that one cell and the volume
            # is cell^2*|dh| -- making reconcile IDEMPOTENT (a second pass logs nothing; audit 2026-06-09)
            r_event = self.cell / math.sqrt(math.pi)
            for r, c in zip(rs[::1], cs[::1]):
                x = c * self.cell + self.origin[0]
                y = r * self.cell + self.origin[1]
                dh = float(resid[r, c])
                new.append(self.add_event(x, y, r_event, dh, t_s=t_s, robot_id=robot_id,
                                          kind="fill" if dh > 0 else "cut"))
        return new

    # --- protected zones (charger keep-out) --------------------------------
    def protect(self, x, y, radius_m, label="charger") -> ProtectedZone:
        z = ProtectedZone(float(x), float(y), float(radius_m), label)
        self.protected.append(z)
        return z

    def is_protected(self, x, y) -> bool:
        return any(math.hypot(z.x - x, z.y - y) <= z.radius_m for z in self.protected)

    def violates_protection(self, event_x, event_y, event_radius_m) -> bool:
        """True if an excavation at (x,y,r) would touch a protected zone (e.g. dig near the charger)."""
        return any(math.hypot(z.x - event_x, z.y - event_y) <= z.radius_m + event_radius_m
                   for z in self.protected)

    def log_task(self, **kw):
        self.tasks.append(kw)

