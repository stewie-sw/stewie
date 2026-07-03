"""[REQ:AS-11] Lunar costmap layers with a VISIBLE blocking reason (§25 Phase 9).

Composes the per-cell navigation cost from named layers, each of which either adds a traversal COST
or marks cells IMPASSABLE, and -- the AS-11 acceptance -- records WHICH layer blocked each cell so a
route that bends or refuses can name the reason. Every layer is wired to a real source:

  slope          slope_deg_map               cost ~ slip-weighted tan(slope); impassable above cap
  roughness      local RMS-slope window      cost ~ terrain roughness (dem_stats family)
  sinkage        terramechanics.wheel_...    cost ~ Bekker static wheel sinkage; impassable when burial
                                             exceeds a depth cap (distinct from slip: soft ground)
  slip           tan(slope)                  cost ~ wheel slip
  tip_risk       stability.tip_tilt_limit    impassable where the tilt exceeds the rover tip limit
  negative_obs   negative_obstacle_mask      impassable at drop-offs / crater rims (don't fall in)
  illumination   illumination.incidence      cost ~ grazing-incidence imaging/charge risk
  psr            illumination.psr_gate        impassable in permanent shadow (no solar, cold trap)
  shadow_conf    illumination.horizon_clip    cost ~ perception UNreliability in local-horizon shadow
                                             (a shadowed cell is drivable but low-confidence to map)
  energy         ipex_specs grade power       cost ~ grade-dependent drive energy
  keepout        operator keep-out mask       impassable (operator no-go)
  reservation    fleet reservation mask       impassable (another vehicle holds the cell)

The 12 PRD-named AS-11 layers map to these with three named synonyms: "dynamic rocks" IS
negative_obstacle (the drop-off / rock-rim hazard), sinkage is its own Bekker layer here (NOT folded
into slip), and shadow_confidence is its own perception-reliability layer (NOT folded into
illumination/psr). Nothing is faked: every layer reads a real source.

`compose` returns the summed cost, the passable mask, and a reason grid (the first blocking layer per
cell). NOT synthetic: costs derive from a real DEM + the sourced models.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from dart import illumination as illum
from lode.planner_routing import negative_obstacle_mask, slope_deg_map
from stewie.physics import stability, terramechanics
from stewie.specs import constants as K
from stewie.specs import ipex_specs


@dataclass
class CostmapContext:
    Z: np.ndarray
    cell_m: float = 0.02
    max_slope_deg: float = 25.0
    slip_alpha: float = 2.0
    max_drop_m: float = 0.15
    sun_az_deg: float = 200.0
    sun_el_deg: float = 12.0
    gauge_m: float = 0.3645
    wheelbase_m: float = 0.30
    cg_height_m: float = 0.21
    payload_kg: float = 0.0                 # drum payload -> per-wheel normal load for the sinkage layer
    max_sinkage_m: float = 0.10             # burial cap: sinkage past this is impassable (~2/3 wheel r)
    sinkage_k_phi: "float | None" = None    # Bekker frictional modulus override (softer soil = smaller)
    keepout_mask: "np.ndarray | None" = None
    reserved_mask: "np.ndarray | None" = None


def _slope(ctx):
    s = slope_deg_map(ctx.Z, ctx.cell_m)
    cost = ctx.slip_alpha * np.tan(np.radians(np.minimum(s, 89.0)))
    return cost, (s > ctx.max_slope_deg), "slope"


def _roughness(ctx):
    # per-cell roughness = local std of the slope field over a 3x3 window (the dem_stats RMS-slope idea,
    # localized): rough terrain costs more even below the slope cap.
    s = slope_deg_map(ctx.Z, ctx.cell_m)
    from scipy.ndimage import uniform_filter
    mean = uniform_filter(s, size=3, mode="nearest")
    var = uniform_filter(s * s, size=3, mode="nearest") - mean * mean
    rough = np.sqrt(np.maximum(var, 0.0))
    return rough / 10.0, np.zeros_like(s, bool), "roughness"


def _sinkage(ctx):
    # Bekker static wheel sinkage under the rover's per-wheel normal load. Denser (compacted) ground
    # bears better and sinks less; loose/soft ground sinks more -> higher motion resistance. Density
    # rises with slope-driven compaction is not modelled per cell, so the layer varies with the soil
    # bearing modulus (sinkage_k_phi) and the wheel load, not with slope. Sinkage past max_sinkage_m is
    # a burial hazard (impassable). Cost = sinkage normalized by the cap (deeper burial costs more).
    load = terramechanics.static_wheel_load_n(ctx.payload_kg, g=K.g)
    k_phi = terramechanics.K.K_PHI if ctx.sinkage_k_phi is None else float(ctx.sinkage_k_phi)
    z = terramechanics.wheel_static_sinkage(load, k_phi=k_phi)
    grid = np.full(ctx.Z.shape, z, float)
    cost = grid / max(ctx.max_sinkage_m, 1e-6)
    impass = grid > ctx.max_sinkage_m
    return cost, impass, "sinkage"


def _slip(ctx):
    s = slope_deg_map(ctx.Z, ctx.cell_m)
    return np.tan(np.radians(np.minimum(s, 89.0))), np.zeros_like(s, bool), "slip"


def _tip_risk(ctx):
    s = slope_deg_map(ctx.Z, ctx.cell_m)
    limit = stability.tip_tilt_limit_deg(gauge_m=ctx.gauge_m, wheelbase_m=ctx.wheelbase_m,
                                         cg_height_m=ctx.cg_height_m)
    return np.zeros_like(s), (s > limit), "tip_risk"


def _negative_obstacle(ctx):
    m = negative_obstacle_mask(ctx.Z, max_drop_m=ctx.max_drop_m)
    return np.zeros(ctx.Z.shape), m, "negative_obstacle"


def _illumination(ctx):
    inc = illum.incidence_angle_deg(ctx.Z, ctx.cell_m, sun_az_deg=ctx.sun_az_deg,
                                    sun_el_deg=ctx.sun_el_deg)
    # grazing incidence (-> 90 deg) is risky imaging / weak charge: cost rises toward grazing
    cost = np.clip(inc, 0.0, 90.0) / 90.0
    return cost, np.zeros(ctx.Z.shape, bool), "illumination"


def _psr(ctx):
    # local-horizon illuminated mask (True = sees the sun); psr_gate returns the shadowed cold-trap
    # candidates (True = permanently/this-epoch shadowed) -> impassable. On a flat plane at high sun
    # everything is lit -> no PSR block.
    lit = illum.horizon_clip(ctx.Z, ctx.cell_m, sun_az_deg=ctx.sun_az_deg, sun_el_deg=ctx.sun_el_deg)
    impass = np.asarray(illum.psr_gate(lit), bool)
    return np.zeros(ctx.Z.shape), impass, "psr"


def _shadow_confidence(ctx):
    # Perception reliability, NOT a hard block: a cell in local-horizon cast shadow is still drivable
    # but is low-confidence to map/localize in (weak texture, no direct light). psr owns the cold-trap
    # BLOCK; this layer adds a traversal cost to shadowed-but-passable ground so a route prefers lit
    # terrain when it can. lit = sees the sun (horizon_clip); shadowed cells pay a flat confidence cost.
    lit = illum.horizon_clip(ctx.Z, ctx.cell_m, sun_az_deg=ctx.sun_az_deg, sun_el_deg=ctx.sun_el_deg)
    cost = np.where(np.asarray(lit, bool), 0.0, 1.0)
    return cost, np.zeros(ctx.Z.shape, bool), "shadow_confidence"


def _energy(ctx):
    s = slope_deg_map(ctx.Z, ctx.cell_m)
    # per-cell grade-dependent lunar drive power (sourced ipex_specs), normalized to a cost multiplier
    base = ipex_specs.lunar_drive_power_w(slope_deg=0.0)
    grade = np.array([[ipex_specs.lunar_drive_power_w(slope_deg=float(min(abs(v), 30.0)))
                       for v in row] for row in s])
    return (grade / base - 1.0), np.zeros_like(s, bool), "energy"


def _keepout(ctx):
    m = (np.asarray(ctx.keepout_mask, bool) if ctx.keepout_mask is not None
         else np.zeros(ctx.Z.shape, bool))
    return np.zeros(ctx.Z.shape), m, "keepout"


def _reservation(ctx):
    m = (np.asarray(ctx.reserved_mask, bool) if ctx.reserved_mask is not None
         else np.zeros(ctx.Z.shape, bool))
    return np.zeros(ctx.Z.shape), m, "reservation"


# ordered: the first impassable layer (in this order) is the visible reason for a blocked cell
LAYERS = (_slope, _roughness, _sinkage, _slip, _tip_risk, _negative_obstacle, _illumination, _psr,
          _shadow_confidence, _energy, _keepout, _reservation)
LAYER_NAMES = tuple(fn(CostmapContext(np.zeros((2, 2))))[2] for fn in LAYERS)


@dataclass
class CompositeCostmap:
    cost: np.ndarray
    passable: np.ndarray
    reason: np.ndarray          # object grid: the blocking layer name per impassable cell, else ""
    per_layer_cost: dict = field(default_factory=dict)
    per_layer_block: dict = field(default_factory=dict)


def compose(ctx: CostmapContext, layers=LAYERS) -> CompositeCostmap:
    """Sum the per-layer costs, OR the impassable masks, and record the first blocking layer per cell."""
    H, W = ctx.Z.shape
    total = np.ones((H, W), float)            # base per-metre cost
    passable = np.ones((H, W), bool)
    reason = np.full((H, W), "", dtype=object)
    per_cost, per_block = {}, {}
    for fn in layers:
        cost_delta, impass, name = fn(ctx)
        total = total + np.asarray(cost_delta, float)
        impass = np.asarray(impass, bool)
        newly = impass & passable                 # cells this layer is the FIRST to block
        reason[newly] = name
        passable = passable & ~impass
        per_cost[name] = float(np.nansum(cost_delta))
        per_block[name] = int(np.count_nonzero(impass))
    return CompositeCostmap(cost=total, passable=passable, reason=reason,
                            per_layer_cost=per_cost, per_layer_block=per_block)


_LAYER_BY_NAME = dict(zip(LAYER_NAMES, LAYERS))


def compose_from_manifest(ctx: CostmapContext, manifest) -> CompositeCostmap:
    """[REQ:FR-10] Build the costmap from the SAME layer manifest the cockpit reads: compose exactly the
    manifest's planning-eligible cost layers (matched by layer id). The planner and the cockpit thus share
    one source of truth for which layers are in play, in what order."""
    fns = tuple(_LAYER_BY_NAME[lid] for lid in manifest.planning_layers() if lid in _LAYER_BY_NAME)
    return compose(ctx, layers=fns)


def blocking_reason(cm: CompositeCostmap, rc) -> str:
    """The visible reason a cell is blocked (empty string if passable)."""
    r, c = int(rc[0]), int(rc[1])
    return str(cm.reason[r, c])
