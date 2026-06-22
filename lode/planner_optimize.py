"""ARCH-2 (#123): the OBJECTIVE scoring + sequence OPTIMIZER, extracted from lode.mission_planner.

The OBJECTIVES / SEQUENCERS tables + size caps, the objective parser + optimality labeller, the hard-
constraint penalty, the per-order core scorer, the nearest/greedy/2-opt/or-opt/LK heuristics, the
Held-Karp exact DP, and optimize_sequence (the "solve in sequence" dispatcher). A leaf: imports only the
planner_sim (_simulate), planner_model (_d) and planner_constants (_CONSTRAINT_CAPS) leaves + stdlib
(routes are PASSED IN, not built here); it NEVER imports lode.mission_planner, so it introduces no cycle.
mission_planner re-exports every name here, so the plan/compare/timeline code's unqualified calls and
MP.OBJECTIVES / MP.optimize_sequence / MP.parse_objective / MP.SEQUENCERS dependents stay byte-identical.
"""
# PROVENANCE: STEWIE LODE subsystem (A. Storey)
from __future__ import annotations

import itertools
import math

from lode.planner_constants import _CONSTRAINT_CAPS
from lode.planner_model import _d
from lode.planner_sim import _simulate


# ---- objectives: the metric the sequencer optimizes / the user sorts by ------------------------
# Each entry is (direction, totals -> scalar). "min" objectives are minimized, "max" maximized (the
# optimizer negates them). Every objective reads from the SIMULATED totals, so ANY algorithm can be
# scored against ANY objective -- overall duration/time, energy, average power, drive distance, recharge
# stops, or amount moved (constant for a full plan -> a sort key; the lever once plans are budgeted).
OBJECTIVES = {
    "time":     ("min", lambda T: T["time_s"]),
    "duration": ("min", lambda T: T["time_s"]),            # alias for "overall duration"
    "energy":   ("min", lambda T: T["energy_J"]),
    # P-10: this is AVERAGE power = total energy / duration, NOT peak/rated electrical demand. Minimizing
    # it can reward SLOWER execution (more time in the denominator), so it is named `average_power` to
    # stop users reading it as a peak-power constraint. `power` is kept as a legacy alias (the browser UI
    # still sends objective=power) and resolves to the same average-power metric.
    "average_power": ("min", lambda T: T["avg_power_w"]),  # average electrical power = energy / duration
    "power":    ("min", lambda T: T["avg_power_w"]),        # [LEGACY ALIAS of average_power -- UI compat]
    "distance": ("min", lambda T: T["distance_m"]),
    "charges":  ("min", lambda T: T["charges"]),
    "mass":     ("max", lambda T: T["mass_kg"]),            # amount moved
}
# P-10: the metric Held-Karp's exact DP actually minimizes (routed DRIVING DISTANCE). Any other objective
# is only HEURISTIC under held_karp (the LK polish improves it but gives no optimality bound), so the
# optimality label must be objective-specific -- "exact" only when the solved metric IS the objective.
HELD_KARP_EXACT_METRIC = "distance"
# Sequencer algorithms. nearest/greedy/two_opt/or_opt/lk are heuristics (objective-scored by simulation);
# brute + held_karp are EXACT (brute over permutations <=7; Held-Karp DP exact-on-driving-distance <=16);
# auto dispatches to the strongest solver the problem size + precedence allow ("solved in sequence").
SEQUENCERS = ("auto", "nearest", "greedy", "two_opt", "or_opt", "lk", "brute", "held_karp")
BRUTE_MAX_TRIPS = 7          # exhaustive permutation search only up to 7! = 5040
HELD_KARP_MAX_TRIPS = 16     # Held-Karp DP is O(2^n * n^2); ~16 trips is the practical ceiling


def _score(core, objective):
    """(sortable, raw) for a SINGLE objective: sortable is always MINIMIZED (max objectives negated)."""
    direction, fn = OBJECTIVES[objective]
    raw = fn(core)
    return (raw if direction == "min" else -raw), raw


