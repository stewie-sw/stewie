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

const MAP_CRS = 'IAU_2015:30135';   // the lunar polar-stereographic workbench CRS (state.map.projection)
const GEO_CRS = 'IAU_2015:30100';   // selenographic lon/lat (order-anchor + globe bbox frame)
const KIND_COLOR = {cut: '#e0563a', fill: '#4fd1ff'};   // Frontend A's palette (cut = drum-down, fill = berm)

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
        this.site = 'haworth';
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
        this._lastPlanPayload = null;   // the exact JSON POSTed to /api/plan (headless-proof readback)
        this.orders = [];          // {kind, footprint_m2, depth_m, coord:[x,y]30135, lonlat:[lon,lat]}
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

        // --- Keep-out / no-go authoring (DEPTH-1). The operator draws avoid-regions (polygon or circle) on
        // the SAME OL map; on Plan they serialize into payload.keepouts -- the EXACT schema the backend parses
        // (lode/planner_routing.py:147 point_in_keepout / :158 _apply_keepouts): a {points:[[x,y],...]}
        // polygon or an {x,y,r} circle in the ORDER FRAME (metres). _apply_keepouts marks those cells
        // IMPASSABLE, so the least-cost router (route_leg, planner_views.py:448 for the rendered GoTo legs)
        // bends the route AROUND them. Geometry is kept in the map CRS on the OL feature and converted to the
        // order frame at Plan time through the SAME y-flipped anchor affine the orders use.
        this.keepouts = [];        // [{idx, kind:'polygon'|'circle', feature}]
        this.koTool = null;        // active no-go draw tool: 'polygon' | 'circle' | null
        this._draw = null;         // the live OL Draw interaction (on the map only while a ko tool is active)
        this._koSeq = 0;
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
    }

    _emptyRun() {
        return {es: null, id: null, legsSeen: 0, total: 0, terminal: null, running: false,
            cumdist: null, len: 0, result: null, evidence: null, lastEvent: '', lastPose: null};
    }

    attach() {
        if (this._attached) { return; }
        this.map.addLayer(this.keepoutLayer);
        this.map.addLayer(this.planLayer);
        this.map.addLayer(this.trailLayer);
        this.map.addLayer(this.roverLayer);
        this.map.addLayer(this.orderLayer);
        this._clickKey = this.map.on('singleclick', (evt) => {
            if (this.activeKind) { this.placeAt(evt.coordinate); }
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
                // No-go authoring drivers (same code path as the Draw tool's drawend + the panel buttons),
                // so a proof can place a no-go region across the route at exact MAP coords without simulating
                // Draw pointer events. No command authority (authoring only).
                setKeepoutTool: (kind) => this.setKeepoutTool(kind),
                addKeepoutCircle: (center, radius) => this.addKeepoutCircle(center, radius),
                addKeepoutPolygon: (ring) => this.addKeepoutPolygon(ring),
                clearKeepouts: () => this.clearKeepouts(),
                keepoutCount: () => this.keepouts.length,
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
                // Read-only readback of the exact /api/plan POST body + the last plan summary (for verifying
                // the chosen levers rode the POST and the resolved algorithm/objective came back).
                lastPlanPayload: () => (this._lastPlanPayload ? JSON.parse(JSON.stringify(this._lastPlanPayload)) : null),
                planResult: () => (this.result ? JSON.parse(JSON.stringify(this.result)) : null)
            };
        }
        this._attached = true;
    }

    detach() {
        if (!this._attached) { return; }
        this._deactivateDraw();
        this._resetRun();
        if (typeof window !== 'undefined' && window.__stewieRun) { delete window.__stewieRun; }
        if (this._clickKey) { this.map.un('singleclick', this._clickKey.listener); this._clickKey = null; }
        this.map.removeLayer(this.orderLayer);
        this.map.removeLayer(this.roverLayer);
        this.map.removeLayer(this.trailLayer);
        this.map.removeLayer(this.planLayer);
        this.map.removeLayer(this.keepoutLayer);
        this._attached = false;
    }

    _emit() {
        this.onState({
            site: this.site, activeKind: this.activeKind, footprint: this.footprint, depth: this.depth,
            orders: this.orders.map((o, i) => ({
                idx: i, kind: o.kind, x: round1(o.coord[0]), y: round1(o.coord[1]),
                footprint_m2: o.footprint_m2, depth_m: o.depth_m
            })),
            hint: this.hint, hintErr: this.hintErr, result: this.result, planning: this.planning,
            // DEPTH-2 plan controls (mirrored to the panel so the selects/inputs reflect the chosen levers).
            algorithm: this.algorithm, objective: this.objective, maxSlopeDeg: this.maxSlopeDeg,
            budgets: {...this.budgets},
            // DEPTH-3 fleet controls (mirrored to the panel).
            vehicles: this.vehicles, chargerCapacity: this.chargerCapacity,
            koTool: this.koTool,
            keepouts: this.keepouts.map((k, i) => ({idx: i, kind: k.kind, label: this._koSummary(k)})),
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
        this.orders = [];
        this.result = null;
        this.wc = null;
        this._resetRun();
        this.route = null; this._planOrders = null;
        this._deactivateDraw();                       // a site change resets authoring incl. any drawn no-go
        this.keepouts = []; this.keepoutSource.clear();
        this.orderSource.clear();
        this.planSource.clear();
        this._setHint('Loading ' + site + ' work area…');
        return fetch('/api/layers/globe/dem/bbox?site=' + encodeURIComponent(site))
            .then((r) => { if (!r.ok) { throw new Error('bbox HTTP ' + r.status); } return r.json(); })
            .then((bb) => {
                if (!bb || bb.ok === false) { throw new Error((bb && bb.error) || 'no bbox'); }
                if (fly) { this._zoomToBbox(bb); }
                this._setHint('Pick a tool (Cut / Fill), then click the map near the work area to place an order.');
            })
            .catch((e) => this._setHint('Could not load the ' + site + ' work area: ' + e.message, true));
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
        this._deactivateDraw();                       // picking a cut/fill tool leaves no-go draw mode
        this.activeKind = (this.activeKind === kind) ? null : kind;
        if (this.activeKind) {
            this._setHint('Click the map to place a ' + (kind === 'cut' ? 'CUT (dig)' : 'FILL (build)') +
                ' order. Click the tool again to stop placing.');
        } else {
            this._setHint('Placing off. Pick a tool to place more orders, or Plan the mission.');
        }
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

    // --- Keep-out / no-go authoring ------------------------------------------------------------------
    // Toggle the no-go draw tool. Turning it on stops order-placing (map clicks now draw a shape, not an
    // order) and adds an OL Draw interaction of the matching geometry; the tool stays active for multiple
    // draws (click the tool again to stop), mirroring the cut/fill placing UX.
    setKeepoutTool(kind) {
        this.activeKind = null;                       // no-go drawing and order-placing are mutually exclusive
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

    // A finished (drawn or programmatic) no-go feature -> the keep-out list. The Draw interaction already
    // added the feature to keepoutSource (its `source` option); the programmatic adders add it explicitly.
    _onDrawEnd(feature, kind) {
        this._koSeq += 1;
        feature.set('label', 'no-go ' + this._koSeq);
        this.keepouts.push({idx: this._koSeq, kind: kind, feature: feature});
        this._setHint('No-go region added (' + this.keepouts.length + ' drawn). Draw more, or press Plan mission.');
        this._emit();
    }

    // Authoring drivers (headless proof + faithful to the Draw path): add a no-go at exact MAP coords.
    addKeepoutCircle(center, radius) {
        const f = new Feature({geometry: new CircleGeom([center[0], center[1]], radius)});
        this.keepoutSource.addFeature(f);
        this._onDrawEnd(f, 'circle');
        return this.keepouts.length;
    }
    addKeepoutPolygon(ring) {
        const f = new Feature({geometry: new Polygon([ring])});
        this.keepoutSource.addFeature(f);
        this._onDrawEnd(f, 'polygon');
        return this.keepouts.length;
    }

    removeKeepout(i) {
        const k = this.keepouts[i];
        if (!k) { return; }
        try { this.keepoutSource.removeFeature(k.feature); } catch (e) { /* already removed */ }
        this.keepouts.splice(i, 1);
        this._setHint('No-go region removed (' + this.keepouts.length + ' left).');
    }
    clearKeepouts() {
        this.keepouts = [];
        this.keepoutSource.clear();
        this._setHint('All no-go regions cleared.');
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
    _keepoutsForFrame(wc) {
        const out = [];
        for (const k of this.keepouts) {
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
        this.orderSource.clear(); this.planSource.clear();
        this._setHint('Cleared. Pick a tool and click the map to place orders.');
    }

    _refreshOrderMarkers() {
        this.orderSource.clear();
        this.orders.forEach((o, i) => {
            const f = new Feature({geometry: new Point(o.coord)});
            f.set('kind', o.kind); f.set('label', String(i + 1));
            this.orderSource.addFeature(f);
        });
        this._emit();
    }

    _orderMarkerStyle(feature) {
        const kind = feature.get('kind');
        const color = KIND_COLOR[kind] || '#ffd24a';
        return new Style({
            image: new RegularShape({
                points: kind === 'cut' ? 4 : 3,               // cut = square, fill = triangle
                radius: 7, angle: kind === 'cut' ? Math.PI / 4 : 0,
                fill: new Fill({color: color}), stroke: new Stroke({color: '#0a0d12', width: 1.5})
            }),
            text: new Text({
                text: String(feature.get('label') || ''), offsetY: -14,
                font: '600 11px system-ui, sans-serif',
                fill: new Fill({color: '#e8edf4'}), stroke: new Stroke({color: '#000', width: 3})
            })
        });
    }

    // --- Plan: anchor at the order centroid, POST /api/plan, render the returned plan -----------------
    plan() {
        if (!this.orders.length) { this._setHint('Add at least one order first.', true); return Promise.resolve(); }
        // Anchor (order-frame origin / charger) = the centroid of the placed orders, in selenographic
        // lon/lat. Passed to /plan as M11 lat/lon so the planner anchors there; reprojected to map coords
        // so we know exactly where order-frame (0,0) sits on the map for both the POST offsets and the redraw.
        const meanLon = this.orders.reduce((s, o) => s + o.lonlat[0], 0) / this.orders.length;
        const meanLat = this.orders.reduce((s, o) => s + o.lonlat[1], 0) / this.orders.length;
        let wc;
        try { wc = this.reproject([meanLon, meanLat], GEO_CRS, MAP_CRS); }
        catch (e) { this._setHint('Could not anchor the work frame: ' + e.message, true); return Promise.resolve(); }
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
            orders: this.orders.map((o, i) => ({
                action: o.kind + ' ' + (i + 1), kind: o.kind,
                x: round1(o.coord[0] - wc[0]),      // 30135 East offset from the anchor
                y: round1(wc[1] - o.coord[1]),      // 30135 North offset, y-flipped to the raster-down order frame
                footprint_m2: o.footprint_m2, depth_m: o.depth_m
            }))
        };
        // DEPTH-1: fold the drawn no-go regions into the SAME /api/plan POST, in the SAME order frame as the
        // orders. The backend parses them (planner_routing.py:147) + routes around them (_apply_keepouts).
        const kos = this._keepoutsForFrame(wc);
        if (kos.length) { payload.keepouts = kos; }
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
                this.planning = false;
                this.result = {feasible: false, error: e.message};
                this._setHint('Plan request failed: ' + e.message, true);
            });
    }

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
        const nVeh = (this.result && this.result.vehicles) || 1;
        this._setHint(feasible
            ? (nVeh > 1
                ? 'Plan rendered: ' + nVeh + ' rovers, each route in its own colour (see the fleet summary); ' +
                  'haul = blue-dashed, charger = green. Press Run mission (SIM) to execute it.'
                : 'Plan rendered: route = gold, haul = blue-dashed, charger = green. Press Run mission (SIM) to execute it.')
            : 'Infeasible plan rendered (route dashed). See the reasons below.', !feasible);
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
        return fetch('/api/evidence')
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
                    // A normal end-of-stream also fires onerror after the server closes; only surface a real
                    // failure (no terminal reached yet).
                    if (!this.run.terminal) {
                        this.run.terminal = 'error'; this.run.running = false;
                        this.run.lastEvent = 'telemetry stream interrupted';
                        this._emit();
                    }
                    if (es.readyState === 2 && this.run.es === es) {
                        this.run.es = null; this.run.running = false; this._emit();
                    }
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
