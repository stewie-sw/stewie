/**
 * SiteZoom — CLICK-A-SITE-TO-ZOOM for the STEWIE lunar IDE main map (artemis.stewie.space/ide/).
 *
 * WHAT + WHY: the operator reported "can't click on locations to zoom in". The Whole Moon overlay already
 * DIVES on a site click (js/plugins/WholeMoon.jsx -> zoomToExtent), but the south-polar WORKBENCH map's
 * Artemis site markers (the .qgz "Artemis site pins" + "Artemis site footprints" layers) were static — a
 * click on one did nothing. This plugin makes a main-map singleclick that lands on an Artemis site FLY the
 * workbench to that site's footprint, using the SAME dive as the overlay.
 *
 * REUSE, not reinvent: the site markers are the SAME public /api/world/site-markers payload the Whole Moon
 * overlay's markers come from ({name, label, lon, lat, extent_m}, sourced from the artemis_sites.geojson that
 * draws the VISIBLE main-map pins); the framing box + CRS + zoomToExtent are IDENTICAL to WholeMoon.dive (via
 * js/mission/siteZoom.js, which keeps HALF_M/GEO_CRS in lockstep with WholeMoon.jsx). So a click on the main
 * map flies to EXACTLY the box the overlay dives to, and lands on the pin the operator clicked.
 *
 * A THIN, ALWAYS-MOUNTED MAP LISTENER (renders null): like SelectionInspector.jsx it grabs the raw OpenLayers
 * map (MapUtils.GET_MAP) and listens for a `singleclick`, reprojecting the site centers to the map CRS
 * (state.map.projection = IAU_2015:30135) before the hit-test. On a hit it dispatches zoomToExtent; on a miss
 * it does NOTHING, so the default map behaviors — pan, scroll / double-click zoom, and QWC2 native Identify —
 * are untouched.
 *
 * WHO OWNS THE CLICK (no conflict): while GW-07 Selection Inspector is the current task it OWNS the click (it
 * reads the clicked cell), and while MissionPlan is the current task its authoring controller OWNS the click
 * (it places orders / draws no-go regions). The stock QWC2 draw/edit/measure/route tools likewise consume the
 * click while active. SiteZoom stands down for ALL of them — CLICK_OWNED_BY below — so it is only the DEFAULT
 * site-click behavior otherwise: on the default map view (state.task.id === null, mapClickAction "identify")
 * and while a benign side panel (Rover HUD / Mission Layers / Layer Tree / ...) is open. Native Identify is
 * deliberately NOT in the set: SiteZoom is additive on top of the default identify click. Because it flies to a
 * site only when the click lands INSIDE a site footprint (else no-op), it never fights a plain pan or an
 * Identify on empty terrain.
 *
 * Registration:
 *   - js/appConfig.js     -> pluginsDef.plugins.SiteZoomPlugin
 *   - static/config.json  -> plugins.common [{"name": "SiteZoom"}]  (no menu item — it is a passive listener)
 */
import React from 'react';

import PropTypes from 'prop-types';
import {connect} from 'react-redux';

import {zoomToExtent} from 'qwc2/actions/map';
import CoordinatesUtils from 'qwc2/utils/CoordinatesUtils';
import MapUtils from 'qwc2/utils/MapUtils';

import SZ from '../mission/siteZoom';   // pure hit-test + WholeMoon-identical framing box (node-tested)
import WS from '../mission/workspace.js';   // #50: propagate the clicked site to the shared workspace
import FT from '../mission/fetchWithTimeout';   // [systems-eng] bounded read: abort a hung /world/site-markers

// The tasks that OWN a map singleclick (each reads it or attaches its own Draw/Modify interaction). While any
// is the current task, the site-zoom default stands down so it never steals their click or flies the view out
// from under a draw. The two STEWIE authoring tasks (GW-07 Inspector, MissionPlan) plus the stock QWC2
// draw/edit/measure/route tools registered in appConfig.js. Native Identify is intentionally ABSENT — SiteZoom
// is additive on top of the default identify click; and a benign side panel (MissionHUD/MissionLayers/
// LayerTree/...) is absent too, so a site click still zooms while one is open.
const CLICK_OWNED_BY = {
    SelectionInspector: true, MissionPlan: true, MissionCrossSection: true,   // council #55 [4]: transect-draw owns clicks
    Measure: true, Redlining: true, Editing: true, Routing: true,
    GeometryDigitizer: true, ScratchDrawing: true, FeatureForm: true
};

