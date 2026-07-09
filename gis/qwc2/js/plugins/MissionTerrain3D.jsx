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
function ensureVizLoaded() {
    if (typeof window !== 'undefined' && window.STEWIE_VIZ) { return Promise.resolve(window.STEWIE_VIZ); }
    if (_vizPromise) { return _vizPromise; }
    _vizPromise = new Promise((resolve, reject) => {
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
        // Cache-bust: /assets/*.js is Cloudflare edge-cached, and this bare (un-versioned) path would
        // otherwise pin to a stale copy (the /viz page busts it with the stamped ?v=, but this runtime
        // inject can't see that hash). viz3d.js loads lazily on first panel-open and once per page-load
        // (_vizPromise), so a per-load cache-bust always fetches the current module at negligible cost.
        s.src = '/assets/viz3d.js?t=' + Date.now();
        s.setAttribute('data-stewie-viz3d', '1');
        s.addEventListener('load', done);
        s.addEventListener('error', () => { _vizPromise = null; reject(new Error('viz3d.js failed to load')); });
        document.head.appendChild(s);
    });
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
        grat: false,
        wire: false,
        loading: false,
        error: null,
        meta: null,       // last loaded X-Dem-* meta (resolution / relief), for the status line
        site: WS.site(),  // the active workspace site (drives the header)
        hover: null       // last onHover payload, coalesced to <=1 setState/frame
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
        this._teardown();
        if (typeof window !== 'undefined' && window.__stewieTerrain3D) { delete window.__stewieTerrain3D; }
    }

    // A site switch anywhere in the IDE (Mission Plan, SiteZoom, Whole Moon dive) reloads the 3D view so it
    // always shows the SAME site the 2D map is on. Only reload while the panel is open + mounted, and only on a
    // real different site (T.shouldReload guards body/profile/source churn + same-site re-emits).
    _onWsChange = (s) => {
        if (s && s.site !== this.state.site) { this.setState({site: s.site}); }
        if (this.props.active && this._mounted && T.shouldReload(this._loadedSite, s && s.site)) {
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
            VIZ.onHover((h) => this._onHover(h));
            VIZ.onLayerError((kind) => this._onLayerError(kind));
            this._mounted = true;
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
    renderBody = () => {
        const s = this.state;
        return (
            <div style={{background: '#0a0a0c', color: '#c7d2e3', padding: '8px', font: '11px system-ui, sans-serif'}}>
                <div style={{fontSize: '10px', color: '#8a93a3', marginBottom: '6px', lineHeight: 1.4}}>
                    Full-resolution 3D terrain for the active site — <b style={{color: '#4db6d4'}}>{s.site}</b> — synced
                    to the 2D map. Drag to orbit, scroll to zoom; hover for coordinates.
                </div>
                <div data-stewie-terrain3d ref={this._setContainer}
                    style={{width: '100%', height: '340px', background: '#05060c', border: '1px solid #14141c',
                        borderRadius: '4px', position: 'relative', overflow: 'hidden'}} />
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
                <div style={{display: 'flex', gap: '14px', fontSize: '11px', color: '#aeb8c6', margin: '3px 0'}}>
                    <label><input checked={s.grid} data-stewie-grid onChange={this._setGrid} type="checkbox" /> km grid</label>
                    <label><input checked={s.grat} data-stewie-grat onChange={this._setGrat} type="checkbox" /> lon/lat</label>
                    <label><input checked={s.wire} data-stewie-wire onChange={this._setWire} type="checkbox" /> wireframe</label>
                </div>

                {this.renderHover()}
            </div>
        );
    };
    render() {
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
