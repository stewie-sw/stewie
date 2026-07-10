/**
 * MissionTerrain3D — the STEWIE full-resolution 3D TERRAIN PANEL ([REQ:GW-11]) inside the lunar IDE
 * (artemis.stewie.space/ide/). This is the "into QWC2" companion to the standalone /viz viewer: the SAME
 * working full-res relief (assets/viz3d.js -> window.STEWIE_VIZ), embedded in a SideBar and SYNCED to the 2D
 * map's active site so the 3D view always shows the site the workbench is on.
 *
 * REUSE, not reinvent: it drives the shipped STEWIE_VIZ API (mount / loadSite / setLayer / setVertExag /
 * setSun / setMetricGrid / setGraticule / setWireframe / onHover / onLayerError). viz3d.js fetches
 * /dem/heightfield_full (native float32 binary), drapes /dem/heightfield_full/layer.png?kind=, overlays the
 * metric km grid + the curved /dem/graticule, and does the hover coordinate readout (order metres +
 * selenographic lon/lat via /dem/site_lonlat). All those are absolute same-origin /dem + /assets paths that the
 * artemis nginx proxies to the backend, so they resolve from inside /ide/ unchanged; the production CSP
 * (deploy/nginx.conf) already allows them (script-src 'self' for /assets/viz3d.js + its /assets/three.module,
 * connect-src 'self' for /dem fetches, img-src 'self' for the layer.png texture) — no CSP change is needed.
 *
 * SITE SYNC (the point of GW-11): it reads the active site from the GW-02 workspace store (../mission/
 * workspace.js, WS) and reloads the relief on every site change, exactly like MissionCrossSection / SiteZoom.
 * A monotonic request guard (../mission/reqGuard.js, RG) drops a slow full-res load that resolves after the
 * operator has already switched sites (the last-load-wins race the WS propagation exposes). The drape list +
 * the site-sync decision + the hover readout formatting are the node-tested pure helpers in
 * ../mission/terrain3d.js (T).
 *
 * LIFECYCLE: the panel is shown while state.task.id === "MissionTerrain3D" (opened via
 * setCurrentTask("MissionTerrain3D") from the TopBar Validate menu). viz3d is loaded ONCE via a one-time
 * <script type="module"> inject of /assets/viz3d.js (it registers window.STEWIE_VIZ; a runtime script inject
 * is not touched by webpack, unlike a bundled dynamic import of an absolute path). On the container div
 * mounting it calls STEWIE_VIZ.mount(); on the container unmounting (task change away / SideBar close) it calls
 * STEWIE_VIZ.dispose() so there is NO leaked WebGL context, ResizeObserver, or animation loop.
 *
 * Registration (both required):
 *   - js/appConfig.js     -> pluginsDef.plugins.MissionTerrain3DPlugin
 *   - static/config.json  -> plugins.common [{"name":"MissionTerrain3D"}] + a TopBar SecValidate menu item
 *                            {"key":"MissionTerrain3D","title":"Terrain 3D","icon":"map3d"}
 */
import React from 'react';
import {connect} from 'react-redux';

import PropTypes from 'prop-types';
import ResizeableWindow from 'qwc2/components/ResizeableWindow';
import SideBar from 'qwc2/components/SideBar';

import RG from '../mission/reqGuard.js';    // #57: last-load-wins / stale-site guard
import T from '../mission/terrain3d.js';   // GW-11: drape list + site-sync decision + hover formatting (node-tested)
import WS from '../mission/workspace.js';   // GW-02: the shared workspace-context store (active site)

