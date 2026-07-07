/**
 * MissionPlan — the STEWIE MISSION-AUTHORING side panel for the lunar IDE (artemis.stewie.space/ide/).
 *
 * Design T9 (design/STEWIE_LUNAR_PLATFORM_DESIGN_2026-07-06.md §D): the operator selects a work site,
 * picks a Cut/Fill tool, clicks the map to place orders, hits Plan, and the REAL routed plan (routes +
 * haul lines + feasibility/makespan/energy) from the backend planner renders on the map.
 *
 * REBIND, not rewrite: it wires the framework-agnostic OpenLayers author->plan controller
 * (js/mission/planAuthor.js -- a port of Frontend A's gis/web/app.js:352-673) to a dark-IDE SideBar,
 * exactly as MissionHUD.jsx wires rover_hud.js and MissionLayers.jsx wires catalogLayers.js. The
 * controller grabs the SAME OpenLayers map (MapUtils.GET_MAP hook) the base .qgz theme draws on, adds its
 * own order/plan vector layers, and POSTs the queue to the key-injected /api/plan. See planAuthor.js for
 * why this needs no auth-gated DEM endpoint.
 *
 * Registration:
 *   - js/appConfig.js     -> pluginsDef.plugins.MissionPlanPlugin
 *   - static/config.json  -> plugins.common [{"name": "MissionPlan"}] + a TopBar menu item
 *                            {"key": "MissionPlan", "title": "Mission Plan", "icon": "draw"}
 * The "Mission Plan" app-menu entry dispatches setCurrentTask("MissionPlan"); the SideBar (id="MissionPlan")
 * shows while state.task.id === "MissionPlan".
 */
import React from 'react';

import {connect} from 'react-redux';

import SideBar from 'qwc2/components/SideBar';
import CoordinatesUtils from 'qwc2/utils/CoordinatesUtils';
import MapUtils from 'qwc2/utils/MapUtils';

import PlanAuthor from '../mission/planAuthor';

// The three imported work-site DEMs the planner backs (matches Frontend A's site dropdown). Haworth is the
// theme's authoritative work site (the T6 default the globe drape + layer catalog also use).
const SITES = [
    {value: 'haworth', label: 'Haworth crater'},
    {value: 'nobile_rim', label: 'Nobile Rim 1'},
    {value: 'shackleton_rim', label: 'Shackleton Rim'}
];

function fmtDur(s) {
    s = Math.round(s || 0);
    if (s < 3600) { return Math.floor(s / 60) + 'm ' + (s % 60) + 's'; }
    const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    if (h < 48) { return h + 'h ' + m + 'm'; }
    return (s / 86400).toFixed(1) + ' days';
}
function fmtEnergy(j) {
    j = j || 0;
    const kwh = j / 3.6e6;
    if (kwh < 1) { return (j / 1e3).toFixed(0) + ' kJ'; }
    if (kwh < 1000) { return kwh.toFixed(1) + ' kWh'; }
    return (kwh / 1000).toFixed(2) + ' MWh';
}
function fmtMass(kg) { kg = kg || 0; return kg >= 1000 ? (kg / 1000).toFixed(1) + ' t' : kg.toFixed(0) + ' kg'; }

class MissionPlan extends React.Component {
    state = {
        ready: false,
        ctrl: null   // the controller's emitted UI state {site, activeKind, footprint, depth, orders, hint, hintErr, result, planning}
    };
    constructor(props) {
        super(props);
        this.ctrl = null;      // the PlanAuthor instance
        this._raf = 0;
        this._framed = false;  // first-show zoom guard
    }
    componentDidMount() {
        this._resolveMap();
    }
    componentWillUnmount() {
        if (this._raf) { cancelAnimationFrame(this._raf); this._raf = 0; }
        if (this.ctrl) { this.ctrl.detach(); this.ctrl = null; }
    }
    _resolveMap = () => {
        const map = MapUtils.getHook(MapUtils.GET_MAP);
        if (!map) { this._raf = requestAnimationFrame(this._resolveMap); return; }   // map not mounted yet
        this.ctrl = new PlanAuthor({
            map: map,
            reproject: CoordinatesUtils.reproject,
            onState: (s) => this.setState({ctrl: s})
        });
        this.ctrl.attach();
        this.setState({ready: true, ctrl: {
            site: 'haworth', activeKind: null, footprint: 60, depth: 0.4, orders: [],
            koTool: null, keepouts: [],
            hint: 'Pick a work site, then a tool, then click the map to place orders.', hintErr: false,
            result: null, planning: false,
            run: {active: false, id: null, legsSeen: 0, total: 0, terminal: null, lastEvent: '',
                result: null, evidence: null},
            canRun: false
        }});
    };
    onShow = () => {
        // Frame the work area on the first open (a deliberate action), like Frontend A's fly-on-tool. The
        // base-map landing view is untouched until the operator opens Mission Plan.
        if (this.ctrl && !this._framed) {
            this._framed = true;
            this.ctrl.selectSite(this.ctrl.site, {fly: true});
        }
    };

