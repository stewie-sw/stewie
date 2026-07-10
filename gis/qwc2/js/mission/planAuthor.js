/**
 * planAuthor — the STEWIE MISSION-AUTHORING controller for the lunar IDE (artemis.stewie.space/ide/).
 * Design T9 (design/STEWIE_LUNAR_PLATFORM_DESIGN_2026-07-06.md §D): the operator places cut/fill orders
 * on the QWC2 map, hits Plan, and the REAL routed plan (routes + haul lines + feasibility/makespan) from
 * the backend planner renders on the map.
 *
 * REBIND, not rewrite: this is a framework-agnostic port of Frontend A's OpenLayers author->plan loop
 * (gis/web/app.js:352-673 -- placeOrder / order queue / POST /api/plan / renderPlan). The QWC2 map IS an
 * OpenLayers 10 map in the SAME lunar CRS (IAU_2015:30135) as Frontend A, so the plan rendering ports
 * verbatim (OL vector features + styles); the MissionPlan.jsx SideBar plugin wires this controller to a
 * dark-IDE panel, exactly as MissionHUD.jsx wires rover_hud.js and MissionLayers.jsx wires catalogLayers.js.
 *
 * THE FRAME (why this needs NO auth-gated DEM endpoint). Frontend A converts a map click to the planner's
 * order frame with three per-click backend GETs (/dem/site_xy, /dem/site_lonlat, /dem/georef). Those routes
 * are now `require_auth` (commit 5a037c66) and 401 through the artemis /api/ proxy, which server-side-injects
 * the shared key for /api/plan ONLY. So this controller derives the frame CLIENT-SIDE instead:
 *   - The planner's DEM tile is a north-up raster in IAU_2015:30135 -- the SAME CRS as this map
 *     (stewie/terrain/site_dem.py latlon_to_dem_origin). Therefore the order frame is an AXIS-ALIGNED,
 *     y-flipped affine of the map: order_x = X30135 - anchorX ; order_y = anchorY - Y30135 (raster-down).
 *     No rotation, no per-tile Jacobian.
 *   - The anchor (order-frame origin / charger) is set via /api/plan's M11 `lat/lon` fields: the planner
 *     anchors the order frame at latlon_to_dem_origin(lat,lon) server-side. We choose the anchor = the
 *     centroid of the placed orders (in selenographic lon/lat, from a client-side proj4 reproject) and pass
 *     it as lat/lon, so we KNOW the anchor's map position (reproject it back to 30135) without any DEM GET.
 *   - The returned plan_ir waypoints/routes/haul are in the order frame; we draw them back through the same
 *     anchor: [X,Y]30135 = [anchorX + ox, anchorY - oy]. Exact to the anchor's pixel rounding (<= cell/2 m).
 * The plan itself is 100% real (routing + feasibility + energy on the real DEM); only the frame math moved
 * from three blocked GETs to client-side proj4 + the one key-injected POST. The keyless
 * /api/layers/globe/{kind}/bbox (the SAME endpoint MissionLayers drapes) supplies the work-area extent for
 * the initial zoom.
 */
import WS from './workspace.js';   // GW-02: the shared workspace-context store (site/body/mission)
import Feature from 'ol/Feature';
import CircleGeom from 'ol/geom/Circle';
import LineString from 'ol/geom/LineString';
import Point from 'ol/geom/Point';
import Polygon from 'ol/geom/Polygon';
import Draw from 'ol/interaction/Draw';
import VectorLayer from 'ol/layer/Vector';
import VectorSource from 'ol/source/Vector';
import CircleStyle from 'ol/style/Circle';
import Fill from 'ol/style/Fill';
import RegularShape from 'ol/style/RegularShape';
import Stroke from 'ol/style/Stroke';
import Style from 'ol/style/Style';
import Text from 'ol/style/Text';

import PlanTools from './planTools';   // pure tool-palette logic (traverse/goto, return-to-lander, place-object)
import FT from './fetchWithTimeout';   // [systems-eng] bounded reads: abort a hung backend GET, never hang the panel
import RG from './reqGuard.js';        // [council #57] monotonic request guard: drop a stale site-A load that resolves after switching to site-B

const MAP_CRS = 'IAU_2015:30135';   // the lunar polar-stereographic workbench CRS (state.map.projection)
const GEO_CRS = 'IAU_2015:30100';   // selenographic lon/lat (order-anchor + globe bbox frame)
const KIND_COLOR = {cut: '#e0563a', fill: '#4fd1ff', goto: '#ffd24a'};   // cut = drum-down, fill = berm, goto = traverse waypoint (amber)
// Place-object marker palette (one hue per mission-object type). Keys MUST match planTools.OBJECT_TYPES /
// the server ALLOWED_MARKER_TYPES; an unknown type falls back to the compare-accent violet.
const MARKER_COLOR = {beacon: '#39ff14', cache: '#ffd24a', instrument: '#4affd2', sample: '#ff8f4a', antenna: '#b47cff'};

// DEPTH-3 fleet: a per-vehicle categorical route palette. Index 0 = the legacy single-vehicle gold, so a
// single-rover plan renders BYTE-IDENTICALLY to before; index >0 gives each fleet rover a distinct colour.
// The backend tags every plan_ir action with a 0-based `vehicle` id (lode/planner_views.py:440,457,492 —
// veh = int(tr.get("vehicle", 0))) and lists per-vehicle allocation in totals.vehicles_detail[i].vehicle
// (lode/planner_assembly.py:382; both 0-based from _allocate_trips's range(vehicles), planner_multivehicle.py),
// so the same index keys the map route colour AND the panel legend swatch. Colours are picked distinct from
// the cut/fill markers (#e0563a/#4fd1ff), the blue-dashed haul (#8fb8ff), and the green charger (#7fe0a8).
const VEHICLE_COLORS = ['#ffd24a', '#ff5ec7', '#7cff5e', '#ff8f4a', '#b47cff', '#4affd2', '#ff6b6b', '#6ba3ff'];
function vehicleColor(veh) {
    const i = Number.isFinite(veh) ? veh : 0;
    return VEHICLE_COLORS[((i % VEHICLE_COLORS.length) + VEHICLE_COLORS.length) % VEHICLE_COLORS.length];
}

function round1(n) { return Math.round(n * 10) / 10; }

// PLAN ANYWHERE: the deterministic ad-hoc site id for an OFF-SITE pick, MATCHING the backend
// (stewie/terrain/adhoc_dem.py adhoc_site_id) exactly -- milli-degree ints, lon wrapped to [-180,180).
// The backend recognises `adhoc_<lat>_<lon>` and crops the global LDEM there on demand; the SAME string
// then drives the globe drape (site=) + the /api/plan POST, so an off-site spot behaves like a curated one.
function adhocSiteId(lat, lon) {
    const wl = ((Number(lon) + 180) % 360 + 360) % 360 - 180;
    return 'adhoc_' + Math.round(Number(lat) * 1000) + '_' + Math.round(wl * 1000);
}

export default class PlanAuthor {
    /**
     * @param {object} opts
     * @param {ol.Map} opts.map        the raw OpenLayers map (MapUtils.getHook(GET_MAP)).
     * @param {function} opts.reproject CoordinatesUtils.reproject([x,y], srcCrs, dstCrs) -> [x,y].
     * @param {function} opts.onState  called with the full UI state on every change (queue/hint/result/tool).
     */
    constructor({map, reproject, onState}) {
        this.map = map;
        this.reproject = reproject;
        this.onState = onState || (() => {});
        this.site = WS.site();   // GW-02: the shared workspace site (hydrated from ?site= on load), not a literal
        this.activeKind = null;
        this.footprint = 60;       // m^2 (Frontend A default)
        this.depth = 0.4;          // m

        // --- Plan controls (DEPTH-2). The planner LEVERS /api/plan already accepts, exposed as UI so the
        // operator picks the solver + objective + budgets instead of the former hardcoded nearest/time. The
        // defaults MATCH the PlanRequest defaults (stewie/server/routers/plan.py:68,69,74), so an untouched
        // panel POSTs the byte-identical legacy payload. Grounded (no synthetic options):
        //   algorithm  -> optimize_sequence, validated against SEQUENCERS (lode/planner_optimize.py:48):
        //                 auto/nearest/greedy/two_opt/or_opt/lk/brute/held_karp.
        //   objective  -> parse_objective, validated against OBJECTIVES (lode/planner_optimize.py:27-40):
        //                 time/energy/average_power/distance/charges/mass (duration==time, power==average_power).
        //   maxSlopeDeg-> PlanRequest.max_traverse_slope_deg (plan.py:74): the routing traversability gate,
        //                 clamped to the backend bound 5..45 deg (planner default 25).
        //   budgets    -> Mission.objective_constraints (lode/planner_model.py:218; parsed :422-436): the hard
        //                 sequencing caps {max_time_s, max_energy_J, max_charges, max_distance_m} + risk_weight
        //                 (planner_constants.py:30 _CONSTRAINT_CAPS | {risk_weight}); each a finite value >= 0
        //                 (planner_model.py:431-433). '' = unset -> the key is omitted -> that budget unconstrained.
        this.algorithm = 'nearest';
        this.objective = 'time';
        this.maxSlopeDeg = 25;
        this.budgets = {max_time_s: '', max_energy_J: '', max_charges: '', max_distance_m: '', risk_weight: ''};
        // DEPTH-3 fleet controls. The REAL /api/plan fleet levers (both ride the SAME POST):
        //   vehicles          -> PlanRequest.vehicles (stewie/server/routers/plan.py:72; int 1..16). vehicles!=1
        //                        dispatches plan_and_simulate -> plan_multi (lode/planner_assembly.py:500) =
        //                        site-exclusive LPT allocation, per-vehicle parallel battery sim, makespan=max,
        //                        fleet-summed energy, space-time/charger conflict detection (planner_multivehicle).
        //   charger_capacity  -> PlanRequest.charger_capacity (plan.py:75; int 1..8). Consumed via
        //                        mission_from_dict -> Mission.charger_capacity (planner_model.py:367,194) ->
        //                        _resolve_joint_resources / _resolve_charger_queue (planner_assembly.py:337,479):
        //                        how many rovers may charge at once (FCFS queue when the fleet exceeds it).
        // Defaults 1/1 MATCH the PlanRequest + Mission defaults, so a single-vehicle plan is semantically the
        // legacy plan (no fleet allocation, no charger contention).
        this.vehicles = 1;
        this.chargerCapacity = 1;
        // --- Forward-compare (CP-05). The director-side "which strategy wins?" surface. The operator picks
        // 2..5 candidate SEQUENCERS (the SAME algorithm keys the Algorithm select uses, lode/planner_optimize.py:48)
        // and STEWIE re-simulates the CURRENT mission under each at wall speed, ranking the resulting plan
        // FUTURES feasible-first with a recommendation (lode/resync.forward_compare, exposed at POST
        // /resync/compare, stewie/server/routers/plan.py:204 -> {ok, objective, futures:[{algorithm, time_s,
        // energy_MJ, feasible, wall_s, ...}], recommended}). It reuses the EXACT order-frame orders the plan()
        // serializer builds for /api/plan (the anchor-relative x/y offsets); the mission carries a charger at the
        // (0,0) anchor -- the same {name,body,charger,orders} shape the endpoint's mission_from_dict expects
        // (test_admin.py::test_resync_compare_endpoint_ranks_futures). The backend caps candidates at 5 ([:5]).
        this.compareCandidates = [];   // selected SEQUENCERS keys (2..5) to forward-compare
        this.compareResult = null;     // last /resync/compare response {objective, futures:[...], recommended}
        this.comparing = false;        // request in flight
        this.compareErr = null;        // last compare error message (surfaced in the panel)
        this._lastComparePayload = null;   // the exact JSON POSTed to /api/resync/compare (headless-proof readback)
        // --- Structure-template authoring (T11). Place a whole STRUCTURE (landing pad / blast berm / haul
        // road / solar pad / habitat foundation / borrow pit / crater fill / trench) and the backend
        // decomposes it into REAL mass-balanced cut/fill orders that flow into the SAME queue the manual
        // Cut/Fill tools fill, so the existing /api/plan routing runs them UNCHANGED. Two real routes (both
        // now key-injected at the artemis /api/ proxy, 200/400 not 401):
        //   catalog     GET  /api/construction (stewie/server/routers/construction.py:66) -> {templates:[{id,
        //               doc, defaults:{param:number}, n_cut, n_fill, balanced}], ...}. The template's
        //               `defaults` IS the real inspect.signature default-param schema (construction.py:44),
        //               so the param editor is seeded from the backend, not a synthetic list.
        //   decompose   POST /api/structure {name,x,y,params} (perception.py:378 -> structures.decompose:123)
        //               -> {ok, name, orders:[{action,kind,x,y,footprint_m2,depth_m,note}]} in the LOCAL site
        //               frame (metres). We POST at local origin (0,0) so the returned x/y are pure offsets
        //               from the placement click; a fill consumes EXACTLY the paired cut volume (structures.py
        //               §mass-balance), so the queued orders are mass-balanced by construction (verified live).
        this.templates = null;      // cached catalog rows from GET /api/construction (null = not loaded yet)
        this.templatesErr = null;   // last catalog fetch error message (surfaced in the panel)
        this.structKind = null;     // active structure id — mutually exclusive with the Cut/Fill + no-go tools
        this.structParams = {};     // current param values for the selected template (seeded from its defaults)
        this.structures = [];       // placed structures [{idx, name, params, coord:[x,y]30135, nOrders}]
        this._structSeq = 0;        // monotonic structure id (tags each structure's orders so it removes cleanly)
        this._lastPlanPayload = null;   // the exact JSON POSTed to /api/plan (headless-proof readback)
        this.orders = [];          // {kind, footprint_m2, depth_m, coord:[x,y]30135, lonlat:[lon,lat], structId?}
        // --- TOOL PALETTE (traverse / return-to-lander / place-object). The palette adds discoverable tools on
        // top of the Cut/Fill/Structure authoring, all sharing the SAME map-click owner (activeKind/structKind/
        // objectType are mutually exclusive placing modes).
        //   TRAVERSE   — a click drops a `goto` waypoint into the order queue; the backend auto-chains
        //                consecutive gotos into a path (lode planner_model, zero-mass sequenced visits). No new
        //                order kind: goto is already first-class. Rendered as an ordered polyline (traverseLayer).
        //   RETURN-TO-LANDER — appends a goto at the lander/charger anchor (the order centroid), so the drive
        //                ends back at base (reuses the SAME anchor /api/plan derives).
        //   PLACE OBJECT — a click drops a mission-object MARKER (beacon/cache/instrument/sample/antenna) that
        //                persists through the backend edit-session (versioned audit + undo, /api/edit/session/
        //                {sid}/marker), kept SEPARATE from the keep-out set so it never routes the planner
        //                around it. this.markers is the render MIRROR of the backend marker set.
        this.objectType = null;    // active place-object type ('beacon'|... ) — exclusive with cut/fill/structure/no-go
        // PLAN ANYWHERE (map-click pick): when true, a map click SETS THE WORK AREA at the clicked lon/lat (the
        // backend crops the global LOLA LDEM there on demand -- #30) instead of placing an order. Mutually
        // exclusive with every placing mode (activeKind/structKind/objectType/koTool). One-shot: the pick
        // adopts the ad-hoc site via planHere() -> selectSite(), which resets authoring and clears this flag.
        this.planHereMode = false;
        this.markers = [];         // [{fid, otype, label, coord:[x,y]30135, feature}] — MIRROR of the backend markers
        this._locMarkerSeq = 0;    // client-only fallback marker id (no backend session)
        this.result = null;        // last plan summary (for the panel)
        this.planning = false;
        this.hint = 'Pick a work site, then a tool, then click the map to place orders.';
        this.hintErr = false;
        this.wc = null;            // last anchor in map coords [x,y]30135 (for redraw)

        // Pending order markers (pre-plan) + the rendered plan (routes/haul/charger). Raw OL layers added
        // straight to the map (like Frontend A) -- QWC2's OlLayer only ever removes ITS OWN tracked layers,
        // never untracked ones, so these survive redux layer reconciliation; zIndex keeps them on top.
        this.orderSource = new VectorSource();
        this.orderLayer = new VectorLayer({source: this.orderSource, zIndex: 20});
        this.orderLayer.setStyle((f) => this._orderMarkerStyle(f));
        this.planSource = new VectorSource();
        this.planLayer = new VectorLayer({source: this.planSource, zIndex: 19});

        // TRAVERSE path: the ordered polyline connecting the dropped goto waypoints (pre-plan preview), drawn
        // UNDER the order markers so each waypoint's number still reads. A dashed amber line = the drive path.
        this.traverseSource = new VectorSource();
        this.traverseLayer = new VectorLayer({source: this.traverseSource, zIndex: 16});
        this.traverseLayer.setStyle(new Style({
            stroke: new Stroke({color: '#ffd24a', width: 2, lineDash: [6, 5]})
        }));

        // PLACE-OBJECT markers: point features (a mission object dropped on the map), drawn ABOVE the plan with
        // a type-coloured diamond + a label. The backend edit-session is the source of truth; this layer is a
        // render mirror rebuilt from each edit-session response (_adoptEditState) or a local fallback.
        this.markerSource = new VectorSource();
        this.markerLayer = new VectorLayer({source: this.markerSource, zIndex: 20});
        this.markerLayer.setStyle((f) => this._markerStyle(f));

        // Structure footprints (T11): a dashed steel-cyan bounding outline + name label per placed structure,
        // drawn UNDER the cut/fill order markers (zIndex 17 < orderLayer 20) so both the whole-structure
        // footprint and its individual decomposed orders read on the map. The orders themselves are ordinary
        // cut/fill features on orderLayer (existing _orderMarkerStyle), so nothing about the plan/run path changes.
        this.structureSource = new VectorSource();
        this.structureLayer = new VectorLayer({source: this.structureSource, zIndex: 17});
        this.structureLayer.setStyle((f) => this._structureStyle(f));

        // --- Keep-out / no-go authoring (DEPTH-1). The operator draws avoid-regions (polygon or circle) on
        // the SAME OL map; on Plan they serialize into payload.keepouts -- the EXACT schema the backend parses
        // (lode/planner_routing.py:147 point_in_keepout / :158 _apply_keepouts): a {points:[[x,y],...]}
        // polygon or an {x,y,r} circle in the ORDER FRAME (metres). _apply_keepouts marks those cells
        // IMPASSABLE, so the least-cost router (route_leg, planner_views.py:448 for the rendered GoTo legs)
        // bends the route AROUND them. Geometry is kept in the map CRS on the OL feature and converted to the
        // order frame at Plan time through the SAME y-flipped anchor affine the orders use.
        this.keepouts = [];        // [{idx:fid, fid, kind:'polygon'|'circle', feature}] -- MIRROR of the backend set
        this.koTool = null;        // active no-go draw tool: 'polygon' | 'circle' | null
        this._draw = null;         // the live OL Draw interaction (on the map only while a ko tool is active)
        this._koSeq = 0;
        // --- Mission-feature EDIT SESSION (GW-08 / ED-01). The keep-out set is now OWNED BY THE BACKEND, not
        // this client array: every create/delete/undo writes through the /api/edit/session routes, which keep a
        // MONOTONIC version + a before/after AUDIT log, and /api/plan reads the session's current set (by id +
        // the order-frame anchor) instead of a client-serialized payload.keepouts. this.keepouts is a render
        // MIRROR rebuilt from each route response (the backend is the source of truth). If the backend session
        // is unavailable (offline), authoring falls back to client-only (this.keepouts + _keepoutsForFrame at
        // plan time), so the IDE never breaks -- degraded, not dead.
        this.editSession = null;   // opaque backend session id (secrets.token_hex); null = client-only fallback
        this.editVersion = 0;      // the session's monotonic version (surfaced in the panel)
        this.editAudit = [];       // the recent audit tail [{version, op, fid, ...}] (surfaced in the panel)
        this._hatch = undefined;   // lazily-built diagonal-hatch CanvasPattern for the no-go fill
        this.keepoutSource = new VectorSource();
        this.keepoutLayer = new VectorLayer({source: this.keepoutSource, zIndex: 18});
        this.keepoutLayer.setStyle(() => this._keepoutStyle());

        // --- Run-SIM (T10, design §D-3 tier-3 analog run as a NON-DESTRUCTIVE desktop_sil). The rover marker
        // + its traversed trail draw ABOVE the plan route; the run is a verbatim port of Frontend A's
        // gis/web/app.js:676-914 execution loop (POST /executive/run -> SSE /executive/run/{id}/stream ->
        // animate the rover along the REAL planned route by leg events -> run summary + /evidence bundle).
        this.trailSource = new VectorSource();
        this.trailLayer = new VectorLayer({source: this.trailSource, zIndex: 21});
        this.trailLayer.setStyle(new Style({stroke: new Stroke({color: '#7fe0a8', width: 3})}));
        this.roverSource = new VectorSource();
        this.roverLayer = new VectorLayer({source: this.roverSource, zIndex: 22});
        this.roverLayer.setStyle(new Style({
            image: new CircleStyle({
                radius: 6, fill: new Fill({color: '#eafff4'}),
                stroke: new Stroke({color: '#1c6b45', width: 2})
            }),
            text: new Text({
                text: 'IPEx', offsetY: -15, font: '700 11px system-ui, sans-serif',
                fill: new Fill({color: '#bff4d8'}), stroke: new Stroke({color: '#000', width: 3})
            })
        }));

        this.route = null;         // ordered drive route in map coords (from the rendered plan) for the SIM rover
        this._planOrders = null;   // the order-frame orders POSTed to /plan -- reused verbatim for /executive/run
        this.run = this._emptyRun();
        this._roverFeat = null; this._trailFeat = null;
        this._animFrom = 0; this._animTo = 0; this._animStart = 0; this._animDur = 400; this._animRaf = 0;

        this._clickKey = null;
        this._attached = false;
        // [council #57] Monotonic request guard, the SAME pattern MissionTerrain3D / SelectionInspector /
        // MissionCrossSection use (reqGuard.js). Each async load (selectSite bbox, plan()) takes a token from
        // next(); on resolve it keeps its result only if current(token) is still latest. Starting a new load
        // (a site switch) or detach() invalidates every in-flight token, so a slow site-A response that lands
        // after the operator switched to site-B is dropped instead of drawing the old site over the new one.
        this._rg = RG.makeReqGuard();
    }

