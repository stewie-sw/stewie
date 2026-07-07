/**
 * RT04Client — reusable, READ-ONLY ROS2 telemetry client for the STEWIE lunar IDE.
 *
 * Ported from the OL viewer's RT-04 engine pane (gis/web/app.js ~953-1075). Connects to the
 * same-origin rosbridge WS (nginx -> read-only collector), subscribes the live rover topics, and
 * parses them into ONE plain state object that the MissionHUD plugin feeds to rover_hud.js.
 *
 * READ-ONLY by construction: it subscribes only; it never advertises or publishes, so it holds no
 * command authority over the rover (/cmd_vel, /cmd/nav_goal, /cmd/safe are never touched).
 *
 * roslib is loaded as a raw global (window.ROSLIB) by index.html (assets/roslib.js) — the same verbatim
 * vendored lib the OL viewer's RT-04 pane uses. It is deliberately NOT bundled through babel, which
 * breaks its browserify prototype chains; this client reads window.ROSLIB lazily at connect() time.
 */
import RoverInstruments from './roverInstruments';   // pure, node-tested proprioception view-model

const WS_PATH = '/rosbridge';

function freshState() {
    return {
        connected: false,
        // pose (nav_msgs/Odometry -> /odom)
        x: null, y: null, z: null, headingDeg: null, speed: null,
        // terrain interaction (std_msgs/String JSON -> /rover/state)
        slip: null, sinkage: null, slopeDeg: null, soc: null,
        legId: null, row: null, col: null, entrapped: false, status: 'no data',
        // URDF proprioception (sensor_msgs/JointState -> /joint_states): the 8 actuated joints,
        // classified into {wheels, arms, drums} with RPM + hinge-degree readouts (roverInstruments)
        joints: null,
        // IMU (sensor_msgs/Imu -> /stewie/imu): attitude (quat->roll/pitch/yaw), angular velocity,
        // linear acceleration, and |linear_acceleration| (the sensed gravity, ~1.62 m/s^2 lunar)
        imu: null,
        // liveness bookkeeping
        messages: 0, lastMsgTs: null, odomHz: null,
        // per-channel counters so consumers can push exactly one sparkline sample per data frame
        odomSeq: 0, stateSeq: 0, jointSeq: 0, imuSeq: 0,
        // topic liveness map (topic name -> true once a message has arrived)
        topics: {}
    };
}

export default class RT04Client {
    constructor(callbacks = {}) {
        this.onState = callbacks.onState || (() => {});
        this.onStatus = callbacks.onStatus || (() => {});
        this.state = freshState();
        this.ros = null;
        this._closed = false;
        this._reconnectTimer = null;
        this._odomStamps = [];
    }

    get url() {
        const proto = (typeof location !== 'undefined' && location.protocol === 'https:') ? 'wss://' : 'ws://';
        const host = (typeof location !== 'undefined') ? location.host : '';
        return proto + host + WS_PATH;
    }

    _emit() {
        // shallow copy so React state comparisons see a new object
        this.onState({...this.state, topics: {...this.state.topics}});
    }

    _bump(topic) {
        this.state.messages += 1;
        this.state.lastMsgTs = Date.now();
        this.state.topics[topic] = true;
    }

