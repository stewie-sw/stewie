/**
 * MissionHUD — a live, READ-ONLY rover HUD side panel for the STEWIE lunar IDE (artemis.stewie.space/ide/).
 *
 * REBIND, not rewrite: it wires the vendored RT-04 telemetry client (js/mission/rt04Client.js) into the
 * pure, framework-agnostic rover HUD renderer (js/mission/rover_hud.js — a verbatim lift of
 * stewie/server/web/assets/rover_hud.js). The client subscribes the read-only rosbridge topics and emits
 * ONE state object; this plugin draws that state onto canvases with drawRoverHUD / teleSpark / teleChip.
 *
 * Registration:
 *   - appConfig.js  -> pluginsDef.plugins.MissionHUDPlugin
 *   - static/config.json -> plugins.common [{"name": "MissionHUD"}] + a TopBar menu item {"key": "MissionHUD"}
 * Opening the "Rover HUD" app-menu entry dispatches setCurrentTask("MissionHUD"); the SideBar (id="MissionHUD")
 * shows when state.task.id === "MissionHUD".
 */
import React from 'react';

import PropTypes from 'prop-types';
import {connect} from 'react-redux';

import SideBar from 'qwc2/components/SideBar';

import RoverHUD from '../mission/rover_hud';   // verbatim FS-24 renderer (window.STEWIE_ROVER_HUD + default export)
import RT04Client from '../mission/rt04Client';

// IPEx large-drum capacity (kg) used only to scale the drum-load bars. The live RT-04 stream does not
// carry drum mass, so those bars read 0.0 kg (honest: no fabricated drum telemetry).
const DRUM_CAP_KG = 30;

function fmt(v, d) {
    return (v === undefined || v === null || Number.isNaN(v)) ? '—' : Number(v).toFixed(d);
}

/**
 * Live rover HUD. Connects on mount (like the OL viewer's RT-04 pane) so telemetry is already flowing
 * when the panel is opened; redraws the canvases on every telemetry frame while the panel is visible.
 */
