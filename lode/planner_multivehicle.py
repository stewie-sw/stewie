"""ARCH-2: multi-vehicle fleet allocation + space-time conflict resolution (extracted from
mission_planner.py).

Self-contained: every function is pure geometry over duck-typed per-vehicle / trip / mission structures
(dicts + attribute access) -- no dependency on the planner core, so importing this never cycles back into
mission_planner. The facade (mission_planner) re-exports these so ``MP.<fn>`` and ``plan_multi`` are
unchanged. FL-02/FL-04/MV1-7: site-exclusive LPT allocation, per-vehicle health, charger queue, shared
resource + temporal + haul-path deconfliction, and FCFS space-time crowd resolution.
"""
# PROVENANCE: STEWIE LODE subsystem (A. Storey)
from __future__ import annotations

import math

import numpy as np


def _trip_work_e(tr):
    """A trip's work energy (dig + sinter + haul) -- the load used to balance the fleet allocation."""
    return tr.get("dig_e", 0.0) + tr.get("sinter_e", 0.0) + tr.get("haul_e", 0.0)


def _allocate_trips(trips, vehicles):
    """MV2: SITE-EXCLUSIVE, load-balanced (LPT) allocation of trips to V vehicles. Trips are grouped by
    site so no two vehicles ever work the SAME site (zero co-occupation by construction); whole site-groups
    are then assigned greedily to the least-loaded vehicle by work energy (longest-processing-time first).
    Returns a list of V index-lists (some may be empty if V exceeds the number of sites)."""
    groups: dict = {}
    for idx, tr in enumerate(trips):
        groups.setdefault(tuple(tr["site"]), []).append(idx)

    def gcost(idxs):
        return sum(_trip_work_e(trips[i]) for i in idxs)

    loads = [0.0] * vehicles
    alloc: list = [[] for _ in range(vehicles)]
    for idxs in sorted(groups.values(), key=gcost, reverse=True):   # biggest site-group first (LPT)
        v = min(range(vehicles), key=lambda k: loads[k])
        alloc[v].extend(idxs)
        loads[v] += gcost(idxs)
    return alloc


def _allocate_components(trips, vehicles, precedence):
    """MV cross-precedence allocation: like _allocate_trips, but the allocation UNIT also keeps
    precedence-connected work together. Union trips that share a SITE (site-exclusivity, as before) OR a
    precedence edge (so a whole precedence chain lands on ONE vehicle and the per-vehicle sequencer can
    honor its order); then LPT-assign whole units to the least-loaded vehicle by work energy. INDEPENDENT
    chains parallelize across the fleet; SPLITTING a single chain across vehicles with cross-vehicle
    wait-coordination is future MV work (documented in plan_multi). Returns a list of V index-lists."""
    n = len(trips)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    site_first: dict = {}
    for idx, tr in enumerate(trips):
        s = tuple(tr["site"])
        if s in site_first:
            union(site_first[s], idx)         # same site -> same vehicle (site-exclusivity preserved)
        else:
            site_first[s] = idx
    for i, j in (precedence or []):
        union(i, j)                           # precedence-connected -> same vehicle (intra-vehicle ordering)

    units: dict = {}
    for k in range(n):
        units.setdefault(find(k), []).append(k)

    def ucost(idxs):
        return sum(_trip_work_e(trips[i]) for i in idxs)

    loads = [0.0] * vehicles
    alloc: list = [[] for _ in range(vehicles)]
    for idxs in sorted(units.values(), key=ucost, reverse=True):    # biggest unit first (LPT)
        v = min(range(vehicles), key=lambda k: loads[k])
        alloc[v].extend(idxs)
        loads[v] += ucost(idxs)
    return alloc


