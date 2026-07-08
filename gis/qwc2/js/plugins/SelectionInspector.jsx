/**
 * SelectionInspector — the STEWIE per-cell SELECTION INSPECTOR ([REQ:GW-07]) for the lunar IDE
 * (artemis.stewie.space/ide/). The RICHER inspector beside QWC2's native Identify: where Identify returns a
 * theme feature's basic info, this returns, for the CLICKED map cell, the servable layers' ACTUAL values +
 * each value's provenance/confidence/freshness + the cell's runtime evidence + the mission actions the cell
 * affords.
 *
 * Opening "Inspector" dispatches setCurrentTask("SelectionInspector"); the SideBar (id="SelectionInspector")
 * shows while state.task.id === "SelectionInspector". WHILE ACTIVE it listens for a map singleclick (the same
 * OpenLayers map + IAU_2015:30135 CRS the base .qgz theme draws on, via MapUtils.GET_MAP), reprojects the
 * click to selenographic lon/lat, and drives ONE backend query:
 *   - ATTRIBUTES + RUNTIME EVIDENCE + ACTIONS: /api/world/point (per-cell values from the SAME functions the
 *     drapes render, so the reading IS the drape value at that cell; honest available=false where a layer has
 *     no per-cell scalar).
 *   - PROVENANCE + CONFIDENCE (GW-03) + FRESHNESS (GW-06): merged from /api/world/layer-catalog +
 *     /api/world/layer-manifest (fetched once), IDENTICAL to the Mission Layers panel.
 * The pure data layer is js/mission/selectionInspect.js (node-tested); this file owns the click + the DOM.
 * Listening ONLY while active keeps it from interfering with Mission Plan authoring or native Identify.
 *
 * Registration:
 *   - js/appConfig.js       -> pluginsDef.plugins.SelectionInspectorPlugin
 *   - static/config.json    -> plugins.common [{"name": "SelectionInspector"}] + a TopBar menu item
 *                              {"key": "SelectionInspector", "title": "Inspector", "icon": "info"}
 */
import React from 'react';

import PropTypes from 'prop-types';
import {connect} from 'react-redux';

import {setCurrentTask} from 'qwc2/actions/task';
import SideBar from 'qwc2/components/SideBar';
import CoordinatesUtils from 'qwc2/utils/CoordinatesUtils';
import MapUtils from 'qwc2/utils/MapUtils';

import SI from '../mission/selectionInspect';   // pure per-cell query + provenance/confidence/freshness merge
import WS from '../mission/workspace.js';        // GW-02: the shared workspace-context store (active site)
import RG from '../mission/reqGuard.js';         // #57: last-click-wins / stale-site request guard

// GW-02: the active site comes from the shared workspace (WS.site()), read at query time so every click
// inspects the current work site without a per-plugin literal or a re-render.
const GEO_CRS = 'IAU_2015:30100';        // selenographic lon/lat (the backend point-query frame)

// provenance accent per coarse source_class token (matches MissionLayers PROV_COLOR).
const PROV_COLOR = {
    live: '#39ff14', sim: '#8a5cff', replay: '#8a5cff', observed: '#4fd1ff', reconciled: '#4fd1ff',
    measured: '#4fd1ff', released: '#39c6ff', derived: '#e0b300', estimated: '#e0b300',
    learned: '#e0b300', belief: '#ff9d3c', forecast: '#c58cff', user: '#c7d2e3', prior: '#7a8290'
};
// confidence tier accent (matches MissionLayers TIER_COLOR).
const TIER_COLOR = {high: '#4fd1ff', medium: '#e0b300', low: '#ff9d3c', 'n/a': '#7a8290', unknown: '#7a8290'};