class SiteZoom extends React.Component {
    static propTypes = {
        /** The workbench map projection (state.map.projection), e.g. IAU_2015:30135. */
        mapCrs: PropTypes.string,
        /** The current task id (state.task.id) — used to stand down while another task owns the click. */
        taskId: PropTypes.string,
        zoomToExtent: PropTypes.func
    };
    static defaultProps = {
        mapCrs: 'IAU_2015:30135'
    };
    constructor(props) {
        super(props);
        this.state = {site: WS.site()};   // #50: the active workspace site, for the always-on chip
        this.map = null;
        this.sites = [];          // the public /api/world/site-markers rows ({name, label, lon, lat, extent_m})
        this._clickKey = null;
        this._raf = 0;
    }
    componentDidMount() {
        this._loadSites();
        this._attachClick();
        this._unsubWS = WS.subscribe((s) => { this.setState({site: s.site}); });   // #50: keep the chip live
        // Read-only headless harness handle for the Playwright verify (same hit-test the click runs, but with
        // NO side effect): report the loaded site count + which site a given map coord would fly to. No command
        // authority — the interactive proof drives a real click for the actual zoom.
        if (typeof window !== 'undefined') {
            window.__stewieSiteZoom = {
                siteCount: () => this.sites.length,
                hitAt: (coord) => {
                    const h = SZ.pickSiteAt(coord, this.sites, CoordinatesUtils.reproject, this.props.mapCrs, SZ.HALF_M);
                    return h ? {name: h.site.name, label: h.site.label, extent: h.extent.slice()} : null;
                }
            };
        }
    }
    componentWillUnmount() {
        this._detachClick();
        if (this._unsubWS) { this._unsubWS(); }
        if (typeof window !== 'undefined' && window.__stewieSiteZoom) { delete window.__stewieSiteZoom; }
    }

    // The PUBLIC Artemis-site markers — the keyless same-origin GET /api/world/site-markers (NOT the auth-gated
    // /api/sites, which 401s to the browser: nginx forwards no key on the generic /api/ block, and S-06 keeps
    // the operational registry gated). site-markers is sourced from the SAME artemis_sites.geojson that draws
    // the VISIBLE main-map pins, so a click lands on the box a pin marks. Rows: {name, label, lon, lat, extent_m}.
    _loadSites = () => {
        FT.fetchWithTimeout('/api/world/site-markers', {}, FT.DEFAULT_MS).then((r) => r.json()).then((j) => {
            this.sites = (j && Array.isArray(j.sites)) ? j.sites : [];
            this.forceUpdate();   // the chip resolves the site NAME -> friendly label once the markers load
        }).catch(() => { this.sites = []; });   // no sites -> every click is a miss -> default behavior stands
    };

    _attachClick = () => {
        const map = MapUtils.getHook(MapUtils.GET_MAP);
        if (!map) { this._raf = requestAnimationFrame(this._attachClick); return; }   // map not mounted yet
        this.map = map;
        if (this._clickKey) { return; }
        this._clickKey = map.on('singleclick', this._onMapClick);
    };
    _detachClick = () => {
        if (this._raf) { cancelAnimationFrame(this._raf); this._raf = 0; }
        if (this.map && this._clickKey) { this.map.un('singleclick', this._clickKey.listener); }
        this._clickKey = null;
    };

    _onMapClick = (evt) => {
        // Stand down while another task owns the click (GW-07 Inspector / MissionPlan authoring). `this.props`
        // is live on the mounted instance, so this reads the CURRENT task at click time.
        if (CLICK_OWNED_BY[this.props.taskId]) { return; }
        if (!this.sites || !this.sites.length) { return; }
        // evt.coordinate is already in the map CRS (IAU_2015:30135); the hit-test reprojects the site centers
        // (selenographic lon/lat) into it. A miss returns null -> we do nothing, so pan / scroll+double-click
        // zoom / Identify all stand.
        const hit = SZ.pickSiteAt(evt.coordinate, this.sites, CoordinatesUtils.reproject,
            this.props.mapCrs, SZ.HALF_M);
        if (hit && hit.extent) {
            this.props.zoomToExtent(hit.extent, this.props.mapCrs);   // the SAME dive as WholeMoon.dive
            if (hit.site && hit.site.name) { WS.set({site: hit.site.name}); }   // #50: propagate the site (was the silent wrong-site bug)
        }
    };

    render() {
        // #50: an always-visible chip so the active work site is never ambiguous (it appeared nowhere before).
        const site = this.state.site;
        if (!site) { return null; }
        const match = (this.sites || []).find((x) => x.name === site);
        const disp = (match && match.label) || site;   // friendly label once site-markers load, else the id
        return (
            <div className="stewie-site-chip" style={{position: 'absolute', top: '52px', left: '8px', zIndex: 20,
                background: 'rgba(16,16,19,0.92)', color: '#e6e8ea', border: '1px solid #26262c', borderRadius: '4px',
                padding: '3px 9px', fontSize: '12px', pointerEvents: 'none', letterSpacing: '0.02em'}}>
                <span style={{color: '#8a9096'}}>Site: </span><span style={{color: '#4db6d4', fontWeight: 600}}>{disp}</span>
            </div>
        );
    }
}

export default connect((state) => ({
    mapCrs: (state.map && state.map.projection) || 'IAU_2015:30135',
    taskId: state.task && state.task.id
}), {
    zoomToExtent: zoomToExtent
})(SiteZoom);