    _emptyRun() {
        return {es: null, id: null, legsSeen: 0, total: 0, terminal: null, running: false,
            cumdist: null, len: 0, result: null, evidence: null, lastEvent: '', lastPose: null};
    }

    attach() {
        if (this._attached) { return; }
        this.map.addLayer(this.structureLayer);
        this.map.addLayer(this.traverseLayer);
        this.map.addLayer(this.keepoutLayer);
        this.map.addLayer(this.planLayer);
        this.map.addLayer(this.trailLayer);
        this.map.addLayer(this.roverLayer);
        this.map.addLayer(this.orderLayer);
        this.map.addLayer(this.markerLayer);
        this._clickKey = this.map.on('singleclick', (evt) => {
            // A map click places whatever authoring mode is active. The placing modes are mutually exclusive
            // (a Cut/Fill/Traverse tool, a structure template, a place-object type, a no-go Draw interaction,
            // or the plan-anywhere pick — never two at once), so exactly one branch fires. Plan-anywhere is
            // checked FIRST: it is a higher-level "set the work area here" action, not an in-frame placement.
            if (this.planHereMode) { this.pickPlanHere(evt.coordinate); }
            else if (this.activeKind) { this.placeAt(evt.coordinate); }
            else if (this.structKind) { this.placeStructure(evt.coordinate); }
            else if (this.objectType) { this.placeObject(evt.coordinate); }
        });
        // Read-only harness handles for the headless LIVE proof (same code paths as the UI) -- mirrors
        // Frontend A's window.stewieRun (gis/web/app.js:916). No command authority; state readback only.
        if (typeof window !== 'undefined') {
            window.__stewieRun = {
                state: () => this._runView(),
                roverPose: () => (this.run.lastPose ? this.run.lastPose.slice() : null),
                routeLen: () => (this.route || []).length,
                orderCount: () => this.orders.length,
                pixelOf: (coord) => this.map.getPixelFromCoordinate(coord),   // read-only map-coord -> pixel
                // Authoring drivers for the headless verification harness -- the SAME controller code paths
                // the tool button + map singleclick call (setTool -> placeAt), so a proof can place orders at
                // exact map coords without pixel-quantised clicks. No command authority (authoring only).
                setTool: (kind) => this.setTool(kind),
                placeAt: (coord) => this.placeAt(coord),
                // PLAN ANYWHERE drivers: toggle the map-click pick mode and drive a pick at an EXACT map coord
                // (the SAME controller path the "Plan here" button + map singleclick call), so a headless proof
                // can set the work area at an arbitrary lon/lat off the fixed sites without a pixel-quantised
                // click. pickPlanHere returns the planHere() promise so the proof can await the crop + re-frame.
                setPlanHereMode: () => this.setPlanHereMode(),
                planHereMode: () => this.planHereMode,
                pickPlanHere: (coord) => this.pickPlanHere(coord),
                planHere: (lat, lon) => this.planHere(lat, lon),
                site: () => this.site,
                // TOOL PALETTE drivers (traverse / return-to-lander / place-object) — the SAME controller code
                // paths the palette buttons + map singleclick call, so a headless proof can drop a traverse
                // waypoint, return to the lander, and place a mission object at exact map coords without pixel-
                // quantised clicks. placeObject returns the fetch promise so the proof can await the backend
                // marker round-trip. Authoring only (no command authority).
                traverseCount: () => this.orders.filter((o) => PlanTools.isTraverse(o)).length,
                returnToLander: () => this.returnToLander(),
                setObjectTool: (otype) => this.setObjectTool(otype),
                objectType: () => this.objectType,
                placeObject: (coord) => this.placeObject(coord),
                removeMarker: (fid) => this.removeMarker(fid),
                markerCount: () => this.markers.length,
                markers: () => this.markers.map((m) => ({fid: m.fid, otype: m.otype, label: m.label,
                    coord: m.coord.slice()})),
                // No-go authoring drivers (same code path as the Draw tool's drawend + the panel buttons),
                // so a proof can place a no-go region across the route at exact MAP coords without simulating
                // Draw pointer events. No command authority (authoring only).
                setKeepoutTool: (kind) => this.setKeepoutTool(kind),
                addKeepoutCircle: (center, radius) => this.addKeepoutCircle(center, radius),
                addKeepoutPolygon: (ring) => this.addKeepoutPolygon(ring),
                clearKeepouts: () => this.clearKeepouts(),
                keepoutCount: () => this.keepouts.length,
                // GW-08 read/authoring drivers: the backend edit-session id + version + audit tail, and undo,
                // so a headless proof can assert a keep-out persisted through the backend with a version/audit
                // and that undo reverts it -- without scraping the panel DOM.
                undoEdit: () => this.undoEdit(),
                editState: () => ({session: this.editSession, version: this.editVersion,
                    audit: this.editAudit.map((a) => ({version: a.version, op: a.op, fid: a.fid}))}),
                route: () => (this.route ? this.route.map((p) => p.slice()) : []),
                // DEPTH-3 read-only: the rendered per-vehicle DRIVE-route features on the map (each tagged
                // with its 0-based vehicle id + the stroke colour actually drawn), so a headless proof can
                // assert distinct-colour routes exist per rover without pixel inspection.
                routeFeatures: () => this.planSource.getFeatures()
                    .filter((f) => f.get('vehicle') != null)
                    .map((f) => {
                        let color = null;
                        try { const st = f.getStyle(); color = (st && st.getStroke) ? st.getStroke().getColor() : null; }
                        catch (e) { color = null; }
                        const g = f.getGeometry();
                        return {vehicle: f.get('vehicle'), color: color,
                            vertices: (g && g.getCoordinates) ? g.getCoordinates().length : 0};
                    }),
                // Plan-control drivers (DEPTH-2) — the SAME controller code paths the panel selects/inputs call,
                // so a proof can pick a solver/objective/budget without simulating DOM events. Authoring only.
                setAlgorithm: (v) => this.setAlgorithm(v),
                setObjective: (v) => this.setObjective(v),
                setMaxSlope: (v) => this.setMaxSlope(v),
                setBudget: (k, v) => this.setBudget(k, v),
                clearBudgets: () => this.clearBudgets(),
                // Fleet drivers (DEPTH-3) — same controller code paths the fleet inputs call, so a proof can
                // set the vehicle/charger counts without simulating DOM events. Authoring only.
                setVehicles: (v) => this.setVehicles(v),
                setChargerCapacity: (v) => this.setChargerCapacity(v),
                // Structure-template drivers (T11) — the SAME controller code paths the palette buttons/inputs
                // + map click call (loadTemplates -> setStructure -> setStructParam -> placeStructure), so a
                // headless proof can place a real structure at exact map coords and adopt its backend-decomposed
                // mass-balanced orders without pixel-quantised clicks. placeStructure returns the fetch promise
                // (the /api/structure POST) so the proof can await the decomposition. Authoring only.
                loadTemplates: () => this.loadTemplates(),
                templates: () => (this.templates ? JSON.parse(JSON.stringify(this.templates)) : null),
                setStructure: (name) => this.setStructure(name),
                setStructParam: (k, v) => this.setStructParam(k, v),
                placeStructure: (coord) => this.placeStructure(coord),
                structureCount: () => this.structures.length,
                // SD-01 read-only: the per-structure constructability evidence (volume/mass + terramechanics
                // bearing/sinkage + verdict) the backend derived, so a headless proof can assert the evidence
                // is real (matches the decompose + spine) without scraping the panel DOM.
                structureEvidence: () => this.structures.map((s) => (s.evidence
                    ? JSON.parse(JSON.stringify(s.evidence)) : null)),
                // Read-only readback of the exact /api/plan POST body + the last plan summary (for verifying
                // the chosen levers rode the POST and the resolved algorithm/objective came back).
                lastPlanPayload: () => (this._lastPlanPayload ? JSON.parse(JSON.stringify(this._lastPlanPayload)) : null),
                planResult: () => (this.result ? JSON.parse(JSON.stringify(this.result)) : null),
                // DEPTH-5 read-only: the Schedule/Gantt view-model (phase runs + per-vehicle swim-lanes) so a
                // headless proof can assert the lanes/colours match the routes without pixel inspection.
                scheduleView: () => ((this.result && this.result.detail && this.result.detail.schedule)
                    ? JSON.parse(JSON.stringify(this.result.detail.schedule)) : null),
                // CP-05 forward-compare drivers — the SAME controller code paths the candidate chips + Compare
                // button call (toggleCompareCandidate -> compareFutures -> adoptRecommended), so a headless proof
                // can select candidates + run the real /api/resync/compare round-trip and read back the ranked
                // futures + recommendation without simulating DOM events. compareFutures returns the fetch promise
                // (so the proof can await it). No command authority (authoring/analysis only).
                toggleCompareCandidate: (k) => this.toggleCompareCandidate(k),
                compareCandidates: () => this.compareCandidates.slice(),
                compareFutures: () => this.compareFutures(),
                adoptRecommended: () => this.adoptRecommended(),
                compareResult: () => (this.compareResult ? JSON.parse(JSON.stringify(this.compareResult)) : null),
                lastComparePayload: () => (this._lastComparePayload
                    ? JSON.parse(JSON.stringify(this._lastComparePayload)) : null)
            };
        }
        this._attached = true;
        // Prefetch the real build catalog (GET /api/construction) so the palette is populated on first open.
        this.loadTemplates();
        // GW-08: mint the backend mission-feature edit session so keep-out authoring writes through the routes
        // (versioned audit + undo). Best-effort: on failure the panel stays in client-only fallback mode.
        this._ensureSession();
    }

