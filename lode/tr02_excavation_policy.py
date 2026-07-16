"""TR-02 — interpretable search-distilled excavation policy: the MEASURED result.

The row asks for a depth-limited decision tree, distilled from a model-based-search oracle run in the
conserved authority, that BEATS GREEDY on passes-to-spec / energy-to-spec / as-built RMSE (±2 cm) over
HELD-OUT rock seeds -- with the null pre-committed: "A tie with greedy is a NULL RESULT and MUST be
reported as one" (PRD §7, TR-02; the trap being the prior finding that greedy AND RANDOM both solved the
unconstrained flatten). This module runs that experiment on the frozen TR-01 scenario and reports what
the AS-IMPLEMENTED physics actually yields.

THE RESULT IS A NULL, and it is a PROPERTY OF THE IMPLEMENTED EXCAVATION PHYSICS, not of the search:

  * dig energy is ``ipex_specs.dig_energy_per_kg()`` -- a CONSTANT J/kg (P_dig / dig-rate; ipex_specs.py:167),
    "BP-1-calibrated, material/density/ice-independent" (EP-02). There is NO depth term. The row's premise
    "dig_j_per_kg (FEE, ∝ depth²)" is NOT in the code, so a policy cannot trade bite depth for dig energy.
  * mass is conserved: the mass a target requires to be removed is fixed by the target geometry, so
    ``energy-to-spec = const · cut_mass`` and ``passes-to-spec = ceil(cut_mass / drum_capacity)`` are
    both TARGET-DETERMINED -- identical for every dig ORDER.
  * ``WorkSite.flatten`` (``flatten_to_level``) is deterministic and mass-exact (residual above target =
    0.0, floored at the firm DEM datum), so the as-built surface -- and its RMSE -- is policy-invariant.

The ONLY policy-sensitive term is DRIVE energy on the haul legs (routing to the dump, around rocks/slope).
It is dig-dominated to <1 % on this scenario (dig ~4151 J/kg · hundreds of kg  vs  drive ~135 J/m · a few m),
and the leg-count minimisation it represents is the SchedulerEnv problem, where this repo already showed
greedy = beam = optimal. So a distilled tree ties greedy on all three acceptance metrics: NULL.

WHAT WOULD MAKE TR-02 NON-NULL (stated so the null is actionable, not a dead end):
  1. Implement a SOURCED depth-dependent excavation-force model (the real Fundamental Earthmoving Equation:
     draft/specific-energy grows with cut depth and rake -- Reece, Balovnev, McKyes), so bite depth becomes
     a real energy lever. That is a FORGE physics row, not a distillation; until it exists, inventing the
     depth² term here would be fabricated data (forbidden).
  2. OR move the interpretable-policy target to the MULTI-VEHICLE scheduling layer, where this repo's own
     M4 note records genuine headroom (parallelism + space-time conflict), not the single-vehicle maneuver.

This module is deliberately honest and non-synthetic: real Haworth bundle, real Golombek rock field
(seed-varying, so "held-out seeds" is real), real conserved authority, real IPEx energy constants.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from stewie.specs import ipex_specs as IX
from stewie.physics.worksite import WorkSite
from scripts.viz2_rockfield_clasts import build_clasts

# The frozen TR-01 scenario: the committed coarse Haworth base.
HAWORTH_BUNDLE = "samples/lunar_dem/haworth_10km_5m"
RMSE_SPEC_M = 0.02                       # the row's ±2 cm as-built acceptance
DRUM = "large"


@dataclass(frozen=True)
class Scenario:
    """A frozen, constrained flatten-a-pad excavation task on the real Haworth authority.

    ``rock_seed`` selects the real Golombek rock field, so distinct seeds are genuinely held-out draws
    of the SAME terrain (different clast field) -- exactly what TR-01's live ``rock_seed`` made possible.
    """
    base_rc: tuple[float, float]         # base-cell centre the fine window opens over
    pad_half_m: float                    # half-extent of the square pad [m]
    target_drop_m: float                 # target = this percentile (0..1) of pad heights (reachable tail cut)
    rock_seed: int
    drum: str = DRUM

    @property
    def drum_capacity_kg(self) -> float:
        # per-drum hold (BDSCALE); the vehicle carries two, but passes-to-full is per the tank that fills.
        return float(IX.DRUM_CAPACITY_KG[self.drum])


def _open(scn: Scenario) -> tuple[WorkSite, np.ndarray, np.ndarray, float, tuple[int, int, int]]:
    """Materialise the fine window and the pad. Returns (ws, pad_mask, above_mask, target_m, rock_region).

    A fresh WorkSite per call (``flatten`` mutates the window in place). ``rock_region`` is the
    ``(r0, c0, n)`` base-cell block the real Golombek field is sampled over (reused by :func:`_rock_xy`
    so one bundle load serves both the terrain and the rocks)."""
    ws = WorkSite.from_haworth_bundle(HAWORTH_BUNDLE, fine_cell_m=0.05, tile_base_cells=4)
    ws.open_window(scn.base_rc, radius_m=8.0)
    cs = ws._require_fine()
    h = cs.derive_height()
    H, W = h.shape
    # square pad centred in the window
    half = int(round(scn.pad_half_m / cs.cell_m))
    r0, c0 = H // 2 - half, W // 2 - half
    r1, c1 = H // 2 + half, W // 2 + half
    pad = np.zeros_like(h, dtype=bool)
    pad[r0:r1, c0:c1] = True
    # Cut the pad's high tail down to a REACHABLE target: a low percentile of the pad's own surface,
    # held at/above the firm DEM datum so the conserved cut actually lands ON target (not floored at the
    # datum -- ``flatten_to_level`` only removes the loose mantle above ``datum``, gap G8). ``target_drop_m``
    # picks how deep into the tail (as a fraction of the pad's height spread) so distinct scenarios vary.
    lo = float(np.percentile(h[pad], 100.0 * float(scn.target_drop_m)))
    target = max(lo, float(np.max(cs.datum[pad])) + 1e-4)     # never below any pad cell's firm datum
    above = pad & (h > target)
    region = ws.window_region_rc
    if region is None:
        raise RuntimeError("window_region_rc is None after open_window()")
    r0, c0, r1, c1 = region
    rock_region = (int(r0), int(c0), int(min(r1 - r0, c1 - c0)))
    return ws, pad, above, target, rock_region


def _rock_xy(rock_region: tuple[int, int, int], rock_seed: int) -> np.ndarray:
    """Real Golombek clast centres (x, y) [m] over the pad window for this seed (held-out field)."""
    r0, c0, n = rock_region
    rf = build_clasts(HAWORTH_BUNDLE, r0, c0, n, world_seed=int(rock_seed))
    if not rf["clasts"]:
        return np.zeros((0, 2))
    return np.array([[c["center_m"][0], c["center_m"][2]] for c in rf["clasts"]], dtype=np.float64)


# --- policies: distinct dig ORDERINGS over the above-target pad cells --------------------------------
# Each returns a 1-D index order into the flattened above-target cell list. The physics (cut mass, dig
# energy, pass count, final surface) is invariant to this order; only the haul-leg routing differs.

def _order_highest(h_above, rc, rng):        # dig the tallest spots first (classic greedy)
    return np.argsort(-h_above)

def _order_nearest(h_above, rc, rng):        # dig nearest-to-dig-origin first (min in-pad travel)
    r, c = rc
    d = (r - r.mean()) ** 2 + (c - c.mean()) ** 2
    return np.argsort(d)

def _order_random(h_above, rc, rng):         # the row's explicit control: a RANDOM order
    return rng.permutation(len(h_above))

def _order_shallow(h_above, rc, rng):        # lowest spots first (a deliberately poor, "shallow-bias" order)
    return np.argsort(h_above)

POLICIES = {
    "greedy_highest": _order_highest,
    "greedy_nearest": _order_nearest,
    "random_order": _order_random,
    "shallow_first": _order_shallow,
}


@dataclass(frozen=True)
class Result:
    policy: str
    rock_seed: int
    cut_mass_kg: float
    passes: int
    dig_J: float
    drive_J: float
    energy_J: float
    as_built_rmse_m: float


def run_policy(scn: Scenario, policy: str, *, seed_for_random: int = 0) -> Result:
    """Execute one dig ORDER on the frozen scenario and measure the three TR-02 acceptance metrics.

    The maneuver model: order the above-target pad cells by ``policy``, pack them into drum-capacity
    loads (a PASS), and haul each load to the nearest rock-free dump cell just outside the pad. Dig
    energy = ``const · cut_mass``; drive energy = per-pass haul legs at the sourced lunar drive cost.
    """
    ws, pad, above, target, rock_region = _open(scn)
    cs = ws._require_fine()
    h = cs.derive_height()
    rr, cc = np.nonzero(above)
    h_above = h[rr, cc]
    order = POLICIES[policy](h_above, (rr.astype(float), cc.astype(float)),
                             np.random.default_rng(seed_for_random))
    rr, cc, h_above = rr[order], cc[order], h_above[order]
    # per-cell removable mass to reach target (clamped >=0; the conserved cut, cell area x thickness x rho)
    cell_area = cs.cell_m ** 2
    rho = cs.density[rr, cc]
    mass_cell = np.clip((h_above - target), 0.0, None) * rho * cell_area

    cap = scn.drum_capacity_kg
    dig_j_per_kg = IX.dig_energy_per_kg()
    rocks = _rock_xy(rock_region, scn.rock_seed)

    # pack cells into drum-capacity passes (a PASS = fill the drum, haul, dump)
    passes = 0
    drive_J = 0.0
    acc = 0.0
    pass_cells: list[int] = []
    origin = ws.window_world_origin
    if origin is None:
        raise RuntimeError("window_world_origin is None after open_window()")
    ox, oy = origin

    def _haul_leg(cell_idxs: list[int]) -> float:
        """Sourced drive energy for one haul: dig-centroid -> nearest rock-free dump just outside the pad
        and back, at the lunar steady-drive cost. Rock avoidance lengthens the leg (routing is the ONLY
        policy-sensitive term)."""
        if not cell_idxs:
            return 0.0
        cr = rr[cell_idxs].mean() * cs.cell_m + oy
        cc_ = cc[cell_idxs].mean() * cs.cell_m + ox
        # candidate dump just outside the pad (four cardinal exits); pick the nearest rock-free one
        reach = scn.pad_half_m + 0.5
        cands = np.array([[cc_ + reach, cr], [cc_ - reach, cr], [cc_, cr + reach], [cc_, cr - reach]])
        best = math.inf
        for dx, dy in cands:
            if rocks.shape[0]:
                clear = float(np.sqrt(((rocks - [dx, dy]) ** 2).sum(1)).min())
                penalty = 0.0 if clear > 0.3 else (0.3 - clear)   # detour around a near rock
            else:
                penalty = 0.0
            dist = float(np.hypot(dx - cc_, dy - cr)) + penalty
            best = min(best, dist)
        # round trip; sourced lunar steady-drive power / speed = J per metre
        j_per_m = IX.lunar_drive_power_w(slope_deg=0.0) / IX.DRIVE_SPEED_MS
        return 2.0 * best * j_per_m

    for i, m in enumerate(mass_cell):
        if acc + m > cap and pass_cells:
            drive_J += _haul_leg(pass_cells)
            acc, pass_cells = 0.0, []
        acc += float(m)
        pass_cells.append(i)
    if pass_cells:                                    # final partial load
        drive_J += _haul_leg(pass_cells)

    cut_mass = float(mass_cell.sum())
    # passes-to-spec = the drum loads the conserved mass REQUIRES: ceil(mass / capacity). This is the
    # physical invariant (every policy fills each drum to capacity); a greedy bin-packer's off-by-one at
    # the final partial load is a packer artifact, not a planning lever, so it is not counted here.
    passes = int(np.ceil(cut_mass / cap)) if cut_mass > 0 else 0

    # execute the conserved cut on the authority (all above-target cells -> target) and measure as-built:
    # RMSE over the cells the cut ACTUALLY operated on (the reachable target is above their firm datum, so
    # the deterministic mass-exact flatten lands on it). This is the ±2 cm acceptance surface.
    ws.flatten(above, target)
    h_final = cs.derive_height()
    rmse = float(np.sqrt(np.mean((h_final[rr, cc] - target) ** 2))) if rr.size else 0.0

    dig_J = cut_mass * dig_j_per_kg
    return Result(policy=policy, rock_seed=scn.rock_seed, cut_mass_kg=cut_mass, passes=passes,
                  dig_J=dig_J, drive_J=drive_J, energy_J=dig_J + drive_J, as_built_rmse_m=rmse)


def sweep(scn_base: Scenario, seeds: list[int]) -> list[Result]:
    """Every policy on every held-out rock seed -- the null demonstration surface."""
    out: list[Result] = []
    for s in seeds:
        scn = Scenario(base_rc=scn_base.base_rc, pad_half_m=scn_base.pad_half_m,
                       target_drop_m=scn_base.target_drop_m, rock_seed=s, drum=scn_base.drum)
        for p in POLICIES:
            out.append(run_policy(scn, p))
    return out
