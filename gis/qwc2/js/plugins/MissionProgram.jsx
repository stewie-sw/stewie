/**
 * MissionProgram — the STEWIE PROGRAM BOARD bound into the lunar IDE (artemis.stewie.space/ide/).
 *
 * The cockpit-only /program board (stewie/server/web/program.html + assets/program_board.js) rendered the
 * committed PRD §7 requirement matrix: bucket-colored row chips grouped by lane, a filter deck
 * (bucket/priority/live-search), a sticky inspect panel (dispatch-brief goal + test target + citations),
 * and the six-slot ConOps spine. As the cockpit→GIS migration makes this IDE STEWIE's single front door,
 * that board must live IN the IDE.
 *
 * REBIND, not rewrite: it fetches the SAME committed snapshot the cockpit serves (/api/program/snapshot →
 * routers/program.py, GET-only, public) and renders it with the SAME pure renderers, lifted verbatim into
 * js/mission/programBoard.js (summaryHTML/spineHTML/priorityHTML/lanesHTML/rowDetailHTML + applyFilter/
 * countsByBucket/bucketMeta), exactly as MissionHUD wires rover_hud.js. No data is re-derived here.
 *
 * DEFAULT VIEW = the §7.B "GIS Mission Workbench" program (lanes GW/LY/PH/TM/RT/ED/SD/AU/EV — the
 * artemis-rebuild rows). That subset is the program of work FOR this IDE, so it is what the operator sees
 * on open. The full STEWIE §7 board stays one click away via the scope switch ("Full §7 board"), which
 * clears the default GIS filter. programBoard.js's GIS_LANES is the single source of the lane set.
 *
 * Registration:
 *   - js/appConfig.js     -> pluginsDef.plugins.MissionProgramPlugin
 *   - static/config.json  -> plugins.common [{"name": "MissionProgram"}] + a TopBar menu item
 *                            {"key": "MissionProgram", "title": "Program", "icon": "list-alt"}
 * The "Program" app-menu entry dispatches setCurrentTask("MissionProgram"); the SideBar (id="MissionProgram")
 * shows while state.task.id === "MissionProgram". MissionHUD/MissionLayers/MissionPlan/WholeMoon untouched.
 */
import React from 'react';

import {connect} from 'react-redux';

import SideBar from 'qwc2/components/SideBar';

import HtmlEsc from '../mission/htmlesc';   // verbatim FS-24 esc (window.STEWIE_HTMLESC + default export)
import PB from '../mission/programBoard';   // lifted /program renderers (window.STEWIE_PROGRAM_BOARD)
import FT from '../mission/fetchWithTimeout';   // [systems-eng] bounded read: abort a hung /program/snapshot

const esc = HtmlEsc.esc;
const GIS_LANES = PB.GIS_LANES;

// short filter-deck labels — the exact words the cockpit deck uses (program.html), so the board reads
// identically. The long PB.BUCKETS labels are kept for the inspect-panel status line.
const DECK_LABEL = {done: 'verified done', buildable: 'buildable now', gated: 'gated', concurrent: 'concurrent-owned'};
const BUCKET_ORDER = ['done', 'buildable', 'gated', 'concurrent'];
const PRI_ORDER = ['P0', 'P1', 'P2'];

