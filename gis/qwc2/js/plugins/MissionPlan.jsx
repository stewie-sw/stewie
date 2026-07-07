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

// DEPTH-2 plan controls — the REAL planner levers /api/plan accepts. These option VALUES are the exact
// backend strings (no synthetic choices); the backend validates them (a bad name is a 400).
//   ALGORITHMS = SEQUENCERS (lode/planner_optimize.py:48): auto/nearest/greedy/two_opt/or_opt/lk/brute/held_karp.
const ALGORITHMS = [
    {value: 'auto', label: 'Auto (strongest for size)'},
    {value: 'nearest', label: 'Nearest-neighbour'},
    {value: 'greedy', label: 'Greedy (objective-scored)'},
    {value: 'two_opt', label: '2-opt local search'},
    {value: 'or_opt', label: 'Or-opt local search'},
    {value: 'lk', label: 'Lin-Kernighan-style'},
    {value: 'brute', label: 'Brute force (exact, ≤7)'},
    {value: 'held_karp', label: 'Held-Karp (exact dist, ≤16)'}
];
//   OBJECTIVES = OBJECTIVES table (lode/planner_optimize.py:27-40). duration (==time) and power
//   (==average_power) aliases are omitted so the menu has no duplicate-meaning entries.
const OBJECTIVES = [
    {value: 'time', label: 'Time / makespan'},
    {value: 'energy', label: 'Energy'},
    {value: 'average_power', label: 'Average power'},
    {value: 'distance', label: 'Drive distance'},
    {value: 'charges', label: 'Recharge stops'},
    {value: 'mass', label: 'Mass moved'}
];
//   BUDGETS = Mission.objective_constraints keys (_CONSTRAINT_CAPS | {risk_weight},
//   lode/planner_constants.py:30 / planner_model.py:426). Each is an OPTIONAL hard cap (blank = not applied);
//   overshooting a cap penalizes the ordering below any feasible one (planner_optimize.py:131 _constraint_penalty).
const BUDGETS = [
    {key: 'max_time_s', label: 'Max time', unit: 's', step: '600'},
    {key: 'max_energy_J', label: 'Max energy', unit: 'J', step: '100000'},
    {key: 'max_distance_m', label: 'Max distance', unit: 'm', step: '100'},
    {key: 'max_charges', label: 'Max recharges', unit: '#', step: '1'},
    {key: 'risk_weight', label: 'Risk weight', unit: '×', step: '0.1'}
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
        ctrl: null,  // the controller's emitted UI state {site, activeKind, footprint, depth, orders, hint, hintErr, result, planning}
        detailOpen: false,  // DEPTH-4: the "Plan detail" expander (Plan IR / validation / timeline+endurance)
        scheduleOpen: true  // DEPTH-5: the "Schedule / Gantt" expander (open by default — the headline of a plan)
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
            algorithm: 'nearest', objective: 'time', maxSlopeDeg: 25,
            budgets: {max_time_s: '', max_energy_J: '', max_charges: '', max_distance_m: '', risk_weight: ''},
            vehicles: 1, chargerCapacity: 1,
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
    // PLAN ANYWHERE: adopt an arbitrary off-site lat/lon as the work area (backend crops the global LDEM there).
    _ahLat = -86.0;   // the off-site lat/lon entry (defaults match the inputs; onChange keeps them live)
    _ahLon = -30.0;
    onPlanHere = () => { if (this.ctrl) { this.ctrl.planHere(parseFloat(this._ahLat), parseFloat(this._ahLon)); } };
    onAhLat = (e) => { this._ahLat = e.target.value; };
    onAhLon = (e) => { this._ahLon = e.target.value; };
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
    // DEPTH-2 plan controls
    onAlgorithm = (e) => { if (this.ctrl) { this.ctrl.setAlgorithm(e.target.value); } };
    onObjective = (e) => { if (this.ctrl) { this.ctrl.setObjective(e.target.value); } };
    onMaxSlope = (e) => { if (this.ctrl) { this.ctrl.setMaxSlope(e.target.value); } };
    onBudget = (key, e) => { if (this.ctrl) { this.ctrl.setBudget(key, e.target.value); } };
    onClearBudgets = () => { if (this.ctrl) { this.ctrl.clearBudgets(); } };
    // DEPTH-3 fleet controls
    onVehicles = (e) => { if (this.ctrl) { this.ctrl.setVehicles(e.target.value); } };
    onChargerCapacity = (e) => { if (this.ctrl) { this.ctrl.setChargerCapacity(e.target.value); } };
    // DEPTH-4 plan-detail expander
    onToggleDetail = () => { this.setState((st) => ({detailOpen: !st.detailOpen})); };
    // DEPTH-5 schedule / Gantt expander
    onToggleSchedule = () => { this.setState((st) => ({scheduleOpen: !st.scheduleOpen})); };

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

    // --- Plan controls (DEPTH-2): the planner levers folded into the SAME /api/plan POST -----------------
    // Algorithm + objective are controlled selects (the exact SEQUENCERS / OBJECTIVES strings); the slope
    // budget is a 5..45 deg range (max_traverse_slope_deg); the resource budgets are optional hard caps
    // (objective_constraints). All ride the one /api/plan POST — no new backend, no new route.
    renderPlanControls(s) {
        const lbl = {fontSize: '9px', letterSpacing: '.06em', color: '#7a8290', textTransform: 'uppercase'};
        const inputStyle = {
            width: '100%', boxSizing: 'border-box', background: '#0c1017', color: '#c7d2e3',
            border: '1px solid #2a2a36', borderRadius: '4px', padding: '5px 6px', font: '11px system-ui, sans-serif'
        };
        const budgets = s.budgets || {};
        const anyBudget = BUDGETS.some((b) => (budgets[b.key] != null && budgets[b.key] !== ''));
        return (
            <div style={{marginTop: '10px', borderTop: '1px solid #1c1c26', paddingTop: '8px'}}>
                <div style={{...lbl, marginBottom: '4px'}}>Plan controls</div>
                <div style={{display: 'flex', gap: '8px', marginBottom: '6px'}}>
                    <div style={{flex: '1 1 0'}}>
                        <label style={lbl} htmlFor="mp-algo">Algorithm</label>
                        <select
                            data-stewie-algo="1" id="mp-algo" onChange={this.onAlgorithm}
                            style={inputStyle} value={s.algorithm}
                        >
                            {ALGORITHMS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                    </div>
                    <div style={{flex: '1 1 0'}}>
                        <label style={lbl} htmlFor="mp-obj">Objective</label>
                        <select
                            data-stewie-obj="1" id="mp-obj" onChange={this.onObjective}
                            style={inputStyle} value={s.objective}
                        >
                            {OBJECTIVES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                    </div>
                </div>

                <label style={lbl} htmlFor="mp-slope">Slope budget · <b style={{color: '#c7d2e3'}}>{s.maxSlopeDeg}°</b> (traversability gate)</label>
                <input
                    data-stewie-slope="1" id="mp-slope" max="45" min="5" onChange={this.onMaxSlope}
                    step="1" style={{width: '100%', accentColor: '#39c6ff'}} type="range" value={s.maxSlopeDeg}
                />

                <div style={{...lbl, margin: '8px 0 2px'}}>Resource budgets (optional caps)</div>
                <div style={{fontSize: '9px', color: '#7a8290', margin: '0 0 4px', lineHeight: 1.35}}>
                    Soft caps the sequencer optimizes toward — an overshooting order is penalized so the
                    least-overshoot sequence wins (honored by greedy / 2-opt / or-opt / brute; nearest &amp;
                    held-karp are order-fixed and ignore them). risk weight adds a recharge-exposure cost. Blank = not applied.
                </div>
                {BUDGETS.map((b) => (
                    <div key={b.key} style={{display: 'flex', alignItems: 'center', gap: '6px', margin: '3px 0'}}>
                        <span style={{flex: '0 0 90px', fontSize: '10px', color: '#8a93a3'}}>{b.label}</span>
                        <input
                            data-stewie-budget={b.key} min="0" onChange={(e) => this.onBudget(b.key, e)}
                            placeholder="—" step={b.step} style={{...inputStyle, flex: '1 1 auto'}}
                            type="number" value={budgets[b.key] != null ? budgets[b.key] : ''}
                        />
                        <span style={{flex: '0 0 14px', fontSize: '9px', color: '#7a8290'}}>{b.unit}</span>
                    </div>
                ))}
                {anyBudget ? (
                    <button
                        data-stewie-budget-clear="1" onClick={this.onClearBudgets}
                        style={{
                            marginTop: '4px', cursor: 'pointer', font: '600 10px system-ui, sans-serif',
                            padding: '5px 8px', borderRadius: '4px', border: '1px solid #2a2a36',
                            color: '#c7d2e3', background: '#12141a'
                        }}
                        type="button"
                    >Clear budgets</button>
                ) : null}
            </div>
        );
    }

    // --- Fleet controls (DEPTH-3): vehicles + charger capacity, folded into the SAME /api/plan POST --------
    // `vehicles` is the typed PlanRequest field (plan.py:72, 1..16); `charger_capacity` rides the mission
    // dict (plan.py:75 -> mission_from_dict, 1..8). vehicles>1 makes the backend run plan_multi
    // (site-exclusive allocation, per-vehicle parallel sim, makespan=max, fleet-summed energy). No new route.
    renderFleet(s) {
        const lbl = {fontSize: '9px', letterSpacing: '.06em', color: '#7a8290', textTransform: 'uppercase'};
        const inputStyle = {
            width: '100%', boxSizing: 'border-box', background: '#0c1017', color: '#c7d2e3',
            border: '1px solid #2a2a36', borderRadius: '4px', padding: '5px 6px', font: '11px system-ui, sans-serif'
        };
        const fleet = (s.vehicles || 1) > 1;
        return (
            <div style={{marginTop: '10px', borderTop: '1px solid #1c1c26', paddingTop: '8px'}}>
                <div style={{...lbl, marginBottom: '4px'}}>Fleet</div>
                <div style={{display: 'flex', gap: '8px'}}>
                    <div style={{flex: '1 1 0'}}>
                        <label style={lbl} htmlFor="mp-vehicles">Rovers</label>
                        <input
                            data-stewie-vehicles="1" id="mp-vehicles" max="16" min="1" onChange={this.onVehicles}
                            step="1" style={inputStyle} type="number" value={s.vehicles != null ? s.vehicles : 1}
                        />
                    </div>
                    <div style={{flex: '1 1 0'}}>
                        <label style={lbl} htmlFor="mp-chargers">Chargers</label>
                        <input
                            data-stewie-chargers="1" id="mp-chargers" max="8" min="1" onChange={this.onChargerCapacity}
                            step="1" style={inputStyle} value={s.chargerCapacity != null ? s.chargerCapacity : 1}
                            type="number"
                        />
                    </div>
                </div>
                <div style={{fontSize: '9px', color: '#7a8290', margin: '4px 0 0', lineHeight: 1.35}}>
                    {fleet
                        ? 'Orders are allocated site-exclusively across the fleet; each rover routes + battery-sims in ' +
                          'parallel from the shared charger (makespan = the slowest rover). Chargers = how many may ' +
                          'charge at once (the rest queue FCFS). Each rover\'s route draws in its own colour.'
                        : 'One rover (single-vehicle plan). Raise Rovers > 1 to allocate the orders across a fleet.'}
                </div>
            </div>
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

    // DEPTH-3 fleet summary: the per-vehicle allocation the backend plan_multi returns (totals.vehicles_detail
    // -> planAuthor result.vehicles_detail). Each row's swatch colour is the SAME vehicleColor() the map route
    // uses, so the operator can read which coloured route belongs to which rover. Rendered only for a fleet.
    renderFleetSummary(r) {
        const vd = (r && r.vehicles_detail) || [];
        if (!(r && r.vehicles > 1 && vd.length)) { return null; }
        const lbl = {fontSize: '9px', letterSpacing: '.06em', color: '#7a8290', textTransform: 'uppercase'};
        return (
            <div style={{marginTop: '8px', borderTop: '1px solid #1c1c26', paddingTop: '6px'}}>
                <div style={{...lbl, marginBottom: '4px'}}>Fleet allocation · {r.vehicles} rovers</div>
                <div style={{fontSize: '9px', color: '#7a8290', margin: '0 0 4px', lineHeight: 1.35}}>
                    Makespan = the slowest rover ({fmtDur(r.makespan_s)}); energy = fleet-summed ({fmtEnergy(r.energy_j)}).
                </div>
                <ul style={{listStyle: 'none', margin: '2px 0', padding: 0}}>
                    {vd.map((d) => (
                        <li key={d.vehicle} style={{display: 'flex', alignItems: 'center', gap: '6px', padding: '2px 0', fontSize: '11px'}}>
                            <span style={{width: '11px', height: '4px', flex: '0 0 auto', borderRadius: '2px', background: d.color}} />
                            <span style={{flex: '0 0 58px', color: '#c7d2e3', fontWeight: 600}}>Rover {d.vehicle + 1}</span>
                            <span style={{flex: '1 1 auto', color: '#8a93a3'}}>
                                {d.n_trips} order{d.n_trips === 1 ? '' : 's'} · {fmtDur(d.time_s)} · {fmtEnergy(d.energy_J)}
                            </span>
                        </li>
                    ))}
                </ul>
                {(r.charger_conflicts != null || r.charger_wait_s != null) ? (
                    <div style={{fontSize: '10px', color: '#8a93a3', marginTop: '2px'}}>
                        Chargers: {r.charger_capacity != null ? r.charger_capacity : 1} ·
                        {' '}{r.charger_conflicts || 0} queue overlap{(r.charger_conflicts || 0) === 1 ? '' : 's'}
                        {r.charger_wait_s ? ' · +' + fmtDur(r.charger_wait_s) + ' queue wait' : ''}
                    </div>
                ) : null}
            </div>
        );
    }

    // --- Plan detail (DEPTH-4): read-only views of what /api/plan ALREADY returns but the panel ignored -----
    // A collapsible "Plan detail" section surfacing the executable Plan IR (resp.plan_ir), the as-built
    // validation block (resp.validation + resp.ordered_acceptance), and the timeline/endurance
    // (resp.timeline + resp.endurance). Pure rebind — planAuthor._planDetail projects these straight from the
    // real /plan response; nothing here recomputes or fabricates. Dark-theme, compact.
    static fmtJ(j) {
        if (j == null) { return '—'; }
        return j >= 1e6 ? (j / 1e6).toFixed(1) + ' MJ' : (j / 1e3).toFixed(0) + ' kJ';
    }
    static fmtSs(s) {
        if (s == null) { return '—'; }
        if (s < 3600) { return Math.round(s) + ' s'; }
        if (s < 172800) { return (s / 3600).toFixed(1) + ' h'; }
        return (s / 86400).toFixed(1) + ' d';
    }
    detailRow(k, v, color) {
        return (
            <div key={k} style={{display: 'flex', justifyContent: 'space-between', fontSize: '10px', padding: '1px 0'}}>
                <span style={{color: '#8a93a3'}}>{k}</span><b style={{color: color || '#c7d2e3'}}>{v}</b>
            </div>
        );
    }

    // PLAN IR: the ordered typed-action step list (GoTo/Excavate/CutHaulFill/Import/Sinter), each with its
    // expected metrics; the plan_id; the precedence DAG; and the headline expectations. Suppressed → the note.
    renderIR(ir) {
        if (!ir) { return null; }
        const lbl = {fontSize: '9px', letterSpacing: '.06em', color: '#7a8290', textTransform: 'uppercase'};
        const OP_COLOR = {GoTo: '#8fb8ff', Excavate: '#e0563a', CutHaulFill: '#ffd24a', Import: '#7cff5e', Sinter: '#b47cff'};
        const multi = (ir.vehicles || 1) > 1;
        const steps = ir.steps || [];
        return (
            <div style={{marginBottom: '8px'}}>
                <div style={{...lbl, marginBottom: '3px'}}>Plan IR · {steps.length} action{steps.length === 1 ? '' : 's'}</div>
                {ir.executable === false ? (
                    <div style={{fontSize: '10px', color: '#e0b300', lineHeight: 1.35, margin: '2px 0'}}>
                        {ir.note || 'Executable IR suppressed (infeasible plan).'}
                        {(ir.infeasible_reasons || []).length ? (
                            <div style={{color: '#e0b3b0', marginTop: '2px'}}>{ir.infeasible_reasons.join(' · ')}</div>
                        ) : null}
                    </div>
                ) : (
                    <ol data-stewie-ir-steps="1" style={{listStyle: 'none', margin: '2px 0', padding: 0, maxHeight: '176px', overflowY: 'auto'}}>
                        {steps.map((a) => (
                            <li key={a.id} style={{display: 'flex', gap: '6px', alignItems: 'baseline', padding: '2px 0', fontSize: '10px', borderBottom: '1px solid #14141c'}}>
                                <span style={{flex: '0 0 15px', color: '#5a6270', textAlign: 'right'}}>{a.id}</span>
                                <span style={{flex: '0 0 auto', fontWeight: 700, color: OP_COLOR[a.op] || '#c7d2e3'}}>{a.op}</span>
                                {multi ? <span style={{flex: '0 0 auto', color: '#7a8290'}}>R{(a.vehicle || 0) + 1}</span> : null}
                                <span style={{flex: '1 1 auto', color: '#8a93a3', textAlign: 'right'}}>
                                    {a.op === 'GoTo'
                                        ? (a.distance_m != null ? a.distance_m.toFixed(1) + ' m · ' + MissionPlan.fmtSs(a.duration_s) : '—')
                                        : ((a.mass_kg != null ? a.mass_kg.toFixed(0) + ' kg' : '') +
                                           (a.loads ? ' · ' + a.loads + ' loads' : '') + ' · ' + MissionPlan.fmtJ(a.energy_J))}
                                </span>
                            </li>
                        ))}
                    </ol>
                )}
                {ir.expect ? this.detailRow('IR expect',
                    MissionPlan.fmtSs(ir.expect.duration_s) + ' · ' + MissionPlan.fmtJ(ir.expect.energy_J) +
                    ' · ' + (ir.expect.distance_m != null ? (ir.expect.distance_m / 1000).toFixed(2) + ' km' : '—') +
                    ' · ' + (ir.expect.charges || 0) + ' rech') : null}
                {(ir.precedence || []).length ? this.detailRow('Precedence',
                    ir.precedence.map((p) => p[0] + '→' + p[1]).join(', ')) : null}
            </div>
        );
    }

    // VALIDATION: the as-built acceptance block as a pass/fail checklist + the ordered IR-replay verdict.
    renderValidation(v, oa) {
        if (!v && !oa) { return null; }
        const lbl = {fontSize: '9px', letterSpacing: '.06em', color: '#7a8290', textTransform: 'uppercase'};
        const check = (label, ok, note) => (
            <div key={label} style={{display: 'flex', justifyContent: 'space-between', fontSize: '10px', padding: '1px 0'}}>
                <span style={{color: '#8a93a3'}}>{label}{note ? <span style={{color: '#5a6270'}}> · {note}</span> : null}</span>
                <b style={{color: ok ? '#39ff14' : '#e0564b', fontWeight: 700}}>{ok ? '✓ pass' : '✗ fail'}</b>
            </div>
        );
        return (
            <div style={{marginBottom: '8px', borderTop: '1px solid #14141c', paddingTop: '6px'}}>
                <div style={{...lbl, marginBottom: '3px'}}>Validation (as-built acceptance)</div>
                {v ? (
                    <div>
                        {check('Material feasible', v.feasible)}
                        {check('Mass conserved', v.mass_conserved)}
                        {check('As-built flat', v.as_built_pass,
                            (v.as_built_flatness_rmse_m != null ? v.as_built_flatness_rmse_m.toFixed(3) + 'm ≤ ' + v.as_built_tol_m + 'm' : '') +
                            (v.as_built_on_real_dem ? '' : ' (flat mantle)'))}
                        {check('Repose stable', v.repose_pass, '≤' + v.repose_limit_deg + '°')}
                        {check('Berm profile', v.berm_profile_pass)}
                        {check('Bearing', v.bearing_pass)}
                        {v.slope_violations ? this.detailRow('Slope-siting rejects', v.slope_violations, '#e0564b') : null}
                        {v.off_dem_orders ? this.detailRow('Off-DEM rejects', v.off_dem_orders, '#e0564b') : null}
                        {this.detailRow('Cut kg (exec / plan)', Math.round(v.executed_cut_kg) + ' / ' + Math.round(v.planned_cut_kg))}
                        {this.detailRow('Fill kg (exec / plan)', Math.round(v.executed_fill_kg) + ' / ' + Math.round(v.planned_fill_kg))}
                    </div>
                ) : null}
                {oa ? check('Ordered IR-replay',
                    oa.feasible, (oa.shuttle_cycles != null ? oa.shuttle_cycles + ' shuttle cycles' : '') +
                    (oa.placed_kg != null ? ' · ' + Math.round(oa.placed_kg) + ' kg placed' : '')) : null}
            </div>
        );
    }

    // TIMELINE / ENDURANCE: the sim timeline reduced to a per-phase makespan breakdown + battery envelope,
    // and the single-sortie endurance (range flat + slope/slip) with the energy-driver verdict.
    renderTimelineEndurance(tl, en) {
        if (!tl && !en) { return null; }
        const lbl = {fontSize: '9px', letterSpacing: '.06em', color: '#7a8290', textTransform: 'uppercase'};
        const PHASE_COLOR = {drive: '#8fb8ff', charge: '#7fe0a8', work: '#ffd24a', dig: '#e0563a'};
        return (
            <div style={{borderTop: '1px solid #14141c', paddingTop: '6px'}}>
                <div style={{...lbl, marginBottom: '3px'}}>Timeline / endurance</div>
                {tl ? (
                    <div>
                        {this.detailRow('Makespan', MissionPlan.fmtSs(tl.duration_s) + ' · ' + tl.n_frames + ' frames')}
                        {(tl.phases || []).map((p) => (
                            <div key={p.phase} style={{display: 'flex', justifyContent: 'space-between', fontSize: '10px', padding: '1px 0'}}>
                                <span style={{color: '#8a93a3'}}>
                                    <span style={{
                                        display: 'inline-block', width: '8px', height: '8px', borderRadius: '2px',
                                        marginRight: '5px', background: PHASE_COLOR[p.phase] || '#8a93a3'
                                    }} />{p.phase}
                                </span>
                                <b style={{color: '#c7d2e3'}}>{MissionPlan.fmtSs(p.dur_s)}</b>
                            </div>
                        ))}
                        {tl.batt_min_frac != null ? this.detailRow('Battery trace',
                            Math.round(tl.batt_min_frac * 100) + '–' + Math.round(tl.batt_max_frac * 100) + '%') : null}
                    </div>
                ) : null}
                {en ? (
                    <div style={{marginTop: '3px'}}>
                        {this.detailRow('Sortie range',
                            (en.range_flat_reserve_km != null ? en.range_flat_reserve_km.toFixed(0) + ' km flat' : '—') +
                            (en.range_slopeslip_km != null ? ' · ' + en.range_slopeslip_km.toFixed(0) + ' km slope/slip' : ''))}
                        {en.work_area_median_slope_deg != null ? this.detailRow('Work-area slope (median)',
                            en.work_area_median_slope_deg.toFixed(1) + '°') : null}
                        {en.drums_dominate != null ? this.detailRow('Energy driver',
                            en.drums_dominate ? 'drums (dig-dominated)' : 'drive') : null}
                    </div>
                ) : null}
            </div>
        );
    }

    // The collapsible "Plan detail" wrapper. Reads the read-only view-model planAuthor attached to result.detail.
    renderPlanDetail(s) {
        const r = s.result;
        const d = r && r.detail;
        if (!d) { return null; }
        const open = !!this.state.detailOpen;
        const lbl = {fontSize: '9px', letterSpacing: '.06em', color: '#7a8290', textTransform: 'uppercase'};
        return (
            <div style={{marginTop: '10px', borderTop: '1px solid #1c1c26', paddingTop: '8px'}}>
                <div
                    data-stewie-detail-toggle="1" onClick={this.onToggleDetail}
                    style={{display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', userSelect: 'none'}}
                >
                    <span style={{fontSize: '10px', color: '#39c6ff', width: '10px'}}>{open ? '▾' : '▸'}</span>
                    <span style={{...lbl, color: '#c7d2e3'}}>Plan detail</span>
                    <span style={{flex: '1 1 auto'}} />
                    {d.ir && d.ir.plan_id ? (
                        <span style={{fontSize: '9px', color: '#7a8290', fontFamily: 'ui-monospace, monospace'}}>plan {d.ir.plan_id}</span>
                    ) : null}
                </div>
                {open ? (
                    <div data-stewie-detail="1" style={{marginTop: '6px'}}>
                        {this.renderIR(d.ir)}
                        {this.renderValidation(d.validation, d.ordered)}
                        {this.renderTimelineEndurance(d.timeline, d.endurance)}
                    </div>
                ) : null}
            </div>
        );
    }

    // --- Schedule / Gantt (DEPTH-5): a compact, dark-themed timeline drawn with CSS flex bars (no SVG path,
    // no canvas) from the read-only view-model planAuthor._schedule attached to result.detail.schedule.
    //   • single-vehicle -> the aggregate MISSION TIMELINE: phase-coloured runs (drive/charge/dig/…) on a
    //     0->makespan axis + the battery-fraction envelope (dips on work/drive, recovers at each recharge).
    //   • fleet (vehicles>1) -> one SWIM-LANE per rover, coloured to match its map route (vehicleColor), each
    //     built from that rover's plan-IR action durations. Every value is projected straight from the real
    //     /plan response (timeline frames + plan_ir action durations) — nothing recomputed or fabricated.
    static PHASE_COLOR = {drive: '#8fb8ff', charge: '#7fe0a8', wait: '#3f4653',
        dig: '#e0563a', offload: '#4fd1ff', sinter: '#b47cff', work: '#ffd24a'};
    static OP_COLOR = {GoTo: '#8fb8ff', Excavate: '#e0563a', CutHaulFill: '#ffd24a', Import: '#7cff5e', Sinter: '#b47cff'};

    // A phase/op bar: flex segments sized by duration (flexGrow), colour by phase (timeline) or op (lane), with
    // a trailing spacer out to the axis so a lane that finishes before the makespan reads as ending early.
    scheduleBar(segments, total, axisMax) {
        const track = {display: 'flex', width: '100%', height: '15px', borderRadius: '3px',
            overflow: 'hidden', background: '#0c1017'};
        return (
            <div style={track}>
                {segments.map((seg, i) => {
                    const dur = seg.t1 != null ? (seg.t1 - seg.t0) : (seg.dur_s || 0);
                    if (!(dur > 0)) { return null; }
                    const color = seg.phase ? (MissionPlan.PHASE_COLOR[seg.phase] || '#8a93a3')
                        : (MissionPlan.OP_COLOR[seg.op] || '#8a93a3');
                    return (
                        <div
                            key={i} data-phase={seg.phase || seg.op}
                            style={{flexGrow: dur, flexBasis: 0, minWidth: '1.5px', background: color}}
                            title={(seg.phase || seg.op) + ' · ' + MissionPlan.fmtSs(dur)}
                        />
                    );
                })}
                {(axisMax > total + 1e-6)
                    ? <div style={{flexGrow: (axisMax - total), flexBasis: 0}} /> : null}
            </div>
        );
    }

    // The battery-fraction envelope as time-proportional flex columns (height = min SoC over the column),
    // green>50% -> amber>20% -> red. Single-vehicle only (a fleet's frames are per-vehicle-local, not one clock).
    scheduleBattery(batt) {
        return (
            <div style={{display: 'flex', alignItems: 'flex-end', width: '100%', height: '22px',
                marginTop: '3px', background: '#0c1017', borderRadius: '3px', overflow: 'hidden'}}
            >
                {batt.map((b, i) => {
                    const frac = Math.max(0, Math.min(1, b.frac));
                    const col = frac > 0.5 ? '#7fe0a8' : (frac > 0.2 ? '#ffd24a' : '#e0563a');
                    return (
                        <div key={i} style={{flexGrow: Math.max(b.w, 1e-6), flexBasis: 0,
                            display: 'flex', alignItems: 'flex-end', height: '100%'}}
                        >
                            <div style={{width: '100%', height: Math.round(frac * 100) + '%', background: col}} />
                        </div>
                    );
                })}
            </div>
        );
    }

    renderSchedule(s) {
        const r = s.result;
        const sch = r && r.detail && r.detail.schedule;
        if (!sch) { return null; }
        const open = this.state.scheduleOpen !== false;
        const lbl = {fontSize: '9px', letterSpacing: '.06em', color: '#7a8290', textTransform: 'uppercase'};
        const lanes = sch.lanes || [];
        const fleet = (sch.vehicles || 1) > 1 && lanes.length > 1;
        const tlDur = (sch.timeline && sch.timeline.duration_s) || 0;
        const laneMax = lanes.reduce((m, l) => Math.max(m, l.total_s || 0), 0);
        // axis extent = makespan, floored so a slight a-priori-model overshoot (IR vs sim) never overflows.
        const axisMax = Math.max(sch.makespan_s || 0, fleet ? laneMax : tlDur, 1e-9);
        // legend items: the ops present (fleet) or phases present (single timeline).
        const legend = fleet
            ? Array.from(new Set(lanes.reduce((acc, l) => acc.concat(l.segments.map((x) => x.op)), [])))
                .map((op) => ({label: op, color: MissionPlan.OP_COLOR[op] || '#8a93a3'}))
            : Array.from(new Set((sch.timeline ? sch.timeline.segments.map((x) => x.phase) : [])))
                .map((ph) => ({label: ph, color: MissionPlan.PHASE_COLOR[ph] || '#8a93a3'}));
        const axisLabels = (
            <div style={{display: 'flex', justifyContent: 'space-between', fontSize: '9px',
                color: '#5a6270', marginTop: '3px'}}
            >
                <span>0</span><span>{MissionPlan.fmtSs(axisMax / 2)}</span><span>{MissionPlan.fmtSs(axisMax)}</span>
            </div>
        );
        return (
            <div style={{marginTop: '10px', borderTop: '1px solid #1c1c26', paddingTop: '8px'}}>
                <div
                    data-stewie-schedule-toggle="1" onClick={this.onToggleSchedule}
                    style={{display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', userSelect: 'none'}}
                >
                    <span style={{fontSize: '10px', color: '#39c6ff', width: '10px'}}>{open ? '▾' : '▸'}</span>
                    <span style={{...lbl, color: '#c7d2e3'}}>Schedule / Gantt</span>
                    <span style={{flex: '1 1 auto'}} />
                    <span style={{fontSize: '9px', color: '#7a8290'}}>makespan {MissionPlan.fmtSs(sch.makespan_s)}</span>
                </div>
                {open ? (
                    <div data-stewie-gantt="1" style={{marginTop: '6px'}}>
                        {fleet ? (
                            <div>
                                <div style={{fontSize: '9px', color: '#7a8290', margin: '0 0 6px', lineHeight: 1.35}}>
                                    One swim-lane per rover (colour matches its map route); segments are the
                                    per-action durations from the plan IR. Axis 0 → makespan. Recharges are
                                    precondition-driven (folded into the makespan), not drawn as lane segments.
                                </div>
                                {lanes.map((l) => (
                                    <div key={l.vehicle} data-stewie-gantt-lane={l.vehicle} style={{margin: '5px 0'}}>
                                        <div style={{display: 'flex', alignItems: 'center', gap: '6px',
                                            fontSize: '10px', marginBottom: '2px'}}
                                        >
                                            <span
                                                data-lane-color={l.color}
                                                style={{width: '11px', height: '4px', borderRadius: '2px', background: l.color}}
                                            />
                                            <span style={{color: '#c7d2e3', fontWeight: 600}}>Rover {l.vehicle + 1}</span>
                                            <span style={{flex: '1 1 auto'}} />
                                            <span style={{color: '#8a93a3'}}>{MissionPlan.fmtSs(l.total_s)}</span>
                                        </div>
                                        <div style={{borderLeft: '3px solid ' + l.color, paddingLeft: '4px'}}>
                                            {this.scheduleBar(l.segments, l.total_s, axisMax)}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <div>
                                <div style={{fontSize: '9px', color: '#7a8290', margin: '0 0 6px', lineHeight: 1.35}}>
                                    Mission timeline — per-phase segments from the sim on a 0 → makespan axis; the
                                    battery envelope below dips on work/drive and recovers at each recharge.
                                </div>
                                {sch.timeline
                                    ? this.scheduleBar(sch.timeline.segments, tlDur, axisMax)
                                    : <div style={{fontSize: '10px', color: '#7a8290'}}>No timeline in this plan.</div>}
                                {sch.timeline && sch.timeline.batt && sch.timeline.batt.length
                                    ? this.scheduleBattery(sch.timeline.batt) : null}
                            </div>
                        )}
                        {axisLabels}
                        {legend.length ? (
                            <div style={{display: 'flex', flexWrap: 'wrap', gap: '4px 10px', marginTop: '6px'}}>
                                {legend.map((it) => (
                                    <span key={it.label} style={{display: 'flex', alignItems: 'center', gap: '4px',
                                        fontSize: '9px', color: '#8a93a3'}}
                                    >
                                        <span style={{width: '8px', height: '8px', borderRadius: '2px', background: it.color}} />
                                        {it.label}
                                    </span>
                                ))}
                            </div>
                        ) : null}
                    </div>
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
                {kv('Algorithm', r.algorithm + (r.optimality ? ' · ' + r.optimality : ''))}
                {kv('Objective', r.objective || '—')}
                {kv('Slope gate', (r.max_slope_deg != null ? r.max_slope_deg + '°' : '—'))}
                {r.budgets && Object.keys(r.budgets).length ? kv('Budgets',
                    Object.entries(r.budgets).map(([k, v]) => k.replace(/^max_/, '≤').replace(/_[sJm]$/, '') + ' ' + v).join(' · ')) : null}
                {kv('Terrain', r.terrain_source || '—')}
                {this.renderFleetSummary(r)}
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
                    style={{...inputStyle, marginBottom: '6px'}} value={s.adhoc ? '' : s.site}
                >
                    {SITES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    {s.adhoc ? <option value="">Off-site (custom lat/lon)</option> : null}
                </select>

                {/* PLAN ANYWHERE: pick any lunar lat/lon; the backend crops the global LDEM there on demand
                    (native ~118 m/px, honestly coarse vs the curated 5 m sites) so the layers + planner run. */}
                <div style={{marginBottom: '8px', border: '1px solid #1c1c26', borderRadius: '4px', padding: '6px'}}>
                    <div style={{...lbl, marginBottom: '4px'}}>Plan anywhere (off-site)</div>
                    <div style={{display: 'flex', gap: '6px', alignItems: 'flex-end'}}>
                        <div style={{flex: '1 1 0'}}>
                            <label htmlFor="mp-ah-lat" style={lbl}>Lat °</label>
                            <input
                                data-stewie-adhoc-lat="1" defaultValue={-86.0} id="mp-ah-lat" max="89.9" min="-89.9"
                                onChange={this.onAhLat} step="0.01" style={inputStyle} type="number"
                            />
                        </div>
                        <div style={{flex: '1 1 0'}}>
                            <label htmlFor="mp-ah-lon" style={lbl}>Lon °</label>
                            <input
                                data-stewie-adhoc-lon="1" defaultValue={-30.0} id="mp-ah-lon" max="360" min="-360"
                                onChange={this.onAhLon} step="0.01" style={inputStyle} type="number"
                            />
                        </div>
                        <button
                            data-stewie-adhoc-go="1" onClick={this.onPlanHere}
                            style={{
                                flex: '0 0 auto', cursor: 'pointer', font: '600 11px system-ui, sans-serif',
                                padding: '7px 8px', borderRadius: '4px', border: '1px solid #39c6ff66',
                                color: '#39c6ff', background: '#39c6ff18'
                            }}
                            type="button"
                        >Set here</button>
                    </div>
                    {s.adhoc ? (
                        <div style={{fontSize: '9px', color: '#7a8290', marginTop: '4px', lineHeight: 1.35}}>
                            Off-site work area <b style={{color: '#c7d2e3'}}>{s.site}</b> — global LOLA DEM
                            cropped to a local frame (~118 m/px, coarse vs the curated sites).
                        </div>
                    ) : null}
                </div>

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

                {this.renderPlanControls(s)}

                {this.renderFleet(s)}

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
                {this.renderSchedule(s)}
                {this.renderPlanDetail(s)}
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