    connect() {
        const ROSLIB = (typeof window !== 'undefined') ? window.ROSLIB : undefined;
        if (!ROSLIB) {
            this.state.status = 'ROSLIB missing';
            this.onStatus({connected: false, error: 'ROSLIB not loaded'});
            this._emit();
            return;
        }
        this._closed = false;
        const ros = new ROSLIB.Ros({url: this.url});
        this.ros = ros;

        ros.on('connection', () => {
            this.state.connected = true;
            if (this.state.status === 'no data' || this.state.status === 'ROSLIB missing') {
                this.state.status = 'idle';
            }
            this.onStatus({connected: true});
            this._emit();
        });
        ros.on('error', () => {
            this.state.connected = false;
            this.onStatus({connected: false, error: 'error'});
            this._emit();
        });
        ros.on('close', () => {
            this.state.connected = false;
            this.onStatus({connected: false, error: 'closed'});
            this._emit();
            if (!this._closed) {
                this._reconnectTimer = setTimeout(() => this.connect(), 2500);   // resilient reconnect
            }
        });

        // /odom (nav_msgs/Odometry) -> pose x/y/z, heading, speed, real odom rate from ROS stamps
        new ROSLIB.Topic({ros, name: '/odom', messageType: 'nav_msgs/Odometry'})
            .subscribe((msg) => {
                this._bump('/odom');
                const p = msg.pose.pose.position, o = msg.pose.pose.orientation;
                this.state.x = p.x; this.state.y = p.y; this.state.z = p.z;
                const yaw = Math.atan2(2 * (o.w * o.z + o.x * o.y), 1 - 2 * (o.y * o.y + o.z * o.z));
                this.state.headingDeg = ((yaw * 180 / Math.PI) % 360 + 360) % 360;   // 0..360, raw odom yaw
                this.state.speed = msg.twist.twist.linear.x;
                const s = msg.header.stamp, t = s.sec + s.nanosec * 1e-9;
                this._odomStamps.push(t);
                if (this._odomStamps.length > 8) this._odomStamps.shift();
                if (this._odomStamps.length > 1) {
                    const span = this._odomStamps[this._odomStamps.length - 1] - this._odomStamps[0];
                    if (span > 0) this.state.odomHz = (this._odomStamps.length - 1) / span;
                }
                this.state.odomSeq += 1;
                this._emit();
            });

        // /rover/state (std_msgs/String JSON) -> slip, sinkage, slope, SOC, leg, drive status
        new ROSLIB.Topic({ros, name: '/rover/state', messageType: 'std_msgs/String'})
            .subscribe((msg) => {
                this._bump('/rover/state');
                let d;
                try { d = JSON.parse(msg.data); } catch (e) { return; }
                this.state.legId = d.leg_id;
                this.state.row = d.row;
                this.state.col = d.col;
                this.state.slip = d.slip;
                this.state.sinkage = d.sinkage_m;
                this.state.slopeDeg = (d.slope_rad != null) ? d.slope_rad * 180 / Math.PI : null;
                this.state.soc = (d.soc === undefined || d.soc === null) ? null : d.soc;
                this.state.entrapped = !!d.entrapped;
                if (d.entrapped) this.state.status = 'entrapped';
                else if (Math.abs(d.v_achieved_mps || 0) > 1e-3) this.state.status = 'driving';
                else this.state.status = 'idle';
                this.state.stateSeq += 1;
                this._emit();
            });

        // /joint_states (sensor_msgs/JointState) -> the 8 actuated URDF joints (4 wheels as RPM, 2 arm
        // hinges + 2 drum spins). Parsed by the pure, node-tested roverInstruments view-model.
        new ROSLIB.Topic({ros, name: '/joint_states', messageType: 'sensor_msgs/JointState'})
            .subscribe((msg) => {
                this._bump('/joint_states');
                const j = RoverInstruments.parseJointStates(msg);
                if (j) { this.state.joints = j; this.state.jointSeq += 1; }
                this._emit();
            });

        // /stewie/imu (sensor_msgs/Imu) -> attitude (quat -> roll/pitch/yaw), angular velocity, linear
        // acceleration + sensed gravity magnitude.
        new ROSLIB.Topic({ros, name: '/stewie/imu', messageType: 'sensor_msgs/Imu'})
            .subscribe((msg) => {
                this._bump('/stewie/imu');
                const im = RoverInstruments.parseImu(msg);
                if (im) { this.state.imu = im; this.state.imuSeq += 1; }
                this._emit();
            });

        // /tf + /rover/leg — liveness only (mirrors app.js; no parsing, subscribe-only)
        new ROSLIB.Topic({ros, name: '/tf', messageType: 'tf2_msgs/TFMessage'})
            .subscribe(() => { this._bump('/tf'); this._emit(); });
        new ROSLIB.Topic({ros, name: '/rover/leg', messageType: 'std_msgs/String'})
            .subscribe(() => { this._bump('/rover/leg'); this._emit(); });
    }

    disconnect() {
        this._closed = true;
        if (this._reconnectTimer) { clearTimeout(this._reconnectTimer); this._reconnectTimer = null; }
        try { if (this.ros) this.ros.close(); } catch (e) { /* ignore */ }
        this.ros = null;
    }
}
