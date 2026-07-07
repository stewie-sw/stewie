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
import RoverWireframe from '../mission/roverWireframe';   // pure, node-tested URDF kinematic-skeleton view-model
import RT04Client from '../mission/rt04Client';

// IPEx large-drum capacity (kg) used only to scale the drum-load bars. The live RT-04 stream does not
// carry drum mass, so those bars read 0.0 kg (honest: no fabricated drum telemetry).
const DRUM_CAP_KG = 30;

function fmt(v, d) {
    return (v === undefined || v === null || Number.isNaN(v)) ? '—' : Number(v).toFixed(d);
}

// ---- kinematic-wireframe styling: dark graphite skeleton, cyan #4fd1ff structure, amber spin marks,
//      sensor markers colour-coded operational=cyan / redundant=dim. Keyed by roverWireframe primitive cls. ----
const WF_COLORS = {
    'chassis': {stroke: '#3f4c5f', fill: 'none', w: 1.1},
    'ground': {stroke: '#2c3340', w: 1, dash: '3 3'},
    'mast': {stroke: '#3f4c5f', w: 1},
    'wheel': {stroke: '#4fd1ff', fill: 'none', w: 1.3},
    'wheel-spoke': {stroke: '#ffcc55', w: 1.5},
    'arm': {stroke: '#6ee7ff', w: 1.7},
    'drum': {stroke: '#4fd1ff', fill: 'none', w: 1.3},
    'drum-spoke': {stroke: '#ffcc55', w: 1.5},
    'cam-op': {fill: '#4fd1ff', stroke: '#dff6ff'},
    'cam-red': {fill: '#55606e', stroke: '#3a424e'},
    'fov-op': {fill: 'rgba(79,209,255,0.14)', stroke: 'rgba(79,209,255,0.45)', w: 0.8},
    'fov-red': {fill: 'rgba(120,132,148,0.07)', stroke: 'rgba(120,132,148,0.28)', w: 0.8},
    'imu': {stroke: '#ffcc55', w: 1.3},
    'depth': {fill: '#8894a5', stroke: '#5a6472'},
    'label-op': {fill: '#7fdcff'},
    'label-red': {fill: '#6b7484'},
    'label-dim': {fill: '#7a8290'}
};