// One-time loader for the shipped full-res viewer. viz3d.js is an ES module that registers window.STEWIE_VIZ
// as a side effect and vendors THREE from /assets/three.module.min.js (both same-origin, CSP script-src
// 'self'). A runtime <script type="module"> inject is deliberately used over a bundled dynamic import: webpack
// would try to resolve a static import("/assets/viz3d.js") at build time (absolute path -> build error),
// whereas a createElement('script') is invisible to webpack and lets the browser load the real module. The
// promise is cached module-wide so re-opening the panel (or two instances) never double-injects.
let _vizPromise = null;
// [GW-11] The UMD companion modules viz3d.js reads at eval time for the geospatial upgrade: frame.js (the
// flat<->globe placement frame), scalebar.js (the scale/north/sun HUD), layers.js (the draped layer stack).
// Best-effort classic-script injects (viz3d degrades to a flat, no-HUD, single-drape viewer if one 404s),
// loaded BEFORE the viz3d module so its window.STEWIE* reads see them. Idempotent via the window global + a
// data-attr guard. Cache-bust each: /assets/*.js is Cloudflare edge-cached and these bare paths carry no ?v=.
function _loadDep(src, globalName, attr) {
    if (typeof window !== 'undefined' && window[globalName]) { return Promise.resolve(); }
    return new Promise((resolve) => {
        if (typeof document === 'undefined' || document.querySelector('script[' + attr + ']')) { resolve(); return; }
        const s = document.createElement('script');
        s.src = src + '?t=' + Date.now();
        s.setAttribute(attr, '1');
        s.addEventListener('load', () => resolve());
        s.addEventListener('error', () => resolve());   // best-effort: viz3d still loads (flat fallback)
        document.head.appendChild(s);
    });
}
function ensureVizLoaded() {
    if (typeof window !== 'undefined' && window.STEWIE_VIZ) { return Promise.resolve(window.STEWIE_VIZ); }
    if (_vizPromise) { return _vizPromise; }
    _vizPromise = Promise.all([
        _loadDep('/assets/viz3d/frame.js', 'STEWIEFrame', 'data-stewie-frame'),
        _loadDep('/assets/viz3d/scalebar.js', 'STEWIE_SCALEBAR', 'data-stewie-scalebar'),
        _loadDep('/assets/viz3d/layers.js', 'STEWIEViz3DLayers', 'data-stewie-vizlayers')
    ]).then(() => new Promise((resolve, reject) => {
        if (typeof document === 'undefined') { reject(new Error('no document')); return; }
        const done = () => (window.STEWIE_VIZ ? resolve(window.STEWIE_VIZ) : reject(new Error('STEWIE_VIZ missing after viz3d.js load')));
        const existing = document.querySelector('script[data-stewie-viz3d]');
        if (existing) {
            if (window.STEWIE_VIZ) { resolve(window.STEWIE_VIZ); return; }
            existing.addEventListener('load', done);
            existing.addEventListener('error', () => reject(new Error('viz3d.js failed to load')));
            return;
        }
        const s = document.createElement('script');
        s.type = 'module';
        // viz3d.js loads lazily on first panel-open and once per page-load (_vizPromise), so a per-load
        // cache-bust always fetches the current module at negligible cost (the /viz page uses the stamped ?v=).
        s.src = '/assets/viz3d.js?t=' + Date.now();
        s.setAttribute('data-stewie-viz3d', '1');
        s.addEventListener('load', done);
        s.addEventListener('error', () => { _vizPromise = null; reject(new Error('viz3d.js failed to load')); });
        document.head.appendChild(s);
    }));
    return _vizPromise;
}

const SECTION = {
    fontSize: '10px', fontWeight: 600, color: '#aeb8c6', letterSpacing: '.03em',
    textTransform: 'uppercase', margin: '8px 0 3px'
};
const ROW = {display: 'flex', gap: '8px', alignItems: 'center', margin: '3px 0', fontSize: '11px'};
const LABEL = {color: '#8a93a3', minWidth: '74px'};
const SELECT = {
    fontSize: '11px', background: '#111319', color: '#c7d2e3', border: '1px solid #26262c',
    borderRadius: '4px', padding: '2px 6px', flex: 1
};