    detach() {
        if (!this._attached) { return; }
        this._deactivateDraw();
        this._resetRun();
        // [council #57] invalidate every in-flight fetch so a plan()/bbox response resolving after unmount
        // bails at its token guard (never re-renders / never pushes state onto the dead panel).
        if (this._rg) { this._rg.bump(); }
        if (typeof window !== 'undefined' && window.__stewieRun) { delete window.__stewieRun; }
        if (this._clickKey) { this.map.un('singleclick', this._clickKey.listener); this._clickKey = null; }
        this.map.removeLayer(this.markerLayer);
        this.map.removeLayer(this.orderLayer);
        this.map.removeLayer(this.roverLayer);
        this.map.removeLayer(this.trailLayer);
        this.map.removeLayer(this.planLayer);
        this.map.removeLayer(this.keepoutLayer);
        this.map.removeLayer(this.traverseLayer);
        this.map.removeLayer(this.structureLayer);
        this._attached = false;
    }

    _emit() {
        // [council #57] never push state onto an unmounted panel: detach() sets _attached=false, so a fetch that
        // resolves after MissionPlan unmounts (its retained onState closes over the dead React component) no-ops
        // here instead of calling setState on it.
        if (!this._attached) { return; }
        this.onState({
            site: this.site, adhoc: (this.site || '').startsWith('adhoc_'),
            activeKind: this.activeKind, planHereMode: this.planHereMode, footprint: this.footprint, depth: this.depth,
            orders: this.orders.map((o, i) => ({
                idx: i, kind: o.kind, x: round1(o.coord[0]), y: round1(o.coord[1]),
                footprint_m2: o.footprint_m2, depth_m: o.depth_m,
                struct: o.structName || null   // a structure-decomposed order carries its parent structure's name
            })),
            hint: this.hint, hintErr: this.hintErr, result: this.result, planning: this.planning,
            // Structure-template authoring (T11): the fetched catalog + the active template + its param
            // editor + the placed-structure list, mirrored to the panel. `structures[i].idx` is the array
            // index (the remove handle); `structId` is the stable sequence id (React key).
            templates: this.templates, templatesErr: this.templatesErr,
            structKind: this.structKind, structParams: {...this.structParams},
            structures: this.structures.map((st, i) => ({
                idx: i, structId: st.idx, name: st.name, nOrders: st.nOrders,
                evidence: st.evidence || null   // SD-01: the per-structure constructability evidence for the panel
            })),
            // DEPTH-2 plan controls (mirrored to the panel so the selects/inputs reflect the chosen levers).
            algorithm: this.algorithm, objective: this.objective, maxSlopeDeg: this.maxSlopeDeg,
            budgets: {...this.budgets},
            // DEPTH-3 fleet controls (mirrored to the panel).
            vehicles: this.vehicles, chargerCapacity: this.chargerCapacity,
            // CP-05 forward-compare (mirrored to the panel): the selected candidate keys + the ranked-futures
            // response + the in-flight/error flags. compareResult is the raw /resync/compare body the panel renders.
            compareCandidates: this.compareCandidates.slice(),
            compareResult: this.compareResult, comparing: this.comparing, compareErr: this.compareErr,
            koTool: this.koTool,
            // TOOL PALETTE state (traverse / return-to-lander / place-object), mirrored to the panel so the
            // palette shows which tool is active + the dropped waypoints/objects.
            objectType: this.objectType, objectTypes: PlanTools.OBJECT_TYPES,
            traverseCount: this.orders.filter((o) => PlanTools.isTraverse(o)).length,
            canReturnToLander: this.orders.length > 0,
            markers: this.markers.map((m) => ({fid: m.fid, otype: m.otype, label: m.label})),
            // GW-08: the keep-out idx is now the backend feature id (fid), the remove/undo handle. The panel
            // also reads the edit-session version + audit tail + whether an undo is available.
            keepouts: this.keepouts.map((k) => ({idx: k.fid, fid: k.fid, kind: k.kind, label: this._koSummary(k)})),
            editSession: this.editSession, editVersion: this.editVersion,
            editAudit: this.editAudit.slice(-8).map((a) => ({version: a.version, op: a.op, fid: a.fid,
                reverted_op: a.reverted_op || null})),
            canUndo: this._undoableCount() > 0,
            run: this._runView(),
            // The SIM run is offered only once a FEASIBLE plan with a drive route is rendered and no run is live.
            canRun: !!(this.route && this.route.length && this.result && this.result.feasible === true &&
                !this.run.running)
        });
    }
    // A serializable snapshot of the live run for React (the panel reads this; never the live EventSource).
    _runView() {
        const r = this.run;
        return {
            active: r.running, id: r.id, legsSeen: r.legsSeen, total: r.total,
            terminal: r.terminal, lastEvent: r.lastEvent, result: r.result, evidence: r.evidence
        };
    }
    _setHint(msg, isErr) { this.hint = msg; this.hintErr = !!isErr; this._emit(); }

    // --- Site select: fetch the keyless work-area bbox + frame the view on it -------------------------
    selectSite(site, {fly} = {}) {
        this.site = site;
        WS.set({site: site});   // GW-02: propagate the pick to the shared workspace (URL + every other consumer)
        this.orders = [];
        this.result = null;
        this.planning = false;   // [council #57] a site switch aborts any in-flight plan (its stale response is dropped below)
        this.wc = null;
        this._resetRun();
        this.route = null; this._planOrders = null;
        this._deactivateDraw();                       // a site change resets authoring incl. any drawn no-go
        this.keepouts = []; this.keepoutSource.clear();
        this.markers = []; this.markerSource.clear();   // place-object markers are per-session -> reset with the site
        this.objectType = null;                         // and any active place-object tool
        this.planHereMode = false;                      // adopting a site (incl. an ad-hoc plan-here pick) ends the pick mode
        this.editSession = null; this.editVersion = 0; this.editAudit = [];   // GW-08: fresh edit session per site
        this._ensureSession();
        this.structKind = null; this.structParams = {};   // and any active structure template + placed structures
        this.structures = []; this.structureSource.clear();
        this.orderSource.clear();
        this.planSource.clear();
        this.traverseSource.clear();
        this._setHint('Loading ' + site + ' work area…');
        const tok = this._rg.next();   // [council #57] a new site invalidates any in-flight plan/bbox from the prior site
        return FT.fetchWithTimeout('/api/layers/globe/dem/bbox?site=' + encodeURIComponent(site), {}, FT.DEFAULT_MS)
            .then((r) => { if (!r.ok) { throw new Error('bbox HTTP ' + r.status); } return r.json(); })
            .then((bb) => {
                // [council #57] Drop a superseded site's bbox: if the operator switched sites (or detached) while
                // this was in flight, this token is no longer current -> do NOT fly/hint the wrong site's extent.
                if (!this._rg.current(tok) || this.site !== site) { return; }
                if (!bb || bb.ok === false) { throw new Error((bb && bb.error) || 'no bbox'); }
                if (fly) { this._zoomToBbox(bb); }
                this._setHint('Pick a tool (Cut / Fill), then click the map near the work area to place an order.');
            })
            .catch((e) => {
                if (!this._rg.current(tok) || this.site !== site) { return; }   // a superseded site's error must not clobber the current one
                this._setHint('Could not load the ' + site + ' work area: ' + e.message, true);
            });
    }

    // PLAN ANYWHERE: adopt an arbitrary off-site (lat, lon) as the work site. Derives the ad-hoc id
    // (matching the backend) and reuses selectSite -- the backend crops the global LDEM there, so the
    // globe drape + planner run on the real cropped DEM instead of the off-site 404 / flat fallback.
    planHere(lat, lon) {
        const la = Number(lat);
        const lo = Number(lon);
        if (!Number.isFinite(la) || !Number.isFinite(lo) || Math.abs(la) > 89.9) {
            this._setHint('Enter a lat in [-89.9, 89.9] and a lon to plan off-site.', true);
            return Promise.resolve();
        }
        return this.selectSite(adhocSiteId(la, lo), {fly: true});
    }

    // PLAN ANYWHERE (map-click pick): toggle the mode where a MAP CLICK sets the work area at the clicked spot
    // (instead of placing an order). Mutually exclusive with every placing mode, so turning it on leaves the
    // Cut/Fill/Traverse tools, the structure templates, place-object, and no-go drawing. While MissionPlan is
    // the active task its controller OWNS the map click (SiteZoom stands down, CLICK_OWNED_BY MissionPlan), so
    // the pick never fights the fixed-site click-to-zoom. Turning it off returns to ordinary order placing.
    setPlanHereMode() {
        this.activeKind = null;
        this.structKind = null;
        this.objectType = null;
        this._deactivateDraw();
        this.planHereMode = !this.planHereMode;
        if (this.planHereMode) {
            this._setHint('Plan anywhere: click ANY point on the map to set the work area there — the global ' +
                'LOLA DEM is cropped to a local frame at that lon/lat (native ~118 m/px, coarse vs the curated ' +
                'sites). Click the button again to cancel.');
        } else {
            this._setHint('Plan-anywhere pick off. Pick a work site, or a tool to place orders.');
        }
        this._emit();
    }

    // A map click while plan-here mode is on: reproject the clicked map coord (IAU_2015:30135) to selenographic
    // lon/lat (IAU_2015:30100) with the SAME reproject the order path uses, refuse a pole-adjacent pick (the
    // curated polar tiles serve there) with the SAME domain the backend crop enforces, then adopt that spot as
    // an ad-hoc site via planHere() -> selectSite(adhoc id) -> the backend crops the global LDEM there on demand
    // (#30). One-shot: planHere -> selectSite clears planHereMode, so the next click places an order once a tool
    // is picked. Returns the planHere() promise (the crop + re-frame) for the headless proof.
    pickPlanHere(coord) {
        const ll = PlanTools.clickToLonLat(coord, this.reproject, MAP_CRS, GEO_CRS);
        if (!ll) {
            this._setHint('Could not resolve that map point to a lunar lon/lat — try a point on the surface.', true);
            return Promise.resolve();
        }
        const lon = ll[0], lat = ll[1];
        if (!PlanTools.isPlannableLatLon(lat, lon)) {
            this._setHint('That point is at the pole (|lat| > ' + PlanTools.MAX_ABS_LAT + '°); the curated polar ' +
                'tiles serve there. Pick a spot away from the exact pole to crop the global DEM.', true);
            return Promise.resolve();
        }
        this._setHint('Plan anywhere: cropping the global LOLA DEM at ' + round1(lat) + '°, ' + round1(lon) + '° …');
        return this.planHere(lat, lon);
    }

    // Fit the view to the site's globe footprint. Reproject the 4 selenographic corners to the map CRS and
    // fit their extent -- robust even at the pole (a lon/lat AABB is not axis-aligned in polar-stereographic).
    _zoomToBbox(bb) {
        try {
            const pts = [[bb.west, bb.south], [bb.east, bb.south], [bb.east, bb.north], [bb.west, bb.north]]
                .map((p) => this.reproject(p, GEO_CRS, MAP_CRS));
            const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
            const ext = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
            if (ext.every(isFinite)) {
                this.map.getView().fit(ext, {padding: [60, 60, 60, 60], maxZoom: 15, duration: 400});
            }
        } catch (e) { /* view unchanged if reprojection fails */ }
    }

    setTool(kind) {
        this._deactivateDraw();                       // picking a cut/fill/traverse tool leaves no-go draw mode
        this.structKind = null;                       // and leaves structure-template placing
        this.objectType = null;                       // and leaves place-object mode
        this.planHereMode = false;                    // and leaves the plan-anywhere pick mode
        this.activeKind = (this.activeKind === kind) ? null : kind;
        if (this.activeKind) {
            const what = kind === 'cut' ? 'a CUT (dig) order'
                : kind === 'fill' ? 'a FILL (build) order'
                    : kind === 'traverse' ? 'a TRAVERSE waypoint (the rover drives them in order)'
                        : 'an order';
            this._setHint('Click the map to drop ' + what + '. Click the tool again to stop placing.');
        } else {
            this._setHint('Placing off. Pick a tool to place more orders, or Plan the mission.');
        }
        this._emit();
    }
    setFootprint(v) { this.footprint = Math.max(1, parseFloat(v) || 60); this._emit(); }
    setDepth(v) { this.depth = Math.max(0.05, parseFloat(v) || 0.4); this._emit(); }

    // --- Plan controls (DEPTH-2): algorithm / objective / slope budget / resource budgets --------------
    // The dropdown/input values are the EXACT backend strings; validation lives server-side (a bad name is a
    // 400 from optimize_sequence/parse_objective/mission_from_dict), so the UI just carries the operator's
    // choice into the /api/plan POST. No client-side allow-list duplication of the backend enums.
    setAlgorithm(v) { this.algorithm = String(v || 'nearest'); this._emit(); }
    setObjective(v) { this.objective = String(v || 'time'); this._emit(); }
    setMaxSlope(v) {
        const n = parseFloat(v);
        // clamp to the PlanRequest bound (plan.py:74 ge=5.0 le=45.0); a blank/NaN keeps the planner default.
        this.maxSlopeDeg = Number.isFinite(n) ? Math.max(5, Math.min(45, Math.round(n))) : 25;
        this._emit();
    }
    setBudget(key, v) {
        if (Object.prototype.hasOwnProperty.call(this.budgets, key)) {
            this.budgets[key] = (v == null ? '' : String(v));
            this._emit();
        }
    }
    clearBudgets() {
        this.budgets = {max_time_s: '', max_energy_J: '', max_charges: '', max_distance_m: '', risk_weight: ''};
        this._setHint('Resource budgets cleared — plan is unconstrained.');
    }