class MissionHUD extends React.Component {
    static propTypes = {
        /** The side of the application on which to display the sidebar. */
        side: PropTypes.string
    };
    static defaultProps = {
        side: 'right'
    };
    state = {
        telem: null
    };
    constructor(props) {
        super(props);
        this.hudCanvas = React.createRef();
        this.sparkCanvas = React.createRef();
        this.railRef = React.createRef();
        this.buf = {batt: [], mass: [], slip: []};   // sparkline ring buffer (rover_hud telePush caps at 240)
        this.client = null;
        this.lastStateSeq = -1;
    }
    componentDidMount() {
        this.client = new RT04Client({
            onState: (s) => {
                // push exactly one sparkline sample per fresh /rover/state frame (soc + slip; drum mass
                // absent from the live stream -> 0)
                if (s.stateSeq !== this.lastStateSeq) {
                    this.lastStateSeq = s.stateSeq;
                    RoverHUD.telePush(this.buf, s.soc != null ? s.soc : 0, 0, s.slip != null ? s.slip : 0, null);
                }
                this.setState({telem: s});
            }
        });
        this.client.connect();
    }
    componentWillUnmount() {
        if (this.client) {
            this.client.disconnect();
            this.client = null;
        }
    }
    componentDidUpdate() {
        this.draw();
    }
    onShow = () => {
        // draw immediately from the last-known state once the SideBar body has mounted its canvases
        window.requestAnimationFrame(() => this.draw());
    };
    draw = () => {
        const s = this.state.telem;
        const hud = this.hudCanvas.current;
        if (hud) {
            RoverHUD.drawRoverHUD(hud, s ? {
                headingDeg: s.headingDeg, soc: s.soc,
                frontKg: null, rearKg: null, x: s.x, y: s.y
            } : null, DRUM_CAP_KG);
        }
        const spark = this.sparkCanvas.current;
        if (spark) {
            RoverHUD.teleSpark(spark, this.buf);
        }
        const rail = this.railRef.current;
        if (rail && s) {
            RoverHUD.teleChip(rail, 'speed', fmt(s.speed, 3) + ' m/s', true);
            RoverHUD.teleChip(rail, 'slip', fmt(s.slip, 3), s.slip == null || s.slip < 0.6);
            RoverHUD.teleChip(rail, 'sink', fmt(s.sinkage, 3) + ' m', true);
            RoverHUD.teleChip(rail, 'slope', fmt(s.slopeDeg, 1) + '°', true);
            RoverHUD.teleChip(rail, 'leg', s.legId != null ? String(s.legId) : '—', true);
            RoverHUD.teleChip(rail, 'state', s.status, !s.entrapped);
            RoverHUD.teleChip(rail, 'odom', fmt(s.odomHz, 1) + ' Hz', true);
        }
    };
    // The faithful URDF instrument block: the 8 actuated joints (4 wheels as RPM, 2 drum-arm hinges +
    // 2 drum spins) + the IMU (attitude / angular rate / linear accel), derived by the pure, node-tested
    // roverInstruments view-model (via rt04Client). Read-only; '—' honestly where no telemetry has arrived.
    renderInstruments = () => {
        const s = this.state.telem;
        const j = s && s.joints;
        const im = s && s.imu;
        const sect = {margin: '12px 0 3px', fontSize: '9px', color: '#7a8290', letterSpacing: '.08em'};
        const row = {display: 'flex', gap: '4px', marginBottom: '4px'};
        const cell = (label, val, color) => (
            <div
                key={label}
                style={{
                    flex: '1 1 0', minWidth: '48px', padding: '3px 5px', border: '1px solid #2a2a36',
                    borderRadius: '4px', background: '#111119'
                }}
            >
                <div style={{fontSize: '8px', color: '#7a8290', letterSpacing: '.05em', whiteSpace: 'nowrap'}}>{label}</div>
                <div style={{fontSize: '11px', color: color || '#c7d2e3', fontVariantNumeric: 'tabular-nums'}}>{val}</div>
            </div>
        );
        const wheels = j ? j.wheels : [{label: 'FL'}, {label: 'FR'}, {label: 'RL'}, {label: 'RR'}];
        const arms = j ? j.arms : [{label: 'FRONT ARM'}, {label: 'REAR ARM'}];
        const drums = j ? j.drums : [{label: 'FRONT DRUM'}, {label: 'REAR DRUM'}];
        return (
            <div>
                <div style={sect}>URDF JOINTS · 4 WHEELS (RPM)</div>
                <div style={row}>
                    {wheels.map((w) => cell(w.label, j ? fmt(w.rpm, 1) : '—',
                        j && Math.abs(w.rpm) > 0.1 ? '#39ff14' : '#c7d2e3'))}
                </div>
                <div style={sect}>DRUM ARMS (deg) · DRUMS (rpm)</div>
                <div style={row}>
                    {arms.map((a) => cell(a.label, j ? fmt(a.positionWrappedDeg, 1) + '°' : '—'))}
                    {drums.map((d) => cell(d.label, j ? fmt(d.rpm, 1) : '—'))}
                </div>
                <div style={sect}>IMU · ATTITUDE / RATE / ACCEL</div>
                <div style={row}>
                    {cell('ROLL', im ? fmt(im.rollDeg, 1) + '°' : '—')}
                    {cell('PITCH', im ? fmt(im.pitchDeg, 1) + '°' : '—')}
                    {cell('YAW', im ? fmt(im.yawDeg, 1) + '°' : '—')}
                </div>
                <div style={row}>
                    {cell('ωx rad/s', im ? fmt(im.angularVel.x, 2) : '—')}
                    {cell('ωy rad/s', im ? fmt(im.angularVel.y, 2) : '—')}
                    {cell('ωz rad/s', im ? fmt(im.angularVel.z, 2) : '—')}
                    {cell('|g| m/s²', im ? fmt(im.gravityMag, 2) : '—')}
                </div>
            </div>
        );
    };
    connLabel() {
        const s = this.state.telem;
        if (!s) return {text: 'connecting…', color: '#e0b300'};
        if (s.connected) return {text: 'rosbridge connected · /rosbridge (read-only)', color: '#39ff14'};
        if (s.status === 'ROSLIB missing') return {text: 'ROSLIB not loaded', color: '#e0564b'};
        return {text: 'rosbridge reconnecting…', color: '#e0b300'};
    }
    renderBody = () => {
        const s = this.state.telem;
        const conn = this.connLabel();
        const wrapStyle = {
            // dark theme + CSS custom properties consumed by rover_hud.teleChip (var(--txt)/var(--line))
            background: '#0a0a0c',
            color: '#c7d2e3',
            padding: '8px',
            font: '11px system-ui, sans-serif',
            '--txt': '#c7d2e3',
            '--line': '#2a2a36'
        };
        return (
            <div style={wrapStyle}>
                <div style={{display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px'}}>
                    <span style={{
                        width: '9px', height: '9px', borderRadius: '50%',
                        background: conn.color, boxShadow: '0 0 6px ' + conn.color, flex: '0 0 auto'
                    }} />
                    <span style={{fontSize: '10px', letterSpacing: '.04em'}}>{conn.text}</span>
                </div>
                <canvas
                    height={96}
                    ref={this.hudCanvas}
                    style={{width: '100%', maxWidth: '312px', display: 'block', borderRadius: '4px', border: '1px solid #2a2a36'}}
                    width={312}
                />
                <div style={{margin: '10px 0 3px', fontSize: '9px', color: '#7a8290', letterSpacing: '.08em'}}>
                    BATT / SLIP — 240-sample trend
                </div>
                <canvas
                    height={46}
                    ref={this.sparkCanvas}
                    style={{width: '100%', maxWidth: '312px', display: 'block', borderRadius: '4px', border: '1px solid #2a2a36'}}
                    width={312}
                />
                <div
                    ref={this.railRef}
                    style={{display: 'flex', flexWrap: 'wrap', gap: '5px', marginTop: '10px'}}
                />
                {this.renderInstruments()}
                <div style={{marginTop: '10px', fontSize: '9px', color: '#7a8290'}}>
                    {s
                        ? 'messages: ' + s.messages + (s.lastMsgTs ? ' · last ' + new Date(s.lastMsgTs).toLocaleTimeString() : '')
                        : 'awaiting telemetry…'}
                </div>
            </div>
        );
    };
    render() {
        return (
            <SideBar
                icon="routing-car"
                id="MissionHUD"
                onShow={this.onShow}
                side={this.props.side}
                title="Rover HUD"
                width="24em"
            >
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

export default connect(() => ({}), {})(MissionHUD);