def _allocate_precedence_split(trips, vehicles, precedence):
    """FL-04 cross-vehicle precedence chain-SPLITTING allocation. Unlike `_allocate_components` (which
    unions whole precedence chains onto ONE vehicle so the per-vehicle sequencer can order them), this
    keeps only the SITE-exclusivity union -- whole site-groups stay together on one vehicle (zero
    co-occupation, as before) -- but does NOT union across precedence edges, so a precedence chain that
    spans two work sites can land on TWO vehicles and run in parallel. The cross-vehicle ORDERING is then
    preserved by `_resolve_cross_vehicle_precedence` (a dependent leg's effective start is held at/after its
    predecessor's effective end, the same per-vehicle wait the shared charger uses). With no precedence this
    is BYTE-IDENTICAL to `_allocate_trips` (it computes the same site-group LPT assignment). The global
    precedence is verified acyclic before allocation (mission_planner._precedence_is_feasible), so splitting
    a chain across vehicles can never create an unsatisfiable cross-vehicle wait cycle. Returns a list of V
    index-lists. `precedence` is accepted for symmetry/intent (and a future smarter split) but the
    site-exclusive LPT assignment alone already separates distinct sites across the fleet."""
    return _allocate_trips(trips, vehicles)


def _resolve_cross_vehicle_precedence(per_vehicle, alloc, precedence, trips):
    """FL-04: hold a CROSS-vehicle precedence edge by delaying the dependent vehicle until its predecessor
    leg (on a DIFFERENT vehicle) has finished -- the chain-splitting counterpart to `_allocate_components`'s
    keep-the-chain-whole policy. `alloc` is the per-vehicle list of GLOBAL trip indices (so a trip's vehicle
    is recoverable); `trips` is the global trip list so each per_trip leg's window is keyed back to its REAL
    global index by TRIP-OBJECT IDENTITY -- NOT by positional zip(alloc, per_trip). The per-vehicle sequencer
    (`optimize_sequence` in plan_multi) reorders a vehicle's trips before `_simulate`, so `per_trip` is in
    SIMULATION order, which is NOT alloc order; zipping the two silently mis-pairs a trip with another trip's
    window and a dependent leg could start before its predecessor's real end (precedence VIOLATED). Matching
    `id(pt["trip"])` to its global index is order-independent and correct under any sequencer permutation.
    `precedence` is the global (i, j) 'trip i before trip j' edges.

    Only edges whose endpoints land on DIFFERENT vehicles need a wait (an INTRA-vehicle edge is already
    honored by the per-vehicle sequencer -> contributes nothing). For each cross edge the dependent
    vehicle's whole schedule is shifted so the dependent leg's EFFECTIVE start (original t_start + that
    vehicle's accrued delay) is at/after the predecessor leg's EFFECTIVE end (its t_end + the predecessor
    vehicle's delay). This is the SAME per-vehicle delay discipline the shared charger
    (`_resolve_charger_queue`) and crowding (`_resolve_spacetime_crowding`) use, so it folds into the
    makespan identically. Iterated to a fixed point: the precedence is acyclic (checked upstream), so the
    delays only grow and converge. CONSERVATIVE: shifting the whole vehicle (not just the dependent leg) can
    over-delay later independent work on that vehicle -- a finer per-leg re-time is future MV work. No
    cross-vehicle edge -> all-zero delays -> byte-identical to the un-coordinated fleet. Returns the
    per-vehicle delay [s]; a vehicle's real finish is time_s + delay[v]."""
    n = len(per_vehicle)
    delay = [0.0] * n
    if not precedence:
        return delay
    veh_of: dict = {}                                            # global trip idx -> vehicle
    for v, idxs in enumerate(alloc):
        for gi in idxs:
            veh_of[gi] = v
    obj_to_gid = {id(tr): g for g, tr in enumerate(trips)}       # trip OBJECT -> global trip idx
    win: dict = {}                                               # global trip idx -> (t_start, t_end)
    for pv in per_vehicle:
        for pt in pv.get("per_trip", []):
            gid = obj_to_gid.get(id(pt["trip"]))                 # REAL identity, not positional zip
            if gid is None:                                      # leg not in the global trips list -> skip
                continue
            win[gid] = (float(pt["t_start"]), float(pt["t_end"]))
    # keep only edges that actually CROSS a vehicle boundary (intra-vehicle edges the sequencer handles)
    cross = []
    for i, j in precedence:
        vi, vj = veh_of.get(i), veh_of.get(j)
        if vi is None or vj is None or vi == vj or i not in win or j not in win:
            continue
        cross.append((vi, win[i][1], vj, win[j][0]))            # (pred_v, pred_end, dep_v, dep_start)
    if not cross:
        return delay
    for _ in range(n + 1):                                       # acyclic DAG over <= n vehicles -> converges
        new_delay = list(delay)
        for pred_v, pred_end, dep_v, dep_start in cross:
            eff_pred_end = pred_end + delay[pred_v]
            eff_dep_start = dep_start + delay[dep_v]
            if eff_dep_start < eff_pred_end:                     # dependent leg would start too early
                need = eff_pred_end - eff_dep_start
                new_delay[dep_v] = max(new_delay[dep_v], delay[dep_v] + need)
        if new_delay == delay:
            break
        delay = new_delay
    return delay


