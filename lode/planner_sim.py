"""ARCH-2 (#123): the battery-aware ordered-trip SIMULATOR, extracted from lode.mission_planner.

_simulate runs an ORDERED trip list against the SELECTED vehicle's energy/speed context (phase-split
recharging, reserve-aware drive, mission-clock windows, partial-credit on strand) and returns
(timeline, per_trip, core). Pure in (mission, trips, routes) so the sequencer can score any candidate
order. A leaf: imports only the planner_model (_d, plan_context), planner_endurance (thermal_derate)
and planner_trips (_window_gate) leaves; it NEVER imports lode.mission_planner, so it introduces no
cycle. mission_planner re-exports _simulate so the sequencer/plan code's unqualified calls stay
byte-identical.
"""
# PROVENANCE: STEWIE LODE subsystem (A. Storey)
from __future__ import annotations

from lode.planner_model import _d, plan_context
from lode.planner_endurance import thermal_derate
from lode.planner_trips import _window_gate


def _simulate(mission, trips, routes=None):
    """Battery-aware simulation of an ORDERED trip list (phase-split recharging; intra-trip haul/lift baked
    into each trip). Pure in (mission, trips, routes) so the optimizer can score any candidate order. H-02:
    when `routes` (from _make_routes) is given the inter-site drive legs use the ROUTED DEM distance -- the
    same geometry the Plan IR executes -- instead of a straight line; None -> straight-line _d (no-DEM).
    Returns (tl, per_trip, core) -- core = the order-dependent metrics."""
    def _rd(a, b):
        return routes(a, b) if routes is not None else _d(a, b)   # H-02: routed inter-site distance
    # H-01: rebind the vehicle-dependent energy/speed names to the SELECTED vehicle's context as locals,
    # so every reference below (and in the nested _leg/charge/drive/spend closures) reads the vehicle's
    # values, not the IPEx module globals. ipex resolves to exactly the globals -> byte-identical.
    ctx = plan_context(mission)
    BATTERY_J = ctx.battery_j
    DRIVE_J_PER_M = ctx.drive_j_per_m
    DRIVE_SPEED_MS = ctx.drive_speed_ms
    CHARGE_W = ctx.charge_w
    RESERVE_FRAC = ctx.reserve_frac
    # EP-05: thermal derating SHRINKS the usable pack on a cold mission (Li-ion cold capacity loss). The
    # whole battery-aware sim (reserve, charge target, reachable work) runs against this derated capacity,
    # so a cold plan genuinely recharges sooner / does fewer sorties. mission.temp_c None -> derate 1.0
    # -> usable_battery_j == BATTERY_J -> byte-identical to an un-temperatured plan (no test drift).
    usable_battery_j = BATTERY_J * thermal_derate(mission.temp_c)
    windows = mission.mission_windows                  # EP-04: action-class mission-clock windows (None -> unconstrained)
    pos = list(mission.charger); batt = usable_battery_j; t = 0.0
    cum_mass = 0.0; cum_energy = 0.0; charges = 0; reserve = RESERVE_FRAC * usable_battery_j
    tl = []; per_trip = []; infeasible = []           # C-04: collected reachability / SoC-floor failures

    def _leg(to):
        """Raw drive leg: append the timeline + draw energy. The caller (drive/charge) has ensured the
        leg fits above reserve, so this never drives SoC below zero."""
        nonlocal pos, batt, t, cum_energy
        d = _rd(pos, to)                                   # H-02: routed inter-site distance (matches Plan IR)
        if d <= 1e-9: return
        e = d * DRIVE_J_PER_M; dur = d / DRIVE_SPEED_MS
        tl.append(dict(t0=t, t1=t+dur, kind="drive", batt0=batt, batt1=batt-e, mass=0.0, speed=DRIVE_SPEED_MS,
                       x0=pos[0], y0=pos[1], x1=to[0], y1=to[1]))   # P5: rover moves pos -> to
        pos = list(to); batt -= e; t += dur; cum_energy += e

    def charge():
        """Return to the charger and refill. C-04: guard the return leg -- the reserve EXISTS so the rover
        can always reach the charger, so the return leg may draw into reserve; it must only never go
        NEGATIVE. If even the full remaining charge can't reach the charger the rover is STRANDED; record
        it and return False (don't drive SoC negative, the caller stops drawing work it can never finish)."""
        nonlocal batt, t, charges
        if _d(pos, mission.charger) > 1e-9 and _rd(pos, mission.charger) * DRIVE_J_PER_M > batt + 1e-6:
            infeasible.append(f"stranded at ({pos[0]:.0f},{pos[1]:.0f}): cannot reach the charger to "
                              "recharge on the remaining charge")
            return False
        _leg(mission.charger)
        # EP-04: solar/power recharge only inside an illumination/power window -- otherwise idle at the
        # charger until the next window opens (a "wait" leg, no energy drawn); if none remains, infeasible.
        start_t, wait_s, reason = _window_gate(windows, "recharge", t)
        if reason is not None:
            infeasible.append(f"recharge at charger: {reason}")
            return False
        if wait_s > 0:
            tl.append(dict(t0=t, t1=start_t, kind="wait", batt0=batt, batt1=batt, mass=0.0, speed=0.0,
                           x0=pos[0], y0=pos[1], x1=pos[0], y1=pos[1]))   # parked, awaiting the recharge window
            t = start_t
        need = usable_battery_j - batt; dur = need / CHARGE_W
        tl.append(dict(t0=t, t1=t+dur, kind="charge", batt0=batt, batt1=usable_battery_j, mass=0.0, speed=0.0,
                       x0=pos[0], y0=pos[1], x1=pos[0], y1=pos[1]))  # parked at charger
        batt = usable_battery_j; t += dur; charges += 1
        return True

    def drive(to):
        """C-04: reserve-aware drive. Returns True when the rover actually reaches `to`, False when the
        leg is infeasible (and skipped + flagged). Driving to a WORK site keeps the reserve margin -- if
        the leg would dip SoC below reserve, recharge first (and if even a full charge can't reach it above
        reserve, the plan is infeasible). Driving HOME may draw into reserve (that is what reserve is for)
        but must never go NEGATIVE -- if the full remaining charge can't reach `to`, the rover is stranded.
        Either way the leg is skipped and flagged rather than run on negative SoC (a prior bug ran the pack
        to ~-14 MJ). P-01: the caller MUST check the return -- a failed transit means NO work happened at
        `to`, so the trip's dig/haul/fill is not credited (the prior bug ran spend() unconditionally)."""
        d = _rd(pos, to)                                  # H-02: routed inter-site distance (matches Plan IR)
        if d <= 1e-9: return True                         # already there (within tol): nothing to drive
        e = d * DRIVE_J_PER_M; usable = usable_battery_j - reserve
        going_home = _d(to, mission.charger) <= 1e-9
        if not going_home and e > batt - reserve:     # to a work site: keep the reserve margin -> recharge
            if _rd(mission.charger, to) * DRIVE_J_PER_M > usable:
                infeasible.append(f"leg to ({to[0]:.0f},{to[1]:.0f}) needs {e / 1e3:.0f} kJ; a full charge "
                                  f"reaches only {usable / 1e3:.0f} kJ above reserve")
                return False
            if not charge():                          # round-trip to the charger, then proceed from full
                return False                          # stranded (infeasible recorded); never drive SoC negative
        if e > batt + 1e-6:                           # can't physically reach `to` even on the full remaining
            infeasible.append(f"stranded at ({pos[0]:.0f},{pos[1]:.0f}): cannot reach ({to[0]:.0f},"
                              f"{to[1]:.0f}) on the remaining {batt / 1e3:.0f} kJ")
            return False
        _leg(to)
        return True

    def spend(kind, total_e, total_dur, work_pos, mass=0.0, speed=0.0, haul_m=0.0, haul_e=None, lift_e=0.0):
        # draw total_e at work_pos, splitting across recharges; haul_e is the haul drive ENERGY (#1
        # slip-adjusted; default flat 135 J/m), haul_m the haul distance (TIME); lift_e the uphill gravity work.
        nonlocal batt, t, cum_mass, cum_energy
        if haul_e is None:
            haul_e = haul_m * DRIVE_J_PER_M
        e = total_e + haul_e + lift_e
        dur = total_dur + (haul_m / DRIVE_SPEED_MS)
        # EP-04: work (dig/offload/sinter) only inside an illumination/thermal window -- idle to the next
        # window before starting; if none remains the work cannot be performed (no mass/energy credited).
        start_t, wait_s, reason = _window_gate(windows, "work", t)
        if reason is not None:
            infeasible.append(f"{kind} at ({work_pos[0]:.0f},{work_pos[1]:.0f}): {reason}")
            return
        if wait_s > 0:
            tl.append(dict(t0=t, t1=start_t, kind="wait", batt0=batt, batt1=batt, mass=0.0, speed=0.0,
                           x0=work_pos[0], y0=work_pos[1], x1=work_pos[0], y1=work_pos[1]))
            t = start_t
        spent = 0.0; completed = True
        while spent < e - 1e-6:
            usable = batt - reserve
            if usable <= 1e-3:
                if not charge():
                    completed = False; break          # C-04: stranded mid-work; stop (infeasible recorded)
                if not drive(work_pos):
                    completed = False; break          # P-01: can't return to the work site -> stop crediting
                continue
            chunk = min(e - spent, usable)
            cd = dur * (chunk / e) if e > 0 else 0.0
            tl.append(dict(t0=t, t1=t+cd, kind=kind, batt0=batt, batt1=batt-chunk,
                           mass=mass*(chunk/e) if e > 0 else 0.0, speed=speed,
                           x0=work_pos[0], y0=work_pos[1], x1=work_pos[0], y1=work_pos[1]))  # working at site
            batt -= chunk; t += cd; spent += chunk
        # P-01: credit only the COMPLETED work fraction. A normally-finished task credits its FULL mass/
        # energy (exact); a task the rover stranded mid-way through (broke out above) credits only the
        # fraction it actually performed -- crediting the full work would over-report what never finished.
        if completed:
            cum_mass += mass; cum_energy += e
        else:
            cum_mass += mass * (spent / e) if e > 1e-9 else 0.0
            cum_energy += spent

    for tr in trips:
        t0 = t
        # EP-04: comms/teleop transit window -- the inter-site drive may only begin inside a "drive" window
        # (e.g. a relay-in-view pass). Idle to the next window; if none remains, the trip is unreachable.
        d_start, d_wait, d_reason = _window_gate(windows, "drive", t)
        if d_reason is not None:
            infeasible.append(f"transit to ({tr['site'][0]:.0f},{tr['site'][1]:.0f}): {d_reason}")
            per_trip.append(dict(trip=tr, t_start=t0, t_end=t)); continue
        if d_wait > 0:
            tl.append(dict(t0=t, t1=d_start, kind="wait", batt0=batt, batt1=batt, mass=0.0, speed=0.0,
                           x0=pos[0], y0=pos[1], x1=pos[0], y1=pos[1]))
            t = d_start
        # P-01: only credit a trip's work if the rover actually REACHED its site. A failed transit
        # (unreachable / stranded; recorded in `infeasible` by drive()) means no work was performed
        # there -- skip spend() entirely so no mass / energy / duration / dig entry is credited for a
        # site never visited (the prior bug ran spend() unconditionally after an infeasible drive).
        if drive(tr["site"]):
            if tr["kind"] == "sinter":
                spend("sinter", tr["sinter_e"], tr["sinter_t"], tr["site"], mass=0.0)
            elif tr["kind"] == "import":
                # P-04: imported fill spends only the OFFLOAD (deposit) energy/time -- NO local dig energy.
                spend("offload", tr.get("offload_e", 0.0), tr.get("offload_t", 0.0), tr["site"],
                      mass=tr["mass"], haul_m=tr.get("haul_m", 0.0), haul_e=tr.get("haul_e"),
                      lift_e=tr.get("lift_e", 0.0))
            else:
                spend("dig", tr["dig_e"], tr["dig_t"], tr["site"], mass=tr["mass"],
                      haul_m=tr.get("haul_m", 0.0), haul_e=tr.get("haul_e"), lift_e=tr.get("lift_e", 0.0))
        per_trip.append(dict(trip=tr, t_start=t0, t_end=t))
    drive(mission.charger)
    # distance_m = inter-site drive legs (timeline speed*dt) + the intra-trip haul shuttle (cut<->fill, baked
    # into each trip as haul_m but NOT a timeline drive leg). Omitting haul_m under-reported total driving
    # ~9x and made the `distance` objective optimize a quantity missing its largest term.
    drive_m = sum((p["t1"]-p["t0"])*p["speed"] for p in tl)
    haul_m = sum(tr.get("haul_m", 0.0) for tr in trips)
    distance_m = drive_m + haul_m
    core = dict(time_s=t, mass_kg=cum_mass, energy_J=cum_energy, charges=charges, distance_m=distance_m,
                avg_power_w=(cum_energy / t if t > 1e-9 else 0.0),
                feasible=(not infeasible), infeasible_reasons=list(infeasible))   # C-04
    return tl, per_trip, core
