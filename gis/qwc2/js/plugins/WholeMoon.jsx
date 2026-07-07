/**
 * WholeMoon — the STEWIE "Whole Moon" overview surface for the lunar IDE (artemis.stewie.space/ide/).
 *
 * WHAT + WHY: the workbench map is south-polar stereographic (IAU_2015:30135), which structurally CANNOT
 * show the whole Moon (the north pole projects to infinity). This plugin adds a SEPARATE overview surface
 * — a spinnable 3-D Cesium globe draped with the real LRO WAC global mosaic — so the operator can see
 * BOTH hemispheres for context, then DIVE into a site: clicking a site marker (or a header chip) recenters
 * the polar workbench on that site and closes the overview.
 *
 * REBIND, not rewrite: the globe itself is the framework-agnostic js/mission/wholeMoonGlobe.js controller,
 * which reuses the app.stewie.space cockpit's proven Cesium 1.119 + Trek WAC setup. This plugin is a thin
 * task-gated React shell: it mounts a full-screen overlay (via a portal to <body>), lazily builds the globe
 * on first open, fetches the public /api/world/site-markers (keyless -- the drawn-pin subset, NOT the auth-
 * gated /api/sites the browser cannot read) for the markers, and dispatches the dive.
 *
 * Registration:
 *   - js/appConfig.js     -> pluginsDef.plugins.WholeMoonPlugin
 *   - static/config.json  -> plugins.common [{"name": "WholeMoon"}] + a TopBar menu item
 *                            {"key": "WholeMoon", "title": "Whole Moon", "icon": "sphere"}
 * The "Whole Moon" app-menu entry dispatches setCurrentTask("WholeMoon"); the overlay shows while
 * state.task.id === "WholeMoon".
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {connect} from 'react-redux';

import PropTypes from 'prop-types';
import {zoomToExtent} from 'qwc2/actions/map';
import {setCurrentTask} from 'qwc2/actions/task';
import CoordinatesUtils from 'qwc2/utils/CoordinatesUtils';

import WholeMoonGlobe from '../mission/wholeMoonGlobe';

// The lunar geographic CRS (selenographic lon/lat, +proj=longlat +R=1737400) — registered from
// config.json `projections`. Site coords come from /api/sites in this frame; we reproject to the map's
// own CRS (state.map.projection = IAU_2015:30135 for the workbench theme) before diving.
const GEO_CRS = 'IAU_2015:30100';
// Half-width (metres, in the map's polar-stereographic CRS) of the framing box a dive fits to (~60 km box).
const DIVE_HALF_M = 30000;

class WholeMoon extends React.Component {
    static propTypes = {
        /** true while state.task.id === "WholeMoon". */
        active: PropTypes.bool,
        /** The workbench map projection (state.map.projection), e.g. IAU_2015:30135. */
        mapCrs: PropTypes.string,
        setCurrentTask: PropTypes.func,
        zoomToExtent: PropTypes.func
    };
    static defaultProps = {
        active: false,
        mapCrs: 'IAU_2015:30135'
    };
    state = {
        sites: [],
        status: 'idle',   // idle | loading | ready | error
        error: null
    };
    constructor(props) {
        super(props);
        this.containerRef = React.createRef();
        this.ctrl = null;       // wholeMoonGlobe controller {viewer, ell, handler}
        this.cesium = null;     // resolved window.Cesium
    }
    componentDidUpdate(prevProps) {
        if (this.props.active && !prevProps.active) {
            this.init();
        } else if (!this.props.active && prevProps.active) {
            this.teardown();
        }
    }
    componentWillUnmount() {
        this.teardown();
    }
    init = () => {
        this.setState({status: 'loading', error: null});
        WholeMoonGlobe.loadCesium().then((Cesium) => {
            this.cesium = Cesium;
            // The overlay (and its container ref) render on the same update that flips `active`; guard with
            // a rAF loop in case the ref is not yet attached when Cesium resolves.
            const mount = () => {
                if (!this.props.active) { return; }        // closed while Cesium was loading
                const el = this.containerRef.current;
                if (!el) { window.requestAnimationFrame(mount); return; }
                if (this.ctrl) { return; }
                this.ctrl = WholeMoonGlobe.createGlobe(Cesium, el, {onSitePick: this.dive});
                this.setState({status: 'ready'});
                this.loadSites();
            };
            window.requestAnimationFrame(mount);
        }).catch((e) => {
            this.setState({status: 'error', error: e && e.message ? e.message : String(e)});
        });
    };
    loadSites = () => {
        // PUBLIC Artemis-site markers via the keyless GET /api/world/site-markers (NOT the auth-gated
        // /api/sites, which 401s to the browser -- nginx forwards no key and S-06 keeps the registry gated).
        // Sourced from the SAME artemis_sites.geojson that draws the main-map pins, so a dive lands on a pin.
        fetch('/api/world/site-markers').then((r) => r.json()).then((j) => {
            const sites = (j && Array.isArray(j.sites)) ? j.sites : [];
            if (this.ctrl && this.cesium) {
                WholeMoonGlobe.addSites(this.cesium, this.ctrl, sites);
            }
            this.setState({sites});
        }).catch((e) => this.setState({error: 'sites: ' + (e && e.message ? e.message : String(e))}));
    };
    teardown = () => {
        if (this.ctrl) {
            WholeMoonGlobe.destroy(this.ctrl);
            this.ctrl = null;
        }
        this.setState({status: 'idle'});
    };
    // Dive to a site: recenter the polar workbench on it, then close the overview.
    dive = (site) => {
        if (!site || typeof site.lon !== 'number' || typeof site.lat !== 'number') { return; }
        const mapCrs = this.props.mapCrs || 'IAU_2015:30135';
        let extent = null;
        try {
            const c = CoordinatesUtils.reproject([site.lon, site.lat], GEO_CRS, mapCrs);
            extent = [c[0] - DIVE_HALF_M, c[1] - DIVE_HALF_M, c[0] + DIVE_HALF_M, c[1] + DIVE_HALF_M];
        } catch {
            extent = null;
        }
        if (extent) {
            this.props.zoomToExtent(extent, mapCrs);
        }
        this.props.setCurrentTask(null);
    };
    close = () => {
        this.props.setCurrentTask(null);
    };
    renderChips() {
        const sites = this.state.sites || [];
        if (!sites.length) { return null; }
        return (
            <div style={{display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '8px'}}>
                {sites.map((s) => (
                    <button
                        key={s.name}
                        onClick={() => this.dive(s)}
                        style={{
                            font: '11px system-ui, sans-serif', cursor: 'pointer',
                            padding: '3px 9px', borderRadius: '12px',
                            border: '1px solid ' + (s.imported ? '#39ff14' : '#e0b300') + '66',
                            color: s.imported ? '#39ff14' : '#e0b300',
                            background: (s.imported ? '#39ff14' : '#e0b300') + '14'
                        }}
                        title={'Dive to ' + (s.label || s.name) + ' (recenter the polar workbench)'}
                        type="button"
                    >
                        {s.label || s.name}
                    </button>
                ))}
            </div>
        );
    }
    renderOverlay() {
        const s = this.state;
        const headerStyle = {
            flex: '0 0 auto', padding: '12px 16px',
            background: 'linear-gradient(180deg, #0a0a12 0%, #0a0a12ee 100%)',
            borderBottom: '1px solid #23232e', color: '#c7d2e3', font: '13px system-ui, sans-serif'
        };
        return (
            <div style={{
                position: 'fixed', inset: 0, zIndex: 100000,
                display: 'flex', flexDirection: 'column', background: '#05050a'
            }}>
                <div style={headerStyle}>
                    <div style={{display: 'flex', alignItems: 'center', gap: '12px'}}>
                        <div style={{flex: '1 1 auto'}}>
                            <div style={{fontSize: '15px', fontWeight: 600, letterSpacing: '.02em', color: '#e6edf6'}}>
                                Whole Moon — mission context
                            </div>
                            <div style={{fontSize: '11px', color: '#8a93a3', marginTop: '2px'}}>
                                Spin the globe (both hemispheres). Click a site marker or chip to dive into the
                                south-polar workbench there. Imagery: <b>{WholeMoonGlobe.WAC.credit}</b>.
                            </div>
                        </div>
                        <button
                            onClick={this.close}
                            style={{
                                flex: '0 0 auto', cursor: 'pointer', font: '12px system-ui, sans-serif',
                                padding: '6px 14px', borderRadius: '4px', border: '1px solid #39ff1466',
                                color: '#39ff14', background: '#39ff1414'
                            }}
                            title="Back to the south-polar workbench"
                            type="button"
                        >
                            ✕ Back to workbench
                        </button>
                    </div>
                    {s.status === 'error' ? (
                        <div style={{marginTop: '8px', fontSize: '11px', color: '#e0564b'}}>
                            3-D globe unavailable on this machine: {s.error} (the south-polar workbench is
                            unaffected — close this overview to return to it).
                        </div>
                    ) : null}
                    {s.error && s.status !== 'error' ? (
                        <div style={{marginTop: '8px', fontSize: '11px', color: '#e0b300'}}>{s.error}</div>
                    ) : null}
                    {this.renderChips()}
                </div>
                <div style={{flex: '1 1 auto', position: 'relative', minHeight: 0}}>
                    <div
                        data-stewie-wholemoon-globe="1"
                        ref={this.containerRef}
                        style={{position: 'absolute', inset: 0}}
                    />
                    {s.status === 'loading' || s.status === 'idle' ? (
                        <div style={{
                            position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
                            justifyContent: 'center', color: '#8a93a3', font: '12px system-ui, sans-serif',
                            pointerEvents: 'none'
                        }}>
                            loading the lunar globe…
                        </div>
                    ) : null}
                </div>
            </div>
        );
    }
    render() {
        if (!this.props.active) { return null; }
        // Portal to <body> so the full-screen overlay is not clipped by any transformed QWC2 ancestor.
        return ReactDOM.createPortal(this.renderOverlay(), document.body);
    }
}

export default connect((state) => ({
    active: state.task.id === 'WholeMoon',
    mapCrs: state.map.projection
}), {
    setCurrentTask: setCurrentTask,
    zoomToExtent: zoomToExtent
})(WholeMoon);