    // --- Fleet controls (DEPTH-3): vehicles + charger_capacity, clamped to the PlanRequest bounds ------
    // The counts ride the SAME /api/plan POST (vehicles as a top-level field, charger_capacity through the
    // mission dict). Clamped to the backend bounds so a bad value is corrected client-side before the POST;
    // the backend re-validates (plan.py:72 ge=1 le=16 / :75 ge=1 le=8).
    setVehicles(v) {
        const n = parseInt(v, 10);
        this.vehicles = Number.isFinite(n) ? Math.max(1, Math.min(16, n)) : 1;
        if (this.vehicles > 1) {
            this._setHint('Fleet: ' + this.vehicles + ' rovers. Plan allocates orders across the fleet; ' +
                'each rover\'s route renders in its own colour.');
        } else {
            this._setHint('Single rover. Add orders, or Plan the mission.');
        }
        this._emit();
    }
    setChargerCapacity(v) {
        const n = parseInt(v, 10);
        this.chargerCapacity = Number.isFinite(n) ? Math.max(1, Math.min(8, n)) : 1;
        this._emit();
    }
    // Serialize the SET budgets into the planner's objective_constraints schema: only finite, >= 0 entries
    // (lode/planner_model.py:431-433); a blank field is omitted so that constraint is simply not applied.
    _objectiveConstraints() {
        const oc = {};
        for (const k of Object.keys(this.budgets)) {
            const raw = this.budgets[k];
            if (raw === '' || raw == null) { continue; }
            const n = parseFloat(raw);
            if (Number.isFinite(n) && n >= 0) { oc[k] = n; }
        }
        return oc;
    }

    // --- Structure-template authoring (T11) ----------------------------------------------------------
    // Fetch the real build catalog (GET /api/construction) once and cache it. The rows carry each template's
    // id/doc + its default-param schema (inspect.signature defaults, construction.py:44) + the cut/fill count
    // + the balanced flag, so the palette is driven by the backend (no synthetic template list). Same-origin;
    // the artemis nginx injects the shared key (the route is operator-gated but now key-injected at the proxy).
    loadTemplates() {
        if (this.templates) { return Promise.resolve(this.templates); }
        return FT.fetchWithTimeout('/api/construction', {}, FT.DEFAULT_MS)
            .then((r) => { if (!r.ok) { throw new Error('HTTP ' + r.status); } return r.json(); })
            .then((d) => {
                if (!d || d.ok === false || !Array.isArray(d.templates)) {
                    throw new Error((d && d.error) || 'no templates');
                }
                this.templates = d.templates.map((t) => ({
                    id: t.id, doc: t.doc || '', defaults: t.defaults || {},
                    n_cut: t.n_cut, n_fill: t.n_fill, n_orders: t.n_orders, balanced: !!t.balanced
                }));
                this.templatesErr = null;
                this._emit();
                return this.templates;
            })
            .catch((e) => { this.templatesErr = e.message; this._emit(); });
    }

    // Toggle the active structure template. Structure placing is mutually exclusive with the Cut/Fill tools
    // and the no-go Draw interaction. Selecting a template seeds the param editor from its REAL default schema
    // (the catalog `defaults`), so an untouched placement POSTs the backend defaults (params omitted -> the
    // decompose() signature defaults, structures.py).
    setStructure(name) {
        this.activeKind = null;                       // structure placing and Cut/Fill placing are exclusive
        this.planHereMode = false;                    // and leave the plan-anywhere pick mode
        this._deactivateDraw();                       // and leave no-go drawing
        const next = (this.structKind === name) ? null : name;
        this.structKind = next;
        this.structParams = {};
        if (next) {
            const tpl = (this.templates || []).find((t) => t.id === next);
            if (tpl && tpl.defaults) {
                for (const k of Object.keys(tpl.defaults)) {
                    const v = tpl.defaults[k];
                    if (typeof v === 'number') { this.structParams[k] = String(v); }
                }
            }
            this._setHint('Click the map to place a ' + next.replace(/_/g, ' ') +
                '. The backend decomposes it into mass-balanced cut/fill orders. Click the button again to stop.');
        } else {
            this._setHint('Structure placing off. Pick a tool or structure, or Plan the mission.');
        }
        this._emit();
    }

    // Update one template param (kept as a raw string; blank -> omitted at POST so the backend default applies).
    setStructParam(key, v) {
        if (!this.structParams) { this.structParams = {}; }
        this.structParams[key] = (v == null ? '' : String(v));
        this._emit();
    }