def _vehicle_conflicts(per_vehicle):
    """MV5: count space-time conflicts -- two DIFFERENT vehicles whose per-trip time windows overlap at the
    SAME site. Site-exclusive allocation makes this 0 by construction; the detector verifies it (and would
    catch a future allocation that lets vehicles share a site). Continuous haul-PATH crossing avoidance is
    not modelled here (future MV work) -- this is site-level deconfliction."""
    spans = [(v, tuple(pt["trip"]["site"]), pt["t_start"], pt["t_end"])
             for v, pv in enumerate(per_vehicle) for pt in pv["per_trip"]]
    conflicts = 0
    for a in range(len(spans)):
        va, sa, s0, s1 = spans[a]
        for b in range(a + 1, len(spans)):
            vb, sb, t0, t1 = spans[b]
            if va != vb and sa == sb and s0 < t1 and t0 < s1:     # same site, overlapping windows
                conflicts += 1
    return conflicts


def _charger_conflicts(per_vehicle, mission):
    """P-06: count SHARED-CHARGER conflicts -- two DIFFERENT vehicles whose recharge (kind='charge')
    timeline windows overlap at the single shared charger. v1 plans each vehicle independently from the
    same charger, so a real fleet would queue at one charger; this detector SURFACES the contention the
    v1 schedule ignores (the audit's 'omits shared-resource constraints'). Each overlapping pair of charge
    windows is one conflict. Returns the integer count (0 when no two vehicles charge at the same time)."""
    charges = [(v, seg["t0"], seg["t1"])
               for v, pv in enumerate(per_vehicle)
               for seg in pv.get("tl", []) if seg.get("kind") == "charge"]
    conflicts = 0
    for a in range(len(charges)):
        va, a0, a1 = charges[a]
        for b in range(a + 1, len(charges)):
            vb, b0, b1 = charges[b]
            if va != vb and a0 < b1 and b0 < a1:                  # different vehicles, overlapping charge windows
                conflicts += 1
    return conflicts