def parse_objective(objective):
    """Normalize an objective spec to a weight dict. Accepts a single name ('time'), a dict
    ({'time': 0.6, 'energy': 0.4}), or a 'name:w,name:w' string. A single name -> {name: 1.0}. Every
    component must be a known objective. Weights are renormalized to sum to 1.

    P-08: the weight DOMAIN is validated, not just the names. A multi-objective spec is a convex
    combination, so every weight must be a FINITE, NON-NEGATIVE real number and the weights must sum to
    a STRICTLY POSITIVE finite total; NaN/Inf/negative weights, a zero (or non-positive) sum, duplicate
    components, and malformed (non-numeric) weight strings are all rejected with ValueError."""
    if isinstance(objective, str) and objective in OBJECTIVES:
        return {objective: 1.0}
    if isinstance(objective, str):                          # "time:0.6,energy:0.4"
        spec = {}
        for part in objective.split(","):
            name, _, w = part.partition(":")
            name = name.strip()
            if name in spec:                                # P-08: a repeated component is ambiguous
                raise ValueError(f"duplicate objective component {name!r} in {objective!r}")
            try:
                spec[name] = float(w) if w.strip() else 1.0   # P-08: a non-numeric weight (e.g. 'time:time')
            except ValueError:
                raise ValueError(f"malformed objective weight {w.strip()!r} for {name!r} in {objective!r}")
        objective = spec
    if not isinstance(objective, dict) or not objective:
        raise ValueError(f"unparseable objective {objective!r}")
    for k, v in objective.items():
        if k not in OBJECTIVES:
            raise ValueError(f"unknown objective {k!r}; known: {sorted(OBJECTIVES)}")
        fv = float(v)
        if not math.isfinite(fv) or fv < 0.0:               # P-08: weights are finite and non-negative
            raise ValueError(f"objective weight for {k!r} must be finite and >= 0 (got {v!r})")
    tot = sum(float(v) for v in objective.values())
    if not (math.isfinite(tot) and tot > 0.0):              # P-08: a convex combination needs a positive sum
        raise ValueError(f"objective weights must sum to a finite positive value (got {tot!r})")
    return {k: float(v) / tot for k, v in objective.items()}


def _objective_is_only(objective, metric):
    """True iff `objective` (single name / 'name:w,...' string / weight dict) is EXACTLY the one `metric`
    (a single-objective spec on that metric), accounting for aliases (time/duration, power/average_power)."""
    aliases = {"time": {"time", "duration"}, "duration": {"time", "duration"},
               "average_power": {"average_power", "power"}, "power": {"average_power", "power"}}
    target = aliases.get(metric, {metric})
    try:
        weights = parse_objective(objective)
    except ValueError:
        return False
    return len(weights) == 1 and next(iter(weights)) in target


def _objective_optimality(resolved, objective):
    """P-10: objective-SPECIFIC optimality label + an `objective_exact` flag.

    - brute simulates every permutation -> EXACT on whatever objective was chosen (objective_exact=True).
    - held_karp / held_karp_lk are exact only on routed DRIVING DISTANCE (then LK-polished). The label
      NAMES the exact metric ("distance-exact (heuristic for this objective)+polish"), and the result is
      objective_exact ONLY when the chosen objective IS distance.
    - everything else is heuristic.

    Returns (label, objective_exact)."""
    if resolved == "brute":
        return "exact", True
    if resolved in ("held_karp", "held_karp_lk"):
        is_distance = _objective_is_only(objective, HELD_KARP_EXACT_METRIC)
        if is_distance:
            return ("distance-exact" if resolved == "held_karp" else "distance-exact+polish"), True
        # exact on distance only -> name the metric and flag the chosen objective as NOT exact.
        return f"distance-exact (heuristic for this objective){'+polish' if resolved == 'held_karp_lk' else ''}", False
    return "heuristic", False


def _constraint_penalty(core, constraints) -> float:
    """CP-08: the hard-constraint + risk penalty added to an ordering's score. A candidate whose simulated
    `core` overshoots a budget (max_time_s / max_energy_J / max_charges / max_distance_m) gets a LARGE
    penalty scaled by the fractional overshoot, so any constraint-feasible ordering ranks below an
    infeasible one is impossible -- feasible always wins, and among infeasible ones the least-overshooting
    is preferred. ``risk_weight`` adds a recharge-exposure cost (more recharges = more operational risk).
    Returns 0.0 when ``constraints`` is None/empty or nothing is violated (byte-identical default)."""
    if not constraints:
        return 0.0
    pen = 0.0
    for cap_key, metric in _CONSTRAINT_CAPS.items():
        cap = constraints.get(cap_key)
        if cap is not None and metric in core:
            v, c = float(core[metric]), float(cap)
            if v > c:
                pen += 1e6 * (1.0 + (v - c) / max(abs(c), 1e-9))   # big + overshoot-scaled (least-bad first)
    rw = constraints.get("risk_weight")
    if rw is not None and "charges" in core:
        pen += float(rw) * float(core["charges"])
    return pen


