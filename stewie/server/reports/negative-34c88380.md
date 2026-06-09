# Lunar Build Mission Plan — negative

**Body:** Mars · **Date:** 2026-06-03 · cut-fill balanced · sequence **nearest** optimizing **time**

## Sequence
| # | Trip | kind | Site (x,y) | Mass t | Duration | Energy (chg) |
|---|------|------|-----------|--------|----------|--------------|

## Material balance
- cut **0.0 t** → fill **-0.6 t** · surplus(spoil) 0.0 t · deficit(import) 0.0 t · sinter 0.00 t

## Totals
- Project time **0.0 h** (0 h) · moved **0.0 t** (0 drum loads)
- Energy **0.0 MJ** = 0.0 charges (0 recharge stops) · drive 0.00 km
- Survival/idle power **not modelled** (active legs only; set IDLE_POWER_W to include the continuous heater/avionics load, the likely-dominant multi-day term) **[ASSUMPTION]**
- **0 drum cycles** (offload events); drum fill SENSED from motor current (no load cell, ICE-RASSOR NTRS 20210022781) -- known to ±2.6% when >half full, ±7.4% below; rover offloads at the upper confidence bound
- **Per-sortie range:** 32.1 km flat to reserve (35.6 km full pack, 30 h driving at 0.30 m/s)
- Power: **psr tower** — anytime (lander/tower budget; a PSR has no sun); charge 700 W (effective 700 W @ duty 1.00)
- Timescale (Mars): **1 sol ≈ 24.7 h** (~12 h daylight) — a full-range 30 h sortie spans ~2.4 sols (> the ~12 h daylight → night pauses); range is not window-bound.
- ConOps [SCHULER24, lunar IPEx]: **70 km traverse + 5–10 t excavated over 11 days** → driving ~9.4 MJ (~2.0 packs) vs digging ~21–42 MJ (~4–9 packs): **the drums dominate the energy budget** (recharged daily).

_Grounded (bodies.json + ipex_specs + rassor_mass_model); sinter 0.92 MJ/kg; recharge 700 W + sinter-head 1000 W are [CALIB]._