def _resolve_charger_queue(per_vehicle, capacity=1):
    """FL-03: resolve the SHARED charger(s) as a CAPACITY-k server queue. `capacity` is the number of
    rovers that can charge at once; the DEFAULT 1 is the single-charger case and is BYTE-IDENTICAL to v1's
    one-server FCFS queue. v1 planned each vehicle's recharges as if chargers were unlimited (optimistic);
    a real fleet shares a finite charger, so charges serialise when they would exceed capacity. Sweep
    every vehicle's charge windows in EFFECTIVE-arrival order; assign each to the charger slot that frees
    earliest and start it at max(arrival, that slot's free time) -- so a charge that arrives while all k
    slots are busy WAITS for the earliest, and that wait shifts the vehicle's later timeline. Each
    scheduled charge is then ADMITTED against a ReservationLedger capacity-k 'charger' resource, so the
    fleet plans AGAINST the ledger (FL-03/FL-04 preventive admission) rather than only detecting overlaps
    after the fact; the k-server schedule fits the ledger by construction (<= k concurrent). Returns the
    per-vehicle accumulated wait [s]; a vehicle's real finish is time_s + delay[v]. Pure + deterministic
    (ties break to the lower vehicle index)."""
    from lode.fleet_resources import Reservation, ReservationLedger, SharedResource
    cap = max(1, int(capacity))
    n = len(per_vehicle)
    queues = [[(float(s["t0"]), float(s["t1"]) - float(s["t0"]))         # (arrival, duration) per charge
               for s in pv.get("tl", []) if s.get("kind") == "charge"]
              for pv in per_vehicle]
    ptr = [0] * n
    delay = [0.0] * n
    slot_free = [0.0] * cap                                             # next-free time of each charger slot
    ledger = ReservationLedger([SharedResource("charger", "charger", cap)])
    while True:
        nxt, nxt_arr = -1, None                                         # next charge to service, by EFFECTIVE arrival
        for v in range(n):
            if ptr[v] < len(queues[v]):
                arr = queues[v][ptr[v]][0] + delay[v]                   # original start shifted by accrued delay
                if nxt_arr is None or arr < nxt_arr:
                    nxt, nxt_arr = v, arr
        if nxt < 0:
            break                                                       # all charges serviced
        dur = queues[nxt][ptr[nxt]][1]
        slot = min(range(cap), key=lambda i: slot_free[i])              # the earliest-free slot (the only one when cap=1)
        start = max(nxt_arr, slot_free[slot])                           # wait if every slot is still busy
        delay[nxt] += start - nxt_arr                                   # this wait shifts the vehicle's later timeline
        slot_free[slot] = start + dur
        if dur > 0:                                                     # admit the scheduled charge against the ledger
            ledger.reserve(Reservation("charger", f"v{nxt}#{ptr[nxt]}", start, start + dur))
        ptr[nxt] += 1
    return delay


def _resolve_shared_resources(per_vehicle, resources, *, tol_m=0.5):
    """FL-03: resolve declared SHARED RESOURCES (pit / dump / vantage / corridor) as capacity-k servers --
    the SAME k-server FCFS discipline as the charger queue, but keyed on WORK SITES instead of charge events.

    `resources` is None/empty -> no contention -> per-vehicle delay all 0 (byte-identical to an un-resourced
    fleet). Each resource is {id, kind, capacity, sites:[[x,y],...]}: a trip whose work site lies within
    `tol_m` of one of the resource's sites OCCUPIES it for that trip's [t_start, t_end] window; when more
    than `capacity` rovers would occupy it at once the excess WAITS for the earliest-free slot, and that
    wait shifts the waiting vehicle's later timeline. Each admitted occupancy is recorded against a
    capacity-k ReservationLedger so the fleet plans AGAINST the ledger (FL-03/FL-04 preventive admission).

    Returns (per_vehicle_delay, per_resource_wait) where per_resource_wait[id] is the summed wait that
    resource caused. v1 approximation (documented): each resource and the charger queue are scheduled
    INDEPENDENTLY, so a vehicle's total wait is the sum of its per-resource waits -- a conservative upper
    estimate (a vehicle cannot truly be in two queues at once). Pure + deterministic (ties -> lower index)."""
    n = len(per_vehicle)
    delay = [0.0] * n
    if not resources:
        return delay, {}
    from lode.fleet_resources import Reservation, ReservationLedger, SharedResource

    def _near(site, pts):
        return any(abs(site[0] - px) <= tol_m and abs(site[1] - py) <= tol_m for px, py in pts)

    per_res_wait: dict = {}
    for res in resources:
        rid = res["id"]
        cap = max(1, int(res["capacity"]))
        pts = res["sites"]
        ledger = ReservationLedger([SharedResource(rid, res["kind"], cap)])
        qs: dict = {}                                          # per-vehicle (arrival, duration) occupancies
        for v, pv in enumerate(per_vehicle):
            for pt in pv.get("per_trip", []):
                site = pt["trip"].get("site")
                if site is None or not _near(site, pts):
                    continue
                t0, t1 = float(pt["t_start"]), float(pt["t_end"])
                if t1 > t0:
                    qs.setdefault(v, []).append((t0, t1 - t0))
        if not qs:
            continue
        for v in qs:
            qs[v].sort()
        ptr = {v: 0 for v in qs}
        res_delay = [0.0] * n
        slot_free = [0.0] * cap
        while True:
            nxt, nxt_arr = -1, None                            # next occupancy by EFFECTIVE arrival
            for v in qs:
                if ptr[v] < len(qs[v]):
                    arr = qs[v][ptr[v]][0] + res_delay[v]
                    if nxt_arr is None or arr < nxt_arr:
                        nxt, nxt_arr = v, arr
            if nxt < 0:
                break
            dur = qs[nxt][ptr[nxt]][1]
            slot = min(range(cap), key=lambda i: slot_free[i])
            start = max(nxt_arr, slot_free[slot])
            res_delay[nxt] += start - nxt_arr
            slot_free[slot] = start + dur
            ledger.reserve(Reservation(rid, f"v{nxt}#{ptr[nxt]}", start, start + dur))
            ptr[nxt] += 1
        for v in range(n):
            delay[v] += res_delay[v]
        w = float(sum(res_delay))
        if w > 0:
            per_res_wait[rid] = w
    return delay, per_res_wait


