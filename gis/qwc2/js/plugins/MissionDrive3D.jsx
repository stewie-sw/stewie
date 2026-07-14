/**
 * MissionDrive3D — the STEWIE viz2 DRIVE-VALIDATE panel inside the lunar IDE (artemis.stewie.space/ide/).
 * The "3D validate" companion to the 2D map: it embeds the viz2 Godot pixel-stream (the driveable rover
 * sim over the real Haworth SfS DEM) as an <iframe>, and hands it the mission the operator authored on the
 * map so the drive VALIDATES the exact plan. Plan -> visualization -> action, all in one web app.
 *
 * SEAM (no reinvention): viz2's stream.html already accepts a mission via postMessage
 * ({type:'stewie:plan', waypoints, lonlat}) from an allowlisted parent origin, converts lon/lat -> 30135
 * via the shared dem_source transform, routes it with lode.route_leg, and drives it on {traverse}. This
 * plugin is the parent side: it reads the mission ROUTE off the GW-02 workspace channel (WS.onRoute, which
 * carries IAU_2015:30100 lon/lat points — MissionPlan._adoptRoute reprojects the same) and postMessages it
 * into the iframe. The iframe's origin gate allowlists *.stewie.space + localhost, so no ?parent trust.
 *
 * viz2 ORIGIN/TOKEN: resolved from window.STEWIE_VIZ2_ORIGIN / STEWIE_VIZ2_TOKEN (set by the /ide config or
 * the artemis reverse-proxy in prod), or the ?viz2token= URL param for local dev; origin defaults to the
 * local :8900 dev server. viz2 is a SEPARATE service (host-side Godot render); this panel only embeds it.
 *
 * LIFECYCLE: shown while state.task.id === 'MissionDrive3D' (opened from the TopBar Validate menu). The
 * iframe mounts once; on a workspace ROUTE emission we forward it; a Re-send button re-forwards the last
 * route (e.g. after the iframe reconnects). Registration (both required):
 *   - js/appConfig.js    -> pluginsDef.plugins.MissionDrive3DPlugin
 *   - static/config.json -> plugins.common [{"name":"MissionDrive3D"}] + a Validate submenu item
 *                           {"key":"MissionDrive3D","title":"Drive 3D","icon":"play"}
 */
import React from 'react';
import {connect} from 'react-redux';

import PropTypes from 'prop-types';
import {setCurrentTask} from 'qwc2/actions/task';
import ResizeableWindow from 'qwc2/components/ResizeableWindow';
import SideBar from 'qwc2/components/SideBar';

import WS from '../mission/workspace.js';   // GW-02: shared workspace store (active site + the route channel)

// viz2 service location. Prod: injected by the /ide config / artemis reverse-proxy. Dev: localhost + a
// ?viz2token= param. viz2's origin gate allowlists *.stewie.space + localhost, so the /ide can embed it.
function _viz2Origin() {
    if (typeof window !== 'undefined' && window.STEWIE_VIZ2_ORIGIN) { return String(window.STEWIE_VIZ2_ORIGIN); }
    return 'http://127.0.0.1:8900';
}
function _viz2Token() {
    if (typeof window !== 'undefined') {
        if (window.STEWIE_VIZ2_TOKEN) { return String(window.STEWIE_VIZ2_TOKEN); }
        try { const t = new URLSearchParams(window.location.search).get('viz2token'); if (t) { return t; } } catch (e) { /* no token */ }
    }
    return '';
}
// [REQ:TR-03] `spawn` is the OPERATOR's chosen worksite section, in IAU_2015:30135 METRES — the frame this
// map already uses, so a click on it IS the coordinate viz2 wants, with NO reprojection anywhere.
// Without it, viz2 falls back to `_flattest_interior_spawn`, which hunts for the flattest ground in the WHOLE
// tile — so every session opened on the most boring 12 m in Haworth (measured relief 0.06 m, slope 0.28°).
// The terrain looked flat because it WAS flat; the DEM, the float32 height texture and the vertex shader
// were all correct. A spawn defines the WORLD, so it rides the iframe URL (a session-creation parameter),
// unlike a route, which is postMessaged live into a running session.
function _viz2StreamUrl(spawn) {
    const tok = _viz2Token();
    const q = [];
    if (tok) { q.push('token=' + encodeURIComponent(tok)); }
    if (Array.isArray(spawn) && Number.isFinite(spawn[0]) && Number.isFinite(spawn[1])) {
        q.push('start=' + encodeURIComponent(spawn[0].toFixed(1) + ',' + spawn[1].toFixed(1)));
    }
    return _viz2Origin() + '/stream' + (q.length ? '?' + q.join('&') : '');
}

