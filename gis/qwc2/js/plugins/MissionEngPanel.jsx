/**
 * [REQ:RT-04] MissionEngPanel -- the RViz/Foxglove ENGINEERING PANEL for the STEWIE lunar IDE
 * (artemis.stewie.space/ide/). A Foxglove-style multi-widget, READ-ONLY diagnostics surface that
 * extends the Rover HUD: topic freshness for the whole RT-04 acceptance roster, the live TF frame
 * tree, the /odom pose + covariance, the /rover/state telemetry, and the diagnostics roster.
 *
 * EVIDENCE-ONLY (PRD §7.B RT-04, acceptance D3): it binds the SAME read-only /rosbridge WS as the HUD
 * via EngPanelClient (subscribe-only; no advertise/publish), and renders NO command control. Acceptance
 * topics not relayed to the browser (/diagnostics, /stewie/costmap) and the 3-D robot-model render show
 * an honest "no data / deferred" -- never fabricated telemetry.
 *
 * Registration: appConfig.js -> pluginsDef.plugins.MissionEngPanelPlugin;
 *   static/config.json -> plugins.common [{"name":"MissionEngPanel"}] + a TopBar menu item.
 * Opening "Eng Panel" dispatches setCurrentTask("MissionEngPanel"); the SideBar (id="MissionEngPanel")
 * shows when state.task.id === "MissionEngPanel".
 */
import React from 'react';

import PropTypes from 'prop-types';
import {connect} from 'react-redux';

import SideBar from 'qwc2/components/SideBar';

import EngPanelClient from '../mission/engPanelClient';

const COLORS = {bg: '#0a0a0c', panel: '#101018', line: '#2a2a36', txt: '#c7d2e3',
    muted: '#7a8290', fresh: '#39ff14', stale: '#e0b300', absent: '#4a4a56', accent: '#35e0d0'};

function fmt(v, d) {
    return (v === undefined || v === null || Number.isNaN(v)) ? '—' : Number(v).toFixed(d);
}
function statusColor(s) {
    return s === 'fresh' ? COLORS.fresh : s === 'stale' ? COLORS.stale : COLORS.absent;
}
function ageLabel(r) {
    if (r.status === 'absent') { return 'absent'; }
    if (r.ageMs == null) { return '—'; }
    return r.ageMs < 1000 ? r.ageMs.toFixed(0) + ' ms' : (r.ageMs / 1000).toFixed(1) + ' s';
}