    onSite = (e) => { if (this.ctrl) { this.ctrl.selectSite(e.target.value, {fly: true}); } };
    onTool = (kind) => { if (this.ctrl) { this.ctrl.setTool(kind); } };
    onFootprint = (e) => { if (this.ctrl) { this.ctrl.setFootprint(e.target.value); } };
    onDepth = (e) => { if (this.ctrl) { this.ctrl.setDepth(e.target.value); } };
    onPlan = () => { if (this.ctrl) { this.ctrl.plan(); } };
    onClear = () => { if (this.ctrl) { this.ctrl.clearOrders(); } };
    onRemove = (i) => { if (this.ctrl) { this.ctrl.removeOrder(i); } };
    onRun = () => { if (this.ctrl) { this.ctrl.runMission(); } };
    onKeepoutTool = (kind) => { if (this.ctrl) { this.ctrl.setKeepoutTool(kind); } };
    onRemoveKeepout = (i) => { if (this.ctrl) { this.ctrl.removeKeepout(i); } };
    onClearKeepouts = () => { if (this.ctrl) { this.ctrl.clearKeepouts(); } };

    renderTools(s) {
        const btn = (kind, label, color) => {
            const on = s.activeKind === kind;
            return (
                <button
                    data-stewie-tool={kind}
                    onClick={() => this.onTool(kind)}
                    style={{
                        flex: '1 1 0', cursor: 'pointer', font: '600 11px system-ui, sans-serif',
                        padding: '7px 4px', borderRadius: '4px',
                        border: '1px solid ' + (on ? color : '#2a2a36'),
                        color: on ? '#0a0a0c' : color, background: on ? color : color + '18'
                    }}
                    type="button"
                >{label}</button>
            );
        };
        return (
            <div style={{display: 'flex', gap: '6px', margin: '8px 0'}}>
                {btn('cut', 'Cut (dig)', '#e0563a')}
                {btn('fill', 'Fill (build)', '#4fd1ff')}
            </div>
        );
    }

    renderQueue(s) {
        if (!s.orders.length) {
            return <div style={{fontSize: '10px', color: '#7a8290', padding: '4px 0'}}>No orders yet — pick a tool and click the map.</div>;
        }
        return (
            <ul style={{listStyle: 'none', margin: '4px 0', padding: 0, maxHeight: '150px', overflowY: 'auto'}}>
                {s.orders.map((o) => (
                    <li key={o.idx} style={{display: 'flex', alignItems: 'center', gap: '6px', padding: '2px 0', fontSize: '11px'}}>
                        <span style={{
                            width: '9px', height: '9px', flex: '0 0 auto', borderRadius: o.kind === 'cut' ? '1px' : '50%',
                            background: o.kind === 'cut' ? '#e0563a' : '#4fd1ff'
                        }} />
                        <span style={{flex: '1 1 auto', color: '#c7d2e3'}}>
                            {o.kind} · {o.footprint_m2} m² · {o.depth_m} m
                        </span>
                        <span
                            onClick={() => this.onRemove(o.idx)}
                            style={{flex: '0 0 auto', cursor: 'pointer', color: '#e0564b', fontWeight: 700, padding: '0 4px'}}
                            title="remove order"
                        >×</span>
                    </li>
                ))}
            </ul>
        );
    }