class MissionTerrain3D extends React.Component {
    static propTypes = {
        /** Whether the MissionTerrain3D task is current (state.task.id). */
        active: PropTypes.bool,
        side: PropTypes.string
    };
    static defaultProps = {active: false, side: 'right'};
    state = {
        drape: 'elevation',
        vex: 1,
        sunAz: 315,
        sunEl: 45,
        grid: false,
        globe: false,     // [GW-11] flat<->3D globe (needs frame.js; falls back to flat if the module didn't load)
        grat: true,       // task #77: lon/lat graticule shows by default (was off) -- oriented plotting context
        wire: false,
        measure: false,       // task #79: measure/waypoints tool toggle
        hasVizLayers: false,  // [GW-11] viz3d/layers.js loaded -> show the draped layer-stack panel
        layerState: {},       // [GW-11] per-drape-kind {on, opacity} for the draped layer stack
        measureInfo: null,    // task #79: last onMeasure payload ({count, totalDist_m, lastLat, lastLon, segments})
        sentRouteMsg: null,   // task #80: brief on-panel confirmation/hint after "Send to plan (route)"
        loading: false,
        error: null,
        meta: null,       // last loaded X-Dem-* meta (resolution / relief), for the status line
        site: WS.site(),  // the active workspace site (drives the header)
        hover: null,      // last onHover payload, coalesced to <=1 setState/frame
        floating: false   // task #56: pop out of the SideBar into a draggable/resizable ResizeableWindow
    };
    constructor(props) {
        super(props);
        this.container = null;
        this._viz = null;
        this._mounted = false;      // whether STEWIE_VIZ.mount() has run into the current container
        this._loadedSite = null;    // the site the relief currently shows (for the site-sync decision)
        this._hoverRaf = 0;
        this._pendingHover = null;
    }
    componentDidMount() {
        this._rg = RG.makeReqGuard();
        this._unsubWS = WS.subscribe(this._onWsChange);
        // task #56 auto-float: MissionPlan's "3D" button asks this panel to pop itself into a floating card
        // (coexisting with the plan) instead of taking over the SideBar. Since render() shows the
        // ResizeableWindow whenever floating is true (independent of the current task), just flip the flag.
        this._unsubFloat = WS.onFloatRequest((id) => { if (id === 'MissionTerrain3D' && !this.state.floating) { this.setState({floating: true}); } });
        // Read-only harness handle for the Playwright verify (no command authority): report the mounted state,
        // the site the relief shows, the active drape, and the loaded DEM meta.
        if (typeof window !== 'undefined') {
            window.__stewieTerrain3D = {
                mounted: () => this._mounted,
                loadedSite: () => this._loadedSite,
                drape: () => this.state.drape,
                meta: () => (this._viz && this._viz.meta) ? this._viz.meta : null
            };
        }
    }
    componentWillUnmount() {
        if (this._rg) { this._rg.bump(); }
        if (this._unsubWS) { this._unsubWS(); }
        if (this._unsubFloat) { this._unsubFloat(); }
        this._teardown();
        if (typeof window !== 'undefined' && window.__stewieTerrain3D) { delete window.__stewieTerrain3D; }
    }

    // A site switch anywhere in the IDE (Mission Plan, SiteZoom, Whole Moon dive) reloads the 3D view so it
    // always shows the SAME site the 2D map is on. Only reload while the panel is open + mounted, and only on a
    // real different site (T.shouldReload guards body/profile/source churn + same-site re-emits).
    _onWsChange = (s) => {
        if (s && s.site !== this.state.site) { this.setState({site: s.site}); }
        // F18: a FLOATING card (opened via WS.requestFloat without setCurrentTask, so props.active===false while
        // it is mounted + visible) must ALSO follow a site change — otherwise it shows a stale wrong-site relief
        // while its header claims the new site. Gate on active OR floating (both mean the panel is on-screen).
        if ((this.props.active || this.state.floating) && this._mounted && T.shouldReload(this._loadedSite, s && s.site)) {
            this._loadSite(s.site);
        }
    };

    // Container ref: mount viz3d when the div attaches (panel opens), dispose when it detaches (panel closes).
    _setContainer = (el) => {
        if (el) { this.container = el; this._ensureMounted(); } else { this._teardown(); this.container = null; }
    };

