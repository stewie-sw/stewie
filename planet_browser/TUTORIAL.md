# Dustgym Mission Planner — Intern Tutorial (beta)

**Product mode:** `DEM_KNOWN_POSE_MISSION_SIM` — a known-pose mission simulation on a real lunar DEM.
It is **not** SLAM and **not** real-rover autonomy (no sensor-derived localization, no hardware control).

## 1. Install / run from source
```bash
VENV=/mnt/projects/07_runtime_system/venv/bin/python
PYTHONPATH=. $VENV -m planet_browser.server --host 0.0.0.0 --port 8770   # open the printed URL
```
The server loads the real LOLA Haworth DEM. If the DEM bundle is missing, `/plan` returns
`terrain_source: "flat_fallback"` (and the report says so) — it never silently pretends terrain is flat.
`terrain_source: "haworth_dem"` means the routes/hazards are on the real DEM.

**The DEM is not bundled in the wheel** (it's 16 MB) — it is **fetched + checksum-verified** post-install:
```bash
dustgym-fetch-dem --source <mirror-url-or-file://dir>    # or set DUSTGYM_DEM_URL
```
Source of truth is **PGDA Product 78** (`Haworth_final_adj_5mpp_surf.tif`; Barker et al. 2021). The fetch
verifies each asset's SHA256 against `planet_browser/assets_manifest.json` and **refuses on mismatch** (no
fabricated/corrupt terrain). Running from the repo, the DEM is already present (the fetch is a no-op).

## 2. Load a sample mission
`planet_browser/sample_missions/` ships three deterministic tutorials:
1. `01_flatten_pad.json` — cut a high spot, fill a landing pad (feasible).
2. `02_haul_around_hazard.json` — a keep-out straddles the haul line; the route **bends around** it (feasible).
3. `03_blocked_infeasible.json` — the fill site has no safe corridor; the plan is **INFEASIBLE** (failure case).

Paste a sample's `orders`/`keepouts` into the browser build queue, or POST it to `/plan`.

## 3. Plan and read the result
`POST /plan` (or the browser "Plan mission" button) returns:
- `totals.routes` — the per-leg terrain-following **waypoint polylines** (the 2D canvas draws routed legs
  in green, blocked legs in red dashed); `totals.feasible`.
- `plan_ir` — the executable plan: each `GoTo` carries `waypoints` + `reached`; the IR has `feasible` and
  `mode: DEM_KNOWN_POSE_MISSION_SIM`.
- the PDF/markdown **report** with the mode banner + `Plan feasibility: FEASIBLE / ⚠ INFEASIBLE`.

## 4. Failure handling
Run tutorial 3: `/plan` succeeds (HTTP 200) but the plan is marked **INFEASIBLE** — the blocked leg has
`reached: false`, `waypoints: []` (no straight line through the hazard), and the report/2D view flag it.
An infeasible plan's energy/distance totals are a straight-line estimate and must not be executed.

## 5. Run the tests
```bash
PYTHONPATH=. $VENV -m pytest planet_browser -q          # full product suite
PYTHONPATH=. $VENV -m pytest planet_browser/test_sample_missions.py -q   # the tutorials plan as documented
```

## 6. Exercises (intern)
1. **Move a fill.** Load `01_flatten_pad`, change the fill `x` to 60, Plan. Watch the route length and the
   green polyline change in the 2D canvas + Metrics playback.
2. **Add a hazard.** Load `02_haul_around_hazard`, add a second keep-out near the haul line (the "+ Obstacle"
   control), Plan. The green route must bend around both discs; the report's detour % goes up.
3. **Make it infeasible.** Load `03_blocked_infeasible` (or grow a keep-out until it encloses a site), Plan.
   The plan returns HTTP 200 but `feasible=false`: the blocked leg draws red dashed (route not driven), the
   report header shows **⚠ INFEASIBLE**, and the Plan IR `GoTo` for that leg has `reached:false, waypoints:[]`.
4. **Read the executable plan.** Download the Plan IR (⤓ Plan IR); confirm each `GoTo` carries `waypoints`
   and the top-level `mode` is `DEM_KNOWN_POSE_MISSION_SIM`.

## 7. Troubleshooting
- **`terrain_source: "flat_fallback"`** in the /plan response (or the report) → the real Haworth DEM bundle
  was not found; routes/hazards are NOT trustworthy. Run from the repo (which has `samples/lunar_dem/...`)
  or install a wheel that bundles the DEM. The server never silently pretends terrain is flat — this flag is
  how you know.
- **Plan marked INFEASIBLE** → a route leg has no safe corridor (too steep / keep-out / drop-off). Move the
  site, widen the traverse cap, or remove the blocking obstacle. The straight-line energy/distance on an
  infeasible plan is a don't-care estimate — do not execute it.
- **Server won't start / port busy** → pick another `--port`; check the printed URL.
- **Cesium globe is blank** → the globe needs a real GPU browser; the 2D plan canvas + report work without it.