def _temporal_conflicts(per_vehicle, *, proximity_m: float = 10.0) -> int:
    """FL-02: SPACE-TIME conflicts beyond exact same-site overlap -- two DIFFERENT vehicles working within
    proximity_m of each other at OVERLAPPING times (rovers crowding adjacent sites simultaneously). Uses
    the timeline's STATIONARY work segments (x0==x1, y0==y1; charge excluded -- the charger is handled by
    the FCFS queue + _charger_conflicts) and their [t0,t1] windows. Returns the count (0 = deconflicted).
    proximity_m is an [ASSUMPTION] safe-separation radius. Continuous moving haul-PATH crossing is future
    MV work; this catches the stationary crowding case the same way _charger_conflicts surfaces overlaps."""
    stat = []                                              # (vehicle, x, y, t0, t1) for each stationary work span
    for v, pv in enumerate(per_vehicle):
        for s in pv.get("tl", []):
            if s.get("kind") == "charge" or "x0" not in s:
                continue
            if abs(s["x0"] - s.get("x1", s["x0"])) < 1e-9 and abs(s["y0"] - s.get("y1", s["y0"])) < 1e-9:
                stat.append((v, float(s["x0"]), float(s["y0"]), float(s["t0"]), float(s["t1"])))
    n = 0
    for i in range(len(stat)):
        vi, xi, yi, a0, a1 = stat[i]
        for j in range(i + 1, len(stat)):
            vj, xj, yj, b0, b1 = stat[j]
            if vi != vj and a0 < b1 and b0 < a1 and math.hypot(xi - xj, yi - yj) < proximity_m:
                n += 1                                     # different vehicles, overlapping time, within radius
    return n


def _seg_seg_min_dist(a0, a1, b0, b1) -> float:
    """Minimum Euclidean distance between two 2-D segments a0->a1 and b0->b1 (Ericson's clamped
    closest-point-between-segments). Used by FL-02 to test whether two moving haul paths pass close."""
    a0 = np.asarray(a0, float); a1 = np.asarray(a1, float)
    b0 = np.asarray(b0, float); b1 = np.asarray(b1, float)
    d1 = a1 - a0; d2 = b1 - b0; r = a0 - b0
    aa = float(d1 @ d1); ee = float(d2 @ d2); f = float(d2 @ r)
    EPS = 1e-12
    if aa <= EPS and ee <= EPS:                            # both degenerate -> point-point
        s = t = 0.0
    elif aa <= EPS:                                        # first degenerate -> point vs segment
        s = 0.0; t = min(max(f / ee, 0.0), 1.0)
    else:
        c = float(d1 @ r)
        if ee <= EPS:                                      # second degenerate
            t = 0.0; s = min(max(-c / aa, 0.0), 1.0)
        else:
            b = float(d1 @ d2); denom = aa * ee - b * b
            s = min(max((b * f - c * ee) / denom, 0.0), 1.0) if denom > EPS else 0.0
            t = (b * s + f) / ee
            if t < 0.0:
                t = 0.0; s = min(max(-c / aa, 0.0), 1.0)
            elif t > 1.0:
                t = 1.0; s = min(max((b - c) / aa, 0.0), 1.0)
    cp1 = a0 + d1 * s; cp2 = b0 + d2 * t
    return float(np.hypot(*(cp1 - cp2)))