class MissionEngPanel extends React.Component {
    static propTypes = {
        /** The side of the application on which to display the sidebar. */
        side: PropTypes.string
    };
    static defaultProps = {
        side: 'right'
    };
    state = {
        vm: null
    };
    constructor(props) {
        super(props);
        this.client = null;
        this.tick = null;
    }
    componentDidMount() {
        this.client = new EngPanelClient({
            onState: (vm) => this.setState({vm})
        });
        this.client.connect();
        // re-derive once a second so topic freshness ages tick even when no new message arrives
        this.tick = setInterval(() => { if (this.client) { this.client.refresh(); } }, 1000);
    }
    componentWillUnmount() {
        if (this.tick) { clearInterval(this.tick); this.tick = null; }
        if (this.client) { this.client.disconnect(); this.client = null; }
    }
    connLabel() {
        const vm = this.state.vm;
        if (!vm) { return {text: 'connecting…', color: COLORS.stale}; }
        if (vm.connected) { return {text: 'rosbridge connected · /rosbridge (read-only)', color: COLORS.fresh}; }
        return {text: 'rosbridge reconnecting…', color: COLORS.stale};
    }
    sectionTitle(t) {
        return (
            <div style={{margin: '12px 0 5px', fontSize: '9px', color: COLORS.muted,
                letterSpacing: '.1em', textTransform: 'uppercase'}}>{t}</div>
        );
    }
    renderFreshness() {
        const vm = this.state.vm;
        const rows = (vm && vm.topicRows) || [];
        return (
            <table style={{width: '100%', borderCollapse: 'collapse', fontSize: '10px'}}>
                <thead>
                    <tr style={{color: COLORS.muted, textAlign: 'left'}}>
                        <th style={{fontWeight: 'normal', padding: '2px 4px'}} scope="col">topic</th>
                        <th style={{fontWeight: 'normal', padding: '2px 4px', textAlign: 'right'}} scope="col">age</th>
                        <th style={{fontWeight: 'normal', padding: '2px 4px', textAlign: 'right'}} scope="col">Hz</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map((r) => (
                        <tr key={r.topic} style={{borderTop: '1px solid ' + COLORS.line}}>
                            <td style={{padding: '3px 4px'}}>
                                <span aria-hidden="true" style={{display: 'inline-block', width: '7px', height: '7px',
                                    borderRadius: '50%', background: statusColor(r.status), marginRight: '6px'}} />
                                <span style={{fontFamily: 'monospace'}}>{r.topic}</span>
                                {!r.expectedLive &&
                                    <span style={{color: COLORS.muted, marginLeft: '5px'}}>· not on WS</span>}
                            </td>
                            <td style={{padding: '3px 4px', textAlign: 'right',
                                color: r.status === 'absent' ? COLORS.muted : COLORS.txt}}>{ageLabel(r)}</td>
                            <td style={{padding: '3px 4px', textAlign: 'right', color: COLORS.muted}}>
                                {r.hz == null ? '—' : r.hz.toFixed(1)}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        );
    }
    renderTf() {
        const vm = this.state.vm;
        const tree = (vm && vm.tfTree) || [];
        if (!tree.length) {
            return <div style={{color: COLORS.muted, fontSize: '10px'}}>no /tf frames yet…</div>;
        }
        return (
            <div style={{fontSize: '10px', fontFamily: 'monospace', lineHeight: 1.5}}>
                {tree.map((n) => (
                    <div key={n.frame} style={{paddingLeft: (n.depth * 14) + 'px', color: COLORS.txt}}>
                        <span style={{color: COLORS.accent}}>{n.depth > 0 ? '└ ' : ''}{n.frame}</span>
                        {n.translation &&
                            <span style={{color: COLORS.muted}}>
                                {'  [' + fmt(n.translation.x, 2) + ', ' + fmt(n.translation.y, 2)
                                    + ', ' + fmt(n.translation.z, 2) + ']'}</span>}
                    </div>
                ))}
            </div>
        );
    }
    renderPose() {
        const vm = this.state.vm;
        const p = vm && vm.pose;
        if (!p) { return <div style={{color: COLORS.muted, fontSize: '10px'}}>no /odom yet…</div>; }
        const s = p.sigma;
        return (
            <div style={{fontSize: '10px'}}>
                <div style={{display: 'flex', gap: '10px', flexWrap: 'wrap', fontFamily: 'monospace'}}>
                    <span>x <b>{fmt(p.x, 1)}</b></span>
                    <span>y <b>{fmt(p.y, 1)}</b></span>
                    <span>z <b>{fmt(p.z, 1)}</b></span>
                    <span>hdg <b>{fmt(p.headingDeg, 0)}°</b></span>
                    <span>v <b>{fmt(p.speed, 3)}</b> m/s</span>
                </div>
                <div style={{marginTop: '5px', color: COLORS.muted}}>
                    pose covariance σ (from /odom):
                    {s
                        ? <span style={{fontFamily: 'monospace', color: COLORS.txt}}>
                            {' σx=' + fmt(s.sx, 3) + '  σy=' + fmt(s.sy, 3) + '  σyaw=' + fmt(s.syaw, 3)}
                            {(s.sx === 0 && s.sy === 0 && s.syaw === 0) &&
                                <span style={{color: COLORS.muted}}> (sim reports zero uncertainty)</span>}
                        </span>
                        : <span> — (no covariance in message)</span>}
                </div>
            </div>
        );
    }
    renderNoData(label, why) {
        return (
            <div style={{fontSize: '10px', color: COLORS.muted, display: 'flex', alignItems: 'center', gap: '6px'}}>
                <span aria-hidden="true" style={{display: 'inline-block', width: '7px', height: '7px',
                    borderRadius: '50%', background: COLORS.absent}} />
                <span><b style={{color: COLORS.txt}}>no data</b> — {why}</span>
            </div>
        );
    }
    renderDiagnostics() {
        const vm = this.state.vm;
        const diags = (vm && vm.diagnostics) || [];
        if (!diags.length) {
            return this.renderNoData('diagnostics', '/diagnostics not published by the sim graph');
        }
        const LVL = {0: COLORS.fresh, 1: COLORS.stale, 2: '#e0564b', 3: COLORS.muted};
        return (
            <div style={{fontSize: '10px', fontFamily: 'monospace'}}>
                {diags.map((d, i) => (
                    <div key={d.name + i} style={{padding: '2px 0'}}>
                        <span style={{color: LVL[d.level] || COLORS.txt}}>●</span>{' '}
                        <span style={{color: COLORS.txt}}>{d.name}</span>
                        <span style={{color: COLORS.muted}}>{' — ' + d.message}</span>
                    </div>
                ))}
            </div>
        );
    }
    renderBody = () => {
        const conn = this.connLabel();
        const wrap = {background: COLORS.bg, color: COLORS.txt, padding: '8px',
            font: '11px system-ui, sans-serif'};
        const card = {background: COLORS.panel, border: '1px solid ' + COLORS.line,
            borderRadius: '5px', padding: '7px 9px', marginBottom: '8px'};
        return (
            <div style={wrap}>
                <div style={{display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px'}}>
                    <span aria-hidden="true" style={{width: '9px', height: '9px', borderRadius: '50%',
                        background: conn.color, boxShadow: '0 0 6px ' + conn.color, flex: '0 0 auto'}} />
                    <span style={{fontSize: '10px', letterSpacing: '.04em'}}>{conn.text}</span>
                </div>
                <div style={{fontSize: '9px', color: COLORS.accent, letterSpacing: '.08em',
                    border: '1px solid ' + COLORS.line, borderRadius: '4px', padding: '4px 7px', marginBottom: '4px'}}>
                    EVIDENCE-ONLY · read-only · no command authority
                </div>

                <div style={card}>
                    {this.sectionTitle('Topic freshness')}
                    {this.renderFreshness()}
                </div>
                <div style={card}>
                    {this.sectionTitle('TF frame tree')}
                    {this.renderTf()}
                </div>
                <div style={card}>
                    {this.sectionTitle('Pose & covariance')}
                    {this.renderPose()}
                </div>
                <div style={card}>
                    {this.sectionTitle('Diagnostics')}
                    {this.renderDiagnostics()}
                </div>
                <div style={card}>
                    {this.sectionTitle('Costmap / occupancy')}
                    {this.renderNoData('costmap',
                        'not relayed to the browser WS (available only via the auth-gated POST /ros/export/costmap)')}
                </div>
                <div style={card}>
                    {this.sectionTitle('Robot model (3-D)')}
                    {this.renderNoData('robot model',
                        'deferred — needs a 3-D renderer + the URDF for full RViz parity')}
                </div>
            </div>
        );
    };
    render() {
        return (
            <SideBar
                icon="plot_info"
                id="MissionEngPanel"
                side={this.props.side}
                title="Eng Panel"
                width="26em"
            >
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

export default connect(() => ({}), {})(MissionEngPanel);