def _make_core_scorer(mission, trips, objective, routes=None):
    """Return a function core -> sortable scalar (lower = better). For a single objective this is the raw
    metric (max objectives negated). For a WEIGHTED multi-objective it is the weighted sum of each metric
    normalized by a reference plan (the nearest-neighbour order), so differently-scaled metrics combine.
    H-02: `routes` is threaded into the reference simulation so the normalization uses routed geometry too.
    CP-08: a mission-level hard-constraint + risk penalty is added on top (0 when unset -> byte-identical)."""
    weights = parse_objective(objective)
    cons = getattr(mission, "objective_constraints", None)
    if len(weights) == 1:
        (name,) = weights
        return lambda core: _score(core, name)[0] + _constraint_penalty(core, cons)
    ref = _simulate(mission, [trips[i] for i in _nn_order(trips, mission)], routes)[2]   # reference scales

    def scorer(core):
        s = 0.0
        for name, w in weights.items():
            direction, fn = OBJECTIVES[name]
            raw, r = fn(core), fn(ref)
            # P-09: stable normalization that handles a ZERO or constant reference. The reference comes
            # from a FIXED plan (nearest-neighbour), so scoring is candidate-set independent; floor the
            # denominator with a tiny positive scale so a zero reference (e.g. zero recharges/distance)
            # cannot divide by zero or produce NaN/Inf. When BOTH raw and reference are ~0 the metric is
            # degenerate (no signal) -> a constant unit contribution, so it never inverts the ranking by
            # the other objectives.
            if direction == "min":
                norm = 1.0 if (abs(raw) <= 1e-9 and abs(r) <= 1e-9) else raw / max(r, 1e-9)
            else:
                norm = 1.0 if (abs(raw) <= 1e-9 and abs(r) <= 1e-9) else max(r, 0.0) / max(raw, 1e-9)
            s += w * norm
        return s + _constraint_penalty(core, cons)
    return scorer


def _nn_order(trips, mission, *, eligible_fn=None):
    """Nearest-neighbour order from the charger; if eligible_fn is given, only choose currently-eligible
    trips (precedence-aware)."""
    n = len(trips); seq = []; unv = list(range(n)); cur = mission.charger
    while unv:
        cands = [i for i in unv if eligible_fn(i, seq)] if eligible_fn else unv
        k = min(cands, key=lambda i: _d(cur, trips[i]["site"])); seq.append(k); unv.remove(k)
        cur = trips[k]["site"]
    return seq


def _prec_masks(n, precedence):
    """Per-trip predecessor bitmask: pred[j] has bit i set iff trip i must precede trip j."""
    pred = [0] * n
    for i, j in (precedence or []):
        pred[j] |= (1 << i)
    return pred


def _respects(order, pred):
    """True iff `order` honors every precedence constraint (each trip after all its predecessors)."""
    seen = 0
    for j in order:
        if pred[j] & ~seen:                                # a predecessor of j not yet visited
            return False
        seen |= (1 << j)
    return True


def _held_karp(trips, mission, pred, routes=None):
    """Exact min-DRIVING-DISTANCE Hamiltonian tour (charger -> all sites -> charger) by Held-Karp DP,
    honoring precedence (a Sequential Ordering Problem). O(2^n * n^2). Returns the trip order; the planner
    then simulates it for the chosen objective's true battery-aware totals (distance is the exact lever;
    it is a near-perfect proxy for time/energy here because dig energy dominates and is order-independent).
    H-02: the seed distance matrix uses the ROUTED inter-site distance (`routes`, the shared _make_routes
    cache) so the exact tour is min-ROUTED-distance -- the geometry the plan actually drives -- not min
    straight-line. No DEM (routes=None) -> straight-line _d, byte-identical; the cache is already built."""
    n = len(trips)
    pts = [tuple(mission.charger)] + [tuple(t["site"]) for t in trips]
    _md = (lambda a, b: routes(a, b)) if routes is not None else _d
    dmat = [[_md(pts[a], pts[b]) for b in range(n + 1)] for a in range(n + 1)]
    full = (1 << n) - 1
    dp = [[math.inf] * n for _ in range(1 << n)]
    par = [[-1] * n for _ in range(1 << n)]
    for j in range(n):
        if pred[j] == 0:                                   # may go first only if it has no predecessors
            dp[1 << j][j] = dmat[0][j + 1]
    for mask in range(1 << n):
        for j in range(n):
            base = dp[mask][j]
            if base == math.inf:
                continue
            for k in range(n):
                if mask & (1 << k):
                    continue
                if pred[k] & ~mask:                        # k's predecessors not all in `mask`
                    continue
                nm = mask | (1 << k); nd = base + dmat[j + 1][k + 1]
                if nd < dp[nm][k]:
                    dp[nm][k] = nd; par[nm][k] = j
    best, endj = math.inf, -1
    for j in range(n):
        v = dp[full][j] + dmat[j + 1][0]
        if v < best:
            best, endj = v, j
    if endj == -1:                                         # no complete tour honors the precedence DAG
        raise ValueError("precedence is infeasible (cyclic / unsatisfiable): no valid trip ordering exists")
    order = []; mask, j = full, endj
    while j != -1:
        order.append(j); pj = par[mask][j]; mask ^= (1 << j); j = pj
    order.reverse()
    return order