// Fit one roverWireframe panel {primitives, bounds} (world metres, u=right/v=up) into a w x h px SVG,
// flipping v so world-up is screen-up. Pure: returns an <svg>. showLabels gates the tiny sensor text so the
// small FRONT/BACK panels stay uncluttered.
function wireframeSvg(panel, w, h, showLabels) {
    const b = panel.bounds;
    const pad = 10;
    const du = Math.max(b.maxU - b.minU, 1e-6);
    const dv = Math.max(b.maxV - b.minV, 1e-6);
    const scale = Math.min((w - 2 * pad) / du, (h - 2 * pad) / dv);
    const ox = (w - du * scale) / 2;
    const oy = (h - dv * scale) / 2;
    const px = (u) => ox + (u - b.minU) * scale;
    const py = (v) => h - (oy + (v - b.minV) * scale);   // flip: +v up
    const els = [];
    panel.primitives.forEach((p, i) => {
        const c = WF_COLORS[p.cls] || {stroke: '#4fd1ff'};
        const key = p.cls + i;
        if (p.type === 'circle') {
            els.push(<circle cx={px(p.u)} cy={py(p.v)} fill={c.fill || 'none'} key={key} r={p.r * scale} stroke={c.stroke} strokeWidth={c.w || 1} />);
        } else if (p.type === 'line') {
            els.push(<line key={key} stroke={c.stroke} strokeDasharray={c.dash} strokeWidth={c.w || 1} x1={px(p.u1)} x2={px(p.u2)} y1={py(p.v1)} y2={py(p.v2)} />);
        } else if (p.type === 'poly') {
            const pts = p.pts.map((q) => px(q.u) + ',' + py(q.v)).join(' ');
            els.push(<polygon fill={c.fill || 'none'} key={key} points={pts} stroke={c.stroke} strokeWidth={c.w || 1} />);
        } else if (p.type === 'cone') {
            const pts = p.pts.map((q) => px(q.u) + ',' + py(q.v)).join(' ');
            els.push(<polygon fill={c.fill} key={key} points={pts} stroke={c.stroke} strokeWidth={c.w || 0.8} />);
        } else if (p.type === 'node') {
            const x = px(p.u), y = py(p.v);
            if (p.shape === 'diamond') {
                els.push(<polygon fill={c.fill} key={key} points={`${x},${y - 2.6} ${x + 2.6},${y} ${x},${y + 2.6} ${x - 2.6},${y}`} stroke={c.stroke} strokeWidth={0.6} />);
            } else if (p.shape === 'cross') {
                els.push(<g key={key} stroke={c.stroke} strokeWidth={c.w || 1.2}><line x1={x - 3} x2={x + 3} y1={y} y2={y} /><line x1={x} x2={x} y1={y - 3} y2={y + 3} /></g>);
            } else {
                els.push(<rect fill={c.fill} height={4.4} key={key} stroke={c.stroke} strokeWidth={0.6} width={4.4} x={x - 2.2} y={y - 2.2} />);
            }
        } else if (p.type === 'label' && showLabels) {
            els.push(<text fill={c.fill} fontFamily="ui-monospace, monospace" fontSize={6.5} key={key} x={px(p.u) + 3} y={py(p.v) - 3}>{p.text}</text>);
        }
    });
    return <svg height={h} style={{display: 'block'}} width={w}>{els}</svg>;
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
    // The LIVE KINEMATIC WIREFRAME: the URDF IPEx skeleton (roverWireframe.js, dimension-faithful to
    // ipex.urdf.xacro) posed from the REAL /joint_states position angles flowing through rt04Client. Four
    // orthographic panels (SIDE/FRONT/BACK/TOP): the wheel spokes, drum-arm arcs and drum-spin marks animate
    // as `joints` changes; the 8 nav cameras are drawn as role-coloured nodes + yaw-direction FOV wedges, plus
    // the IMU + forward depth/LiDAR/RGB-D hardpoints. No live camera video (GPU render is on-demand only) --
    // the rig shows sensor POSITIONS + pointing, with an honest render-gated affordance below.
    renderWireframe = () => {
        const s = this.state.telem;
        const joints = s && s.joints ? s.joints : null;   // parsed roverInstruments model, or null (neutral pose)
        const all = RoverWireframe.buildAll(joints);
        const panelBox = {border: '1px solid #2a2a36', borderRadius: '4px', background: '#0d0d13', overflow: 'hidden'};
        const cap = {fontSize: '7.5px', color: '#7a8290', letterSpacing: '.06em', padding: '2px 4px 0'};
        const wideW = 296, smallW = 144;
        const panel = (view, w, hgt, title, showLabels) => (
            <div style={{...panelBox, width: w + 'px'}}>
                <div style={cap}>{title}</div>
                {wireframeSvg(all[view], w, hgt, showLabels)}
            </div>
        );
        return (
            <div>
                <div style={{margin: '14px 0 4px', fontSize: '9px', color: '#7a8290', letterSpacing: '.08em'}}>
                    KINEMATIC WIREFRAME · URDF ipex · live /joint_states
                </div>
                <div style={{display: 'flex', flexDirection: 'column', gap: '6px'}}>
                    {panel('side', wideW, 150, 'SIDE · x→ z↑', true)}
                    <div style={{display: 'flex', gap: '6px'}}>
                        {panel('front', smallW, 128, 'FRONT · look −x', false)}
                        {panel('back', smallW, 128, 'BACK · look +x', false)}
                    </div>
                    {panel('top', wideW, 160, 'TOP · plan, nose ↑', true)}
                </div>
                <div style={{marginTop: '6px', display: 'flex', flexWrap: 'wrap', gap: '8px', fontSize: '8px', color: '#7a8290', alignItems: 'center'}}>
                    <span><span style={{color: '#4fd1ff'}}>■</span> cam operational</span>
                    <span><span style={{color: '#55606e'}}>■</span> redundant</span>
                    <span><span style={{color: '#8894a5'}}>◆</span> depth/LiDAR</span>
                    <span><span style={{color: '#ffcc55'}}>+</span> IMU</span>
                </div>
                <div style={{marginTop: '4px', fontSize: '8px', color: '#6b7484', fontStyle: 'italic'}}>
                    8-cam nav rig: positions + FOV shown · live video render-gated (GPU on-demand, not streamed)
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
                {this.renderWireframe()}
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
