# IPEx power model — lunar calibration analysis (2026-06-09)

Analysis of `terrain_authority/ipex_specs.py` power functions for lunar-environment fidelity. Two
independent errors, pulling in **opposite directions**. (Aaron-requested; flagged for John — additive,
John's sourced `drive_power_w`/`dig_power_w` are unchanged.)

## Finding 1 — drive power SEVERELY overestimates lunar steady drive (~9x)
`drive_power_w() = N_WHEELS * DRIVE_MOTOR_TORQUE_NM * omega = 4 * 0.063 Nm * (1530 rpm) = 40.4 W`.
- That is the **Table-3 ConOps motor load** through the 80:1 gearbox → ~132 N tractive force at the
  wheels → a tractive *coefficient* of ~0.45 for a 30 kg rover. That is an **Earth-g / high-load**
  figure (the GMRO/BP-1 testbed is Earth gravity; Table 3 is "loads experienced during ConOps", not
  flagged lunar — unlike Table 7's dig load, which IS "predicted on the moon").
- Steady-drive resistance (rolling + grade) is **gravity-dependent (~ m·g)**. On the Moon (1/6 g) the
  flat-drive draw is ~6x lower. Physical estimate: `F = m·g·(Crr·cosθ + sinθ)`, `P = F·v/η`:
  - flat, lunar g, Crr 0.15, η 0.5 → **4.4 W** (the Earth-test 40 W is **9.2x** too high)
  - 15° lunar slope → **11.8 W**
- Using 40 W as the operational lunar draw overestimates drive energy by ~6-9x. **Fix:**
  `lunar_drive_power_w()` (gravity/slope/Crr physical tractive force). `drive_power_w()` retained as the
  design/worst-case actuator figure. (The rigorous resistance is the terramechanics Bekker motion
  resistance; Crr + η here are tagged estimates.)
- `dig_power_w()` (48.4 W) is **already lunar** (Table 7's 18.5 N·m is published "predicted on the
  moon"); the 25-RPM operational pairing is the standing [CALIB] item, not a gravity error.

## Finding 2 — the model omits the loads that DOMINATE a lunar energy budget
`IDLE_POWER_W = 0` — the model had **no thermal, avionics/CPU, or comms** draw. These continuous loads
dominate a real budget over the 11-day / 70 km mission (housekeeping integrated over days ≫ intermittent
drive/dig). Added as **[ASSUMPTION]** (subsystem watts are not public for IPEx; do not treat as sourced):
- `AVIONICS_POWER_W = 15 W` — flight computer + autonomy compute. *Rationale:* CADRE's autonomy compute
  produces enough heat to force 30-min cooldown shutdowns → non-trivial.
- `COMMS_TX_POWER_W = 15 W` — X-band direct-to-Earth transmit (duty-cycled). *Rationale:* VIPER/CLPS
  X-band DTE.
- `THERMAL_SURVIVAL_POWER_W = 30 W` — heater load; tens-to-hundreds W, PSR/lunar-night much higher.
  *Rationale:* VIPER runs **solar-only heaters** to survive shadow.
- `system_power_w(...)` = lunar drive + dig + avionics + comms + thermal.

## The combined picture
| Case | Old model | Calibrated |
|---|---|---|
| Flat drive (mobility only) | 40.4 W | **4.4 W** (9.2x lower) |
| 15° slope drive | 40.4 W | 11.8 W |
| System, driving flat, idle housekeeping | 40.4 W (drive only; 0 housekeeping) | **49.4 W** (drive 4.4 + avionics 15 + thermal 30) |
| System, drive + dig + comms | — | 112.8 W |

**Housekeeping (45 W) dominates lunar drive (4.4 W).** The old 40 W "drive" was near the right *total*
only by overcounting drive ~9x to stand in for the ~45 W of missing housekeeping — a coincidence that
breaks the moment the rover climbs, digs, transmits, or idles. The calibrated model separates the
gravity-correct [PHYSICS] mobility from the [ASSUMPTION] housekeeping so each can be refined independently.

## Honest limits
- Housekeeping watts are engineering [ASSUMPTION]s, not sourced — refine against an IPEx/VIPER power
  budget when available; thermal is the largest uncertainty (PSR vs lunar-day vs sunlit differ widely).
- `Crr` + drivetrain `η` are tagged estimates; the rigorous drive resistance is the terramechanics
  Bekker motion-resistance already in the core (a future wire-up would replace the constant Crr).
- `drive_power_w()`/`dig_power_w()` (John's [SCHULER24] values) are unchanged; the calibration is additive.