    _ensureMounted() {
        if (!this.container || this._mounted) { return; }
        this.setState({loading: true, error: null});
        ensureVizLoaded().then((VIZ) => {
            if (!this.container || this._mounted) { return; }   // panel closed while viz3d.js loaded
            this._viz = VIZ;
            VIZ.mount(this.container);
            if (VIZ.setHud) { VIZ.setHud({scale: this._scaleEl, north: this._northEl, sun: this._sunEl}); }   // [GW-11] scale/north/sun HUD
            VIZ.onHover((h) => this._onHover(h));
            VIZ.onLayerError((kind) => this._onLayerError(kind));
            // task #77: a Shift+click on the relief plots the active Mission-Plan tool there -- forward the
            // raycast point (e_m/n_m/elev_m/lat/lon) into the SAME shared workspace channel MissionPlan
            // subscribes to, so it feeds the identical order queue the 2D map's singleclick fills.
            VIZ.onPlot((pt) => WS.emitPlot(pt));
            // task #79: the measure/waypoints tool -- viz3d owns the click handling + polyline/marker drawing;
            // this panel just mirrors the running count/distance into React state for the readout.
            VIZ.onMeasure((m) => this.setState({measureInfo: m}));
            this._mounted = true;
            if (window.STEWIEViz3DLayers && !this.state.hasVizLayers) { this.setState({hasVizLayers: true}); }   // [GW-11] layer panel
            this._loadSite(WS.site());
        }).catch((e) => {
            if (this.container) { this.setState({loading: false, error: 'viewer load failed: ' + (e && e.message ? e.message : e)}); }
        });
    }

    _teardown() {
        if (this._rg) { this._rg.bump(); }   // invalidate any in-flight loadSite
        if (this._hoverRaf) { cancelAnimationFrame(this._hoverRaf); this._hoverRaf = 0; }
        this._pendingHover = null;
        if (this._viz && typeof this._viz.dispose === 'function') {
            try { this._viz.dispose(); } catch { /* teardown must never throw */ }
        }
        this._viz = null;
        this._mounted = false;
    }

    // Load a site at full resolution and re-apply the panel's control state to the fresh relief (viz3d keeps
    // most control state on its own singleton, but re-applying makes the React controls authoritative and
    // survives a dispose/re-mount). Stale-guarded: a slow load is dropped if the site changed under it.
    _loadSite(site) {
        if (!this._viz || !site) { return; }
        const tok = this._rg.next();
        this._loadedSite = site;
        this.setState({loading: true, error: null});
        this._viz.loadSite(site, {}).then((meta) => {
            if (!this._rg.current(tok) || WS.site() !== site) { return; }
            this._viz.setVertExag(this.state.vex);
            this._viz.setSun(this.state.sunAz, this.state.sunEl);
            this._viz.setLayer(this.state.drape);
            this._viz.setMetricGrid(this.state.grid);
            this._viz.setGraticule(this.state.grat);
            this._viz.setWireframe(this.state.wire);
            if (this.state.globe && this._viz.setGlobe) { this._viz.setGlobe(true); }   // [GW-11] re-curve after a flat load
            this._applyLayers();                                                        // [GW-11] re-drape the layer stack for the new site
            this.setState({loading: false, meta, site});
        }).catch((e) => {
            if (!this._rg.current(tok) || WS.site() !== site) { return; }
            this.setState({loading: false, error: 'load ' + site + ': ' + (e && e.message ? e.message : e)});
        });
    }

    // Coalesce the high-frequency hover stream to at most one setState per animation frame.
    _onHover = (h) => {
        this._pendingHover = h;
        if (this._hoverRaf) { return; }
        this._hoverRaf = requestAnimationFrame(() => {
            this._hoverRaf = 0;
            this.setState({hover: this._pendingHover});
        });
    };
    _onLayerError = (kind) => {
        this.setState({drape: 'elevation', error: "drape '" + kind + "' unavailable for this window — reverted to elevation"});
    };