// Scoped board CSS — lifted from stewie/server/web/program.html <style>, every selector prefixed
// .stewie-program so it cannot leak into the QWC2 chrome. The bucket colors (b-done/b-build/b-gated/
// b-conc) and the graphite/drum-red board palette are preserved exactly (the semantic color contract the
// cockpit board established). The rise animation is deliberately omitted (no re-animate flicker on every
// keystroke); the inline animation-delay in laneSectionHTML then references no keyframes and stays inert.
const BOARD_CSS = `
.stewie-program { --bg:#0a0a0c; --panel:#101013; --field:#141417; --line:#26262c; --txt:#d6d6da;
  --muted:#8a8a93; --accent:#ef3a52; color:var(--txt); background:var(--bg); padding:10px;
  font:12px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
.stewie-program * { box-sizing:border-box; }
.stewie-program h2 { font-size:11px; letter-spacing:.1em; text-transform:uppercase; color:var(--muted);
  margin:0 0 8px; font-weight:400; }
.stewie-program .board-card { background:var(--panel); border:1px solid var(--line); border-radius:8px;
  padding:10px 12px; margin-bottom:12px; min-width:0; overflow-wrap:anywhere; }
.stewie-program .chip { display:inline-block; border:1px solid var(--line); border-radius:999px;
  padding:2px 9px; margin:2px 6px 2px 0; background:var(--field); font-size:11px; }
.stewie-program .chip b { color:var(--txt); }
.stewie-program .prov { color:var(--muted); margin-top:8px; font-size:11px; overflow-wrap:anywhere; }
.stewie-program code { background:var(--field); border:1px solid var(--line); border-radius:3px;
  padding:0 4px; color:var(--txt); }
.stewie-program .prov code { color:var(--txt); }
.stewie-program .spine { overflow-x:auto; white-space:nowrap; }
.stewie-program .spine .step { letter-spacing:.08em; padding:2px 4px; font-weight:600; }
.stewie-program .spine .arrow { color:var(--muted); padding:0 6px; }
.stewie-program .spine .applink { color:var(--accent); text-decoration:none; margin-left:12px; }
.stewie-program .spine .applink:hover { text-decoration:underline; }
.stewie-program .scope { display:flex; gap:6px; margin-bottom:8px; }
.stewie-program .scopebtn { flex:1 1 0; font:600 11px system-ui,sans-serif; padding:7px 6px;
  border-radius:4px; cursor:pointer; border:1px solid var(--line); background:var(--field); color:var(--txt); }
.stewie-program .scopebtn.on { border-color:var(--accent); color:#fff; box-shadow:inset 0 0 0 1px var(--accent); }
.stewie-program .scopemeta { font-size:11px; color:var(--muted); margin-bottom:10px; line-height:1.5; }
.stewie-program .scopemeta b { color:var(--txt); }
.stewie-program .deck { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-bottom:10px; }
.stewie-program .deck .lbl { color:var(--muted); font-size:11px; text-transform:uppercase;
  letter-spacing:.08em; margin-right:2px; }
.stewie-program .fbtn { font:12px/1.2 ui-monospace,monospace; border-radius:4px; padding:4px 9px;
  cursor:pointer; border:1px solid var(--line); background:var(--field); color:var(--txt); }
.stewie-program .fbtn:hover { border-color:#3a3a44; }
.stewie-program .fbtn[aria-pressed="true"] { border-color:var(--accent); box-shadow:inset 0 0 0 1px var(--accent); }
.stewie-program .fbtn .n { color:var(--muted); }
.stewie-program .psearch { font:12px/1.2 ui-monospace,monospace; background:var(--field); color:var(--txt);
  border:1px solid var(--line); border-radius:4px; padding:5px 9px; min-width:150px; flex:1 1 150px; }
.stewie-program .psearch:focus { outline:2px solid var(--accent); outline-offset:1px; }
.stewie-program .results { color:var(--muted); font-size:11px; margin-left:auto; }
.stewie-program table { border-collapse:collapse; width:100%; }
.stewie-program th, .stewie-program td { text-align:left; padding:3px 8px 3px 0; border-bottom:1px solid var(--line); }
.stewie-program th { color:var(--muted); font-weight:normal; font-size:11px; text-transform:uppercase; letter-spacing:.08em; }
.stewie-program .barcell { width:52%; white-space:nowrap; color:var(--muted); }
.stewie-program .bar { display:inline-block; height:8px; background:#3fa34d; border-radius:4px;
  vertical-align:middle; margin-right:6px; max-width:82%; }
.stewie-program .lanegroup { margin:4px 0 16px; }
.stewie-program .grouphdr { font:600 12px/1.3 ui-monospace,monospace; text-transform:uppercase;
  letter-spacing:.04em; color:var(--txt); margin:0 0 8px; padding:6px 0 5px; border-bottom:1px solid var(--line);
  display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.stewie-program .grouproll { margin-left:auto; display:flex; align-items:center; gap:8px; }
.stewie-program .gbar { flex:0 0 90px; height:5px; background:var(--field); border:1px solid var(--line);
  border-radius:3px; overflow:hidden; }
.stewie-program .gbar > span { display:block; height:100%; background:#3fa34d; }
.stewie-program .gcount { color:var(--muted); font-size:11px; white-space:nowrap; }
.stewie-program .lanegrid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:2px 16px; }
.stewie-program .lane h3 { font-size:12px; margin:6px 0 4px; display:flex; align-items:center; gap:8px; }
.stewie-program .lanebar { flex:0 0 70px; height:4px; background:var(--field); border:1px solid var(--line);
  border-radius:2px; overflow:hidden; }
.stewie-program .lanebar span { display:block; height:100%; background:#3fa34d; opacity:.85; }
.stewie-program .lanecount { color:var(--muted); font-weight:normal; font-size:11px; }
.stewie-program .rowchip { font:12px/1.2 ui-monospace,monospace; border-radius:4px; padding:3px 7px;
  margin:2px 4px 2px 0; cursor:pointer; border:1px solid var(--line); background:var(--field); color:var(--txt); }
.stewie-program .rowchip:hover { border-color:#3a3a44; }
.stewie-program .rowchip.selected { box-shadow:inset 0 0 0 1px currentColor; background:#1a1a1f; }
.stewie-program .b-done { border-color:#2f6f3f; color:#7fd191; }
.stewie-program .b-build { border-color:#3e6478; color:#7fb6cc; }
.stewie-program .b-gated { border-color:#8a6a1f; color:#e3b64f; }
.stewie-program .b-conc { border-color:#5b4a8a; color:#b9a5ee; }
.stewie-program .empty { padding:12px 2px; }
.stewie-program .muted { color:var(--muted); }
.stewie-program #pd-detail h3 { margin:2px 0 6px; font-size:12px; }
.stewie-program .status { font-weight:bold; }
.stewie-program .glyphs { color:var(--muted); }
.stewie-program .brief { border-top:1px solid var(--line); margin-top:8px; padding-top:6px; }
.stewie-program .brief h4 { margin:0 0 4px; font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); }
.stewie-program .err { color:var(--accent); }
`;