def _haul_path_conflicts(per_vehicle, *, proximity_m: float = 10.0) -> int:
    """FL-02: continuous moving HAUL-PATH crossings -- two DIFFERENT vehicles whose DRIVE legs (the routed
    inter-site segments, x0 != x1 or y0 != y1) pass within proximity_m of each other during OVERLAPPING
    time windows. The moving path-vs-path case that complements _temporal_conflicts (stationary work
    crowding), _vehicle_conflicts (same site) and _charger_conflicts (shared charger). Returns the count
    (0 = deconflicted). proximity_m is an [ASSUMPTION] safe-separation radius; pure geometry over the
    per-vehicle timelines -- no behaviour change, a reported fleet-safety metric like temporal_conflicts."""
    segs = []                                              # (vehicle, (x0,y0), (x1,y1), t0, t1) per moving leg
    for v, pv in enumerate(per_vehicle):
        for s in pv.get("tl", []):
            if s.get("kind") != "drive" or "x0" not in s:
                continue
            if abs(s["x0"] - s.get("x1", s["x0"])) < 1e-9 and abs(s["y0"] - s.get("y1", s["y0"])) < 1e-9:
                continue                                   # a zero-length leg is not a moving path
            segs.append((v, (float(s["x0"]), float(s["y0"])), (float(s["x1"]), float(s["y1"])),
                         float(s["t0"]), float(s["t1"])))
    n = 0
    for i in range(len(segs)):
        vi, ai0, ai1, a0, a1 = segs[i]
        for j in range(i + 1, len(segs)):
            vj, bj0, bj1, b0, b1 = segs[j]
            if vi != vj and a0 < b1 and b0 < a1 and _seg_seg_min_dist(ai0, ai1, bj0, bj1) < proximity_m:
                n += 1                                     # different vehicles, overlapping time, paths near
    return n