    _setDrape = (e) => { const drape = e.target.value; this.setState({drape}); if (this._viz) { this._viz.setLayer(drape); } };
    _setVex = (e) => { const vex = +e.target.value; this.setState({vex}); if (this._viz) { this._viz.setVertExag(vex); } };
    _setSunAz = (e) => { const sunAz = +e.target.value; this.setState({sunAz}); if (this._viz) { this._viz.setSun(sunAz, this.state.sunEl); } };
    _setSunEl = (e) => { const sunEl = +e.target.value; this.setState({sunEl}); if (this._viz) { this._viz.setSun(this.state.sunAz, sunEl); } };
    _setGrid = (e) => { const grid = e.target.checked; this.setState({grid}); if (this._viz) { this._viz.setMetricGrid(grid); } };
    _setGrat = (e) => { const grat = e.target.checked; this.setState({grat}); if (this._viz) { this._viz.setGraticule(grat); } };
    _setWire = (e) => { const wire = e.target.checked; this.setState({wire}); if (this._viz) { this._viz.setWireframe(wire); } };
    _setGlobe = (e) => { const globe = e.target.checked; this.setState({globe}); if (this._viz && this._viz.setGlobe) { this._viz.setGlobe(globe); } };
    // [GW-11] draped layer stack: build the stack from the per-kind {on,opacity} React state + render it.
    _applyLayers = () => {
        const LS = (typeof window !== 'undefined') ? window.STEWIEViz3DLayers : null;
        if (!LS || !this._viz || !this._viz.renderLayerStack) { return; }
        const meta = this._viz.meta; if (!meta) { return; }
        const ctx = {site: meta.site, window_m: meta.window_m, x0: meta.x0, y0: meta.y0};
        const stack = LS.makeLayerStack();
        const ls = this.state.layerState;
        LS.LAYER_CATALOG.filter((e) => e.available && e.render === 'drape').forEach((e) => {
            const st = ls[e.kind];
            if (st && st.on) { const spec = LS.layerFromCatalog(e.kind, ctx); if (spec) { spec.opacity = (st.opacity != null) ? st.opacity : 1; try { stack.add(spec); } catch { /* dup */ } } }
        });
        this._viz.renderLayerStack(stack.visibleOrdered());
    };
    _toggleLayer = (kind) => (e) => {
        const on = e.target.checked;
        this.setState((s) => ({layerState: {...s.layerState, [kind]: {on, opacity: (s.layerState[kind] && s.layerState[kind].opacity != null) ? s.layerState[kind].opacity : 1}}}), this._applyLayers);
    };
    _setLayerOpacity = (kind) => (e) => {
        const opacity = +e.target.value;
        this.setState((s) => ({layerState: {...s.layerState, [kind]: {on: !!(s.layerState[kind] && s.layerState[kind].on), opacity}}}), this._applyLayers);
    };
    _setMeasure = (e) => { const measure = e.target.checked; this.setState({measure}); if (this._viz) { this._viz.setMeasureMode(measure); } };
    _clearMeasure = () => { if (this._viz) { this._viz.clearMeasure(); } };
    // task #80 / council F29: push the measured waypoints into Mission Plan as a Traverse route over the shared
    // workspace WS.emitRoute() channel (MissionPlan._adoptRoute subscribes). A waypoint only carries lon/lat
    // once its async /dem/site_lonlat lookup resolves; a point without it cannot reproject into the planner
    // frame. The old path SILENTLY filtered those out and emitted the survivors, so an unresolved INTERIOR
    // point cut a straight leg past the dropped waypoint while the confirmation still said "Sent N".
    // T.routeSendDecision (node-tested) now REFUSES to send when any point is still unresolved and reports the
    // count, instead of thinning the route.
    _sendRoute = () => {
        const pts = (this._viz && this._viz.getMeasurePoints) ? this._viz.getMeasurePoints() : [];
        const d = T.routeSendDecision(pts);
        if (d.emit) { WS.emitRoute(d.points); }
        this.setState({sentRouteMsg: d.msg});
    };