const SCOPE_LABEL = {gis: 'GIS Mission Workbench (PRD2 §7.B)', all: 'Full STEWIE §7 board'};

class MissionProgram extends React.Component {
    state = {
        snap: null,       // the committed /program snapshot (fetched once)
        error: null,      // fetch/parse error (honest, never a silent blank pane)
        scope: 'gis',     // 'gis' (default: the artemis-rebuild program) | 'all' (full §7)
        bucket: null,     // filter-deck bucket toggle
        pri: null,        // filter-deck priority toggle
        q: '',            // live search
        selected: null    // inspected row id
    };
    componentDidMount() {
        // fetch the SAME committed snapshot the cockpit serves, through the keyless /api proxy (public,
        // GET-only). Errors surface in the panel rather than a blank board.
        FT.fetchWithTimeout('/api/program/snapshot', {}, FT.DEFAULT_MS)
            .then((r) => { if (!r.ok) { throw new Error('snapshot HTTP ' + r.status); } return r.json(); })
            .then((snap) => this.setState({snap}))
            .catch((e) => this.setState({error: e.message}));
    }
    scopedRows(snap) {
        return this.state.scope === 'gis'
            ? snap.rows.filter((r) => GIS_LANES.indexOf(r.lane) >= 0)
            : snap.rows;
    }
    setScope = (scope) => this.setState({scope});
    toggleBucket = (bk) => this.setState((s) => ({bucket: s.bucket === bk ? null : bk}));
    togglePri = (p) => this.setState((s) => ({pri: s.pri === p ? null : p}));
    onSearch = (e) => this.setState({q: e.target.value});
    onLaneClick = (e) => {
        // delegated click-to-inspect: walk up to the .rowchip carrying data-id (chips are inside the
        // dangerouslySetInnerHTML lane board).
        let el = e.target;
        while (el && el !== e.currentTarget && !(el.getAttribute && el.getAttribute('data-id'))) { el = el.parentNode; }
        const id = el && el.getAttribute && el.getAttribute('data-id');
        if (id) { this.setState({selected: id}); }
    };