    // --- No-go / keep-out authoring: draw avoid-regions the planner routes around (payload.keepouts) ------
    renderKeepouts(s) {
        const lbl = {fontSize: '9px', letterSpacing: '.06em', color: '#7a8290', textTransform: 'uppercase'};
        const kos = s.keepouts || [];
        const kbtn = (kind, label) => {
            const on = s.koTool === kind;
            const color = '#e0563a';
            return (
                <button
                    data-stewie-ko={kind}
                    onClick={() => this.onKeepoutTool(kind)}
                    style={{
                        flex: '1 1 0', cursor: 'pointer', font: '600 11px system-ui, sans-serif',
                        padding: '7px 4px', borderRadius: '4px',
                        border: '1px dashed ' + (on ? color : '#4a2a2a'),
                        color: on ? '#0a0a0c' : color, background: on ? color : color + '14'
                    }}
                    type="button"
                >{label}</button>
            );
        };
        return (
            <div style={{marginTop: '10px', borderTop: '1px solid #1c1c26', paddingTop: '8px'}}>
                <div style={{...lbl, marginBottom: '2px'}}>No-go regions ({kos.length})</div>
                <div style={{fontSize: '9px', color: '#7a8290', margin: '0 0 4px', lineHeight: 1.35}}>
                    Draw avoid-regions over the red-cost / blocking layers; the planner routes the mission around them.
                </div>
                <div style={{display: 'flex', gap: '6px', margin: '4px 0'}}>
                    {kbtn('polygon', '⬡ No-go polygon')}
                    {kbtn('circle', '◯ No-go circle')}
                </div>
                {kos.length ? (
                    <ul style={{listStyle: 'none', margin: '4px 0', padding: 0, maxHeight: '110px', overflowY: 'auto'}}>
                        {kos.map((k) => (
                            <li key={k.idx} style={{display: 'flex', alignItems: 'center', gap: '6px', padding: '2px 0', fontSize: '11px'}}>
                                <span style={{
                                    width: '10px', height: '10px', flex: '0 0 auto', borderRadius: '2px',
                                    border: '1px solid #e0403a',
                                    background: 'repeating-linear-gradient(45deg,#e0403a55 0 2px,transparent 2px 4px)'
                                }} />
                                <span style={{flex: '1 1 auto', color: '#e6b8b3'}}>{k.label}</span>
                                <span
                                    onClick={() => this.onRemoveKeepout(k.idx)}
                                    style={{flex: '0 0 auto', cursor: 'pointer', color: '#e0564b', fontWeight: 700, padding: '0 4px'}}
                                    title="remove no-go region"
                                >×</span>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <div style={{fontSize: '10px', color: '#7a8290', padding: '2px 0'}}>None — pick a no-go tool and draw on the map.</div>
                )}
                {kos.length ? (
                    <button
                        data-stewie-ko-clear="1" onClick={this.onClearKeepouts}
                        style={{
                            marginTop: '4px', cursor: 'pointer', font: '600 10px system-ui, sans-serif',
                            padding: '5px 8px', borderRadius: '4px', border: '1px solid #4a2a2a',
                            color: '#e0563a', background: '#e0563a10'
                        }}
                        type="button"
                    >Clear no-go</button>
                ) : null}
            </div>
        );
    }

    renderResult(s) {
        const r = s.result;
        if (!r) { return null; }
        if (r.error && r.feasible === false && r.n_orders == null) {
            return (
                <div style={{marginTop: '10px', borderTop: '1px solid #1c1c26', paddingTop: '8px'}}>
                    <div style={{fontSize: '11px', fontWeight: 700, color: '#e0564b'}}>Plan rejected</div>
                    <div style={{fontSize: '10px', color: '#e0b3b0', marginTop: '4px'}}>{r.error}</div>
                </div>
            );
        }
        const kv = (k, v) => (
            <div key={k} style={{display: 'flex', justifyContent: 'space-between', fontSize: '11px', padding: '2px 0'}}>
                <span style={{color: '#8a93a3'}}>{k}</span><b style={{color: '#c7d2e3'}}>{v}</b>
            </div>
        );
        return (
            <div style={{marginTop: '10px', borderTop: '1px solid #1c1c26', paddingTop: '8px'}}>
                <div style={{fontSize: '12px', fontWeight: 700, color: r.feasible ? '#39ff14' : '#e0564b', marginBottom: '4px'}}>
                    {r.feasible ? '✓ Feasible plan' : '✗ Infeasible plan'}
                </div>
                {kv('Orders', r.n_orders)}
                {kv('Vehicles', r.vehicles)}
                {kv('Makespan', fmtDur(r.makespan_s))}
                {kv('Energy', fmtEnergy(r.energy_j))}
                {kv('Mass moved', fmtMass(r.mass_moved_kg))}
                {kv('Distance', ((r.distance_m || 0) / 1000).toFixed(2) + ' km')}
                {kv('Recharges', r.recharges)}
                {kv('Drum cycles', r.drum_cycles)}
                {kv('Algorithm', r.algorithm)}
                {kv('Terrain', r.terrain_source || '—')}
                {(r.infeasible_reasons || []).length ? (
                    <div style={{fontSize: '10px', color: '#e0b300', marginTop: '4px'}}>
                        {r.infeasible_reasons.join(' · ')}
                    </div>
                ) : null}
                {r.pdf ? (
                    <a
                        href={r.pdf}
                        rel="noopener"
                        style={{display: 'inline-block', marginTop: '6px', fontSize: '11px', color: '#39c6ff'}}
                        target="_blank"
                    >↓ Mission report (PDF)</a>
                ) : null}
            </div>
        );
    }

    // --- Run-SIM (T10): the button + live run status/summary/evidence, once a feasible plan is rendered ----
    runKv(k, v) {
        return (
            <div style={{display: 'flex', justifyContent: 'space-between', fontSize: '11px', padding: '2px 0'}}>
                <span style={{color: '#8a93a3'}}>{k}</span><b style={{color: '#c7d2e3'}}>{v}</b>
            </div>
        );
    }

    renderEvidence(ev) {
        if (!ev) { return null; }
        const link = (href, label) => (
            <a
                href={href} rel="noopener"
                style={{display: 'block', fontSize: '11px', color: '#39c6ff', marginTop: '3px'}}
                target="_blank"
            >{label}</a>
        );
        return (
            <div style={{marginTop: '6px', borderTop: '1px solid #1c1c26', paddingTop: '6px'}}>
                <div style={{
                    fontSize: '9px', letterSpacing: '.06em', color: '#7a8290',
                    textTransform: 'uppercase', marginBottom: '2px'
                }}>Evidence bundle</div>
                {ev.blurbKey ? this.runKv(ev.blurbKey, ev.blurbVal) : null}
                {ev.navUrl ? link(ev.navUrl, '↓ Nav evidence (JSON)') : null}
                {ev.pdfUrl ? link(ev.pdfUrl, '↓ Mission report (PDF)') : null}
            </div>
        );
    }

    renderRunStatus(run) {
        if (!run || (!run.active && !run.id && !run.terminal)) { return null; }
        const t = run.terminal, running = run.active && !t;
        const label = running ? 'Executing (SIM)…'
            : (t === 'completed' ? 'SIM run COMPLETED'
                : t === 'safed' ? 'SIM run SAFED (watchdog)'
                    : t === 'error' ? 'Run error' : 'Done');
        const headColor = running ? '#39c6ff' : (t === 'completed' ? '#39ff14' : '#e0564b');
        const frac = run.total ? Math.min(1, run.legsSeen / run.total) : (t ? 1 : 0);
        const rr = run.result || {};
        return (
            <div style={{marginTop: '8px'}}>
                <div style={{fontSize: '12px', fontWeight: 700, color: headColor, marginBottom: '4px'}}>{label}</div>
                <div style={{height: '5px', background: '#12141a', borderRadius: '3px', overflow: 'hidden', margin: '4px 0'}}>
                    <div style={{
                        height: '100%', width: Math.round(frac * 100) + '%',
                        background: running ? '#39c6ff' : '#39ff14', transition: 'width .3s'
                    }} />
                </div>
                {run.id ? this.runKv('Run id', run.id) : null}
                {this.runKv('Legs', run.legsSeen + ' / ' + (run.total || '—'))}
                {rr.final_state ? this.runKv('Final state', rr.final_state) : null}
                {rr.executability ? this.runKv('Executable', rr.executability.executable ? 'yes' : 'no') : null}
                {rr.physics_attribution ? this.runKv('Physics', rr.physics_attribution.backend +
                    (rr.physics_attribution.conserves_mass ? ' · mass-conserving' : '')) : null}
                {rr.live_token ? this.runKv('Live token', rr.live_token.issued ? 'issued' : 'refused') : null}
                {rr.reconciliation ? this.runKv('Energy residual',
                    Math.abs(rr.reconciliation.residual || 0).toFixed(0) + ' J') : null}
                {run.lastEvent ? (
                    <div style={{fontSize: '10px', color: '#8a93a3', marginTop: '4px'}}>{run.lastEvent}</div>
                ) : null}
                {this.renderEvidence(run.evidence)}
            </div>
        );
    }

    renderRun(s) {
        // Only a rendered, FEASIBLE plan can be run (the button appears with the feasible-plan card).
        if (!s.result || !s.result.feasible) { return null; }
        const run = s.run || {};
        const running = run.active;
        const canRun = s.canRun && !running;
        return (
            <div style={{marginTop: '10px', borderTop: '1px solid #1c1c26', paddingTop: '8px'}}>
                <button
                    data-stewie-run="1" disabled={!canRun} onClick={this.onRun}
                    style={{
                        width: '100%', cursor: canRun ? 'pointer' : 'default',
                        font: '700 11px system-ui, sans-serif', padding: '8px', borderRadius: '4px',
                        border: '1px solid #39c6ff66',
                        color: canRun ? '#39c6ff' : '#3a5a6a',
                        background: canRun ? '#39c6ff18' : '#0d141a'
                    }}
                    type="button"
                >{running ? 'Running SIM…' : 'Run mission (SIM)'}</button>
                <div style={{fontSize: '9px', color: '#7a8290', margin: '4px 0 0', lineHeight: 1.35}}>
                    Non-destructive desktop-SIL run on the real DEM. The rover drives the planned route as
                    live leg telemetry arrives; a validation summary + evidence bundle follow.
                </div>
                {this.renderRunStatus(run)}
            </div>
        );
    }

    renderBody = () => {
        const s = this.state.ctrl;
        const wrapStyle = {
            background: '#0a0a0c', color: '#c7d2e3', padding: '10px',
            font: '11px system-ui, sans-serif', '--txt': '#c7d2e3', '--line': '#2a2a36'
        };
        if (!this.state.ready || !s) {
            return <div style={wrapStyle}><div style={{color: '#7a8290'}}>Connecting to the map…</div></div>;
        }
        const inputStyle = {
            width: '100%', boxSizing: 'border-box', background: '#0c1017', color: '#c7d2e3',
            border: '1px solid #2a2a36', borderRadius: '4px', padding: '5px 6px', font: '11px system-ui, sans-serif'
        };
        const lbl = {fontSize: '9px', letterSpacing: '.06em', color: '#7a8290', textTransform: 'uppercase'};
        return (
            <div style={wrapStyle}>
                <div style={{fontSize: '10px', color: '#8a93a3', marginBottom: '8px', lineHeight: 1.4}}>
                    Place cut/fill orders on the map, then <b>Plan</b> to route them on the real DEM via the
                    STEWIE planner (<b>/api/plan</b>). Route = gold, haul = blue-dashed, charger = green.
                </div>

                <label style={lbl} htmlFor="mp-site">Work site (planner DEM)</label>
                <select
                    data-stewie-site="1" id="mp-site" onChange={this.onSite}
                    style={{...inputStyle, marginBottom: '8px'}} value={s.site}
                >
                    {SITES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>

                <div style={{display: 'flex', gap: '8px', marginBottom: '4px'}}>
                    <div style={{flex: '1 1 0'}}>
                        <label style={lbl} htmlFor="mp-fp">Footprint m²</label>
                        <input
                            defaultValue={s.footprint} id="mp-fp" min="1" onChange={this.onFootprint}
                            step="10" style={inputStyle} type="number"
                        />
                    </div>
                    <div style={{flex: '1 1 0'}}>
                        <label style={lbl} htmlFor="mp-depth">Depth m</label>
                        <input
                            defaultValue={s.depth} id="mp-depth" min="0.05" onChange={this.onDepth}
                            step="0.05" style={inputStyle} type="number"
                        />
                    </div>
                </div>

                {this.renderTools(s)}

                <div style={{
                    fontSize: '10px', margin: '2px 0 8px', minHeight: '26px', lineHeight: 1.35,
                    color: s.hintErr ? '#e0564b' : '#8a93a3'
                }}>{s.hint}</div>

                <div style={{...lbl, marginBottom: '2px'}}>Order queue ({s.orders.length})</div>
                {this.renderQueue(s)}

                {this.renderKeepouts(s)}

                <div style={{display: 'flex', gap: '6px', marginTop: '8px'}}>
                    <button
                        data-stewie-plan="1" disabled={!s.orders.length || s.planning} onClick={this.onPlan}
                        style={{
                            flex: '2 1 0', cursor: (!s.orders.length || s.planning) ? 'default' : 'pointer',
                            font: '700 11px system-ui, sans-serif', padding: '8px', borderRadius: '4px',
                            border: '1px solid #39ff1466',
                            color: (!s.orders.length || s.planning) ? '#4a5a4a' : '#39ff14',
                            background: (!s.orders.length || s.planning) ? '#12160f' : '#39ff1418'
                        }}
                        type="button"
                    >{s.planning ? 'Planning…' : 'Plan mission'}</button>
                    <button
                        onClick={this.onClear}
                        style={{
                            flex: '1 1 0', cursor: 'pointer', font: '600 11px system-ui, sans-serif',
                            padding: '8px', borderRadius: '4px', border: '1px solid #2a2a36',
                            color: '#c7d2e3', background: '#12141a'
                        }}
                        type="button"
                    >Clear</button>
                </div>

                {this.renderResult(s)}
                {this.renderRun(s)}
            </div>
        );
    };

    render() {
        return (
            <SideBar
                icon="draw"
                id="MissionPlan"
                onShow={this.onShow}
                side="right"
                title="Mission Plan"
                width="24em"
            >
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

export default connect(() => ({}), {})(MissionPlan);
