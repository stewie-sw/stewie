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

import math
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
    # F1 (viz2 plan v4 Phase F): the spatial-k Golombek clast list (stewie.terrain.rockfield) as the
    # rock_hazard layer's INPUT -- each clast {center_m:[x, h, z], radius_m, buried_frac} in the SAME
    # DEM-window metric frame as ``Z`` (x = col*cell_m, z = row*cell_m). None/empty -> the layer is a
    # no-op zero field, so a compose without a rock field is byte-identical to the pre-F costmap.
    rock_clasts: "list | None" = None
    obstacle_height_m: float = ipex_specs.OBSTACLE_HEIGHT_M   # [SCHULER24] traversable-rock limit (0.075 m)


def _slope(ctx, slope=None):
    # P1: reuse compose's single shared slope pass when given; recompute (byte-identical, slope_deg_map
    # is deterministic) only when the layer is invoked standalone (slope=None).
    s = slope_deg_map(ctx.Z, ctx.cell_m) if slope is None else slope
    cost = ctx.slip_alpha * np.tan(np.radians(np.minimum(s, 89.0)))
    return cost, (s > ctx.max_slope_deg), "slope"


def _roughness(ctx, slope=None):
    # per-cell roughness = local std of the slope field over a 3x3 window (the dem_stats RMS-slope idea,
    # localized): rough terrain costs more even below the slope cap.
    s = slope_deg_map(ctx.Z, ctx.cell_m) if slope is None else slope
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
    k_phi = K.K_PHI if ctx.sinkage_k_phi is None else float(ctx.sinkage_k_phi)   # [REQ:PX-06] constants direct, not via terramechanics
    z = terramechanics.wheel_static_sinkage(load, k_phi=k_phi)
    grid = np.full(ctx.Z.shape, z, float)
    cost = grid / max(ctx.max_sinkage_m, 1e-6)
    impass = grid > ctx.max_sinkage_m
    return cost, impass, "sinkage"


def _slip(ctx, slope=None):
    s = slope_deg_map(ctx.Z, ctx.cell_m) if slope is None else slope
    return np.tan(np.radians(np.minimum(s, 89.0))), np.zeros_like(s, bool), "slip"


def _tip_risk(ctx, slope=None):
    s = slope_deg_map(ctx.Z, ctx.cell_m) if slope is None else slope
    limit = stability.tip_tilt_limit_deg(gauge_m=ctx.gauge_m, wheelbase_m=ctx.wheelbase_m,
                                         cg_height_m=ctx.cg_height_m)
    return np.zeros_like(s), (s > limit), "tip_risk"


def _negative_obstacle(ctx):
    m = negative_obstacle_mask(ctx.Z, max_drop_m=ctx.max_drop_m)
    return np.zeros(ctx.Z.shape), m, "negative_obstacle"


def rock_exposed_height_grid(shape, cell_m, clasts) -> np.ndarray:
    """F1: rasterize a spatial-k Golombek clast list to a per-cell MAX EXPOSED ROCK HEIGHT grid [m].

    A partially-buried clast of radius ``r`` and burial fraction ``buried_frac`` protrudes
    ``h = 2*r*(1 - buried_frac)`` above the surface (its full diameter 2r, less the buried part). Each
    clast is stamped over its DISK footprint -- every cell whose centre lies within ``r`` of the clast
    centre -- taking the per-cell MAX so overlapping clasts keep the tallest obstacle. A sub-cell clast
    (radius < cell) whose disk clears every neighbouring cell centre still occupies the cell it sits in,
    so it is stamped there. ``clasts`` carry ``center_m = [x, height, z]`` in the DEM-window metric frame
    (x = col*cell_m, z = row*cell_m -- the same frame ``Z`` and the viz2 scene use); ``None``/empty -> an
    all-zero grid. Pure geometry, no thresholding (the traversability cut is the layer's job)."""
    H, W = shape
    grid = np.zeros((H, W), float)
    if not clasts:
        return grid
    for c in clasts:
        r_m = float(c["radius_m"])
        bf = float(c.get("buried_frac", 0.0))
        h = 2.0 * r_m * (1.0 - bf)                 # exposed height above the surface
        if h <= 0.0:
            continue
        x, _y, z = (float(v) for v in c["center_m"])
        cc = x / cell_m                            # fractional cell col of the clast centre
        cr = z / cell_m                            # fractional cell row of the clast centre
        rad_cells = r_m / cell_m
        c_lo, c_hi = max(0, int(math.floor(cc - rad_cells))), min(W - 1, int(math.ceil(cc + rad_cells)))
        r_lo, r_hi = max(0, int(math.floor(cr - rad_cells))), min(H - 1, int(math.ceil(cr + rad_cells)))
        covered = False
        rad2 = rad_cells * rad_cells
        for rr in range(r_lo, r_hi + 1):
            for col in range(c_lo, c_hi + 1):
                if (rr - cr) ** 2 + (col - cc) ** 2 <= rad2:
                    grid[rr, col] = max(grid[rr, col], h)
                    covered = True
        if not covered:                            # sub-cell clast -> stamp the cell it sits in
            ri = min(max(int(round(cr)), 0), H - 1)
            ci = min(max(int(round(cc)), 0), W - 1)
            grid[ri, ci] = max(grid[ri, ci], h)
    return grid


