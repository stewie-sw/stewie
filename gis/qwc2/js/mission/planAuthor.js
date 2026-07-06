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
import LineString from 'ol/geom/LineString';
import Point from 'ol/geom/Point';
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
        this._clickKey = null;
        this._attached = false;
    }

    attach() {
        if (this._attached) { return; }
        this.map.addLayer(this.planLayer);
        this.map.addLayer(this.orderLayer);
        this._clickKey = this.map.on('singleclick', (evt) => {
            if (this.activeKind) { this.placeAt(evt.coordinate); }
        });
        this._attached = true;
    }

    detach() {
        if (!this._attached) { return; }
        if (this._clickKey) { this.map.un('singleclick', this._clickKey.listener); this._clickKey = null; }
        this.map.removeLayer(this.orderLayer);
        this.map.removeLayer(this.planLayer);
        this._attached = false;
    }

    _emit() {
        this.onState({
            site: this.site, activeKind: this.activeKind, footprint: this.footprint, depth: this.depth,
            orders: this.orders.map((o, i) => ({
                idx: i, kind: o.kind, x: round1(o.coord[0]), y: round1(o.coord[1]),
                footprint_m2: o.footprint_m2, depth_m: o.depth_m
            })),
            hint: this.hint, hintErr: this.hintErr, result: this.result, planning: this.planning
        });
    }
    _setHint(msg, isErr) { this.hint = msg; this.hintErr = !!isErr; this._emit(); }

    // --- Site select: fetch the keyless work-area bbox + frame the view on it -------------------------
    selectSite(site, {fly} = {}) {
        this.site = site;
        this.orders = [];
        this.result = null;
        this.wc = null;
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
            algorithm: 'nearest', objective: 'time', lat: meanLat, lon: meanLon,
            orders: this.orders.map((o, i) => ({
                action: o.kind + ' ' + (i + 1), kind: o.kind,
                x: round1(o.coord[0] - wc[0]),      // 30135 East offset from the anchor
                y: round1(wc[1] - o.coord[1]),      // 30135 North offset, y-flipped to the raster-down order frame
                footprint_m2: o.footprint_m2, depth_m: o.depth_m
            }))
        };
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
        const pir = resp.plan_ir || {};
        const feasible = resp.feasible !== false && pir.feasible !== false;
        const routeStyle = new Style({
            stroke: new Stroke({color: '#ffd24a', width: 2.5, lineDash: feasible ? undefined : [6, 5]})
        });
        const haulStyle = new Style({stroke: new Stroke({color: '#8fb8ff', width: 2, lineDash: [2, 4]})});
        (pir.actions || []).forEach((a) => {
            if (a.op === 'GoTo' && Array.isArray(a.waypoints) && a.waypoints.length > 1) {
                const line = a.waypoints.map((w) => this._orderToMap(wc, w[0], w[1]));
                const f = new Feature({geometry: new LineString(line)});
                f.setStyle(routeStyle); this.planSource.addFeature(f);
            } else if (a.op === 'CutHaulFill' && a.site && a.dest) {
                const s = this._orderToMap(wc, a.site[0], a.site[1]);
                const d = this._orderToMap(wc, a.dest[0], a.dest[1]);
                const hf = new Feature({geometry: new LineString([s, d])});
                hf.setStyle(haulStyle); this.planSource.addFeature(hf);
            }
        });
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
            algorithm: pr.resolved_algorithm || t.resolved_algorithm || t.algorithm || '—',
            infeasible_reasons: resp.infeasible_reasons || [],
            pdf: resp.pdf ? ('/api' + resp.pdf) : null,
            terrain_source: resp.terrain_source || ''
        };
        this._setHint(feasible
            ? 'Plan rendered: route = gold, haul = blue-dashed, charger = green.'
            : 'Infeasible plan rendered (route dashed). See the reasons below.', !feasible);
    }
}
