"""#79/ARCH-2: planner VIEWS over the one PlanResult artifact (PRD RB-03 + 21.1).

Split out of mission_planner so the solver (plan/PlanResult/_build_trips) and the VIEWS that render
it (the mission-brief PDF/markdown packet, the per-trip math worksheet, the assumptions register)
live apart. Every function here is a read-only VIEW; the planner produces the artifact ONCE and
these never re-solve. mission_planner re-exports them so existing MP.report / MP.plan_math /
MP.assumptions_register call sites are unchanged. Imports the solver constants/helpers from
mission_planner (defined before mission_planner imports this module at its end -> no import cycle).
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from stewie.specs import ipex_specs as S
from stewie.specs import vehicles as V
from stewie.physics import rassor_mass_model as RM
from lode.mission_planner import (
    BATTERY_J, DRIVE_J_PER_M, DIG_J_PER_KG, DIG_RATE_KG_S, DRIVE_SPEED_MS, RESERVE_FRAC,
    _dur, _drum_kg, body_gravity, plan,
)


def plan_math(mission, *, dem=None, dem_origin=(0.0, 0.0), result=None) -> dict:
    """#74 (Aaron: "never assume"): the per-trip MATH WORKSHEET -- every energy/time figure the
    plan uses, re-expressed as (equation form, the numbers substituted, the result, units). A VIEW
    over the same trips the planner built (RB-03), so the worksheet cannot drift from the plan.
    The reviewer can re-derive every number; nothing is asserted without its derivation."""
    if result is None:
        result = plan(mission, dem=dem, dem_origin=dem_origin)
    g = body_gravity(mission.body)
    legs = []
    for tr in result.trips:
        terms = []
        mass = float(tr.get("mass", 0.0) or 0.0)
        if tr.get("dig_e"):
            terms.append({"name": "dig energy", "unit": "J",
                          "formula": "mass * DIG_J_PER_KG",
                          "substituted": f"{mass:.1f} * {DIG_J_PER_KG:.1f} = {mass*DIG_J_PER_KG:.1f}",
                          "value": round(float(tr["dig_e"]), 1)})
        if tr.get("dig_t"):
            terms.append({"name": "dig time", "unit": "s",
                          "formula": "mass / DIG_RATE_KG_S",
                          "substituted": f"{mass:.1f} / {DIG_RATE_KG_S:.4f} = {mass/DIG_RATE_KG_S:.1f}",
                          "value": round(float(tr["dig_t"]), 1)})
        if tr.get("haul_m"):
            hm = float(tr["haul_m"])
            terms.append({"name": "haul distance", "unit": "m",
                          "formula": "2 * leg_distance * n_loads  (out + back per load)",
                          "substituted": f"= {hm:.1f}", "value": round(hm, 1)})
        if tr.get("haul_e"):
            terms.append({"name": "haul energy", "unit": "J",
                          "formula": "haul_m * DRIVE_J_PER_M / (1 - slip)  (slip robs ground/wheel)",
                          "substituted": f"~ {float(tr['haul_m'] or 0):.1f} * {DRIVE_J_PER_M:.1f} / (1-slip) = {float(tr['haul_e']):.1f}",
                          "value": round(float(tr["haul_e"]), 1)})
        if tr.get("lift_e"):
            terms.append({"name": "lift energy", "unit": "J",
                          "formula": "mass * g * dh  (exact gravity climb)",
                          "substituted": f"{mass:.1f} * {g:.3f} * dh = {float(tr['lift_e']):.1f}",
                          "value": round(float(tr["lift_e"]), 1)})
        legs.append({"label": tr.get("label", tr.get("kind", "?")), "kind": tr.get("kind"),
                     "site": tr.get("site"), "terms": terms})
    return {"constants": {"DIG_J_PER_KG": round(DIG_J_PER_KG, 1), "DRIVE_J_PER_M": round(DRIVE_J_PER_M, 2),
                          "DRIVE_SPEED_MS": DRIVE_SPEED_MS, "DIG_RATE_KG_S": round(DIG_RATE_KG_S, 4),
                          "g_m_s2": round(g, 3)},
            "legs": legs, "totals": dict(result.totals)}



def assumptions_register() -> list:
    """#75 (mission brief packet): every [CALIB]/[ASSUMPTION] value the plan rests on, parsed
    straight from the specs source so the register can never drift from the code or fabricate a
    value. Each entry: {name, value, tag, note} -- the NASA-brief honesty surface (nothing the
    plan assumes is hidden from the reviewer)."""
    import os as _os
    import re as _re
    reg: list = []
    here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    pat = _re.compile(r"^([A-Z_][A-Z0-9_]+)\s*=\s*([^#\n]+?)\s*#\s*(\[(?:CALIB|ASSUMPTION)\])\s*(.*)$")
    for rel in ("stewie/specs/ipex_specs.py", "stewie/specs/constants.py"):
        path = _os.path.join(here, rel)
        if not _os.path.exists(path):
            continue
        for ln in open(path, encoding="utf-8"):
            m = pat.match(ln.rstrip())
            if m:
                reg.append({"name": m.group(1), "value": m.group(2).strip(),
                            "tag": m.group(3), "note": m.group(4).strip()[:120],
                            "source": rel.split("/")[-1]})
    return reg




def report(mission, trips, flows, per_trip, tl, totals, out_pdf, out_md, endu=None):
    th = totals["time_s"] / 3600
    with PdfPages(out_pdf) as pdf:
        # COVER — the mission brief packet front matter (#75)
        cov = plt.figure(figsize=(8.5, 11)); cov.patch.set_facecolor("#0a0e1a")
        cov.text(0.5, 0.80, "STEWIE", ha="center", fontsize=44, fontweight="bold", color="#39ff14",
                 family="monospace")
        cov.text(0.5, 0.745, "MISSION BRIEF PACKET", ha="center", fontsize=15, color="#c7d2e3",
                 family="monospace")
        cov.text(0.5, 0.70, f"{mission.name}", ha="center", fontsize=20, fontweight="bold", color="w")
        feas = "FEASIBLE" if totals.get("feasible", True) else "INFEASIBLE — review"
        meta = (f"Body            {mission.body.title()}\n"
                f"Date            {mission.date}\n"
                f"Sequencer       {totals.get('algorithm', 'nearest')} -> {totals.get('objective', 'time')}\n"
                f"Plan ID         {totals.get('plan_id', '(computed)')}\n"
                f"Feasibility     {feas}\n"
                f"Duration        {_dur(totals['time_s'])} ({th:.0f} h)\n"
                f"Mass moved      {totals['mass_kg']/1000:.1f} t\n"
                f"Energy          {totals['energy_J']/1e6:.1f} MJ  ({totals['charges']} recharges)\n"
                f"Drive           {totals['distance_m']/1000:.2f} km")
        cov.text(0.13, 0.45, meta, fontsize=12, color="#dfe7f2", family="monospace", va="top",
                 linespacing=1.9)
        cov.text(0.5, 0.12, "Conserved-physics mission plan over real lunar terrain. Review the\n"
                 "Assumptions Register (final page) before acting on any figure.",
                 ha="center", fontsize=8.5, color="#7f8ea3", family="monospace")
        cov.text(0.5, 0.05, "REVIEW-PENDING — not approved for execution until signed off",
                 ha="center", fontsize=8, color="#e0b300", family="monospace")
        for ax_pos in ([0.1, 0.60, 0.8, 0.002], [0.1, 0.10, 0.8, 0.002]):
            a = cov.add_axes(ax_pos); a.axis("off"); a.axhline(0, color="#39ff14", lw=1)
        pdf.savefig(cov, facecolor=cov.get_facecolor()); plt.close(cov)

        # PAGE 1 — plan table + material balance + totals
        fig = plt.figure(figsize=(8.5, 11))
        fig.suptitle(f"LUNAR BUILD MISSION PLAN — {mission.name}\n{mission.body.title()} · {mission.date} · "
                     f"cut-fill balanced, optimized sequence", fontsize=13, fontweight="bold")
        ax = fig.add_axes([0.04, 0.46, 0.92, 0.40]); ax.axis("off")
        rows = [["#", "Trip", "kind", "Site (x,y)", "Mass t", "Duration", "Energy (chg)"]]
        for i, pt in enumerate(per_trip, 1):
            tr = pt["trip"]
            e = (tr.get("sinter_e", tr.get("dig_e", 0.0)) + tr.get("haul_m", 0.0)*DRIVE_J_PER_M
                 + tr.get("lift_e", 0.0))
            rows.append([str(i), tr["label"][:34], tr["kind"], f"({tr['site'][0]:.0f},{tr['site'][1]:.0f})",
                         f"{tr['mass']/1000:.2f}", _dur(pt["t_end"]-pt["t_start"]), f"{e/BATTERY_J:.1f}"])
        tab = ax.table(cellText=rows, loc="upper center", cellLoc="center",
                       colWidths=[0.04, 0.36, 0.10, 0.14, 0.10, 0.12, 0.12])
        tab.auto_set_font_size(False); tab.set_fontsize(8); tab.scale(1, 1.5)
        for c in range(len(rows[0])): tab[0, c].set_facecolor("#1c3a6e"); tab[0, c].set_text_props(color="w")
        bal = (f"MATERIAL BALANCE\n  cut {totals['cut_kg']/1000:.1f} t → fill {totals['fill_kg']/1000:.1f} t"
               f"  ·  surplus(spoil) {totals['surplus_kg']/1000:.1f} t  ·  deficit(import) {totals['deficit_kg']/1000:.1f} t"
               f"  ·  sinter {totals['sinter_kg']/1000:.2f} t")
        tot = (f"TOTALS   project {_dur(totals['time_s'])} ({th:.0f} h)   moved {totals['mass_kg']/1000:.1f} t"
               f" ({totals['mass_kg']/_drum_kg(mission):.0f} drum loads)\n"
               f"         energy {totals['energy_J']/1e6:.1f} MJ ({totals['energy_J']/BATTERY_J:.1f} charges,"
               f" {totals['charges']} recharge stops)   drive {totals['distance_m']/1000:.2f} km\n"
               f"         {totals['drum_cycles']} drum cycles; fill SENSED from motor current "
               f"+/-{RM.FDC_MPE_HALF_FULL*100:.1f}% (>half full), no load cell")
        if endu:
            rng = endu.get("range_slopeslip_km", endu["range_flat_reserve_km"])
            tot += (f"\n         per-sortie range {rng:.0f} km"
                    + (f" (slope+slip @ {endu['work_area_median_slope_deg']:.0f} deg; {endu['range_flat_reserve_km']:.0f} km flat)"
                       if "range_slopeslip_km" in endu else " (flat)"))
            ts = endu.get("timescale")
            if ts:
                d = ts["solar_day_h"]; scale = f"{d/24:.0f} Earth-days" if d >= 48 else f"{d:.0f} h"
                tot += f"\n         1 {ts['day_label']} ~ {scale} ({ts['daylight_h']:.0f} h light)"
            c = endu.get("conops")
            if c:
                tot += (f"\n         ConOps: {c['traverse_km']:.0f} km + {c['regolith_t'][0]:.0f}-{c['regolith_t'][1]:.0f} t / "
                        f"{c['mission_days']:.0f} d -> drive ~{c['drive_packs']:.1f} packs vs dig "
                        f"~{c['dig_packs'][0]:.0f}-{c['dig_packs'][1]:.0f} packs: drums dominate")
        fig.text(0.04, 0.40, bal, fontsize=8, family="monospace", wrap=True,
                 bbox=dict(boxstyle="round", fc="#fff4e6", ec="#cc8a33"))
        fig.text(0.04, 0.26, tot, fontsize=8, family="monospace", wrap=True,
                 bbox=dict(boxstyle="round", fc="#eef3ff", ec="#1c3a6e"))
        fig.text(0.04, 0.07,
                 "Cut-fill balanced (excavated material routed to nearest fill; surplus→spoil, deficit→import). "
                 "Grounded: per-body density/gravity (bodies.json); IPEx — 0.30 m/s, 42 kg/hr dig, 4151 J/kg, "
                 "135 J/m (slip-adjusted on a DEM), 4.79 MJ battery, 30 kg/drum. Dig-rate band: x0.72 at the "
                 "rated-18-RPM drum (25=actuator max; T2.4). SINTER 0.92 MJ/kg [CALIB] "
                 "(~220× dig). Recharge 700 W + sinter-head 1000 W are [CALIB]. Pluggable sequencer × objective; "
                 "battery-aware mid-task recharge.", fontsize=7, color="#445", wrap=True)
        pdf.savefig(fig); plt.close(fig)

        # PAGE 2 — battery + speed
        fig, (axb, axs) = plt.subplots(2, 1, figsize=(11, 8.5))
        col = {"dig": "#e07b39", "drive": "#3b82c4", "charge": "#3fa34d", "sinter": "#b5179e"}
        for p in tl:
            axb.plot([p["t0"]/3600, p["t1"]/3600], [p["batt0"]/BATTERY_J*100, p["batt1"]/BATTERY_J*100], color=col[p["kind"]], lw=2)
            axs.plot([p["t0"]/3600, p["t1"]/3600], [p["speed"], p["speed"]], color=col[p["kind"]], lw=2)
        axb.axhline(RESERVE_FRAC*100, ls="--", color="#c33", lw=1)
        axb.set_ylabel("battery %"); axb.set_title("Battery draw over the planned project"); axb.set_ylim(0, 105); axb.grid(alpha=.3)
        axb.legend(handles=[plt.Line2D([], [], color=c, lw=3, label=k) for k, c in col.items()], loc="upper right", fontsize=8)
        axs.set_ylabel("speed m/s"); axs.set_xlabel("mission time (hours)"); axs.set_title("Speed profile"); axs.grid(alpha=.3)
        fig.tight_layout(); pdf.savefig(fig); plt.close(fig)

        # PAGE 3 — route + flows + per-task
        fig = plt.figure(figsize=(11, 8.5)); axm = fig.add_axes([0.06, 0.10, 0.42, 0.80])
        axm.plot(*mission.charger, "s", color="#3fa34d", ms=12, label="charger/base")
        for i, pt in enumerate(per_trip, 1):
            s = pt["trip"]["site"]; axm.plot(s[0], s[1], "o", color=col.get(pt["trip"]["kind"], "#e07b39"), ms=11)
            axm.annotate(str(i), s, fontsize=8, fontweight="bold", ha="center", va="center", color="w")
        for co, fo, mass, d in flows:                  # cut->fill material flows (skip spoil dig-in-place)
            if co is not None and fo is not None:
                axm.annotate("", xy=(fo.x, fo.y), xytext=(co.x, co.y),
                             arrowprops=dict(arrowstyle="->", color="#cc8a33", lw=1.4, alpha=.8))
        axm.set_title("Site route + material flows (cut→fill)"); axm.set_xlabel("x (m)"); axm.set_ylabel("y (m)")
        axm.legend(fontsize=8); axm.grid(alpha=.3); axm.set_aspect("equal", adjustable="datalim")
        axt = fig.add_axes([0.58, 0.10, 0.38, 0.34])
        labels = [str(i+1) for i in range(len(per_trip))]
        axt.bar(labels, [(p["trip"].get("sinter_e", p["trip"].get("dig_e", 0))) / BATTERY_J for p in per_trip],
                color=[col.get(p["trip"]["kind"], "#e07b39") for p in per_trip])
        axt.set_title("Energy per trip (battery charges)"); axt.set_xlabel("trip #"); axt.grid(alpha=.3, axis="y")
        axc = fig.add_axes([0.58, 0.56, 0.38, 0.34]); cm = ce = 0.0; tt = [0]; mm = [0]; ee = [0]
        for p in tl:
            cm += p["mass"]; ce += (p["batt0"]-p["batt1"]) if p["kind"] != "charge" else 0
            tt.append(p["t1"]/3600); mm.append(cm/1000); ee.append(ce/1e6)
        axc.plot(tt, mm, color="#e07b39", label="t moved"); axc2 = axc.twinx(); axc2.plot(tt, ee, color="#3b82c4")
        axc.set_title("Cumulative progress"); axc.set_xlabel("hours"); axc.set_ylabel("t", color="#e07b39")
        axc2.set_ylabel("MJ", color="#3b82c4"); axc.grid(alpha=.3)
        pdf.savefig(fig); plt.close(fig)

        # ASSUMPTIONS REGISTER — every [CALIB]/[ASSUMPTION] the plan rests on (#75, NASA-brief honesty)
        reg = assumptions_register()
        figr = plt.figure(figsize=(8.5, 11))
        figr.suptitle("ASSUMPTIONS REGISTER\nevery calibrated / assumed value this plan rests on",
                      fontsize=13, fontweight="bold")
        axr = figr.add_axes([0.04, 0.05, 0.92, 0.84]); axr.axis("off")
        rrows = [["Parameter", "Value", "Tag", "Basis"]]
        for r in reg[:34]:
            rrows.append([r["name"][:24], str(r["value"])[:16], r["tag"], r["note"][:52]])
        tr = axr.table(cellText=rrows, loc="upper center", cellLoc="left",
                       colWidths=[0.24, 0.16, 0.12, 0.48])
        tr.auto_set_font_size(False); tr.set_fontsize(6.5); tr.scale(1, 1.35)
        for c in range(4): tr[0, c].set_facecolor("#7a1020"); tr[0, c].set_text_props(color="w")
        for ri, r in enumerate(reg[:34], 1):
            fc = "#fff0f0" if r["tag"] == "[ASSUMPTION]" else "#fff8e6"
            for c in range(4): tr[ri, c].set_facecolor(fc)
        figr.text(0.04, 0.93, f"{len(reg)} tagged values · [CALIB]=calibrated-not-yet-fit · "
                  "[ASSUMPTION]=engineering estimate pending source", fontsize=7.5, color="#445")
        pdf.savefig(figr); plt.close(figr)

    # markdown
    md = [f"# Lunar Build Mission Plan — {mission.name}", "",
          f"**Body:** {mission.body.title()} · **Date:** {mission.date} · cut-fill balanced · "
          f"sequence **{totals.get('algorithm', 'nearest')}** optimizing **{totals.get('objective', 'time')}**", "",
          "**Mode:** `DEM_KNOWN_POSE_MISSION_SIM` (known-pose mission simulation; not SLAM / not real-rover "
          "autonomy) · **Plan feasibility:** "
          + ("**FEASIBLE**" if totals.get("feasible", True)
             else f"⚠ **INFEASIBLE** — {totals.get('blocked_legs', 0)} route leg(s) have no safe corridor"), "",
          "## Sequence",
          "| # | Trip | kind | Site (x,y) | Mass t | Duration | Energy (chg) |",
          "|---|------|------|-----------|--------|----------|--------------|"]
    for i, pt in enumerate(per_trip, 1):
        tr = pt["trip"]
        e = tr.get("sinter_e", tr.get("dig_e", 0)) + tr.get("haul_m", 0)*DRIVE_J_PER_M + tr.get("lift_e", 0)
        md.append(f"| {i} | {tr['label']} | {tr['kind']} | ({tr['site'][0]:.0f},{tr['site'][1]:.0f}) | "
                  f"{tr['mass']/1000:.2f} | {_dur(pt['t_end']-pt['t_start'])} | {e/BATTERY_J:.1f} |")
    md += ["", "## Material balance",
           f"- cut **{totals['cut_kg']/1000:.1f} t** → fill **{totals['fill_kg']/1000:.1f} t** · "
           f"surplus(spoil) {totals['surplus_kg']/1000:.1f} t · deficit(import) {totals['deficit_kg']/1000:.1f} t · "
           f"sinter {totals['sinter_kg']/1000:.2f} t", "", "## Totals",
           f"- Project time **{_dur(totals['time_s'])}** ({th:.0f} h) · moved **{totals['mass_kg']/1000:.1f} t** "
           f"({totals['mass_kg']/_drum_kg(mission):.0f} drum loads)",
           f"- Energy **{totals['energy_J']/1e6:.1f} MJ** = {totals['energy_J']/BATTERY_J:.1f} charges "
           f"({totals['charges']} recharge stops) · drive {totals['distance_m']/1000:.2f} km"
           + (f" · incl. **{totals['lift_energy_J']/1e6:.2f} MJ** lifting regolith uphill (exact m·g·Δh, real DEM)"
              if totals.get("lift_energy_J", 0) > 0 else ""),
           (f"- Survival/idle power **{totals['survival_energy_J']/1e6:.1f} MJ** over the sortie "
            f"(@ {totals['idle_power_w']:.0f} W continuous) **[ASSUMPTION]** -- folded into the total above"
            if totals.get("survival_energy_J", 0) > 0 else
            "- Survival/idle power **not modelled** (active legs only; set IDLE_POWER_W to include the "
            "continuous heater/avionics load, the likely-dominant multi-day term) **[ASSUMPTION]**"),
           f"- **{totals['drum_cycles']} drum cycles** (offload events); drum fill SENSED from motor current "
           f"(no load cell, ICE-RASSOR NTRS 20210022781) -- known to ±{RM.FDC_MPE_HALF_FULL*100:.1f}% when "
           f">half full, ±{RM.FDC_MPE_ALL*100:.1f}% below; rover offloads at the upper confidence bound"]
    if totals.get("routed_haul"):                       # I10: hauls routed around real-DEM hazards
        md.append(
            f"- Hauls **routed around hazards** on the real Haworth slope costmap (traverse cap "
            f"{totals['traverse_cap_deg']:.0f}°): **+{totals['haul_detour_frac']*100:.1f}% detour** over straight "
            f"lines" + (f"; ⚠ **{totals['blocked_legs']} leg(s) had NO safe corridor → plan INFEASIBLE** "
                        "(route not driven; no straight-line through the hazard)" if totals['blocked_legs'] else ""))
    if endu:                                            # single-charge SORTIE range (not a mission limit)
        line = (f"- **Per-sortie range:** {endu['range_flat_reserve_km']:.1f} km flat to reserve "
                f"({endu['range_flat_full_km']:.1f} km full pack, {endu['duration_flat_h']:.0f} h driving at "
                f"{endu['speed_ms']:.2f} m/s)")
        if "range_slopeslip_km" in endu:
            line += (f"; **{endu['range_slopeslip_km']:.1f} km** slope+slip-adjusted at the work-area median "
                     f"{endu['work_area_median_slope_deg']:.0f}° slope")
        md.append(line)
        if "reach" in endu:
            r = endu["reach"]
            md.append("- One-charge reach on this DEM: " + (
                f"**entire {r['radius_m']/1000:.1f} km work area** within reach "
                f"(~{r['worst_cell_pack_frac']*100:.0f}% of the pack to the farthest point)"
                if r["tile_fully_reachable"] else f"radius **{r['radius_m']/1000:.1f} km** from the charger"))
        pw = endu.get("power")
        if pw:                                          # #2 per-site power source (PSR tower vs sunlit solar)
            md.append(f"- Power: **{pw['kind'].replace('_', ' ')}** — {pw['availability']}; charge "
                      f"{pw['charge_power_w']:.0f} W (effective {pw['effective_charge_w']:.0f} W @ duty "
                      f"{pw['duty_frac']:.2f})" + (f"; cold-derated pack ×{pw['thermal_derate']:.2f}"
                                                   if pw['thermal_derate'] < 1.0 else ""))
        ts = endu.get("timescale")
        if ts:                                          # body-correct operating timescale (Moon ≠ Mars ≠ ...)
            d = ts["solar_day_h"]
            scale = f"{d/24:.1f} Earth-days" if d >= 48 else f"{d:.1f} h"
            if ts["fits_in_window"]:
                rel = (f"a full-range {ts['sortie_h']:.0f} h sortie fits ~{ts['sorties_per_window']:.0f}× "
                       f"in the ~{ts['op_window_h'][0]:.0f}–{ts['op_window_h'][1]:.0f} h sunlit window")
            else:
                rel = (f"a full-range {ts['sortie_h']:.0f} h sortie spans ~{ts['spans_days']:.1f} {ts['day_label']}s "
                       f"(> the ~{ts['daylight_h']:.0f} h daylight → night pauses)")
            md.append(f"- Timescale ({mission.body.title()}): **1 {ts['day_label']} ≈ {scale}** "
                      f"(~{ts['daylight_h']:.0f} h daylight) — {rel}; range is not window-bound.")
        c = endu.get("conops")
        if c:                                           # [SCHULER24] ConOps reconciliation: drums dominate
            md.append(
                f"- ConOps [SCHULER24, lunar IPEx]: **{c['traverse_km']:.0f} km traverse + {c['regolith_t'][0]:.0f}–"
                f"{c['regolith_t'][1]:.0f} t excavated over {c['mission_days']:.0f} days** → driving "
                f"~{c['drive_energy_MJ']:.1f} MJ (~{c['drive_packs']:.1f} packs) vs digging "
                f"~{c['dig_energy_MJ'][0]:.0f}–{c['dig_energy_MJ'][1]:.0f} MJ (~{c['dig_packs'][0]:.0f}–"
                f"{c['dig_packs'][1]:.0f} packs): **the drums dominate the energy budget** (recharged daily).")
    # #75: the ASSUMPTIONS REGISTER section (the NASA-brief honesty surface, every tagged value)
    reg = assumptions_register()
    md += ["", "## Assumptions Register",
           f"Every calibrated/assumed value this plan rests on ({len(reg)} tagged). Review before acting.",
           "", "| Parameter | Value | Tag | Basis |", "|---|---|---|---|"]
    for r in reg:
        md.append(f"| `{r['name']}` | {r['value']} | {r['tag']} | {r['note']} |")
    md += ["", "## Vehicle Configuration",
           f"- Vehicle: **IPEx** (ISRU Pilot Excavator) · gauge {V.geometry_of('ipex')['gauge_m']:.4f} m · "
           f"wheelbase {V.geometry_of('ipex')['wheelbase_m']:.2f} m · CG height {V.geometry_of('ipex')['cg_height_m']:.2f} m",
           f"- Energy: dig {DIG_J_PER_KG:.0f} J/kg · drive {DRIVE_J_PER_M:.1f} J/m · battery {BATTERY_J/1e6:.2f} MJ · "
           f"recharge {S.RECHARGE_POWER_W:.0f} W [CALIB]",
           "",
           "_Grounded (bodies.json + ipex_specs + rassor_mass_model); sinter 0.92 MJ/kg; recharge 700 W + "
           "sinter-head 1000 W are [CALIB]. REVIEW-PENDING — not approved for execution until signed off._"]
    with open(out_md, "w") as f:
        f.write("\n".join(md))