// The workspace route channel carries selenographic lon/lat points; normalize each to a plain [lon,lat] pair
// (points may be {lon,lat} objects or [lon,lat]/[lon,lat,...] arrays) for viz2's waypoints_lonlat ingest.
function _toLonLat(points) {
    if (!Array.isArray(points)) { return []; }
    return points.map((p) => {
        if (Array.isArray(p) && p.length >= 2) { return [Number(p[0]), Number(p[1])]; }
        if (p && typeof p === 'object' && p.lon != null && p.lat != null) { return [Number(p.lon), Number(p.lat)]; }
        return null;
    }).filter((p) => p && Number.isFinite(p[0]) && Number.isFinite(p[1]));
}

class MissionDrive3D extends React.Component {
    static propTypes = {
        active: PropTypes.bool,   // state.task.id === 'MissionDrive3D'
        mapClick: PropTypes.object,   // [REQ:TR-03] state.map.click — coordinate is in the map CRS (30135 m)
        setCurrentTask: PropTypes.func,
        side: PropTypes.string
    };
    static defaultProps = {active: false, side: 'right'};
    state = {
        site: WS.site(),
        lastRouteN: 0,      // waypoints in the last forwarded route
        floating: false,
        spawn: null,        // [REQ:TR-03] operator-chosen worksite section, IAU_2015:30135 metres
        driven: null        // the spawn the CURRENTLY MOUNTED iframe was opened with
    };
    constructor(props) {
        super(props);
        this._iframe = null;
        this._lastRoute = null;   // last lon/lat route forwarded (for Re-send + iframe reconnect)
    }
    componentDidMount() {
        this._unsubWS = WS.subscribe((s) => { if (s && s.site !== this.state.site) { this.setState({site: s.site}); } });
        // when the operator authors/sends a mission route on the 2D map, forward it to the embedded drive sim.
        this._unsubRoute = WS.onRoute((points) => this._forwardRoute(points));
        if (typeof window !== 'undefined') {
            window.__stewieDrive3D = {
                streamUrl: () => _viz2StreamUrl(this.state.driven),
                lastRouteN: () => this.state.lastRouteN,
                resend: () => this._resend(),
                forward: (points) => this._forwardRoute(points),   // harness: drive a lon/lat route through the panel
                open: () => this.props.setCurrentTask('MissionDrive3D'),   // open the panel (also the TopBar Validate menu path)
                // [REQ:TR-03] harness: pick a section without a real map click, and read back what is armed/driven.
                setSpawn: (x, y) => this._setSpawn([Number(x), Number(y)]),
                spawn: () => this.state.spawn,
                driven: () => this.state.driven,
                driveHere: () => this._driveHere()
            };
        }
    }
    // [REQ:TR-03] A click on the /ide map, while this panel is open, ARMS a worksite section. The map CRS is
    // IAU_2015:30135 metres, so `coordinate` IS start_xy — no reprojection. Arming is deliberately separate
    // from driving: a spawn defines the WORLD, so applying it restarts the sim session, and that must be an
    // explicit act, not a side effect of clicking the map.
    componentDidUpdate(prevProps) {
        if (!this.props.active) { return; }
        const c = this.props.mapClick;
        if (!c || c === prevProps.mapClick) { return; }
        const xy = c.coordinate;
        if (Array.isArray(xy) && Number.isFinite(Number(xy[0])) && Number.isFinite(Number(xy[1]))) {
            this._setSpawn([Number(xy[0]), Number(xy[1])]);
        }
    }
    _setSpawn = (xy) => {
        if (!Array.isArray(xy) || !Number.isFinite(xy[0]) || !Number.isFinite(xy[1])) { return; }
        this.setState({spawn: xy});
    };
    // Remount the iframe on the chosen section. The URL is the seam (see _viz2StreamUrl): a new `start=`
    // means a NEW viz2 session over a new window of the DEM, which is exactly right — you cannot teleport a
    // conserved world, you open a different one.
    _driveHere = () => {
        if (!this.state.spawn) { return; }
        this.setState({driven: this.state.spawn});
    };
    componentWillUnmount() {
        if (this._unsubWS) { this._unsubWS(); }
        if (this._unsubRoute) { this._unsubRoute(); }
        if (typeof window !== 'undefined' && window.__stewieDrive3D) { delete window.__stewieDrive3D; }
    }
    _post(msg) {
        if (this._iframe && this._iframe.contentWindow) {
            this._iframe.contentWindow.postMessage(msg, _viz2Origin());   // targetOrigin scoped to viz2, not '*'
        }
    }
    _forwardRoute(points) {
        const wps = _toLonLat(points);
        if (!wps.length) { return; }
        this._lastRoute = wps;
        this._post({type: 'stewie:plan', waypoints: wps, lonlat: true});
        this.setState({lastRouteN: wps.length});
    }
    _resend = () => { if (this._lastRoute) { this._post({type: 'stewie:plan', waypoints: this._lastRoute, lonlat: true}); } };
    _setIframe = (el) => { this._iframe = el; };
    _setFloating = () => { this.setState({floating: true}); };