def _resolve_spacetime_crowding(per_vehicle, *, proximity_m: float = 10.0, max_iter: int = 64):
    """FL-02 re-sequencing: RESOLVE the space-time crowding the detectors surface, not just count it. Two
    vehicles that would work within ``proximity_m`` at overlapping times (the `_temporal_conflicts` class)
    or whose moving haul paths pass that close at overlapping times (`_haul_path_conflicts`) are
    deconflicted by the SAME FCFS discipline as the shared charger (`_resolve_charger_queue`): the lower
    vehicle index keeps its slot and the HIGHER index (the loser) WAITS until the winner's conflicting span
    clears -- a real re-sequence of when the loser does that work. The geometry is fixed; only the time
    window shifts, so a wait that pushes the loser's window past the winner's removes the overlap.

    Iterated to a fixed point: priority = vehicle index (lower wins), so lower indices never move and a
    higher index's delay only grows, bounded by the winners' span lengths -> it converges (a few passes for
    a real 2-4 rover fleet). Spans are selected to MATCH the two detectors exactly, so applying the returned
    delays drives both `_temporal_conflicts` and `_haul_path_conflicts` to 0. Returns the per-vehicle delay
    [s]; a vehicle's real finish is ``time_s + delay[v]``, folded into the makespan exactly like the
    charger/resource waits. No crowding -> all-zero delays -> byte-identical to the un-resequenced fleet.
    CONSERVATIVE (each loser yields to every lower-index crowder; the whole later timeline shifts by the
    wait); optimal JOINT re-ordering across the fleet remains future MV work."""
    n = len(per_vehicle)
    delay = [0.0] * n
    stat: list[tuple[int, float, float, float, float]] = []   # (v, x, y, t0, t1) stationary work spans
    move: list[tuple[int, tuple[float, float], tuple[float, float], float, float]] = []  # moving drive legs
    for v, pv in enumerate(per_vehicle):
        for s in pv.get("tl", []):
            if "x0" not in s or s.get("kind") == "charge":
                continue
            x0, y0 = float(s["x0"]), float(s["y0"])
            x1, y1 = float(s.get("x1", x0)), float(s.get("y1", y0))
            t0, t1 = float(s["t0"]), float(s["t1"])
            if abs(x0 - x1) < 1e-9 and abs(y0 - y1) < 1e-9:           # stationary -> _temporal_conflicts class
                stat.append((v, x0, y0, t0, t1))
            elif s.get("kind") == "drive":                           # moving drive leg -> _haul_path class
                move.append((v, (x0, y0), (x1, y1), t0, t1))
    # each geometry-close crowding pair as (winner_idx, loser_idx, winner_t0, winner_t1, loser_t0, loser_t1)
    # with ORIGINAL (un-delayed) windows; only vi < vj (lower index wins). Resolution pushes the loser's
    # effective start past the winner's effective end whenever their delayed windows still overlap.
    pairs: list[tuple[int, int, float, float, float, float]] = []
    for i in range(len(stat)):
        vi, xi, yi, ai0, ai1 = stat[i]
        for j in range(len(stat)):
            vj, xj, yj, aj0, aj1 = stat[j]
            if vi < vj and math.hypot(xi - xj, yi - yj) < proximity_m:
                pairs.append((vi, vj, ai0, ai1, aj0, aj1))
    for i in range(len(move)):
        vi, pi0, pi1, ti0, ti1 = move[i]          # distinct names from the stat loop (those ai0/ai1 are floats)
        for j in range(len(move)):
            vj, pj0, pj1, tj0, tj1 = move[j]
            if vi < vj and _seg_seg_min_dist(pi0, pi1, pj0, pj1) < proximity_m:
                pairs.append((vi, vj, ti0, ti1, tj0, tj1))
    if not pairs:
        return delay
    for _ in range(max_iter):
        new_delay = list(delay)
        for vi, vj, wt0, wt1, lt0, lt1 in pairs:
            wi0, wi1 = wt0 + delay[vi], wt1 + delay[vi]              # winner's effective window
            lj0, lj1 = lt0 + delay[vj], lt1 + delay[vj]             # loser's effective window
            if wi0 < lj1 and lj0 < wi1:                             # windows still overlap -> re-sequence
                need = wi1 - lj0                                    # push the loser past the winner's end
                if need > 0:
                    new_delay[vj] = max(new_delay[vj], delay[vj] + need)
        if new_delay == delay:
            break
        delay = new_delay
    return delay


def _rover_health(pv) -> dict:
    """FL-04: distill one rover's belief/health/resource state from its battery-aware sim -- feasibility,
    the LOWEST battery SoC fraction it reaches (the resource margin), its recharge count, and a health
    rollup (stranded / low_margin / nominal). The fleet 'coordinates replans' off this: a stranded rover
    sets fleet_needs_replan so its remaining work can be reallocated (the reallocation itself is future MV
    work; this is the per-rover state + the trigger)."""
    core = pv.get("core", {})
    tl = pv.get("tl", [])
    batts = [s["batt1"] for s in tl if "batt1" in s]
    full = max((s["batt0"] for s in tl if "batt0" in s), default=0.0)
    min_frac = (min(batts) / full) if (batts and full > 1e-9) else 1.0
    stranded = not core.get("feasible", True)
    health = "stranded" if stranded else ("low_margin" if min_frac < 0.15 else "nominal")
    return {"feasible": bool(core.get("feasible", True)), "min_batt_frac": round(float(min_frac), 3),
            "charges": int(core.get("charges", 0)), "health": health,
            "infeasible_reasons": list(core.get("infeasible_reasons", []))[:3]}