def _rock_hazard(ctx):
    """F1: the ROCK obstacle-height hazard layer. Rock HEIGHT/SIZE (not just DEM drop-offs) drives cost and
    rejection: the per-cell exposed rock height ``h`` (rock_exposed_height_grid over ctx.rock_clasts) costs
    ``h / obstacle_height_m`` (a rock the rover can climb still costs to cross -- higher rock, higher cost)
    and is IMPASSABLE where ``h`` exceeds the IPEx traversable-rock limit ``obstacle_height_m`` (0.075 m,
    "traversing rock obstacles up to 7.5 cm in height" [SCHULER24]). This is the F1 gap-fix: before F, rocks
    entered the costmap ONLY as DEM drop-offs (negative_obstacle); their height/size was never an input.
    No clasts -> a zero cost / no-block layer (byte-identical to the pre-F costmap)."""
    lim = float(ctx.obstacle_height_m)
    grid = rock_exposed_height_grid(ctx.Z.shape, ctx.cell_m, ctx.rock_clasts)
    cost = grid / max(lim, 1e-6)
    impass = grid > lim
    return cost, impass, "rock_hazard"


def _illumination(ctx):
    inc = illum.incidence_angle_deg(ctx.Z, ctx.cell_m, sun_az_deg=ctx.sun_az_deg,
                                    sun_el_deg=ctx.sun_el_deg)
    # grazing incidence (-> 90 deg) is risky imaging / weak charge: cost rises toward grazing
    cost = np.clip(inc, 0.0, 90.0) / 90.0
    return cost, np.zeros(ctx.Z.shape, bool), "illumination"


def _psr(ctx, lit=None):
    # local-horizon illuminated mask (True = sees the sun); psr_gate returns the shadowed cold-trap
    # candidates (True = permanently/this-epoch shadowed) -> impassable. On a flat plane at high sun
    # everything is lit -> no PSR block.
    # P3: reuse compose's single shared horizon sweep when given (byte-identical, horizon_clip is
    # deterministic); recompute only when invoked standalone (lit=None).
    if lit is None:
        lit = illum.horizon_clip(ctx.Z, ctx.cell_m, sun_az_deg=ctx.sun_az_deg, sun_el_deg=ctx.sun_el_deg)
    impass = np.asarray(illum.psr_gate(lit), bool)
    return np.zeros(ctx.Z.shape), impass, "psr"


def _shadow_confidence(ctx, lit=None):
    # Perception reliability, NOT a hard block: a cell in local-horizon cast shadow is still drivable
    # but is low-confidence to map/localize in (weak texture, no direct light). psr owns the cold-trap
    # BLOCK; this layer adds a traversal cost to shadowed-but-passable ground so a route prefers lit
    # terrain when it can. lit = sees the sun (horizon_clip); shadowed cells pay a flat confidence cost.
    # P3: reuse compose's single shared horizon sweep when given; recompute only standalone (lit=None).
    if lit is None:
        lit = illum.horizon_clip(ctx.Z, ctx.cell_m, sun_az_deg=ctx.sun_az_deg, sun_el_deg=ctx.sun_el_deg)
    cost = np.where(np.asarray(lit, bool), 0.0, 1.0)
    return cost, np.zeros(ctx.Z.shape, bool), "shadow_confidence"


def _energy(ctx, slope=None):
    s = slope_deg_map(ctx.Z, ctx.cell_m) if slope is None else slope
    # per-cell grade-dependent lunar drive power (sourced ipex_specs), normalized to a cost multiplier
    base = ipex_specs.lunar_drive_power_w(slope_deg=0.0)
    # P2: lunar_drive_power_w is a BRANCH-FREE closed form (ipex_specs.py:186-196), so the per-cell scalar
    # loop vectorizes EXACTLY. Reproduce it on the clamped slope array with the SAME module defaults the
    # scalar call uses (mass/g/crr/v/efficiency), in the SAME operation order -- byte-identical, one op.
    th = np.radians(np.minimum(np.abs(s), 30.0))
    f_tractive = (ipex_specs.ROVER_MASS_CLASS_KG * ipex_specs.LUNAR_G_MS2
                  * (ipex_specs.ROLLING_RESISTANCE_COEFF * np.cos(th) + np.sin(th)))
    grade = f_tractive * ipex_specs.DRIVE_SPEED_MS / ipex_specs.DRIVETRAIN_EFFICIENCY
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