class SelectionInspector extends React.Component {
    static propTypes = {
        /** true while state.task.id === "SelectionInspector". */
        active: PropTypes.bool,
        /** The workbench map projection (state.map.projection), e.g. IAU_2015:30135. */
        mapCrs: PropTypes.string,
        setCurrentTask: PropTypes.func,
        side: PropTypes.string
    };
    static defaultProps = {
        active: false,
        mapCrs: 'IAU_2015:30135',
        side: 'right'
    };
    state = {
        catalog: null,     // /world/layer-catalog (per-layer provenance/confidence source)
        freshness: null,   // freshnessFromManifest(/world/layer-manifest) (per-site freshness, GW-06)
        point: null,       // the last /world/point payload
        clickLonLat: null, // [lon, lat] of the last click
        loading: false,
        error: null
    };
    constructor(props) {
        super(props);
        this.map = null;
        this._clickKey = null;
        this._raf = 0;
    }
    componentDidMount() {
        this._rg = RG.makeReqGuard();   // #57: last-click-wins guard for the point query
        // the provenance/confidence (catalog) source — site-independent, fetched once.
        if (SI.fetchCatalog) {
            SI.fetchCatalog().then((cat) => this.setState({catalog: cat})).catch(() => {});
        }
        this._loadManifest();
        // #57 (was mount-only): re-fetch the per-site freshness manifest on a site change, and invalidate any
        // in-flight point query so an old-site cell can't resolve into the new site's inspector.
        this._unsubWS = WS.subscribe(() => {
            if (this._rg) { this._rg.bump(); }
            this.setState({point: null, clickLonLat: null});   // council #55 [2]: clear the stale per-cell readout on a site switch
            this._loadManifest();
        });
    }
    _loadManifest = () => {
        if (SI.fetchLayerManifest && SI.freshnessFromManifest) {
            const site = WS.site();
            SI.fetchLayerManifest(site)
                .then((m) => { if (WS.site() !== site) { return; } this.setState({freshness: SI.freshnessFromManifest(m)}); })
                .catch(() => {});   // degrade silently to "no freshness" — the inspector still renders values
        }
    };
    componentDidUpdate(prevProps) {
        if (this.props.active && !prevProps.active) { this._attachClick(); }
        else if (!this.props.active && prevProps.active) { this._detachClick(); }
    }
    componentWillUnmount() { if (this._rg) { this._rg.bump(); } if (this._unsubWS) { this._unsubWS(); } this._detachClick(); }

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
        // the OL view coordinate is in the map CRS (IAU_2015:30135); reproject to selenographic lon/lat for
        // the backend point-query (which resolves lat/lon -> the site DEM cell).
        let lonlat;
        try { lonlat = CoordinatesUtils.reproject(evt.coordinate, this.props.mapCrs, GEO_CRS); }
        catch (e) { this.setState({error: 'reproject failed: ' + e.message}); return; }
        const lon = lonlat[0];
        const lat = lonlat[1];
        this.setState({loading: true, error: null, clickLonLat: [lon, lat]});
        const site = WS.site();
        const tok = this._rg.next();   // #57: last-click-wins + drop if the site changed while in flight
        SI.fetchPoint(site, {lon, lat})
            .then((point) => { if (!this._rg.current(tok) || WS.site() !== site) { return; } this.setState({point, loading: false}); })
            .catch((e) => { if (!this._rg.current(tok) || WS.site() !== site) { return; } this.setState({error: 'point query: ' + e.message, loading: false, point: null}); });
    };

    _rows() {
        const catById = SI.catalogById(this.state.catalog);
        return SI.mergeAttributes(this.state.point, catById, this.state.freshness);
    }

    renderBadge(txt, color, title) {
        return (
            <span style={{
                fontSize: '8px', letterSpacing: '.02em', padding: '0 3px', borderRadius: '3px',
                border: '1px solid ' + color + '55', color: color, flex: '0 0 auto', whiteSpace: 'nowrap'
            }} title={title}>{txt}</span>
        );
    }
    renderAttrRow(row) {
        const provCol = PROV_COLOR[row.provClass] || '#7a8290';
        const val = SI.formatValue(row);
        const conf = row.confidence;
        const confCol = conf ? (TIER_COLOR[conf.tier] || '#7a8290') : null;
        return (
            <div key={row.id} data-stewie-attr={row.id}
                style={{display: 'flex', alignItems: 'center', gap: '6px', padding: '3px 0 3px 4px',
                    borderTop: '1px solid #14141c', fontSize: '11px'}}>
                <span style={{flex: '1 1 auto', color: '#c7d2e3', whiteSpace: 'nowrap', overflow: 'hidden',
                    textOverflow: 'ellipsis'}} title={row.id}>{row.label}</span>
                {row.available ? (
                    <span data-stewie-val={row.id}
                        style={{flex: '0 0 auto', color: '#e6edf6', fontFamily: 'ui-monospace, monospace',
                            fontSize: '11px'}}>{val}</span>
                ) : (
                    <span data-stewie-nodata={row.id} title={row.note || 'no data at this cell'}
                        style={{flex: '0 0 auto', color: '#6f7684', fontStyle: 'italic', fontSize: '10px'}}>
                        no data
                    </span>
                )}
                {row.sourceClass ? this.renderBadge(row.sourceClass, provCol,
                    'provenance (source_class): ' + row.sourceClass) : null}
                {conf && conf.cls ? this.renderBadge('◈' + conf.cls + (conf.downgraded ? '~' : ''), confCol,
                    'confidence: ' + conf.cls + ' / ' + conf.tier
                    + (conf.downgraded ? ' (downgraded — site is prior/unobserved)' : '')) : null}
                {row.freshness && row.freshness.provClass ? this.renderBadge(
                    '◷' + row.freshness.provClass,
                    row.freshness.provClass === 'observed' ? '#4fd1ff' : '#6f7684',
                    'freshness (GW-06): ' + row.freshness.provClass
                    + (row.freshness.observedPct != null ? ' · ' + row.freshness.observedPct + '% obs' : '')
                    + (row.freshness.demSource ? ' · ' + row.freshness.demSource : '')) : null}
            </div>
        );
    }
    renderRuntime(ev) {
        if (!ev) return null;
        const built = ev.cell_source === 'as_built';
        const obs = ev.cell_source === 'observed';
        const col = obs ? '#4fd1ff' : (built ? '#ff9d3c' : '#8a93a3');
        const pct = (typeof ev.observed_fraction === 'number')
            ? (Math.round(ev.observed_fraction * 1000) / 10) + '%' : 'n/a';
        return (
            <div style={{marginTop: '10px'}}>
                <div style={SECTION}>Runtime evidence</div>
                <div style={{fontSize: '11px', color: '#c7d2e3', lineHeight: 1.5}}>
                    <div>cell state: <b style={{color: col}}>{ev.cell_source}</b>
                        {ev.observed_at_cell ? ' (measured here)' : ''}</div>
                    <div>as-built change: <b style={{color: '#e6edf6', fontFamily: 'ui-monospace, monospace'}}>
                        {(Math.round(ev.as_built_delta_m * 1000) / 1000)} m</b>
                        {ev.as_built_version ? ' · built v' + ev.as_built_version : ''}</div>
                    <div>site observed twin: <b style={{color: '#4fd1ff'}}>{pct}</b>
                        {ev.twin_version ? ' · twin v' + ev.twin_version : ''}</div>
                </div>
            </div>
        );
    }
    renderActions(actions) {
        if (!Array.isArray(actions) || !actions.length) return null;
        return (
            <div style={{marginTop: '10px'}}>
                <div style={SECTION}>Available actions</div>
                <div style={{display: 'flex', flexWrap: 'wrap', gap: '5px'}}>
                    {actions.map((a) => (
                        <span key={a.id} data-stewie-action={a.id}
                            title={a.enabled ? a.label : (a.reason || 'unavailable')}
                            style={{fontSize: '10px', padding: '3px 7px', borderRadius: '4px',
                                border: '1px solid ' + (a.enabled ? '#39c6ff66' : '#2a2a36'),
                                color: a.enabled ? '#39c6ff' : '#565b66',
                                background: a.enabled ? '#39c6ff14' : 'transparent',
                                cursor: a.enabled ? 'pointer' : 'not-allowed'}}>
                            {a.label}{a.enabled ? '' : ' ⃠'}
                        </span>
                    ))}
                </div>
            </div>
        );
    }
    renderBody = () => {
        const s = this.state;
        const p = s.point;
        const rows = this._rows();
        const parts = SI.partition(rows);
        return (
            <div style={{background: '#0a0a0c', color: '#c7d2e3', padding: '8px',
                font: '11px system-ui, sans-serif'}}>
                <div style={{fontSize: '10px', color: '#8a93a3', marginBottom: '6px', lineHeight: 1.4}}>
                    Click a map cell to inspect the servable layers there: <b>values</b> (from
                    <b> /api/world/point</b>, computed by the same functions the drapes render), each with its
                    <b> provenance · confidence · freshness</b>, plus the cell's runtime evidence + the actions
                    it affords. Honest <i>no data</i> where a layer has no per-cell value.
                </div>
                {s.error ? (
                    <div style={{fontSize: '10px', color: '#e0564b', marginBottom: '6px'}}>error: {s.error}</div>
                ) : null}
                {s.loading ? (
                    <div style={{fontSize: '11px', color: '#7a8290', padding: '6px 0'}}>querying cell…</div>
                ) : null}
                {!p && !s.loading ? (
                    <div data-stewie-empty style={{fontSize: '11px', color: '#7a8290', padding: '10px 4px'}}>
                        No cell selected — click the map.
                    </div>
                ) : null}
                {p ? (
                    <div>
                        <div style={{fontSize: '10px', color: '#8a93a3', marginBottom: '6px',
                            fontFamily: 'ui-monospace, monospace'}}>
                            {p.cell && p.cell.in_bounds
                                ? ('cell r' + p.cell.row + ' c' + p.cell.col + ' @ ' + p.cell.cell_m + ' m'
                                   + (s.clickLonLat
                                       ? '  ·  ' + s.clickLonLat[1].toFixed(4) + '°, ' + s.clickLonLat[0].toFixed(4) + '°'
                                       : ''))
                                : 'outside the site tile — no data at this location'}
                        </div>
                        <div style={SECTION}>
                            Attributes <span style={{color: '#565b66', fontWeight: 400}}>
                                ({parts.measured.length} measured)</span>
                        </div>
                        {parts.measured.map((r) => this.renderAttrRow(r))}
                        {parts.nodata.length ? (
                            <div style={{marginTop: '8px'}}>
                                <div style={SECTION}>No per-cell value
                                    <span style={{color: '#565b66', fontWeight: 400}}> ({parts.nodata.length})</span>
                                </div>
                                {parts.nodata.map((r) => this.renderAttrRow(r))}
                            </div>
                        ) : null}
                        {this.renderRuntime(p.runtime_evidence)}
                        {this.renderActions(p.actions)}
                    </div>
                ) : null}
            </div>
        );
    };
    render() {
        return (
            <SideBar
                icon="info"
                id="SelectionInspector"
                side={this.props.side}
                title="Selection Inspector"
                width="24em"
            >
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

const SECTION = {
    fontSize: '10px', fontWeight: 600, color: '#aeb8c6', letterSpacing: '.03em',
    textTransform: 'uppercase', margin: '4px 0 2px'
};

export default connect((state) => ({
    active: state.task.id === 'SelectionInspector',
    mapCrs: (state.map && state.map.projection) || 'IAU_2015:30135'
}), {
    setCurrentTask: setCurrentTask
})(SelectionInspector);