    renderBody = () => {
        const s = this.state;
        return (
            <div style={{background: '#0a0a0c', color: '#c7d2e3', padding: '8px', font: '11px system-ui, sans-serif'}}>
                {!s.floating && (
                    <button data-stewie-drive-float="1" onClick={this._setFloating} type="button"
                        title="pop out into a floating, draggable/resizable window"
                        style={{display: 'block', marginBottom: '6px', cursor: 'pointer', font: '600 10px system-ui, sans-serif',
                            padding: '4px 8px', borderRadius: '4px', border: '1px solid #39c6ff66', color: '#39c6ff', background: '#39c6ff14'}}
                    >⤢ Float</button>
                )}
                <div style={{fontSize: '10px', color: '#8a93a3', marginBottom: '6px', lineHeight: 1.4}}>
                    Drive-validate the authored mission on the real Haworth surface — site <b style={{color: '#4db6d4'}}>{s.site}</b>.
                    A route sent from the map drives the rover here; use the sim's WASD / touch pad + ▶ traverse.
                </div>
                {/* [REQ:TR-03] Choose the WORKSITE SECTION. Without this the sim always spawned on the flattest
                    interior spot of the whole tile (relief 0.06 m) — real terrain existed, the spawn avoided it. */}
                <div data-stewie-drive-spawnbar style={{display: 'flex', alignItems: 'center', gap: '8px',
                    margin: '0 0 6px', padding: '5px 6px', borderRadius: '4px',
                    border: '1px solid ' + (s.spawn ? '#ffc86644' : '#14141c'), background: s.spawn ? '#ffc86610' : '#0d0d12'}}>
                    <button data-stewie-drive-here="1" disabled={!s.spawn} onClick={this._driveHere} type="button"
                        title="open a new sim session on the selected section of the DEM"
                        style={{cursor: s.spawn ? 'pointer' : 'not-allowed', font: '600 10px system-ui, sans-serif',
                            padding: '3px 8px', borderRadius: '4px', whiteSpace: 'nowrap',
                            border: '1px solid ' + (s.spawn ? '#ffc866aa' : '#2a2a35'),
                            color: s.spawn ? '#ffc866' : '#4a4a57', background: s.spawn ? '#ffc86618' : 'transparent'}}
                    >⌖ Drive here</button>
                    <span data-stewie-drive-spawn style={{color: s.spawn ? '#c7d2e3' : '#8a93a3', fontSize: '10px'}}>
                        {s.spawn
                            ? ('section ' + s.spawn[0].toFixed(0) + ', ' + s.spawn[1].toFixed(0) + ' m'
                               + (s.driven && s.driven[0] === s.spawn[0] && s.driven[1] === s.spawn[1] ? ' — driving' : ' — press Drive here'))
                            : 'click the map to select a worksite section (else: flattest spot in the tile)'}
                    </span>
                </div>
                <div style={{position: 'relative', width: '100%', height: '340px', background: '#05060c',
                    border: '1px solid #14141c', borderRadius: '4px', overflow: 'hidden'}}>
                    {/* keyed on the driven section: changing it REMOUNTS the iframe, i.e. opens a new viz2
                        session over a new window of the conserved world (you cannot teleport a conserved world). */}
                    <iframe data-stewie-drive-iframe key={s.driven ? s.driven.join(',') : 'auto'}
                        title="viz2 drive-validate stream" ref={this._setIframe}
                        src={_viz2StreamUrl(s.driven)} style={{width: '100%', height: '100%', border: 0}}
                        allow="fullscreen" />
                </div>
                <div style={{display: 'flex', alignItems: 'center', gap: '8px', margin: '6px 0 0'}}>
                    <button data-stewie-drive-resend="1" onClick={this._resend} type="button"
                        style={{cursor: 'pointer', font: '600 10px system-ui, sans-serif', padding: '3px 8px', borderRadius: '4px',
                            border: '1px solid #7fe0a866', color: '#7fe0a8', background: '#7fe0a814'}}
                    >↻ Re-send route</button>
                    <span data-stewie-drive-routen style={{color: '#8a93a3', fontSize: '10px'}}>
                        {s.lastRouteN ? (s.lastRouteN + ' wp forwarded — ▶ traverse in the sim to drive') : 'no route sent yet (author one on the map)'}
                    </span>
                </div>
            </div>
        );
    };
    render() {
        if (this.state.floating) {
            return (
                <ResizeableWindow dockable="right" icon="play" initialHeight={560} initialWidth={440}
                    initialX={480} initialY={70} maximizeable minimizeable
                    onClose={() => this.setState({floating: false})} scrollable title="Drive 3D">
                    {this.renderBody()}
                </ResizeableWindow>
            );
        }
        return (
            <SideBar icon="play" id="MissionDrive3D" side={this.props.side} title="Drive 3D" width="26em">
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

export default connect((state) => ({
    active: state.task.id === 'MissionDrive3D',
    // [REQ:TR-03] the map click, in the map CRS (IAU_2015:30135 metres) — already start_xy, no reprojection.
    mapClick: state.map ? state.map.click : null
}), {setCurrentTask})(MissionDrive3D);
