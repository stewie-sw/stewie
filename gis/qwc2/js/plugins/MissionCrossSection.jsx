/**
 * MissionCrossSection — the STEWIE resource-exploration CROSS-SECTION ([REQ:SD-03], task #45) for the lunar IDE
 * (artemis.stewie.space/ide/). Draw a transect (click a START then an END on the map) and get a PROFILE CHART of
 * the REAL per-cell layers sampled along it: elevation (LOLA DEM) + slope + bearing + sinkage (terramechanics
 * spine) + PSR (permanently-shadowed cold-trap, horizon-computed), each traced to its producer.
 *
 * Opening "Cross-section" dispatches setCurrentTask("MissionCrossSection"); the SideBar shows while
 * state.task.id === "MissionCrossSection". WHILE ACTIVE it listens for map singleclicks (the same OL map +
 * IAU_2015:30135 CRS the base .qgz theme draws on, via MapUtils.GET_MAP): the first two clicks set the transect
 * start + end (30135 metres). On the 2nd click it densifies the line to N uniform samples (js/mission/
 * crossSection.js, node-tested), reprojects each to selenographic lon/lat, and POSTs /api/world/transect
 * {frame:'lonlat'}; the backend converts to order metres (like /world/point) + returns the profile.
 *
 * HONESTY: ice-stability has no real per-cell dataset (terrain.thermal is catalog-only), so the backend reports
 * it in `unavailable` and this panel renders it as an explicit GREY GAP NOTE — never a fabricated curve. PSR is
 * the real ice-relevant proxy.
 *
 * Registration: js/appConfig.js -> pluginsDef.plugins.MissionCrossSectionPlugin ; static/config.json ->
 * plugins.common [{"name":"MissionCrossSection"}] + a TopBar SecValidate menu item.
 */
import React from 'react';

import PropTypes from 'prop-types';
import {connect} from 'react-redux';

import {setCurrentTask} from 'qwc2/actions/task';
import SideBar from 'qwc2/components/SideBar';
import CoordinatesUtils from 'qwc2/utils/CoordinatesUtils';
import MapUtils from 'qwc2/utils/MapUtils';

import CS from '../mission/crossSection.js';    // #45: pure densify + profile series / PSR bands (node-tested)
import WS from '../mission/workspace.js';        // GW-02: the shared workspace-context store (active site)
import RG from '../mission/reqGuard.js';         // #57: last-request-wins / stale-site guard

const GEO_CRS = 'IAU_2015:30100';                // selenographic lon/lat (the backend transect frame)
const N_SAMPLES = 128;                           // densified transect samples (<=512; backend caps)

const SECTION = {
    fontSize: '10px', fontWeight: 600, color: '#aeb8c6', letterSpacing: '.03em',
    textTransform: 'uppercase', margin: '6px 0 2px'
};
const BTN = {
    fontSize: '10px', padding: '3px 9px', borderRadius: '4px', border: '1px solid #39c6ff66',
    color: '#39c6ff', background: '#39c6ff14', cursor: 'pointer'
};