# F1: rock_hazard is a DATA-DRIVEN overlay, NOT one of the 12 always-on DEM-derived layers -- it is
# active only when a rock field (ctx.rock_clasts) is supplied, so it is NOT in the static LAYERS /
# LAYER_NAMES the manifest catalog and compose_from_manifest enumerate. compose AUTO-INCLUDES it when
# ctx.rock_clasts is present (below), so a plain compose(ctx) over a rock field names "rock_hazard"
# like the 12; a compose without rocks stays byte-identical to the pre-F costmap.

# P1/P3: the layers that consume, respectively, a full-grid slope map or the local-horizon `lit` mask.
# compose computes each shared quantity ONCE and hands it to its consumers, so one compose does a single
# slope pass (not five) and a single horizon sweep (not two). Byte-identical: slope_deg_map / horizon_clip
# are deterministic, so a shared array equals a per-layer recompute exactly.
_SLOPE_LAYERS = frozenset({_slope, _roughness, _slip, _tip_risk, _energy})
_LIT_LAYERS = frozenset({_psr, _shadow_confidence})


@dataclass
class CompositeCostmap:
    cost: np.ndarray
    passable: np.ndarray
    reason: np.ndarray          # object grid: the blocking layer name per impassable cell, else ""
    per_layer_cost: dict = field(default_factory=dict)
    per_layer_block: dict = field(default_factory=dict)


def compose(ctx: CostmapContext, layers=LAYERS) -> CompositeCostmap:
    """Sum the per-layer costs, OR the impassable masks, and record the first blocking layer per cell.

    F1: when ``ctx.rock_clasts`` is supplied, the data-driven ``rock_hazard`` layer is auto-appended
    (rock HEIGHT drives cost + rejection). With no rock field it is NOT run, so the compose is
    byte-identical to the pre-F 12-layer costmap and the DEM-derived LAYER_NAMES / manifest are unchanged."""
    if ctx.rock_clasts and _rock_hazard not in layers:
        layers = tuple(layers) + (_rock_hazard,)
    H, W = ctx.Z.shape
    total = np.ones((H, W), float)            # base per-metre cost
    passable = np.ones((H, W), bool)
    reason = np.full((H, W), "", dtype=object)
    per_cost, per_block = {}, {}
    # P1/P3: compute the shared slope map + local-horizon lit mask ONCE for the whole compose (only when a
    # layer in play actually needs each), then hand them to their consumers instead of recomputing per layer.
    slope = (slope_deg_map(ctx.Z, ctx.cell_m)
             if any(fn in _SLOPE_LAYERS for fn in layers) else None)
    lit = (illum.horizon_clip(ctx.Z, ctx.cell_m, sun_az_deg=ctx.sun_az_deg, sun_el_deg=ctx.sun_el_deg)
           if any(fn in _LIT_LAYERS for fn in layers) else None)
    for fn in layers:
        if fn in _SLOPE_LAYERS:
            cost_delta, impass, name = fn(ctx, slope)
        elif fn in _LIT_LAYERS:
            cost_delta, impass, name = fn(ctx, lit)
        else:
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


def rock_keepouts(clasts, *, obstacle_height_m: "float | None" = None):
    """F2 bridge: the IMPASSABLE rock clasts -> keep-out circles the mission planner routes around.

    The rock_hazard layer is impassable where the exposed rock height ``h = 2*r*(1 - buried_frac)``
    exceeds ``obstacle_height_m`` (the IPEx traversable-rock limit, 0.075 m [SCHULER24]). Those clasts are
    discrete obstacles a rover must drive around, so each becomes a ``{x, y, r}`` keep-out circle in the
    planner's LOCAL order frame -- the SAME representation ``lode.planner_routing._apply_keepouts`` already
    rasterizes to impassable cells, so ``mission_planner.plan(..., keepouts=...)`` bends the routed haul
    around a rock cluster with no new routing code. The clast's horizontal centre is ``center_m[0]`` (x)
    and ``center_m[2]`` (z); the keep-out radius is the clast radius (its ground footprint). Sub-limit
    rocks (``h <= obstacle_height_m``) are NOT keep-outs -- they cost-but-pass in the rock_hazard cost."""
    lim = ipex_specs.OBSTACLE_HEIGHT_M if obstacle_height_m is None else float(obstacle_height_m)
    kos = []
    for c in (clasts or []):
        r_m = float(c["radius_m"])
        bf = float(c.get("buried_frac", 0.0))
        h = 2.0 * r_m * (1.0 - bf)
        if h > lim:
            x, _y, z = (float(v) for v in c["center_m"])
            kos.append({"x": x, "y": z, "r": r_m})
    return kos
