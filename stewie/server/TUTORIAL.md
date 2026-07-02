# Stewie Mission Planner — Intern Tutorial (beta)

**Product mode:** `DEM_KNOWN_POSE_MISSION_SIM` — a known-pose mission simulation on a real lunar DEM.
It is **not** SLAM and **not** real-rover autonomy (no sensor-derived localization, no hardware control).

## 1. Install / run from source
```bash
pip install -e .[dev]                # from the repo root (or .[server] for the server only)
STEWIE_DEV_OPEN=1 stewie-serve       # http://127.0.0.1:8770
```
`STEWIE_DEV_OPEN=1` opens the auth-gated POST routes (`/plan`, …) for a **loopback-only** dev
server; without it (or a `STEWIE_API_KEY`) they fail closed. The server loads the real LOLA
Haworth DEM. If the DEM bundle is missing, `/plan` returns `terrain_source: "flat_fallback"` (and
the report says so) — it never silently pretends terrain is flat. `terrain_source: "haworth_dem"`
means the routes/hazards are on the real DEM.

**The DEM is not bundled in the wheel** (it's 16 MB) — it is **fetched + checksum-verified** post-install:
```bash
stewie-fetch-dem --source <mirror-url-or-file://dir>    # or set STEWIE_DEM_URL
```
Source of truth is **PGDA Product 78** (`Haworth_final_adj_5mpp_surf.tif`; Barker et al. 2021). The fetch
verifies each asset's SHA256 against `stewie/server/assets_manifest.json` and **refuses on mismatch** (no
fabricated/corrupt terrain). Running from the repo, the DEM is already present (the fetch is a no-op).

## 2. Load a sample mission
`stewie/server/sample_missions/` ships three deterministic tutorials (also served at `/sample_missions`
and loadable from the cockpit's sample picker in the Plan tab):
1. `01_flatten_pad.json` — cut a high spot, fill a landing pad (feasible).
2. `02_haul_around_hazard.json` — a keep-out straddles the haul line; the route **bends around** it (feasible).
3. `03_blocked_infeasible.json` — the fill site has no safe corridor; the plan is **INFEASIBLE** (failure case).

Load a sample in the cockpit, or POST it to `/plan`:
```bash
curl -X POST http://127.0.0.1:8770/plan -H 'Content-Type: application/json' \
     -d @stewie/server/sample_missions/01_flatten_pad.json
```

## 3. Plan and read the result
`POST /plan` (or the cockpit "Plan mission" button) returns:
- `feasible` + `infeasible_reasons` — the top-level verdict.
- `totals.routes` — the per-leg terrain-following **waypoint polylines** (the 2D canvas draws routed legs
  in green, blocked legs in red dashed).
- `plan_ir` — the executable plan: each `GoTo` carries `waypoints` + `reached`; the IR has `feasible` and
  `mode: DEM_KNOWN_POSE_MISSION_SIM`.
- the PDF/markdown **report** with the mode banner + `Plan feasibility: FEASIBLE / ⚠ INFEASIBLE`.

## 4. Failure handling
Run tutorial 3: `/plan` succeeds (HTTP 200) but the plan is marked **INFEASIBLE** —
`feasible: false` with human-readable `infeasible_reasons` (no safe corridor, battery-infeasible
transit), the blocked leg draws red dashed in the 2D view, and the report header shows
**⚠ INFEASIBLE**. The execution IR is deliberately **suppressed** for an infeasible plan
(`plan_ir.executable: false`, empty `actions`, an explanatory `note`) so an unexecutable plan can
never be handed to an executor. An infeasible plan's energy/distance totals are a straight-line
estimate and must not be executed.

## 5. Run the tests
```bash
pytest lode/test_mission_planner.py stewie/server/test_sample_missions.py -q   # planner round-trip + the tutorials
pytest -q                                                                      # the full configured suite
```

## 6. Exercises (intern)
1. **Move a fill.** Load `01_flatten_pad`, change the fill `x` to 60, Plan. Watch the route length and the
   green polyline change in the 2D canvas + Execute playback.
2. **Add a hazard.** Load `02_haul_around_hazard`, add a second keep-out near the haul line (the "+ Obstacle"
   control), Plan. The green route must bend around both discs; the report's detour % goes up.
3. **Make it infeasible.** Load `03_blocked_infeasible` (or grow a keep-out until it encloses a site), Plan.
   The plan returns HTTP 200 but `feasible: false`: the blocked leg draws red dashed (route not driven), the
   report header shows **⚠ INFEASIBLE**, and the Plan IR is suppressed (`executable: false` + `note`).
4. **Read the executable plan.** Plan a *feasible* mission, download the Plan IR (⤓ Plan IR); confirm each
   `GoTo` carries `waypoints` and the top-level `mode` is `DEM_KNOWN_POSE_MISSION_SIM`.

## 7. Troubleshooting
- **`{"ok": false, "error": "auth not configured..."}` on POST** → the mutating routes fail closed.
  Restart with `STEWIE_DEV_OPEN=1` (loopback dev) or set `STEWIE_API_KEY` and send it in the `X-API-Key` header.
- **`terrain_source: "flat_fallback"`** in the /plan response (or the report) → the real Haworth DEM bundle
  was not found; routes/hazards are NOT trustworthy. Run from the repo (which has `samples/lunar_dem/...`)
  or run `stewie-fetch-dem`. The server never silently pretends terrain is flat — this flag is
  how you know.
- **Plan marked INFEASIBLE** → a route leg has no safe corridor (too steep / keep-out / drop-off). Move the
  site, widen the traverse cap, or remove the blocking obstacle. The straight-line energy/distance on an
  infeasible plan is a don't-care estimate — do not execute it.
- **Server won't start / port busy** → pick another `--port`; check the printed URL.
- **Cesium globe is blank** → the globe needs a real GPU browser; the 2D plan canvas + report work without it.