    renderStatus() {
        const s = this.state;
        if (s.error) { return <span style={{color: '#e0564b'}}>{s.error}</span>; }
        if (s.loading) { return <span style={{color: '#7a8290'}}>loading {s.site} at full resolution…</span>; }
        const m = s.meta;
        if (!m) { return <span style={{color: '#7a8290'}}>—</span>; }
        const res = m.lod ? (m.n + '×' + m.n + ' (LOD, native ' + m.native_n + ')') : (m.n + '×' + m.n + ' native');
        return (
            <span style={{color: '#8a93a3'}}>
                {res} @ {T.fmt(m.cell_m, 1)} m/cell · {T.fmt(m.window_m / 1000, 2)} km · relief {T.fmt(m.z_min, 0)}…{T.fmt(m.z_max, 0)} m
            </span>
        );
    }
    renderHover() {
        const f = T.formatHover(this.state.hover);
        const dim = !f;
        return (
            <div data-stewie-terrain3d-hud style={{marginTop: '8px', padding: '6px 8px', background: '#111319',
                border: '1px solid #1c1c24', borderRadius: '4px', fontSize: '11px', lineHeight: 1.5,
                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', opacity: dim ? 0.45 : 1}}>
                <div><span data-stewie-hud-en style={{color: '#c7d2e3'}}>{f ? f.en : 'E — m N — m'}</span>
                    {'  '}<span data-stewie-hud-elev style={{color: '#4fd1ff'}}>{f ? f.elev : 'elev — m'}</span></div>
                <div data-stewie-hud-ll style={{color: '#e0b300'}}>{f ? f.lonlat : 'lat — lon —'}</div>
            </div>
        );
    }
    // task #79: the measure/waypoints readout (count + running planar distance) + a Clear button. viz3d
    // reports {count, totalDist_m, ...} via onMeasure(); this just formats it as plain JSX text -- no raw-HTML sink.
    renderMeasure() {
        const m = this.state.measureInfo;
        const count = m ? m.count : 0;
        const totalM = m ? m.totalDist_m : 0;
        const distTxt = totalM >= 1000 ? (totalM / 1000).toFixed(2) + ' km' : totalM.toFixed(1) + ' m';
        return (
            <div style={{display: 'flex', alignItems: 'center', gap: '8px', margin: '3px 0 6px'}}>
                <span data-stewie-measure-out style={{color: '#aeb8c6'}}>{count ? (count + ' pts · ' + distTxt) : '—'}</span>
                <button
                    data-stewie-measure-clear onClick={this._clearMeasure} type="button"
                    style={{
                        cursor: 'pointer', font: '600 10px system-ui, sans-serif', padding: '2px 8px',
                        borderRadius: '4px', border: '1px solid #39c6ff44', color: '#39c6ff', background: '#39c6ff10'
                    }}
                >Clear</button>
            </div>
        );
    }
    // task #80: the "send measured route to plan" control -- only makes sense where a planner exists (the
    // /ide Mission Plan panel this button targets via WS.emitRoute), which is exactly where this SideBar
    // plugin lives (the standalone /viz page never mounts MissionTerrain3D.jsx, so it never gets this button).
    // Shown once measuring is active OR at least 2 waypoints are already down (this.state.measureInfo.count),
    // so it stays out of the way before there is anything useful to send. The confirmation/hint line is plain
    // JSX text -- rendered through React children, not any raw-markup DOM sink.
    renderSendRoute() {
        const s = this.state;
        const count = s.measureInfo ? s.measureInfo.count : 0;
        if (!s.measure && count < 2) { return null; }
        return (
            <div style={{display: 'flex', flexDirection: 'column', gap: '4px', margin: '0 0 6px'}}>
                <button
                    data-stewie-send-route="1" onClick={this._sendRoute} type="button"
                    style={{
                        cursor: 'pointer', font: '600 10px system-ui, sans-serif', padding: '3px 8px',
                        borderRadius: '4px', border: '1px solid #7fe0a866', color: '#7fe0a8', background: '#7fe0a814',
                        alignSelf: 'flex-start'
                    }}
                >→ Send to plan (route)</button>
                {s.sentRouteMsg && (
                    <span data-stewie-send-route-msg style={{color: '#8a93a3', fontSize: '10px'}}>{s.sentRouteMsg}</span>
                )}
            </div>
        );
    }
    // task #56: float control -- pops the panel out of the SideBar into a draggable/resizable ResizeableWindow
    // (see render()). Shown only while docked; the floating window's own titlebar close returns it to the SideBar.
    _setFloating = () => { this.setState({floating: true}); };
    renderBody = () => {
        const s = this.state;
        return (
            <div style={{background: '#0a0a0c', color: '#c7d2e3', padding: '8px', font: '11px system-ui, sans-serif'}}>
                {!s.floating && (
                    <button
                        data-stewie-float="1" onClick={this._setFloating} type="button"
                        title="pop out into a floating, draggable/resizable window"
                        style={{
                            display: 'block', marginBottom: '6px', cursor: 'pointer',
                            font: '600 10px system-ui, sans-serif', padding: '4px 8px', borderRadius: '4px',
                            border: '1px solid #39c6ff66', color: '#39c6ff', background: '#39c6ff14'
                        }}
                    >⤢ Float</button>
                )}
                <div style={{fontSize: '10px', color: '#8a93a3', marginBottom: '6px', lineHeight: 1.4}}>
                    Full-resolution 3D terrain for the active site — <b style={{color: '#4db6d4'}}>{s.site}</b> — synced
                    to the 2D map. Drag to orbit, scroll to zoom; hover for coordinates.
                </div>
                <div style={{fontSize: '10px', color: '#7fe0a8', marginBottom: '6px', lineHeight: 1.4}}>
                    ⇧ Shift+click the terrain to drop the active Mission Plan tool here.
                </div>
                <div style={{position: 'relative', width: '100%', height: '340px'}}>
                    <div data-stewie-terrain3d ref={this._setContainer}
                        style={{position: 'absolute', inset: 0, background: '#05060c', border: '1px solid #14141c',
                            borderRadius: '4px', overflow: 'hidden'}} />
                    <div data-stewie-scale ref={(el) => { this._scaleEl = el; }}
                        style={{position: 'absolute', left: '50%', bottom: '6px', transform: 'translateX(-50%)', pointerEvents: 'none', zIndex: 2}} />
                    <div style={{position: 'absolute', right: '6px', top: '6px', display: 'flex', gap: '6px', pointerEvents: 'none',
                        zIndex: 2, background: 'rgba(8,11,15,.5)', border: '1px solid #1c1c24', borderRadius: '6px', padding: '4px 6px'}}>
                        <div data-stewie-north ref={(el) => { this._northEl = el; }} />
                        <div data-stewie-sun ref={(el) => { this._sunEl = el; }} />
                    </div>
                </div>
                <div style={{fontSize: '10px', margin: '4px 0 2px', minHeight: '13px'}}>{this.renderStatus()}</div>

                <div style={SECTION}>analysis drape</div>
                <div style={ROW}>
                    <select data-stewie-drape onChange={this._setDrape} style={SELECT} value={s.drape}>
                        {T.DRAPE_KINDS.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
                    </select>
                </div>

                <div style={SECTION}>vertical exaggeration</div>
                <div style={ROW}>
                    <input data-stewie-vex max="5" min="1" onChange={this._setVex} step="0.5" style={{flex: 1}}
                        type="range" value={s.vex} />
                    <span style={{color: '#c7d2e3', minWidth: '30px', textAlign: 'right'}}>{s.vex.toFixed(1)}×</span>
                </div>

                <div style={SECTION}>sun</div>
                <div style={ROW}>
                    <span style={LABEL}>azimuth</span>
                    <input data-stewie-sun-az max="360" min="0" onChange={this._setSunAz} step="5" style={{flex: 1}}
                        type="range" value={s.sunAz} />
                    <span style={{minWidth: '34px', textAlign: 'right'}}>{s.sunAz}°</span>
                </div>
                <div style={ROW}>
                    <span style={LABEL}>elevation</span>
                    <input data-stewie-sun-el max="90" min="0" onChange={this._setSunEl} step="1" style={{flex: 1}}
                        type="range" value={s.sunEl} />
                    <span style={{minWidth: '34px', textAlign: 'right'}}>{s.sunEl}°</span>
                </div>

                <div style={SECTION}>overlays</div>
                <div style={{display: 'flex', gap: '14px', flexWrap: 'wrap', fontSize: '11px', color: '#aeb8c6', margin: '3px 0'}}>
                    <label><input checked={s.globe} data-stewie-globe onChange={this._setGlobe} type="checkbox" /> 🌕 globe</label>
                    <label><input checked={s.grid} data-stewie-grid onChange={this._setGrid} type="checkbox" /> km grid</label>
                    <label><input checked={s.grat} data-stewie-grat onChange={this._setGrat} type="checkbox" /> lon/lat</label>
                    <label><input checked={s.wire} data-stewie-wire onChange={this._setWire} type="checkbox" /> wireframe</label>
                    <label><input checked={s.measure} data-stewie-measure onChange={this._setMeasure} type="checkbox" /> 📏 Measure</label>
                </div>

                {s.hasVizLayers && typeof window !== 'undefined' && window.STEWIEViz3DLayers && (
                    <div data-stewie-layerstack>
                        <div style={SECTION}>layer stack (draped)</div>
                        {window.STEWIEViz3DLayers.LAYER_CATALOG.filter((e) => e.available && e.render === 'drape').map((e) => {
                            const st = s.layerState[e.kind] || {on: false, opacity: 1};
                            return (
                                <div key={e.kind} style={{display: 'flex', alignItems: 'center', gap: '6px', margin: '2px 0', fontSize: '10px'}}>
                                    <label style={{flex: 1, display: 'flex', alignItems: 'center', gap: '5px', color: '#aeb8c6',
                                        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}} title={e.label}>
                                        <input checked={st.on} data-stewie-layer={e.kind} onChange={this._toggleLayer(e.kind)} type="checkbox" />
                                        {e.label}
                                    </label>
                                    <input disabled={!st.on} max="1" min="0" onChange={this._setLayerOpacity(e.kind)} step="0.05"
                                        style={{width: '54px'}} type="range" value={st.opacity != null ? st.opacity : 1} />
                                </div>
                            );
                        })}
                    </div>
                )}

                {this.renderMeasure()}
                {this.renderSendRoute()}
                {this.renderHover()}
            </div>
        );
    };
    // task #56: while floating, render() returns a ResizeableWindow instead of the SideBar. This plugin's
    // render() runs unconditionally regardless of state.task.id (the SideBar self-hides on task, not the
    // plugin), so the floating window shows independent of whichever task is "current" -- the mechanism that
    // lets this float alongside a floating MissionPlan. The container ref inside renderBody() (mount/dispose
    // of window.STEWIE_VIZ) is unaffected: exactly one of the two branches renders at a time, so there is
    // still only ever one container in the tree -> no double-mount.
    render() {
        if (this.state.floating) {
            return (
                <ResizeableWindow
                    dockable="right" icon="map3d" initialHeight={560} initialWidth={440}
                    initialX={480} initialY={70} maximizeable minimizeable
                    onClose={() => this.setState({floating: false})} scrollable title="Terrain 3D"
                >
                    {this.renderBody()}
                </ResizeableWindow>
            );
        }
        return (
            <SideBar icon="map3d" id="MissionTerrain3D" side={this.props.side} title="Terrain 3D" width="26em">
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

export default connect((state) => ({
    active: state.task.id === 'MissionTerrain3D'
}), {})(MissionTerrain3D);