    renderDeck(counts, scoped, filtered) {
        return (
            <div className="deck" aria-label="Filter the requirement board" role="group">
                <span className="lbl">state</span>
                {BUCKET_ORDER.map((bk) => {
                    const on = this.state.bucket === bk;
                    return (
                        <button
                            aria-pressed={String(on)} className={'fbtn ' + PB.bucketMeta(bk).cls}
                            key={bk} onClick={() => this.toggleBucket(bk)} type="button"
                        >{DECK_LABEL[bk]} <span className="n">{counts[bk]}</span></button>
                    );
                })}
                <span className="lbl" style={{marginLeft: '8px'}}>priority</span>
                {PRI_ORDER.map((p) => {
                    const on = this.state.pri === p;
                    return (
                        <button
                            aria-pressed={String(on)} className="fbtn"
                            key={p} onClick={() => this.togglePri(p)} type="button"
                        >{p}</button>
                    );
                })}
                <input
                    aria-label="Search requirements" className="psearch"
                    onChange={this.onSearch} placeholder="search id or requirement…"
                    type="search" value={this.state.q}
                />
                <span aria-live="polite" className="results" role="status">
                    {PB.resultsLine(filtered.length, scoped.length)}
                </span>
            </div>
        );
    }

    renderBoard(snap) {
        const scoped = this.scopedRows(snap);
        const counts = PB.countsByBucket(scoped);
        const filtered = PB.applyFilter(scoped, {bucket: this.state.bucket, pri: this.state.pri, q: this.state.q});
        const selectedRow = PB.findRow(snap, this.state.selected);
        return (
            <div>
                <div className="board-card">
                    <h2>Program summary — committed PRD §7</h2>
                    <div dangerouslySetInnerHTML={{__html: PB.summaryHTML(snap, esc)}} />
                </div>
                <div className="board-card">
                    <h2>Mission workflow (ConOps spine)</h2>
                    <div className="spine" dangerouslySetInnerHTML={{__html: PB.spineHTML(snap.workflow_spine, esc)}} />
                </div>
                <div className="board-card">
                    <h2>Program scope</h2>
                    <div className="scope">
                        <button
                            className={'scopebtn' + (this.state.scope === 'gis' ? ' on' : '')}
                            onClick={() => this.setScope('gis')} type="button"
                        >GIS Mission Workbench</button>
                        <button
                            className={'scopebtn' + (this.state.scope === 'all' ? ' on' : '')}
                            onClick={() => this.setScope('all')} type="button"
                        >Full §7 board</button>
                    </div>
                    <div className="scopemeta">
                        In view: <b>{SCOPE_LABEL[this.state.scope]}</b> — <b>{scoped.length}</b> requirements ·{' '}
                        {counts.done} done · {counts.buildable} buildable · {counts.gated} gated · {counts.concurrent} concurrent
                    </div>
                    {this.renderDeck(counts, scoped, filtered)}
                    <div
                        dangerouslySetInnerHTML={{__html: PB.lanesHTML(snap, esc, filtered, this.state.selected)}}
                        onClick={this.onLaneClick}
                    />
                </div>
                <div className="board-card">
                    <h2>Inspect</h2>
                    <div
                        aria-live="polite" dangerouslySetInnerHTML={{__html: PB.rowDetailHTML(selectedRow, esc)}}
                        id="pd-detail"
                    />
                </div>
                <div className="board-card">
                    <h2>By priority (full §7 board)</h2>
                    <div dangerouslySetInnerHTML={{__html: PB.priorityHTML(snap, esc)}} />
                </div>
            </div>
        );
    }

    renderBody = () => {
        const {snap, error} = this.state;
        let inner;
        if (error) {
            inner = <div className="board-card"><span className="err">Could not load the program snapshot: {error}</span></div>;
        } else if (!snap) {
            inner = <div className="board-card"><span className="muted">Loading the committed snapshot…</span></div>;
        } else {
            inner = this.renderBoard(snap);
        }
        return (
            <div className="stewie-program">
                <style>{BOARD_CSS}</style>
                {inner}
            </div>
        );
    };
    render() {
        return (
            <SideBar
                icon="list-alt"
                id="MissionProgram"
                side="left"
                title="Program"
                width="36em"
            >
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

export default connect(() => ({}), {})(MissionProgram);