    // Place the active structure at a map click: POST /api/structure at LOCAL origin (0,0) so the returned
    // order x/y are pure offsets from the click, map each decomposed order back to map coords (order frame is
    // raster-DOWN: +y = South, so mapY = clickY - oy in the north-up 30135 map), and ADOPT them into the same
    // order queue the manual tools fill. The fill consumes exactly the paired cut volume (structures.py mass
    // balance), so the queued orders are mass-balanced by construction; the plan() round-trip preserves each
    // order's footprint*depth and the cut<->fill separation vector exactly (up to 0.1 m coord rounding).
    placeStructure(coord) {
        if (!this.structKind) { return Promise.resolve(); }
        const name = this.structKind;
        let originLonlat;
        try { originLonlat = this.reproject(coord, MAP_CRS, GEO_CRS); }
        catch (e) { this._setHint('Could not reproject the click: ' + e.message, true); return Promise.resolve(); }
        // Build the params payload: finite numeric values only (blank -> omitted -> backend default).
        const params = {};
        for (const k of Object.keys(this.structParams || {})) {
            const raw = this.structParams[k];
            if (raw === '' || raw == null) { continue; }
            const n = Number(raw);
            if (Number.isFinite(n)) { params[k] = n; }
        }
        this._setHint('Decomposing ' + name.replace(/_/g, ' ') + ' into mass-balanced orders…');
        return fetch('/api/structure', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            // SD-01: carry the work site + selenographic placement so the backend samples the REAL DEM slope at
            // the structure's location for the constructability evidence (bearing/sinkage verdict). originLonlat
            // = [lon, lat] from the click reproject above; off-tile/absent -> the backend defers (no fake slope).
            body: JSON.stringify({name: name, x: 0, y: 0, params: params,
                site: this.site, lon: originLonlat[0], lat: originLonlat[1]})
        })
            .then((r) => r.text().then((t) => {
                let b = null; try { b = JSON.parse(t); } catch (e) { b = null; }
                return {status: r.status, body: b};
            }))
            .then((res) => {
                const orders = res.body && res.body.orders;
                if (!res.body || !res.body.ok || !Array.isArray(orders) || !orders.length) {
                    const err = (res.body && res.body.error) || ('HTTP ' + res.status);
                    this._setHint('Structure rejected: ' + err, true);
                    return res.body;
                }
                this._structSeq += 1;
                const structId = this._structSeq;
                // SD-01: the per-structure CONSTRUCTABILITY EVIDENCE the backend derived from the REAL decompose
                // (volume/mass) + the terramechanics spine at the site slope (bearing/sinkage) + a derived
                // verdict. null on an older backend (pre-SD-01) -> the panel simply shows no evidence card.
                const evidence = (res.body && res.body.evidence) || null;
                const added = [];
                for (const o of orders) {
                    const mapX = coord[0] + o.x;      // local East offset -> map East (30135 is metric, north-up)
                    const mapY = coord[1] - o.y;      // local raster-down offset -> map North (y flips)
                    let ll;
                    try { ll = this.reproject([mapX, mapY], MAP_CRS, GEO_CRS); } catch (e) { ll = originLonlat; }
                    const ord = {
                        kind: o.kind, footprint_m2: o.footprint_m2, depth_m: o.depth_m,
                        coord: [mapX, mapY], lonlat: ll,
                        structId: structId, structName: name, action: o.action, note: o.note || ''
                    };
                    this.orders.push(ord); added.push(ord);
                }
                this.structures.push({
                    idx: structId, name: name, params: {...params},
                    coord: [coord[0], coord[1]], nOrders: added.length, evidence: evidence
                });
                this._addStructureFootprint(structId, name, added);
                this._refreshOrderMarkers();
                const nCut = added.filter((o) => o.kind === 'cut').length;
                const nFill = added.filter((o) => o.kind === 'fill').length;
                this._setHint('Placed ' + name.replace(/_/g, ' ') + ' -> ' + added.length +
                    ' mass-balanced order' + (added.length === 1 ? '' : 's') +
                    ' (' + nCut + ' cut / ' + nFill + ' fill) added to the queue. Place more, or press Plan mission.');
                return res.body;
            })
            .catch((e) => { this._setHint('Structure request failed: ' + e.message, true); });
    }

    // Draw the structure's footprint: a dashed steel-cyan bounding box (over its decomposed orders, each
    // padded by its footprint radius) with the structure name, so the whole build reads as one placed unit.
    _addStructureFootprint(structId, name, orders) {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        orders.forEach((o) => {
            const r = Math.sqrt(Math.max(o.footprint_m2, 1) / Math.PI);
            minX = Math.min(minX, o.coord[0] - r); maxX = Math.max(maxX, o.coord[0] + r);
            minY = Math.min(minY, o.coord[1] - r); maxY = Math.max(maxY, o.coord[1] + r);
        });
        if (!isFinite(minX)) { return; }
        const pad = 2.0;
        minX -= pad; minY -= pad; maxX += pad; maxY += pad;
        const ring = [[minX, minY], [maxX, minY], [maxX, maxY], [minX, maxY], [minX, minY]];
        const f = new Feature({geometry: new Polygon([ring])});
        f.set('structId', structId); f.set('label', name.replace(/_/g, ' '));
        this.structureSource.addFeature(f);
    }

    _structureStyle(feature) {
        return new Style({
            stroke: new Stroke({color: '#7cc6ff', width: 1.5, lineDash: [4, 4]}),
            fill: new Fill({color: 'rgba(124,198,255,0.06)'}),
            text: new Text({
                text: feature.get('label') || 'structure', offsetY: -7, overflow: true,
                font: '600 10px system-ui, sans-serif',
                fill: new Fill({color: '#9fd4ff'}), stroke: new Stroke({color: '#000', width: 3})
            })
        });
    }

    // Remove a placed structure (by array index) and every order it decomposed into, plus its footprint.
    removeStructure(i) {
        const st = this.structures[i];
        if (!st) { return; }
        this.orders = this.orders.filter((o) => o.structId !== st.idx);
        this.structures.splice(i, 1);
        this.structureSource.getFeatures().slice().forEach((f) => {
            if (f.get('structId') === st.idx) { this.structureSource.removeFeature(f); }
        });
        this._refreshOrderMarkers();
        this._setHint('Removed ' + st.name.replace(/_/g, ' ') + ' and its orders (' +
            this.structures.length + ' structure' + (this.structures.length === 1 ? '' : 's') + ' left).');
    }

    // --- Keep-out / no-go authoring ------------------------------------------------------------------
    // Toggle the no-go draw tool. Turning it on stops order-placing (map clicks now draw a shape, not an
    // order) and adds an OL Draw interaction of the matching geometry; the tool stays active for multiple
    // draws (click the tool again to stop), mirroring the cut/fill placing UX.
    setKeepoutTool(kind) {
        this.activeKind = null;                       // no-go drawing and order-placing are mutually exclusive
        this.structKind = null;                       // (as is structure-template placing)
        this.planHereMode = false;                    // (as is the plan-anywhere pick mode)
        const next = (this.koTool === kind) ? null : kind;
        this._deactivateDraw();                       // remove any prior interaction; sets koTool = null
        this.koTool = next;
        if (next) {
            this._draw = new Draw({source: this.keepoutSource, type: next === 'circle' ? 'Circle' : 'Polygon'});
            this._draw.on('drawend', (evt) => this._onDrawEnd(evt.feature, next));
            this.map.addInteraction(this._draw);
            this._setHint(next === 'circle'
                ? 'Draw a no-go CIRCLE: click the centre, move out, click again for the radius. Click the tool again to stop.'
                : 'Draw a no-go POLYGON: click each vertex, double-click to finish. Click the tool again to stop.');
        } else {
            this._setHint('No-go drawing off. Place orders, or Plan to route around the drawn no-go regions.');
        }
        this._emit();
    }
    _deactivateDraw() {
        if (this._draw) { this.map.removeInteraction(this._draw); this._draw = null; }
        this.koTool = null;
    }

    // GW-08: mint the backend edit session (idempotent). On success the keep-out set is owned by the server;
    // on failure we stay in client-only fallback (this.editSession = null).
    _ensureSession() {
        if (this.editSession) { return Promise.resolve(this.editSession); }
        return fetch('/api/edit/session', {method: 'POST'})
            .then((r) => { if (!r.ok) { throw new Error('HTTP ' + r.status); } return r.json(); })
            .then((d) => {
                if (!d || d.ok === false || !d.session) { throw new Error((d && d.error) || 'no session'); }
                this.editSession = d.session;
                this._adoptEditState(d);
                return this.editSession;
            })
            .catch(() => { this.editSession = null; /* client-only fallback */ return null; });
    }

    // Rebuild the render MIRROR (this.keepouts + the OL layer) from an authoritative edit-session response --
    // the backend is the source of truth, so the map is a pure render of body.features. Also mirrors the
    // monotonic version + audit tail into the panel state.
    _adoptEditState(body) {
        this.editVersion = Number(body.version) || 0;
        this.editAudit = Array.isArray(body.audit) ? body.audit : [];
        this.keepoutSource.clear();
        this.keepouts = [];
        for (const f of (body.features || [])) {
            let geom;
            if (f.kind === 'circle') { geom = new CircleGeom([f.cx, f.cy], f.r); }
            else { geom = new Polygon([f.ring]); }
            const feat = new Feature({geometry: geom});
            feat.set('label', f.fid); feat.set('fid', f.fid);
            this.keepoutSource.addFeature(feat);
            this.keepouts.push({idx: f.fid, fid: f.fid, kind: f.kind, feature: feat});
        }
        // Every edit-session response also carries the place-object marker set (state() includes markers), so
        // re-render the marker mirror from the authoritative set alongside the keep-outs.
        this._adoptMarkers(body.markers || []);
        // [GW-11 clause 4] publish the authoritative feature set on the shared WS features channel so the 3D
        // terrain panel (MissionTerrain3D) renders these keep-outs + markers in 3D within one refresh of any 2D
        // edit -- _adoptEditState runs on session load AND after every create / modify / delete / undo.
        WS.emitFeatures({features: body.features || [], markers: body.markers || []});
    }

    // The map-frame geometry (IAU_2015:30135 metres) for the backend create/modify body, read off an OL feature.
    _geomBody(feature, kind) {
        const g = feature.getGeometry();
        if (kind === 'circle') {
            const c = g.getCenter();
            return {kind: 'circle', cx: c[0], cy: c[1], r: g.getRadius()};
        }
        const ring = g.getCoordinates()[0] || [];
        const n = ring.length;
        const open = (n > 1 && ring[0][0] === ring[n - 1][0] && ring[0][1] === ring[n - 1][1])
            ? ring.slice(0, -1) : ring;                // OL closes the ring; the store wants an open ring
        return {kind: 'polygon', ring: open.map((p) => [p[0], p[1]])};
    }

    // A finished (drawn or programmatic) no-go feature WRITES THROUGH the backend edit-session create route
    // (GW-08): the server versions + audits it and becomes the source of truth; on the response we re-adopt
    // the authoritative set. If there is no session (offline), fall back to keeping the drawn feature locally
    // so the IDE still plans (client-only) -- degraded, not dead.
    _onDrawEnd(feature, kind) {
        return this._createKeepout(kind, this._geomBody(feature, kind), feature);
    }
    _createKeepout(kind, body, olFeature) {
        if (!this.editSession) {                       // client-only fallback (no backend session)
            return this._localFallbackAdd(kind, olFeature, body);
        }
        return fetch('/api/edit/session/' + encodeURIComponent(this.editSession) + '/keepout', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
        })
            .then((r) => r.json().then((d) => ({status: r.status, body: d})))
            .then((res) => {
                if (!res.body || res.body.ok === false) {
                    throw new Error((res.body && res.body.error) || ('HTTP ' + res.status));
                }
                this._adoptEditState(res.body);        // backend is the source of truth -> re-render the mirror
                this._setHint('No-go region added through the backend (v' + this.editVersion +
                    ', ' + this.keepouts.length + ' active). Draw more, undo, or press Plan mission.');
                this._emit();
                return res.body;
            })
            .catch((e) => {
                this._localFallbackAdd(kind, olFeature, body);   // keep the region locally so a plan still routes around it
                this._setHint('No-go saved locally (backend edit-session unavailable: ' + e.message + ').', true);
            });
    }
    // Client-only fallback: keep the region in the local mirror (and the OL layer) so plan()'s _keepoutsForFrame
    // path still serializes it into payload.keepouts. Used when there is no backend session.
    _localFallbackAdd(kind, olFeature, body) {
        this._koSeq += 1;
        const fid = 'loc' + this._koSeq;
        let feat = olFeature;
        if (!feat) {
            const geom = kind === 'circle'
                ? new CircleGeom([body.cx, body.cy], body.r) : new Polygon([body.ring]);
            feat = new Feature({geometry: geom});
            this.keepoutSource.addFeature(feat);
        }
        feat.set('label', fid); feat.set('fid', fid);
        this.keepouts.push({idx: fid, fid: fid, kind: kind, feature: feat});
        this._setHint('No-go region added (' + this.keepouts.length + ' drawn). Draw more, or press Plan mission.');
        this._emit();
        return Promise.resolve(null);
    }

    // Authoring drivers (headless proof + faithful to the Draw path): add a no-go at exact MAP coords. Return
    // the create promise so a proof can await the backend round-trip before reading keepoutCount/editState.
    addKeepoutCircle(center, radius) {
        return this._createKeepout('circle', {kind: 'circle', cx: center[0], cy: center[1], r: radius}, null);
    }
    addKeepoutPolygon(ring) {
        const open = ring.map((p) => [p[0], p[1]]);
        return this._createKeepout('polygon', {kind: 'polygon', ring: open}, null);
    }

    // Delete a keep-out through the backend DELETE route (by its backend fid); re-adopt the authoritative set.
    // A local-fallback region (fid 'loc…', no backend row) is just removed from the mirror.
    removeKeepout(fid) {
        const k = this.keepouts.find((x) => x.fid === fid);
        if (!k) { return Promise.resolve(); }
        if (!this.editSession || String(fid).startsWith('loc')) {
            try { this.keepoutSource.removeFeature(k.feature); } catch (e) { /* already gone */ }
            this.keepouts = this.keepouts.filter((x) => x.fid !== fid);
            this._setHint('No-go region removed (' + this.keepouts.length + ' left).');
            this._emit();
            return Promise.resolve();
        }
        return fetch('/api/edit/session/' + encodeURIComponent(this.editSession) + '/keepout/' +
            encodeURIComponent(fid), {method: 'DELETE'})
            .then((r) => r.json())
            .then((d) => {
                if (!d || d.ok === false) { throw new Error((d && d.error) || 'delete failed'); }
                this._adoptEditState(d);
                this._setHint('No-go region deleted through the backend (v' + this.editVersion + ', ' +
                    this.keepouts.length + ' left).');
                this._emit();
            })
            .catch((e) => this._setHint('Could not delete the no-go region: ' + e.message, true));
    }

    // Undo the LAST edit through the backend undo route (GW-08): the server applies the compensating inverse
    // from the audit's before/after and bumps the version; we re-adopt the authoritative set.
    undoEdit() {
        if (!this.editSession) { this._setHint('Undo needs the backend edit-session (unavailable).', true); return Promise.resolve(); }
        return fetch('/api/edit/session/' + encodeURIComponent(this.editSession) + '/undo', {method: 'POST'})
            .then((r) => r.json())
            .then((d) => {
                if (!d || d.ok === false) { this._setHint((d && d.error) || 'Nothing to undo.', true); return; }
                this._adoptEditState(d);
                const rv = d.undone ? d.undone.reverted_op : 'edit';
                this._setHint('Undid the last ' + rv + ' (v' + this.editVersion + ', ' +
                    this.keepouts.length + ' active).');
                this._emit();
            })
            .catch((e) => this._setHint('Undo failed: ' + e.message, true));
    }

    clearKeepouts() {
        // Delete every keep-out through the backend (each auditable + individually undoable), then re-adopt;
        // a local-only set is just cleared. Serial to keep the audit order deterministic.
        const backendFids = this.editSession ? this.keepouts.filter((k) => !String(k.fid).startsWith('loc'))
            .map((k) => k.fid) : [];
        this.keepouts = this.keepouts.filter((k) => String(k.fid).startsWith('loc') && this.editSession);
        if (!this.editSession || !backendFids.length) {
            this.keepouts = [];
            this.keepoutSource.clear();
            this._setHint('All no-go regions cleared.');
            this._emit();
            return Promise.resolve();
        }
        return backendFids.reduce((p, fid) => p.then(() =>
            fetch('/api/edit/session/' + encodeURIComponent(this.editSession) + '/keepout/' +
                encodeURIComponent(fid), {method: 'DELETE'}).then((r) => r.json()).then((d) => {
                if (d && d.ok !== false) { this._adoptEditState(d); }
            })), Promise.resolve())
            .then(() => { this._setHint('All no-go regions cleared (v' + this.editVersion + ').'); this._emit(); })
            .catch((e) => this._setHint('Could not clear all no-go regions: ' + e.message, true));
    }

    // The count of undoable edits (live create/modify/delete not yet undone) -> drives the panel Undo button.
    _undoableCount() {
        const undone = new Set(this.editAudit.filter((a) => a.op === 'undo').map((a) => a.target));
        return this.editAudit.filter((a) => ['create', 'modify', 'delete'].includes(a.op)
            && !undone.has(a.version)).length;
    }

    _koSummary(k) {
        const g = k.feature.getGeometry();
        if (k.kind === 'circle') { return 'circle · r ' + Math.round(g.getRadius()) + ' m'; }
        const ring = g.getCoordinates()[0] || [];
        return 'polygon · ' + Math.max(0, ring.length - 1) + ' pts';
    }

    // Convert the drawn no-go regions (map-CRS geometry) into the planner keep-out schema in the ORDER FRAME
    // -- the SAME y-flipped anchor affine the orders use (ox = X30135 - wc[0]; oy = wc[1] - Y30135). Matches
    // EXACTLY what lode/planner_routing.py:147 point_in_keepout / :158 _apply_keepouts parse:
    //   circle  -> {x, y, r}           (r is a distance -> unchanged by the y-flip)
    //   polygon -> {points:[[x,y],..]} (>= 3 verts; the even-odd test is affine-invariant so the flip is safe)
    _keepoutsForFrame(wc, predicate) {
        const out = [];
        for (const k of this.keepouts) {
            if (predicate && !predicate(k)) { continue; }   // caller may restrict to a subset (e.g. local-fallback 'loc…' fids)
            const g = k.feature.getGeometry();
            if (k.kind === 'circle') {
                const c = g.getCenter(), r = g.getRadius();
                if (r > 0) { out.push({x: round1(c[0] - wc[0]), y: round1(wc[1] - c[1]), r: round1(r)}); }
            } else {
                const ring = g.getCoordinates()[0] || [];
                const n = ring.length;
                // OL closes the ring (last vertex == first); drop the duplicate so the vertex count is honest.
                const open = (n > 1 && ring[0][0] === ring[n - 1][0] && ring[0][1] === ring[n - 1][1])
                    ? ring.slice(0, -1) : ring;
                const pts = open.map((p) => [round1(p[0] - wc[0]), round1(wc[1] - p[1])]);
                if (pts.length >= 3) { out.push({points: pts}); }
            }
        }
        return out;
    }

    // Lazily build a diagonal-hatch CanvasPattern for the distinct no-go fill (falls back to a translucent
    // red if the canvas is unavailable). Solid red stroke outlines the region.
    _keepoutStyle() {
        if (this._hatch === undefined) {
            try {
                const cv = document.createElement('canvas');
                cv.width = 8; cv.height = 8;
                const g = cv.getContext('2d');
                g.strokeStyle = 'rgba(224,64,58,0.85)'; g.lineWidth = 1.4;
                g.beginPath();
                g.moveTo(0, 8); g.lineTo(8, 0);
                g.moveTo(-2, 2); g.lineTo(2, -2);
                g.moveTo(6, 10); g.lineTo(10, 6);
                g.stroke();
                this._hatch = g.createPattern(cv, 'repeat');
            } catch (e) { this._hatch = null; }
        }
        return new Style({
            fill: new Fill({color: this._hatch || 'rgba(224,64,58,0.22)'}),
            stroke: new Stroke({color: '#e0403a', width: 2})
        });
    }

    // --- Placement: a map click -> a queued order (map coords + selenographic lon/lat) ----------------
    placeAt(coord) {
        if (!this.activeKind) { return; }
        let lonlat;
        try { lonlat = this.reproject(coord, MAP_CRS, GEO_CRS); }
        catch (e) { this._setHint('Could not reproject the click: ' + e.message, true); return; }
        if (this.activeKind === 'traverse') {
            // A traverse waypoint = a backend `goto` order (zero mass; the planner auto-chains consecutive
            // gotos into a path). Shares the SAME order queue + /api/plan path as cut/fill.
            this.orders.push(PlanTools.traverseOrder([coord[0], coord[1]], lonlat));
            this._refreshOrderMarkers();
            const nwp = this.orders.filter((o) => PlanTools.isTraverse(o)).length;
            this._setHint('Dropped traverse waypoint ' + nwp + '. Drop more to extend the path, use ' +
                'Return to lander to close it, or press Plan mission.');
            return;
        }
        this.orders.push({
            kind: this.activeKind, footprint_m2: this.footprint, depth_m: this.depth,
            coord: [coord[0], coord[1]], lonlat: lonlat
        });
        this._refreshOrderMarkers();
        this._setHint('Placed ' + this.activeKind + ' order · ' + this.orders.length + ' queued. ' +
            'Place more, or press Plan mission.');
    }

    removeOrder(i) { this.orders.splice(i, 1); this._refreshOrderMarkers(); this._emit(); }
    clearOrders() {
        this.orders = []; this.result = null; this.wc = null;
        this._resetRun();
        this.route = null; this._planOrders = null;
        this.structures = []; this.structureSource.clear();   // placed structures + their footprints go too
        this.orderSource.clear(); this.planSource.clear(); this.traverseSource.clear();
        this._setHint('Cleared. Pick a tool or structure and click the map to place orders. ' +
            '(Placed objects are kept — clear them from the palette.)');
    }

    _refreshOrderMarkers() {
        this.orderSource.clear();
        this.orders.forEach((o, i) => {
            const f = new Feature({geometry: new Point(o.coord)});
            f.set('kind', o.kind); f.set('label', String(i + 1));
            this.orderSource.addFeature(f);
        });
        // TRAVERSE path: connect the dropped goto waypoints in authorship order (the drive the planner chains).
        this.traverseSource.clear();
        const path = PlanTools.traversePath(this.orders);
        if (path.length > 1) {
            this.traverseSource.addFeature(new Feature({geometry: new LineString(path)}));
        }
        this._emit();
    }

    _orderMarkerStyle(feature) {
        const kind = feature.get('kind');
        const color = KIND_COLOR[kind] || '#ffd24a';
        // cut = square, fill = triangle, goto = small circle waypoint dot (the traverse path connects them).
        const image = kind === 'goto'
            ? new CircleStyle({radius: 5, fill: new Fill({color: color}), stroke: new Stroke({color: '#0a0d12', width: 1.5})})
            : new RegularShape({
                points: kind === 'cut' ? 4 : 3,
                radius: 7, angle: kind === 'cut' ? Math.PI / 4 : 0,
                fill: new Fill({color: color}), stroke: new Stroke({color: '#0a0d12', width: 1.5})
            });
        return new Style({
            image: image,
            text: new Text({
                text: String(feature.get('label') || ''), offsetY: -14,
                font: '600 11px system-ui, sans-serif',
                fill: new Fill({color: '#e8edf4'}), stroke: new Stroke({color: '#000', width: 3})
            })
        });
    }

    // --- TRAVERSE: return-to-lander ------------------------------------------------------------------
    // Append a goto waypoint at the lander/charger anchor (the order centroid) so the drive ends back at base.
    // The anchor = the SAME centroid /api/plan derives (planTools.centroidLonLat -> reproject), computed over
    // the CURRENT orders BEFORE appending, so the appended leg is a real "return" from the last waypoint home.
    returnToLander() {
        if (!this.orders.length) {
            this._setHint('Drop at least one order/waypoint first — the lander anchors at the work-area centre.', true);
            return;
        }
        const ll = PlanTools.centroidLonLat(this.orders);   // [meanLon, meanLat] = the lander/charger anchor
        if (!ll) { this._setHint('No orders to anchor the lander to.', true); return; }
        let coord;
        try { coord = this.reproject(ll, GEO_CRS, MAP_CRS); }
        catch (e) { this._setHint('Could not locate the lander: ' + e.message, true); return; }
        this.orders.push(PlanTools.traverseOrder([coord[0], coord[1]], ll));
        this._refreshOrderMarkers();
        this._setHint('Return-to-lander leg appended: the rover drives from the last waypoint back to the ' +
            'charger/lander at the work-area centre. Press Plan mission to route it.');
    }

    // --- PLACE OBJECT: drop a mission-object marker (persisted through the backend edit-session) ------
    // A place-object type is exclusive with the Cut/Fill/Traverse tools, the structure templates, and the
    // no-go Draw tool (only one placing mode owns the map click at a time).
    setObjectTool(otype) {
        this.activeKind = null;
        this.structKind = null;
        this.planHereMode = false;                    // place-object and the plan-anywhere pick are exclusive
        this._deactivateDraw();
        this.objectType = (this.objectType === otype) ? null : otype;
        if (this.objectType) {
            this._setHint('Click the map to place a ' + this.objectType +
                '. Click the button again to stop placing.');
        } else {
            this._setHint('Place-object off. Pick a tool, or Plan the mission.');
        }
        this._emit();
    }

    // Place the active object at a map click: POST /api/edit/session/{sid}/marker (versioned + audited through
    // the SAME edit-session store the keep-outs use, but as a POINT marker kept SEPARATE from the keep-out set
    // so it never routes the planner around it). Adopts the authoritative marker set on the response. FALLBACK:
    // with no backend session, keep the marker locally so the IDE still annotates (degraded, not dead). Returns
    // the fetch promise so a headless proof can await the round-trip.
    placeObject(coord) {
        if (!this.objectType) { return Promise.resolve(); }
        const otype = this.objectType;
        const label = otype.charAt(0).toUpperCase() + otype.slice(1) + ' ' + (this.markers.length + 1);
        let body;
        try { body = PlanTools.markerBody([coord[0], coord[1]], otype, label); }
        catch (e) { this._setHint('Could not place object: ' + e.message, true); return Promise.resolve(); }
        if (!this.editSession) { return this._localMarkerAdd(body); }
        return fetch('/api/edit/session/' + encodeURIComponent(this.editSession) + '/marker', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
        })
            .then((r) => r.json().then((d) => ({status: r.status, body: d})))
            .then((res) => {
                if (!res.body || res.body.ok === false) {
                    throw new Error((res.body && res.body.error) || ('HTTP ' + res.status));
                }
                this._adoptEditState(res.body);   // backend is the source of truth -> re-render keep-outs + markers
                this._setHint('Placed a ' + otype + ' through the backend (' + this.markers.length +
                    ' object' + (this.markers.length === 1 ? '' : 's') + '). Place more, or Plan the mission.');
                this._emit();
                return res.body;
            })
            .catch((e) => {
                this._localMarkerAdd(body);
                this._setHint('Object saved locally (backend edit-session unavailable: ' + e.message + ').', true);
            });
    }

    _localMarkerAdd(body) {
        this._locMarkerSeq += 1;
        const fid = 'locmk' + this._locMarkerSeq;
        const feat = new Feature({geometry: new Point([body.x, body.y])});
        feat.set('otype', body.otype); feat.set('label', body.label || body.otype); feat.set('fid', fid);
        this.markerSource.addFeature(feat);
        this.markers.push({fid: fid, otype: body.otype, label: body.label || body.otype,
            coord: [body.x, body.y], feature: feat});
        this._setHint('Object placed (' + this.markers.length + '). Place more, or Plan the mission.');
        this._emit();
        return Promise.resolve(null);
    }

    // Authoring driver (headless proof): drop an object of `otype` at exact MAP coords (same path as a click).
    placeObjectAt(otype, coord) { this.objectType = otype; return this.placeObject(coord); }

    // Delete a placed object through the backend DELETE route (by its backend fid); re-adopt the authoritative
    // set. A local-fallback marker ('locmk…', no backend row) is just removed from the mirror.
    removeMarker(fid) {
        const m = this.markers.find((x) => x.fid === fid);
        if (!m) { return Promise.resolve(); }
        if (!this.editSession || String(fid).startsWith('locmk')) {
            try { this.markerSource.removeFeature(m.feature); } catch (e) { /* already gone */ }
            this.markers = this.markers.filter((x) => x.fid !== fid);
            this._setHint('Object removed (' + this.markers.length + ' left).');
            this._emit();
            return Promise.resolve();
        }
        return fetch('/api/edit/session/' + encodeURIComponent(this.editSession) + '/marker/' +
            encodeURIComponent(fid), {method: 'DELETE'})
            .then((r) => r.json())
            .then((d) => {
                if (!d || d.ok === false) { throw new Error((d && d.error) || 'delete failed'); }
                this._adoptEditState(d);
                this._setHint('Object deleted through the backend (' + this.markers.length + ' left).');
                this._emit();
            })
            .catch((e) => this._setHint('Could not delete the object: ' + e.message, true));
    }

    // Re-render the marker MIRROR (this.markers + the OL layer) from an authoritative edit-session response
    // (body.markers). The backend is the source of truth; the map is a pure render of the marker set.
    _adoptMarkers(list) {
        this.markerSource.clear();
        this.markers = [];
        for (const m of (list || [])) {
            const feat = new Feature({geometry: new Point([m.x, m.y])});
            feat.set('otype', m.otype); feat.set('label', m.label || m.otype); feat.set('fid', m.fid);
            this.markerSource.addFeature(feat);
            this.markers.push({fid: m.fid, otype: m.otype, label: m.label || m.otype,
                coord: [m.x, m.y], feature: feat});
        }
    }

    _markerStyle(feature) {
        const otype = feature.get('otype') || 'object';
        const color = MARKER_COLOR[otype] || '#b47cff';
        return new Style({
            image: new RegularShape({
                points: 4, radius: 7, angle: Math.PI / 4,   // a diamond glyph
                fill: new Fill({color: color}), stroke: new Stroke({color: '#0a0d12', width: 1.5})
            }),
            text: new Text({
                text: feature.get('label') || otype, offsetY: -13, font: '600 10px system-ui, sans-serif',
                fill: new Fill({color: color}), stroke: new Stroke({color: '#000', width: 3})
            })
        });
    }

    // The order-frame serialization shared by plan() (-> /api/plan) and compareFutures() (-> /api/resync/compare).
    // Anchor (order-frame origin / charger) = the centroid of the placed orders in selenographic lon/lat,
    // reprojected to map coords so we know exactly where order-frame (0,0) sits on the map; every order is then an
    // anchor-relative x/y offset in metres (30135 East / y-flipped North -> the raster-down order frame the backend
    // planner expects). Throws if the anchor reprojection fails (each caller sets its own hint).
    _anchorAndOrders() {
        const meanLon = this.orders.reduce((s, o) => s + o.lonlat[0], 0) / this.orders.length;
        const meanLat = this.orders.reduce((s, o) => s + o.lonlat[1], 0) / this.orders.length;
        const wc = this.reproject([meanLon, meanLat], GEO_CRS, MAP_CRS);
        // cut / fill / goto all serialize through the ONE shared order-frame entry (planTools.orderFrameEntry),
        // so a traverse waypoint rides the exact same anchor affine + /api/plan path as a cut order.
        const orders = this.orders.map((o, i) => PlanTools.orderFrameEntry(o, i, wc));
        return {wc, meanLat, meanLon, orders};
    }

    // --- Plan: anchor at the order centroid, POST /api/plan, render the returned plan -----------------
    plan() {
        if (!this.orders.length) { this._setHint('Add at least one order first.', true); return Promise.resolve(); }
        // Anchor (order-frame origin / charger) = the centroid of the placed orders, in selenographic
        // lon/lat. Passed to /plan as M11 lat/lon so the planner anchors there; reprojected to map coords
        // so we know exactly where order-frame (0,0) sits on the map for both the POST offsets and the redraw.
        let frame;
        try { frame = this._anchorAndOrders(); }
        catch (e) { this._setHint('Could not anchor the work frame: ' + e.message, true); return Promise.resolve(); }
        const {wc, meanLat, meanLon, orders} = frame;
        const payload = {
            name: 'artemis-ide mission', body: 'moon', site: this.site,
            // DEPTH-2: the chosen solver + objective + slope budget (the /api/plan levers, plan.py:68,69,74),
            // replacing the former hardcoded nearest/time.
            algorithm: this.algorithm, objective: this.objective,
            max_traverse_slope_deg: this.maxSlopeDeg,
            // DEPTH-3: the fleet levers on the SAME POST. vehicles is a typed PlanRequest field (plan.py:72,
            // passed as MP.plan(vehicles=...)); charger_capacity is read off the mission dict (plan.py:75 ->
            // mission_from_dict, planner_model.py:367). Both default to 1 (== the legacy single-vehicle plan).
            vehicles: this.vehicles, charger_capacity: this.chargerCapacity,
            lat: meanLat, lon: meanLon,
            orders: orders   // CP-05: the anchor-relative order-frame orders (shared with compareFutures)
        };
        // GW-08 / ED-01: the keep-out set is owned by the backend edit session, so /plan READS it server-side
        // by the session id + the order-frame anchor (payload.anchor_xy = the map-coord anchor wc). The server
        // projects the session's map-frame keep-outs into the order frame (the same _keepoutsForFrame affine)
        // and folds them into the planner keep-outs -- so an edit-session keep-out routes the mission around it
        // through the EXACT same _apply_keepouts path as before. FALLBACK: with no backend session, serialize
        // the local mirror client-side into payload.keepouts (the pre-GW-08 behavior), so the IDE still routes.
        if (this.editSession && this.keepouts.length) {
            payload.edit_session = this.editSession;
            payload.anchor_xy = [wc[0], wc[1]];
            // [council correctness] Local-fallback keep-outs ('loc…' fids, drawn during a backend blip when a
            // /keepout POST failed) live ONLY in this client mirror -- the backend session never received them.
            // Fold them into payload.keepouts so the planner still routes AROUND an operator-drawn no-go; the
            // backend merges BOTH the session set and payload.keepouts (plan.py:_merge_session_keepouts:100).
            const localKos = this._keepoutsForFrame(wc, (k) => String(k.fid).startsWith('loc'));
            if (localKos.length) { payload.keepouts = localKos; }
        } else {
            const kos = this._keepoutsForFrame(wc);
            if (kos.length) { payload.keepouts = kos; }
        }
        // DEPTH-2: fold the resource budgets into the SAME POST as objective_constraints (the planner accepts
        // it via PlanRequest extra="allow", plan.py:64; parsed lode/planner_model.py:422-436). An empty set is
        // omitted so an unbudgeted plan is byte-identical to before.
        const oc = this._objectiveConstraints();
        if (Object.keys(oc).length) { payload.objective_constraints = oc; }
        this._lastPlanPayload = payload;   // exact POST body for the headless LIVE proof readback
        // Reuse the EXACT order-frame orders for the SIM run (POST /executive/run is anchored at the site DEM;
        // it carries no lat/lon field, so the run reuses these order-frame offsets -- the same queue shape the
        // OL viewer runs, gis/web/app.js:870-876). The rover animates on THIS plan's route regardless.
        this._planOrders = payload.orders;
        this.planning = true;
        // [council #57] Guard the plan against a site switch (or detach) landing before it resolves: capture the
        // request token + the site NOW. selectSite()/detach() bump the guard, so if either changed by the time the
        // planner returns, drop the response -- a stale plan can NEVER draw the old site's routes over the new site
        // or arm Run on a wrong-site plan. The site switch already reset this.planning, so bailing touches nothing.
        const tok = this._rg.next();
        const planSite = this.site;
        this._setHint('Running the planner on the real ' + this.site + ' DEM…');
        return fetch('/api/plan', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
        })
            .then((r) => r.text().then((t) => {
                let body = null;
                try { body = JSON.parse(t); } catch (e) { body = null; }
                return {status: r.status, body: body, raw: t};
            }))
            .then((res) => {
                if (!this._rg.current(tok) || this.site !== planSite) { return res.body; }   // superseded plan -> drop
                this.planning = false;
                if (!res.body || !res.body.ok) {
                    const err = (res.body && res.body.error) ||
                        (res.status >= 500 ? 'planner error (HTTP ' + res.status + ') — try moving the work area or reducing orders'
                            : 'HTTP ' + res.status);
                    this.result = {feasible: false, error: err};
                    this._setHint('Plan rejected: ' + err, true);
                    return res.body;
                }
                this._renderPlan(res.body, wc);
                return res.body;
            })
            .catch((e) => {
                if (!this._rg.current(tok) || this.site !== planSite) { return; }   // superseded plan -> don't clobber the current site
                this.planning = false;
                this.result = {feasible: false, error: e.message};
                this._setHint('Plan request failed: ' + e.message, true);
            });
    }

    // --- Forward-compare (CP-05): pick 2..5 candidate SEQUENCERS, re-simulate the CURRENT mission under each,
    // and rank the resulting plan FUTURES feasible-first with a recommendation. See the constructor block for
    // the endpoint contract. ----------------------------------------------------------------------------------

    // Toggle a candidate SEQUENCERS key in/out of the compare set (the backend caps candidates at 5, [:5]).
    toggleCompareCandidate(key) {
        const k = String(key);
        const i = this.compareCandidates.indexOf(k);
        if (i >= 0) {
            this.compareCandidates.splice(i, 1);
        } else {
            if (this.compareCandidates.length >= 5) {
                this._setHint('Forward-compare accepts up to 5 strategies at once.', true); return;
            }
            this.compareCandidates.push(k);
        }
        this._emit();
    }

    // Re-simulate the CURRENT authored orders under every selected candidate and rank the futures. Reuses the
    // EXACT order-frame orders plan() serializes for /api/plan; the mission carries a charger at the (0,0)
    // anchor -- the {name,body,charger,orders} shape /resync/compare's mission_from_dict expects. The endpoint
    // does not take a site DEM (it holds every lever but the sequencer constant), so this is a fast
    // strategy-only forward comparison, not the site-anchored full plan.
    compareFutures() {
        if (!this.orders.length) { this._setHint('Add at least one order first.', true); return Promise.resolve(); }
        const cands = this.compareCandidates.slice();
        if (cands.length < 2) { this._setHint('Pick at least 2 strategies to compare.', true); return Promise.resolve(); }
        let frame;
        try { frame = this._anchorAndOrders(); }
        catch (e) { this._setHint('Could not anchor the work frame: ' + e.message, true); return Promise.resolve(); }
        const body = {
            mission: {name: 'artemis-ide compare', body: 'moon', charger: [0, 0], orders: frame.orders},
            candidates: cands, objective: this.objective
        };
        this._lastComparePayload = body;   // exact POST body for the headless LIVE proof readback
        this.comparing = true; this.compareResult = null; this.compareErr = null;
        this._setHint('Forward-comparing ' + cands.length + ' strategies on the conserved planner…');
        return fetch('/api/resync/compare', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
        })
            .then((r) => r.text().then((t) => {
                let b = null;
                try { b = JSON.parse(t); } catch (e) { b = null; }
                return {status: r.status, body: b};
            }))
            .then((res) => {
                this.comparing = false;
                if (!res.body || !res.body.ok) {
                    const err = (res.body && res.body.error) ||
                        (res.status >= 500 ? 'compare error (HTTP ' + res.status + ')' : 'HTTP ' + res.status);
                    this.compareErr = err;
                    this._setHint('Compare rejected: ' + err, true);
                    this._emit();
                    return res.body;
                }
                this.compareResult = res.body;   // {objective, futures:[...], recommended}
                const rec = res.body.recommended;
                this._setHint(rec
                    ? ('Forward-compare: ' + rec + ' recommended (feasible-first over ' + (res.body.futures || []).length + ' futures).')
                    : 'Forward-compare complete — no candidate was feasible.', !rec);
                this._emit();
                return res.body;
            })
            .catch((e) => {
                this.comparing = false; this.compareErr = e.message;
                this._setHint('Compare request failed: ' + e.message, true);
                this._emit();
            });
    }

    // Adopt the recommended algorithm into the Plan controls (this.algorithm), so the next Plan routes it. The
    // recommendation is the feasible-first head (a real SEQUENCERS key), so it is a valid Algorithm-select value.
    adoptRecommended() {
        const rec = this.compareResult && this.compareResult.recommended;
        if (!rec) { return; }
        this.algorithm = String(rec);
        this._setHint('Adopted ' + rec + ' into the plan controls — hit Plan mission to route it.');
        this._emit();
    }

    // Clear the compare result (keeps the selected candidates so the operator can re-run).
    clearCompare() { this.compareResult = null; this.compareErr = null; this._emit(); }

    _orderToMap(wc, ox, oy) { return [wc[0] + ox, wc[1] - oy]; }

    _renderPlan(resp, wc) {
        this.wc = wc;
        this.planSource.clear();
        this._resetRun();                 // a fresh plan clears any prior run's rover/trail/telemetry
        const pir = resp.plan_ir || {};
        const feasible = resp.feasible !== false && pir.feasible !== false;
        // DEPTH-3: colour each GoTo drive leg by its vehicle id (plan_ir action `vehicle`, 0-based). A route
        // dash marks an infeasible plan. vehicleColor(0) == the legacy gold, so a single-rover plan is
        // rendered exactly as before; a fleet gets one distinct colour per rover.
        const routeStyleFor = (veh) => new Style({
            stroke: new Stroke({color: vehicleColor(veh), width: 2.5, lineDash: feasible ? undefined : [6, 5]})
        });
        const haulStyle = new Style({stroke: new Stroke({color: '#8fb8ff', width: 2, lineDash: [2, 4]})});
        // The SIM-run rover animates one marker; keep a per-vehicle route array so the primary rover (vehicle 0)
        // drives its OWN track, and fall back to the stitched order for a single-vehicle plan (byte-identical).
        const routeByVeh = {};            // vehicle id -> ordered drive route in map coords
        (pir.actions || []).forEach((a) => {
            if (a.op === 'GoTo' && Array.isArray(a.waypoints) && a.waypoints.length > 1) {
                const veh = Number.isFinite(a.vehicle) ? a.vehicle : 0;
                const line = a.waypoints.map((w) => this._orderToMap(wc, w[0], w[1]));
                const rm = (routeByVeh[veh] = routeByVeh[veh] || []);
                line.forEach((p) => {     // append, dropping a duplicate shared endpoint between this rover's legs
                    const last = rm[rm.length - 1];
                    if (!last || last[0] !== p[0] || last[1] !== p[1]) { rm.push(p); }
                });
                const f = new Feature({geometry: new LineString(line)});
                f.set('vehicle', veh);
                f.setStyle(routeStyleFor(veh)); this.planSource.addFeature(f);
            } else if (a.op === 'CutHaulFill' && a.site && a.dest) {
                const s = this._orderToMap(wc, a.site[0], a.site[1]);
                const d = this._orderToMap(wc, a.dest[0], a.dest[1]);
                const hf = new Feature({geometry: new LineString([s, d])});
                hf.setStyle(haulStyle); this.planSource.addFeature(hf);
            }
        });
        // Stitch the per-vehicle routes (vehicle order) into the single SIM-run animation track. For a
        // single-vehicle plan this is exactly the legacy route (one vehicle -> one polyline); for a fleet the
        // SIM rover drives the concatenated tracks (Run-SIM stays a single-marker desktop_sil, unchanged).
        const routeMap = [];
        Object.keys(routeByVeh).map(Number).sort((a, b) => a - b).forEach((veh) => {
            routeByVeh[veh].forEach((p) => {
                const last = routeMap[routeMap.length - 1];
                if (!last || last[0] !== p[0] || last[1] !== p[1]) { routeMap.push(p); }
            });
        });
        this.route = routeMap;            // retained so the operator can now RUN the plan as a SIM mission
        // Charger = order-frame origin (plan_ir.frame.charger, [0,0]) = the anchor.
        const ch = (pir.frame && pir.frame.charger) || [0, 0];
        const charger = new Feature({geometry: new Point(this._orderToMap(wc, ch[0], ch[1]))});
        charger.setStyle(new Style({
            image: new RegularShape({
                points: 4, radius: 6, angle: 0,
                fill: new Fill({color: '#7fe0a8'}), stroke: new Stroke({color: '#0a0d12', width: 1.5})
            }),
            text: new Text({
                text: 'charger', offsetY: 14, font: '600 10px system-ui',
                fill: new Fill({color: '#7fe0a8'}), stroke: new Stroke({color: '#000', width: 3})
            })
        }));
        this.planSource.addFeature(charger);

        // Fit the view to the plan (work-area scale) so the route is visible.
        const ext = this.planSource.getExtent();
        if (ext && isFinite(ext[0])) {
            this.map.getView().fit(ext, {padding: [80, 80, 80, 80], maxZoom: 20, duration: 400});
        }

        // Summary from the REAL response (typed PlanResult + totals) -- the panel reads this.
        const pr = resp.plan_result || {}, t = resp.totals || {};
        this.result = {
            feasible: feasible,
            n_orders: pr.n_orders != null ? pr.n_orders : this.orders.length,
            vehicles: pr.vehicles != null ? pr.vehicles : 1,
            makespan_s: pr.makespan_s != null ? pr.makespan_s : (t.makespan_s || t.time_s || 0),
            energy_j: pr.energy_j != null ? pr.energy_j : (t.energy_J || 0),
            mass_moved_kg: pr.mass_moved_kg != null ? pr.mass_moved_kg : ((t.cut_kg || 0) + (t.fill_kg || 0)),
            distance_m: t.distance_m || 0,
            recharges: pr.recharges != null ? pr.recharges : (t.charges || 0),
            drum_cycles: pr.drum_cycles != null ? pr.drum_cycles : (t.drum_cycles || 0),
            // DEPTH-2: echo the RESOLVED levers straight from the response. resolved_algorithm is the solver
            // the planner actually ran (e.g. auto -> brute/held_karp_lk/lk, plan.py:370 / planner_assembly.py:540);
            // totals.objective is the objective it optimized (planner_assembly.py:545). optimality is the
            // exact/heuristic label. max_slope_deg + budgets echo the operator's request for verification.
            algorithm: pr.resolved_algorithm || t.resolved_algorithm || t.algorithm || '—',
            objective: t.objective || this.objective || '—',
            optimality: t.optimality || '',
            max_slope_deg: this.maxSlopeDeg,
            budgets: this._objectiveConstraints(),
            infeasible_reasons: resp.infeasible_reasons || [],
            pdf: resp.pdf ? ('/api' + resp.pdf) : null,
            terrain_source: resp.terrain_source || '',
            // DEPTH-3 fleet summary — VIEWS of the real plan_multi aggregate (lode/planner_assembly.py). The
            // per-vehicle allocation is totals.vehicles_detail (:382): each rover's own trip count / time /
            // energy / distance / charges + its charger-queue wait. makespan_s is the fleet wall-clock = MAX
            // per-vehicle time (:397); energy_j (the headline above) is the fleet-summed energy. charger_*
            // fields surface shared-charger contention (:398,408). Each row carries the SAME vehicleColor()
            // the map route uses, so the panel legend swatch matches the drawn route. Empty for 1 vehicle.
            vehicles_detail: (t.vehicles_detail || []).map((d) => ({
                vehicle: d.vehicle, n_trips: d.n_trips, time_s: d.time_s, energy_J: d.energy_J,
                distance_m: d.distance_m, charges: d.charges, charger_wait_s: d.charger_wait_s,
                color: vehicleColor(d.vehicle)
            })),
            makespan_parallel_s: t.makespan_parallel_s != null ? t.makespan_parallel_s : null,
            charger_conflicts: t.charger_conflicts != null ? t.charger_conflicts : null,
            charger_wait_s: t.charger_wait_s != null ? t.charger_wait_s : null,
            charger_capacity: this.chargerCapacity
        };
        // DEPTH-4: read-only "Plan detail" view-model of what /api/plan ALREADY returns but the panel
        // ignored -- the executable Plan IR, the acceptance/validation block, and the timeline/endurance.
        // Pure surfacing: no extra POST, no synthetic fields; every value is projected straight from the
        // real /plan response (stewie/server/routers/plan.py:371-393). Attached to result so _emit carries it.
        this.result.detail = this._planDetail(resp);
        const nVeh = (this.result && this.result.vehicles) || 1;
        this._setHint(feasible
            ? (nVeh > 1
                ? 'Plan rendered: ' + nVeh + ' rovers, each route in its own colour (see the fleet summary); ' +
                  'haul = blue-dashed, charger = green. Press Run mission (SIM) to execute it.'
                : 'Plan rendered: route = gold, haul = blue-dashed, charger = green. Press Run mission (SIM) to execute it.')
            : 'Infeasible plan rendered (route dashed). See the reasons below.', !feasible);
    }

    // --- Plan detail (DEPTH-4): read-only projection of the /plan response fields the panel didn't surface.
    // Compact + serializable (dropped the GoTo waypoint polyline the map already draws). Cited keys:
    //   PLAN IR      resp.plan_ir            (stewie/server/routers/plan.py:390; built lode/planner_views.py:413-533)
    //                  .plan_id/.schema_version/.feasible/.expect + .actions[] (typed GoTo/Excavate/CutHaulFill/
    //                  Import/Sinter, planner_views.py:456-504) + .precedence[] (planner_views.py:508). When the
    //                  plan is infeasible the backend suppresses the IR (plan.py:342-345): {executable:false,
    //                  feasible:false, infeasible_reasons[], actions:[], note}.
    //   VALIDATION   resp.validation         (plan.py:385; lode/planner_acceptance.validate_plan:224-269 return)
    //   ORDERED      resp.ordered_acceptance (plan.py:391; H-07 ordered IR-replay verdict)
    //   TIMELINE     resp.timeline           (plan.py:386; lode/mission_planner.build_timeline:330-338 frames)
    //   ENDURANCE    resp.endurance          (plan.py:387; lode/planner_endurance.endurance:148-192 return)
    _planDetail(resp) {
        const pir = resp.plan_ir || {};
        const v = resp.validation || null;
        const oa = resp.ordered_acceptance || null;
        const tl = resp.timeline || null;
        const en = resp.endurance || null;
        // PLAN IR: the ordered typed-action step list + plan_id + precedence DAG + headline expect.
        const ir = {
            plan_id: pir.plan_id || null,
            schema_version: pir.schema_version || null,
            executable: pir.executable !== false && pir.feasible !== false,   // suppressed IR sets executable:false
            note: pir.note || null,
            infeasible_reasons: pir.infeasible_reasons || [],
            vehicles: pir.vehicles || 1,
            algorithm: pir.algorithm || null,
            objective: pir.objective || null,
            expect: pir.expect || null,
            precedence: pir.precedence || [],
            steps: (pir.actions || []).map((a) => ({
                id: a.id, op: a.op, vehicle: (a.vehicle != null ? a.vehicle : 0),
                mass_kg: (a.mass_kg != null ? a.mass_kg : null),
                loads: (a.loads || 0), haul_m: (a.haul_m != null ? a.haul_m : null),
                orders: (a.actions || []),
                distance_m: (a.expect && a.expect.distance_m != null ? a.expect.distance_m : null),
                duration_s: (a.expect ? a.expect.duration_s : null),
                energy_J: (a.expect ? a.expect.energy_J : null),
                reached: (a.reached != null ? a.reached : null)
            }))
        };
        // VALIDATION: the as-built acceptance checklist (pass/fail booleans + the mass ledger).
        const validation = v ? {
            feasible: v.feasible, mass_conserved: v.mass_conserved,
            as_built_pass: v.as_built_pass, as_built_flatness_rmse_m: v.as_built_flatness_rmse_m,
            as_built_tol_m: v.as_built_tol_m, as_built_on_real_dem: v.as_built_on_real_dem,
            repose_pass: v.repose_pass, repose_limit_deg: v.repose_limit_deg,
            berm_profile_pass: v.berm_profile_pass, bearing_pass: v.bearing_pass,
            slope_violations: (v.slope_violations || []).length,
            off_dem_orders: (v.off_dem_orders || []).length,
            planned_cut_kg: v.planned_cut_kg, executed_cut_kg: v.executed_cut_kg,
            planned_fill_kg: v.planned_fill_kg, executed_fill_kg: v.executed_fill_kg,
            drum_capacity_kg: v.drum_capacity_kg, shuttle_cycles_est: v.shuttle_cycles_est
        } : null;
        const ordered = oa ? {
            executes_ordered_ir: oa.executes_ordered_ir, feasible: oa.feasible,
            mass_conserved: oa.mass_conserved, shuttle_cycles: oa.shuttle_cycles, placed_kg: oa.placed_kg,
            max_simultaneous_drum_kg: oa.max_simultaneous_drum_kg
        } : null;
        // TIMELINE: makespan + per-phase duration breakdown (drive/work/charge) + battery-fraction envelope,
        // reduced from the real per-segment sim frames (each carries t0/t1/phase/batt0_frac/batt1_frac).
        let timeline = null;
        if (tl && Array.isArray(tl.frames)) {
            const byPhase = {}; const order = [];
            let bmin = null, bmax = null;
            tl.frames.forEach((f) => {
                if (!(f.phase in byPhase)) { byPhase[f.phase] = 0; order.push(f.phase); }
                byPhase[f.phase] += (f.t1 - f.t0);
                const lo = Math.min(f.batt0_frac, f.batt1_frac), hi = Math.max(f.batt0_frac, f.batt1_frac);
                bmin = (bmin == null) ? lo : Math.min(bmin, lo);
                bmax = (bmax == null) ? hi : Math.max(bmax, hi);
            });
            timeline = {
                duration_s: tl.duration_s, n_frames: tl.frames.length,
                phases: order.map((p) => ({phase: p, dur_s: byPhase[p]})),
                batt_min_frac: bmin, batt_max_frac: bmax
            };
        }
        // ENDURANCE: single-sortie reachability + the energy-driver verdict (conops.drums_dominate).
        const endurance = en ? {
            range_flat_reserve_km: (en.range_flat_reserve_km != null ? en.range_flat_reserve_km : null),
            range_slopeslip_km: (en.range_slopeslip_km != null ? en.range_slopeslip_km : null),
            duration_flat_h: (en.duration_flat_h != null ? en.duration_flat_h : null),
            work_area_median_slope_deg: (en.work_area_median_slope_deg != null ? en.work_area_median_slope_deg : null),
            drums_dominate: (en.conops ? en.conops.drums_dominate : null),
            fits_in_window: (en.timescale ? en.timescale.fits_in_window : null),
            day_label: (en.timescale ? en.timescale.day_label : null)
        } : null;
        const schedule = this._schedule(resp);
        return {ir, validation, ordered, timeline, endurance, schedule};
    }

    // --- Schedule / Gantt (DEPTH-5): the mission timeline as a phase-coloured schedule the panel draws.
    // PURE REBIND of data already in the /plan response — nothing recomputed or fabricated. Two views:
    //   • single-vehicle -> the aggregate MISSION TIMELINE: the sim's per-segment frames (resp.timeline.frames,
    //     lode/mission_planner.build_timeline:330-338 — each carries t0/t1/phase/batt0_frac/batt1_frac; phase
    //     ∈ drive/charge/wait/dig/offload/sinter, lode/planner_sim.py:53,79,140,171-178) reduced to phase RUNS
    //     (consecutive same-phase frames merged) on a monotonic 0->makespan axis + a downsampled battery-
    //     fraction envelope. Faithful: the frames ARE the executed sim, incl. the charge phases.
    //   • fleet (vehicles>1) -> per-vehicle SWIM-LANES: the plan IR actions (resp.plan_ir.actions,
    //     lode/planner_views.py:456-504) grouped by their 0-based `vehicle` id (:440,492), each segment sized by
    //     expect.duration_s (:459,499) and coloured by op. A fleet's timeline frames are per-vehicle-LOCAL and
    //     concatenated (lode/planner_assembly.py:376 all_tl), i.e. NOT one monotonic clock, so the honest
    //     per-rover view is the IR-action lanes, each laid from t=0 to its own total (recharges are
    //     precondition-driven, NOT positional IR actions, so a lane shows drive+work; the charge phases live in
    //     the single-vehicle aggregate timeline). Each lane's colour = vehicleColor(veh) = the SAME map route.
    _schedule(resp) {
        const pir = resp.plan_ir || {};
        const tl = resp.timeline || null;
        const pr = resp.plan_result || {}, t = resp.totals || {};
        const vehicles = pir.vehicles || t.vehicles || pr.vehicles || 1;
        // axis extent: the fleet wall-clock makespan (max per-vehicle time, planner_assembly.py:397) if given,
        // else totals.time_s, else the aggregate timeline duration.
        const makespanS = (pr.makespan_s != null) ? pr.makespan_s
            : (t.makespan_s != null ? t.makespan_s
                : (t.time_s != null ? t.time_s : (tl && tl.duration_s != null ? tl.duration_s : 0)));
        // aggregate mission-timeline phase runs + battery envelope (one monotonic clock; faithful for 1 vehicle)
        let timeline = null;
        if (tl && Array.isArray(tl.frames) && tl.frames.length) {
            const frames = tl.frames;
            const segments = [];
            frames.forEach((f) => {   // RLE: merge consecutive same-phase frames into one run
                const last = segments[segments.length - 1];
                if (last && last.phase === f.phase && Math.abs(last.t1 - f.t0) < 1e-3) { last.t1 = f.t1; }
                else { segments.push({phase: f.phase, t0: f.t0, t1: f.t1}); }
            });
            // battery envelope: downsample frames to <=120 time-groups, each carrying its time width + min frac.
            const N = frames.length, CAP = 120, step = Math.max(1, Math.ceil(N / CAP));
            const batt = [];
            for (let i = 0; i < N; i += step) {
                let w = 0, lo = 1;
                for (let j = i; j < Math.min(N, i + step); j++) {
                    w += Math.max(0, frames[j].t1 - frames[j].t0);
                    lo = Math.min(lo, frames[j].batt0_frac, frames[j].batt1_frac);
                }
                batt.push({w: w, frac: lo});
            }
            timeline = {
                duration_s: (tl.duration_s != null ? tl.duration_s
                    : (segments.length ? segments[segments.length - 1].t1 : 0)),
                segments: segments, batt: batt
            };
        }
        // per-vehicle swim-lanes from the plan IR actions (grouped by the 0-based vehicle id)
        const byVeh = {}; const order = [];
        (pir.actions || []).forEach((a) => {
            const veh = Number.isFinite(a.vehicle) ? a.vehicle : 0;
            if (!(veh in byVeh)) { byVeh[veh] = []; order.push(veh); }
            const dur = (a.expect && a.expect.duration_s != null) ? a.expect.duration_s : 0;
            byVeh[veh].push({op: a.op, dur_s: dur});
        });
        const lanes = order.sort((x, y) => x - y).map((veh) => ({
            vehicle: veh, color: vehicleColor(veh),
            total_s: byVeh[veh].reduce((sum, x) => sum + (x.dur_s || 0), 0),
            segments: byVeh[veh]
        }));
        return {makespan_s: makespanS, vehicles: vehicles, timeline: timeline, lanes: lanes};
    }

    // =====================================================================================================
    // RUN-SIM (T10) — run the rendered plan as a NON-DESTRUCTIVE desktop_sil execution via the REAL backend
    // (POST /api/executive/run, key injected server-side by the artemis nginx), subscribe to the run's
    // Server-Sent-Events telemetry (/api/executive/run/{id}/stream), and animate the rover along the REAL
    // planned route as each execution leg arrives. The stream carries per-leg EVENTS (kind/detail/outcome/
    // t_s), NOT x/y telemetry, so the rover is placed on the plan's REAL trajectory and advanced by real leg
    // events -- no synthetic coordinates. On completion the panel shows the run summary (executability /
    // physics tier / energy residual / live token) + the /api/evidence bundle. SIM-labeled throughout; the
    // whole /executive surface is director-gated on the backend and this never touches the live-rover path.
    // Verbatim port of Frontend A's gis/web/app.js:676-914. See §D-3 (read-only evidence vs command).
    // =====================================================================================================

    _resetRun() {
        if (this.run.es) { try { this.run.es.close(); } catch (e) { /* already closed */ } }
        if (this._animRaf) { cancelAnimationFrame(this._animRaf); this._animRaf = 0; }
        // [council bug] revoke the prior run's evidence object URL before dropping the reference, else the backing
        // Blob is pinned for the page lifetime (a leak per SIM-run / per _resetRun that replaces this.run).
        if (this.run.evidence && this.run.evidence.navUrl) {
            try { URL.revokeObjectURL(this.run.evidence.navUrl); } catch (e) { /* noop */ }
        }
        this.roverSource.clear(); this.trailSource.clear();
        this._roverFeat = null; this._trailFeat = null;
        this._animFrom = 0; this._animTo = 0;
        this.run = this._emptyRun();
    }

    // Cumulative arc-length of the route so a 0..1 fraction maps to a real point ON the planned path.
    _buildArcLength() {
        const r = this.route || [];
        const cum = [0];
        for (let i = 1; i < r.length; i++) {
            const dx = r[i][0] - r[i - 1][0], dy = r[i][1] - r[i - 1][1];
            cum.push(cum[i - 1] + Math.sqrt(dx * dx + dy * dy));
        }
        this.run.cumdist = cum; this.run.len = cum[cum.length - 1] || 0;
    }
    _pointAtFraction(f) {
        const r = this.route || [];
        if (!r.length) { return null; }
        if (r.length === 1 || this.run.len === 0) { return r[0].slice(); }
        f = Math.max(0, Math.min(1, f));
        const target = f * this.run.len, cum = this.run.cumdist;
        for (let i = 1; i < r.length; i++) {
            if (cum[i] >= target) {
                const seg = cum[i] - cum[i - 1];
                const t = seg > 0 ? (target - cum[i - 1]) / seg : 0;
                return [r[i - 1][0] + (r[i][0] - r[i - 1][0]) * t,
                    r[i - 1][1] + (r[i][1] - r[i - 1][1]) * t];
            }
        }
        return r[r.length - 1].slice();
    }
    // Trail = the real planned route resampled from 0 up to the current fraction.
    _trailUpTo(f) {
        const r = this.route || [];
        if (r.length < 2 || this.run.len === 0) { return r.slice(); }
        const target = Math.max(0, Math.min(1, f)) * this.run.len, cum = this.run.cumdist, out = [r[0]];
        for (let i = 1; i < r.length; i++) {
            if (cum[i] < target) { out.push(r[i]); } else { out.push(this._pointAtFraction(f)); break; }
        }
        return out;
    }

    _setRoverFraction(f) {
        const pt = this._pointAtFraction(f);
        if (!pt) { return; }
        if (!this._roverFeat) { this._roverFeat = new Feature(); this.roverSource.addFeature(this._roverFeat); }
        this._roverFeat.setGeometry(new Point(pt));
        const trail = this._trailUpTo(f);
        if (!this._trailFeat) { this._trailFeat = new Feature(); this.trailSource.addFeature(this._trailFeat); }
        if (trail.length >= 2) { this._trailFeat.setGeometry(new LineString(trail)); }
        this.run.lastPose = pt;
    }
    // Smoothly tween the rover from its current fraction to `f` over _animDur so the motion reads as driving.
    _animateRoverTo(f) {
        if (this._animRaf) { cancelAnimationFrame(this._animRaf); }
        this._animFrom = this._animTo; this._animTo = f; this._animStart = performance.now();
        const step = (now) => {
            const t = Math.min(1, (now - this._animStart) / this._animDur);
            this._setRoverFraction(this._animFrom + (this._animTo - this._animFrom) * t);
            if (t < 1) { this._animRaf = requestAnimationFrame(step); } else { this._animRaf = 0; }
        };
        this._animRaf = requestAnimationFrame(step);
    }

    _onStreamEvent(ev) {
        let d;
        try { d = JSON.parse(ev.data); } catch (e) { return; }
        if (d.done) {
            this.run.terminal = d.safed ? 'safed'
                : (d.final_state === 'completed' ? 'completed' : (d.final_state || 'done'));
            this.run.legsSeen = this.run.total || this.run.legsSeen;
            this.run.running = false;
            if (this.run.terminal === 'completed') { this._animateRoverTo(1); }   // finish the traverse to the end
            if (this.run.es) { try { this.run.es.close(); } catch (e) { /* closed */ } this.run.es = null; }
            this._emit();
            this._loadEvidence();
            return;
        }
        if (d.kind === 'leg') {
            this.run.legsSeen = Math.max(this.run.legsSeen,
                (typeof d.t_s === 'number' ? d.t_s + 1 : this.run.legsSeen + 1));
            this.run.lastEvent = 'leg ' + (this.run.legsSeen - 1) + ': ' + (d.outcome || '') +
                (d.detail ? ' · ' + d.detail : '');
            if (this.run.total) { this._animateRoverTo(Math.min(1, this.run.legsSeen / this.run.total)); }
        } else if (d.kind === 'safe') {
            this.run.lastEvent = d.detail || 'watchdog safed';
        } else if (d.kind === 'acceptance') {
            this.run.lastEvent = d.detail || 'as-built acceptance';
        }
        this._emit();
    }

    // On completion, link the keyless /api/evidence navigation-evidence bundle (accuracy/precision blurb +
    // a downloadable JSON) alongside the mission-report PDF. Structured for the React panel (no HTML string).
    _loadEvidence() {
        return FT.fetchWithTimeout('/api/evidence', {}, FT.DEFAULT_MS)
            .then((r) => (r.ok ? r.json() : null))
            .then((j) => {
                if (!j || !j.ok) { return; }
                const cmp = j.accuracy_precision || {}, keys = Object.keys(cmp);
                let blurbKey = null, blurbVal = null;
                if (keys.length) {
                    const k0 = keys[0], m = cmp[k0] || {};
                    const acc = (m.accuracy_m != null) ? m.accuracy_m + ' m'
                        : (m.rmse_m != null ? m.rmse_m + ' m' : '');
                    blurbKey = k0; blurbVal = acc || '—';
                }
                let navUrl = null;
                try {
                    // [council bug] revoke a prior evidence URL (if any) before minting a new one, so repeated
                    // plan/run cycles don't accumulate blob URLs pinned for the page lifetime.
                    if (this.run.evidence && this.run.evidence.navUrl) {
                        try { URL.revokeObjectURL(this.run.evidence.navUrl); } catch (e2) { /* noop */ }
                    }
                    const blob = new Blob([JSON.stringify(j, null, 2)], {type: 'application/json'});
                    navUrl = URL.createObjectURL(blob);
                } catch (e) { navUrl = null; }
                this.run.evidence = {
                    blurbKey, blurbVal, navUrl,
                    pdfUrl: (this.result && this.result.pdf) ? this.result.pdf : null
                };
                this._emit();
            })
            .catch(() => { /* evidence is a bonus over the run summary; never fail the run on it */ });
    }

    runMission() {
        if (!this.route || !this.route.length || !this._planOrders) {
            this._setHint('Plan a feasible mission first, then run it.', true); return Promise.resolve();
        }
        this._resetRun();
        this._buildArcLength();
        this._setRoverFraction(0);                 // rover starts at the charger / route origin
        this.run.running = true;
        this._setHint('Submitting the SIM run to the executive…');
        this._emit();
        const payload = {
            orders: this._planOrders, body: 'moon', site: this.site, mission_id: 'artemis-ide run'
        };
        return fetch('/api/executive/run', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
        })
            .then((r) => r.json().then((b) => ({status: r.status, body: b})))
            .then((res) => {
                if (!res.body || !res.body.ok || !res.body.run_id) {
                    this.run.running = false; this.run.terminal = 'error';
                    this.run.lastEvent = (res.body && res.body.error) || ('HTTP ' + res.status);
                    this._setHint('SIM run rejected: ' + this.run.lastEvent, true);
                    return res.body;
                }
                this.run.id = res.body.run_id;
                this.run.total = res.body.n_legs_total || 0;
                this.run.result = res.body;
                this._setHint('SIM run ' + this.run.id + ' executing — watch the rover drive the route.');
                // Subscribe to the run's live telemetry. interval_s paces the replay so the rover visibly
                // drives; the key is injected by nginx (same-origin GET, the browser never holds it).
                const url = '/api/executive/run/' + encodeURIComponent(this.run.id) + '/stream?interval_s=0.5';
                const es = new EventSource(url);
                this.run.es = es;
                es.onmessage = (ev) => this._onStreamEvent(ev);
                es.onerror = () => {
                    // #58.2: a TRANSIENT blip fires onerror with readyState 0 (CONNECTING) and the browser
                    // auto-reconnects (resuming via Last-Event-ID) -- do NOT mark the run failed then (that
                    // flashed a false 'error' mid-run). Only readyState 2 (CLOSED) is terminal: a normal
                    // end-of-stream (a terminal already arrived) or a real failure before completion.
                    if (es.readyState !== 2) { return; }   // reconnecting -> wait it out
                    if (this.run.es === es) { this.run.es = null; }
                    if (!this.run.terminal) {
                        this.run.terminal = 'error'; this.run.running = false;
                        this.run.lastEvent = 'telemetry stream closed before completion';
                    } else {
                        this.run.running = false;
                    }
                    this._emit();
                };
                this._emit();
                return res.body;
            })
            .catch((e) => {
                this.run.running = false; this.run.terminal = 'error'; this.run.lastEvent = e.message;
                this._setHint('SIM run failed: ' + e.message, true);
            });
    }
}