class MissionCrossSection extends React.Component {
    static propTypes = {
        active: PropTypes.bool,
        mapCrs: PropTypes.string,
        setCurrentTask: PropTypes.func,
        side: PropTypes.string
    };
    static defaultProps = {active: false, mapCrs: 'IAU_2015:30135', side: 'right'};
    state = {
        picks: [],        // 0..2 clicked points in the map (30135) frame: [[x,y], ...]
        profile: null,    // the last /world/transect payload
        overlay: null,    // null | 'bearing' | 'slope' -- the 2nd curve overlaid on elevation
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
        this._rg = RG.makeReqGuard();
        // on a site change: drop any in-flight transect + clear the picks/profile (a transect is site-specific).
        this._unsubWS = WS.subscribe(() => {
            if (this._rg) { this._rg.bump(); }
            this.setState({picks: [], profile: null, loading: false, error: null});
        });
    }
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
        const picks = this.state.picks.length >= 2 ? [] : this.state.picks.slice();   // 3rd click starts fresh
        picks.push([evt.coordinate[0], evt.coordinate[1]]);
        this.setState({picks, error: null});
        if (picks.length === 2) { this._runTransect(picks); }
    };
    _runTransect(picks) {
        let lonlat;
        try {
            lonlat = CS.densify(picks, N_SAMPLES).map((pt) => {
                const ll = CoordinatesUtils.reproject(pt, this.props.mapCrs, GEO_CRS);
                return [ll[0], ll[1]];   // [lon, lat]
            });
        } catch (e) { this.setState({error: 'reproject failed: ' + e.message}); return; }
        const site = WS.site();
        const tok = this._rg.next();   // #57: last-transect-wins + drop if the site changed while in flight
        this.setState({loading: true, error: null});
        fetch('/api/world/transect', {
            method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({site: site, frame: 'lonlat', points: lonlat})
        }).then((r) => { if (!r.ok) { throw new Error('HTTP ' + r.status); } return r.json(); })
            .then((profile) => {
                if (!this._rg.current(tok) || WS.site() !== site) { return; }
                this.setState({profile, loading: false});
            })
            .catch((e) => {
                if (!this._rg.current(tok) || WS.site() !== site) { return; }
                this.setState({error: 'transect: ' + e.message, loading: false, profile: null});
            });
    }
    _clear = () => { if (this._rg) { this._rg.bump(); } this.setState({picks: [], profile: null, error: null, loading: false}); };

    renderChart(profile) {
        const W = 320, H = 140, PAD = 5;
        const elev = CS.series(profile.samples, 'elevation_m');
        if (elev.length < 2) {
            return <div style={{fontSize: '11px', color: '#7a8290', padding: '8px 0'}}>
                the transect has no in-bounds elevation samples (drawn outside the site tile?)
            </div>;
        }
        const maxDist = elev[elev.length - 1].dist || 1;
        const ee = CS.extent(elev);
        const x = (d) => PAD + (d / maxDist) * (W - 2 * PAD);
        const y = (v, lo, hi) => H - PAD - ((v - lo) / (hi - lo)) * (H - 2 * PAD);
        const line = (pts, lo, hi) => pts.map((p, i) => (i ? 'L' : 'M') + x(p.dist).toFixed(1) + ' ' + y(p.value, lo, hi).toFixed(1)).join(' ');
        const bands = CS.psrBands(profile.samples);
        const ov = this.state.overlay;
        let ovPath = null;
        if (ov) {
            const os = CS.series(profile.samples, ov === 'bearing' ? 'bearing_pa' : 'slope_deg');
            if (os.length >= 2) { const oe = CS.extent(os); ovPath = line(os, oe[0], oe[1]); }
        }
        return (
            <svg width={W} height={H} data-stewie-transect-chart
                style={{background: '#0a0a0c', border: '1px solid #14141c', display: 'block'}}>
                {bands.map((b, i) => (
                    <rect key={i} data-stewie-psr-band x={x(b[0])} y={PAD}
                        width={Math.max(1.5, x(b[1]) - x(b[0]))} height={H - 2 * PAD}
                        fill="#8a5cff" fillOpacity="0.20" />
                ))}
                <path data-stewie-elev d={line(elev, ee[0], ee[1])} fill="none" stroke="#4fd1ff" strokeWidth="1.5" />
                {ovPath ? <path d={ovPath} fill="none" stroke="#e0b300" strokeWidth="1" strokeDasharray="3 2" /> : null}
            </svg>
        );
    }
    renderBody = () => {
        const s = this.state;
        const p = s.profile;
        return (
            <div style={{background: '#0a0a0c', color: '#c7d2e3', padding: '8px', font: '11px system-ui, sans-serif'}}>
                <div style={{fontSize: '10px', color: '#8a93a3', marginBottom: '6px', lineHeight: 1.4}}>
                    Draw a transect — click a <b>start</b> then an <b>end</b> on the map — to sample the REAL layers
                    along it from <b>/api/world/transect</b>: elevation · slope · bearing · sinkage · PSR (cold-trap).
                </div>
                <div style={{display: 'flex', gap: '8px', marginBottom: '6px', alignItems: 'center'}}>
                    <button data-stewie-clear onClick={this._clear} style={BTN}>Clear</button>
                    <span style={{fontSize: '10px', color: '#7a8290'}}>
                        {s.picks.length === 0 ? 'click the START point' : (s.picks.length === 1 ? 'click the END point' : 'transect set')}
                    </span>
                </div>
                {s.error ? <div style={{fontSize: '10px', color: '#e0564b', marginBottom: '6px'}}>error: {s.error}</div> : null}
                {s.loading ? (
                    <div data-stewie-loading style={{fontSize: '11px', color: '#7a8290', padding: '6px 0'}}>
                        sampling the transect… (first one per site ~13 s — computing the PSR sun-azimuth sweep)
                    </div>
                ) : null}
                {p ? (
                    <div>
                        {this.renderChart(p)}
                        <div style={{display: 'flex', gap: '10px', marginTop: '4px', fontSize: '10px', color: '#aeb8c6'}}>
                            <span>overlay:</span>
                            <label><input type="radio" name="ovl" checked={s.overlay === null} onChange={() => this.setState({overlay: null})} /> none</label>
                            <label><input type="radio" name="ovl" checked={s.overlay === 'bearing'} onChange={() => this.setState({overlay: 'bearing'})} /> bearing</label>
                            <label><input type="radio" name="ovl" checked={s.overlay === 'slope'} onChange={() => this.setState({overlay: 'slope'})} /> slope</label>
                        </div>
                        <div style={{fontSize: '10px', color: '#8a93a3', marginTop: '6px', lineHeight: 1.45}}>
                            <div><b style={{color: '#4fd1ff'}}>▬</b> elevation (m)
                                {s.overlay ? <span> · <b style={{color: '#e0b300'}}>┈</b> {s.overlay}</span> : null}
                                {' · '}<b style={{color: '#8a5cff'}}>▮</b> PSR band
                                {' · '}length {p.samples && p.samples.length ? p.samples[p.samples.length - 1].dist_m : 0} m</div>
                            <div style={SECTION}>sources</div>
                            {Object.keys(p.sources || {}).map((k) => (
                                <div key={k} style={{color: '#6f7684'}}><b style={{color: '#8a93a3'}}>{k}</b>: {p.sources[k]}</div>
                            ))}
                            {p.unavailable && p.unavailable.ice_stability ? (
                                <div data-stewie-ice-gap style={{color: '#7a8290', marginTop: '5px', fontStyle: 'italic',
                                    borderLeft: '2px solid #3a3a44', paddingLeft: '6px'}}>
                                    ice-stability: no real dataset wired — PSR (cold-trap) is the ice-relevant proxy;
                                    quantitative depth-to-ice needs a Diviner/LOLA thermal dataset. (Not a fabricated curve.)
                                </div>
                            ) : null}
                        </div>
                    </div>
                ) : (!s.loading ? (
                    <div data-stewie-empty style={{fontSize: '11px', color: '#7a8290', padding: '10px 4px'}}>
                        No transect yet — click a start + end point on the map.
                    </div>
                ) : null)}
            </div>
        );
    };
    render() {
        return (
            <SideBar icon="plot_info" id="MissionCrossSection" side={this.props.side} title="Cross-section" width="24em">
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

export default connect((state) => ({
    active: state.task.id === 'MissionCrossSection',
    mapCrs: (state.map && state.map.projection) || 'IAU_2015:30135'
}), {
    setCurrentTask: setCurrentTask
})(MissionCrossSection);