def optimize_sequence(trips, mission, *, algorithm="auto", objective="time", precedence=None, routes=None):
    """Return a visit order (trip indices) chosen by `algorithm` to optimize `objective` (a name, a
    'name:w,...' string, or a weight dict), honoring `precedence` (list of (i, j): trip i before trip j).

      auto       -- dispatch to the strongest solver the size + precedence allow (brute<=7, held_karp<=16,
                    else lk); precedence routes to the SOP-aware variants.
      nearest    -- distance nearest-neighbour from the charger (no simulation; fast; objective-agnostic).
      greedy     -- append the eligible trip minimizing the objective of the prefix-so-far (sim-scored).
      two_opt    -- nearest seed + 2-opt segment reversals improving the objective (precedence-valid only).
      or_opt     -- nearest seed + Or-opt relocations of 1-3 consecutive trips (precedence-valid only).
      lk         -- 2-opt + Or-opt to convergence (a Lin-Kernighan-STYLE composite, not full variable-depth LK).
      brute      -- exhaustive over (precedence-valid) permutations, <= BRUTE_MAX_TRIPS. Optimal.
      held_karp  -- exact min-driving-distance DP (SOP-aware), <= HELD_KARP_MAX_TRIPS, then simulated."""
    parse_objective(objective)                             # validates the objective spec (raises if bad)
    n = len(trips)
    if n <= 1:
        return list(range(n))
    pred = _prec_masks(n, precedence)
    has_prec = any(pred)

    def eligible(i, placed):
        seen = 0
        for p in placed:
            seen |= (1 << p)
        return (pred[i] & ~seen) == 0

    score_core = _make_core_scorer(mission, trips, objective, routes)

    def score(order):
        return score_core(_simulate(mission, [trips[i] for i in order], routes)[2])   # H-02: routed scoring

    if algorithm == "auto":
        if n <= BRUTE_MAX_TRIPS:
            return optimize_sequence(trips, mission, algorithm="brute", objective=objective,
                                     precedence=precedence, routes=routes)
        # 8..16: exact driving tour (Held-Karp) as a strong SEED, then LK-polish on the REAL (recharge-
        # coupled) objective -- "solved in sequence". >16: LK from the nearest seed.
        algorithm = "held_karp_lk" if n <= HELD_KARP_MAX_TRIPS else "lk"

    if algorithm == "nearest":
        return _nn_order(trips, mission, eligible_fn=eligible if has_prec else None)

    if algorithm == "held_karp" and n <= HELD_KARP_MAX_TRIPS:
        return _held_karp(trips, mission, pred, routes)    # PURE exact driving tour (no real-objective polish)

    if algorithm == "greedy":
        order = []; unv = list(range(n))
        while unv:
            cands = [i for i in unv if eligible(i, order)] if has_prec else unv
            nxt = min(cands, key=lambda i: score(order + [i]))
            order.append(nxt); unv.remove(nxt)
        return order

    if algorithm == "brute" and n <= BRUTE_MAX_TRIPS:
        perms = (p for p in itertools.permutations(range(n)) if not has_prec or _respects(p, pred))
        return list(min(perms, key=score))

    # ---- local-search family (2-opt / Or-opt / LK-style), precedence-valid moves only ----
    def two_opt_moves(o):
        for i in range(n - 1):
            for j in range(i + 1, n):
                yield o[:i] + o[i:j + 1][::-1] + o[j + 1:]

    def or_opt_moves(o):                                   # relocate a run of 1-3 consecutive trips
        for seg in (1, 2, 3):
            for i in range(n - seg + 1):
                chunk = o[i:i + seg]; rest = o[:i] + o[i + seg:]
                for k in range(len(rest) + 1):
                    if k != i:
                        yield rest[:k] + chunk + rest[k:]

    def local_search(seed, use_two_opt=True, use_or_opt=True):
        order = list(seed); best = score(order); gens = []
        if use_two_opt: gens.append(two_opt_moves)
        if use_or_opt: gens.append(or_opt_moves)
        improving = True
        while improving:
            improving = False
            for gen in gens:
                for cand in gen(order):
                    if has_prec and not _respects(cand, pred):
                        continue
                    s = score(cand)
                    if s < best - 1e-9:
                        order, best, improving = list(cand), s, True
        return order

    nn_seed = _nn_order(trips, mission, eligible_fn=eligible if has_prec else None)
    if algorithm == "two_opt":
        return local_search(nn_seed, use_or_opt=False)
    if algorithm == "or_opt":
        return local_search(nn_seed, use_two_opt=False)
    if algorithm == "held_karp_lk":                        # auto's 8-16 path: HK seed + LK polish
        return local_search(_held_karp(trips, mission, pred, routes))
    if algorithm in ("lk", "brute", "held_karp"):          # lk; also the >cap fallback for brute/held_karp
        return local_search(nn_seed)
    raise ValueError(f"unknown algorithm {algorithm!r}; known: {SEQUENCERS}")
