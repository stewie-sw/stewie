/**
 * [REQ:RT-04] EngPanelClient -- READ-ONLY rosbridge subscriber for the STEWIE engineering panel.
 *
 * Same wire as the Rover HUD (rt04Client.js): the same-origin /rosbridge WS (nginx -> read-only
 * collector). Where rt04Client parses only the HUD's fields, this client forwards each rosbridge
 * publish frame verbatim into the pure engPanel.js model, which derives the richer engineering view
 * (topic freshness / TF tree / pose+covariance / diagnostics). One place parses (engPanel.js, tested);
 * this file is just the I/O shell + reconnect, mirroring rt04Client.
 *
 * EVIDENCE-ONLY BY CONSTRUCTION (acceptance D3): it calls .subscribe() only. It never advertises or
 * publishes, so it holds NO command authority over the rover (/cmd_vel, /cmd/nav_goal, /cmd/safe are
 * never touched). window.ROSLIB is read lazily at connect() time (loaded as a raw global by index.html,
 * NOT babel-bundled -- see rt04Client.js for why).
 */
import EngPanel from './engPanel';   // pure model (window.STEWIE_ENG_PANEL + default export)

const WS_PATH = '/rosbridge';

// the read-only telemetry topics the RT-04 feeder relays to the browser collector. Command topics
// (/cmd_vel, /cmd/nav_goal, /cmd/safe) are DELIBERATELY absent -- this panel cannot command.
const SUBS = [
    ['/tf', 'tf2_msgs/TFMessage'],
    ['/odom', 'nav_msgs/Odometry'],
    ['/rover/state', 'std_msgs/String'],
    ['/rover/leg', 'std_msgs/String']
];

export default class EngPanelClient {
    constructor(callbacks = {}) {
        this.onState = callbacks.onState || (() => {});
        this.onStatus = callbacks.onStatus || (() => {});
        this.model = EngPanel.freshModel();
        this.connected = false;
        this.ros = null;
        this._closed = false;
        this._reconnectTimer = null;
        this._seq = 0;
    }

    get url() {
        const proto = (typeof location !== 'undefined' && location.protocol === 'https:') ? 'wss://' : 'ws://';
        const host = (typeof location !== 'undefined') ? location.host : '';
        return proto + host + WS_PATH;
    }

    // derive + push the current view model (also called on a timer so freshness ages tick with no new msg)
    refresh() {
        const now = Date.now();
        this.onState({
            connected: this.connected,
            seq: ++this._seq,
            topicRows: EngPanel.topicRows(this.model, now),
            tfTree: EngPanel.tfTree(this.model),
            pose: EngPanel.poseCovariance(this.model),
            diagnostics: EngPanel.diagnosticsRows(this.model),
            state: this.model.state
        });
    }

    connect() {
        const ROSLIB = (typeof window !== 'undefined') ? window.ROSLIB : undefined;
        if (!ROSLIB) {
            this.onStatus({connected: false, error: 'ROSLIB not loaded'});
            this.refresh();
            return;
        }
        this._closed = false;
        const ros = new ROSLIB.Ros({url: this.url});
        this.ros = ros;

        ros.on('connection', () => {
            this.connected = true;
            this.onStatus({connected: true});
            this.refresh();
        });
        ros.on('error', () => {
            this.connected = false;
            this.onStatus({connected: false, error: 'error'});
            this.refresh();
        });
        ros.on('close', () => {
            this.connected = false;
            this.onStatus({connected: false, error: 'closed'});
            this.refresh();
            if (!this._closed) {
                this._reconnectTimer = setTimeout(() => this.connect(), 2500);   // resilient reconnect
            }
        });

        // subscribe-only: each frame folds into the pure model, then we re-derive + emit
        SUBS.forEach(([name, type]) => {
            new ROSLIB.Topic({ros, name, messageType: type})
                .subscribe((msg) => {
                    EngPanel.ingest(this.model, {topic: name, msg}, Date.now());
                    this.refresh();
                });
        });
    }

    disconnect() {
        this._closed = true;
        if (this._reconnectTimer) { clearTimeout(this._reconnectTimer); this._reconnectTimer = null; }
        try { if (this.ros) { this.ros.close(); } } catch (e) { /* ignore */ }
        this.ros = null;
    }
}
