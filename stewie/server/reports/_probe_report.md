# Lunar Build Mission Plan — South-Pole Site Development

**Body:** Moon · **Date:** 2026-06-03 · cut-fill balanced · sequence **nearest** optimizing **time**

## Sequence
| # | Trip | kind | Site (x,y) | Mass t | Duration | Energy (chg) |
|---|------|------|-----------|--------|----------|--------------|
| 1 | Grade access road → Fill crater dip | cutfill | (15,5) | 0.83 | 22.2 h | 0.8 |
| 2 | Excavate spoil: Grade access road | dig | (15,5) | 0.32 | 9.4 h | 0.3 |
| 3 | Level landing pad → Build blast berm | cutfill | (40,30) | 1.82 | 46.3 h | 1.6 |
| 4 | Excavate spoil: Level landing pad | dig | (40,30) | 0.94 | 24.3 h | 0.8 |

## Material balance
- cut **3.9 t** → fill **2.7 t** · surplus(spoil) 1.3 t · deficit(import) 0.0 t · sinter 0.00 t

## Totals
- Project time **4.3 d** (102 h) · moved **3.9 t** (131 drum loads)
- Energy **16.8 MJ** = 3.5 charges (3 recharge stops) · drive 4.09 km · incl. **0.00 MJ** lifting regolith uphill (exact m·g·Δh, real DEM)
- Survival/idle power **not modelled** (active legs only; set IDLE_POWER_W to include the continuous heater/avionics load, the likely-dominant multi-day term) **[ASSUMPTION]**
- **89 drum cycles** (offload events); drum fill SENSED from motor current (no load cell, ICE-RASSOR NTRS 20210022781) -- known to ±2.6% when >half full, ±7.4% below; rover offloads at the upper confidence bound
- Hauls **routed around hazards** on the real Haworth slope costmap (traverse cap 25°): **+4.4% detour** over straight lines
- **Per-sortie range:** 32.1 km flat to reserve (35.6 km full pack, 30 h driving at 0.30 m/s); **25.1 km** slope+slip-adjusted at the work-area median 17° slope
- One-charge reach on this DEM: **entire 9.0 km work area** within reach (~37% of the pack to the farthest point)
- Power: **psr tower** — anytime (lander/tower budget; a PSR has no sun); charge 700 W (effective 700 W @ duty 1.00)
- Timescale (Moon): **1 lunar day ≈ 29.5 Earth-days** (~354 h daylight) — a full-range 30 h sortie fits ~7× in the ~216–264 h sunlit window; range is not window-bound.
- ConOps [SCHULER24, lunar IPEx]: **70 km traverse + 5–10 t excavated over 11 days** → driving ~9.4 MJ (~2.0 packs) vs digging ~21–42 MJ (~4–9 packs): **the drums dominate the energy budget** (recharged daily).

_Grounded (bodies.json + ipex_specs + rassor_mass_model); sinter 0.92 MJ/kg; recharge 700 W + sinter-head 1000 W are [CALIB]._