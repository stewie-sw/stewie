/**
 * MissionEvidence — the STEWIE EVIDENCE / REPORT view bound into the lunar IDE ([REQ:EV-01],
 * artemis.stewie.space/ide/). One read-only bundle that REPRODUCES what a mission ran on.
 *
 * REBIND, not invent: it fetches the backend's own evidence bundle (/api/evidence/bundle — a PUBLIC
 * map-data read like /world/layer-catalog), normalizes it with the pure module js/mission/evidenceReport.js,
 * and shows, for a site (+ optional mission), the FIVE persisted axes the EV-01 acceptance requires —
 * plan inputs, selected layers, runtime profile, world transactions, audit trail — each reproduced from a
 * durable source, plus the host-gated ROS/Gazebo/RViz/Godot run captures shown HONESTLY as "not captured".
 *
 * Honesty: the panel shows only what the backend genuinely persists (an empty world log / empty audit ->
 * honest empties, no placeholder), and a host-gated capture renders as "not captured" with its reason,
 * never a fabricated artifact. The single bundle_sha attests the assembly.
 *
 * Registration:
 *   - js/appConfig.js    -> pluginsDef.plugins.MissionEvidencePlugin
 *   - static/config.json -> plugins.common [{"name": "MissionEvidence"}] + a TopBar menu item
 *                           {"key": "MissionEvidence", "title": "Evidence / Report", "icon": "info"}
 */
import React from 'react';

import PropTypes from 'prop-types';
import {connect} from 'react-redux';

import SideBar from 'qwc2/components/SideBar';

import EV from '../mission/evidenceReport';   // pure evidence-bundle bridge (window.STEWIE_EVIDENCE_REPORT)

const C = {
    bg: '#0a0a0c', panel: '#0d0f15', line: '#1c1c26', card: '#12151d', border: '#2a2a36',
    text: '#c7d2e3', dim: '#8a93a3', mute: '#6f7684', cyan: '#39c6ff', ok: '#39ff14',
    warn: '#e0b300', bad: '#e0564b', amber: '#e0b300'
};

class MissionEvidence extends React.Component {
    static propTypes = {
        /** The side of the application on which to display the sidebar. */
        side: PropTypes.string
    };
    static defaultProps = {
        side: 'right'
    };
    state = {
        model: null,      // normalized view model from EV.buildModel
        error: null,
        site: 'haworth',
        collapsed: {}      // sectionId -> true
    };
    componentDidMount() { this.load(); }
    load = () => {
        this.setState({model: null, error: null});
        EV.fetchBundle({site: this.state.site}).then((d) => {
            this.setState({model: EV.buildModel(d)});
        }).catch((e) => this.setState({error: 'evidence: ' + e.message}));
    };
    toggle = (id) => { this.setState((s) => ({collapsed: {...s.collapsed, [id]: !s.collapsed[id]}})); };
    isOpen(id, dflt) {
        if (id in this.state.collapsed) return !this.state.collapsed[id];
        return dflt !== false;
    }
    renderAxes(m) {
        return (
            <div data-stewie-ev-axes style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px', marginBottom: '8px'}}>
                {m.axes.map((a) => (
                    <div key={a.key} data-stewie-ev-axis={a.key}
                        style={{padding: '5px 7px', background: C.card, border: '1px solid ' + C.border,
                            borderLeft: '3px solid ' + (a.reproduced ? C.ok : C.bad), borderRadius: '4px'}}>
                        <div style={{display: 'flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: C.text}}>
                            <span style={{color: C.mute}}>{a.glyph}</span>
                            <span style={{flex: '1 1 auto', fontWeight: 600}}>{a.label}</span>
                            <span style={{fontSize: '9px', color: a.reproduced ? C.ok : C.bad}}
                                title={a.reproduced ? 'reproduced from a persisted source' : 'not reproduced'}>
                                {a.reproduced ? '✓ reproduced' : '✗'}
                            </span>
                        </div>
                        <div style={{fontSize: '9px', color: C.dim, marginTop: '2px'}}>{a.summary}</div>
                    </div>
                ))}
            </div>
        );
    }
    section(id, label, count, body, dflt) {
        const open = this.isOpen(id, dflt);
        return (
            <div key={id} data-stewie-ev-section={id} style={{borderTop: '1px solid ' + C.line}}>
                <div onClick={() => this.toggle(id)}
                    style={{display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer',
                        padding: '5px 2px', fontWeight: 600, fontSize: '11px', color: '#aeb8c6', userSelect: 'none'}}>
                    <span style={{width: '10px', color: C.mute}}>{open ? '▾' : '▸'}</span>
                    <span style={{flex: '1 1 auto'}}>{label}</span>
                    <span style={{fontSize: '9px', color: C.cyan}}>{count}</span>
                </div>
                {open ? <div style={{margin: '0 0 6px 4px'}}>{body}</div> : null}
            </div>
        );
    }
    kv(rows) {
        return rows.map((r, i) => (
            <div key={i} style={{fontSize: '9px', color: C.dim, lineHeight: 1.5, padding: '1px 0',
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}} title={r.title || ''}>
                {r.cells}
            </div>
        ));
    }
    renderBody = () => {
        const s = this.state;
        const wrap = {background: C.bg, color: C.text, padding: '8px', font: '11px system-ui, sans-serif'};
        if (s.error) return <div style={wrap}><div style={{color: C.bad, fontSize: '10px'}}>error: {s.error}</div></div>;
        if (!s.model) return <div style={wrap}><div style={{color: C.mute}}>loading evidence…</div></div>;
        const m = s.model;
        return (
            <div style={wrap}>
                <div style={{fontSize: '10px', color: C.dim, marginBottom: '6px', lineHeight: 1.4}}>
                    STEWIE evidence/report · <b>/api/evidence/bundle</b>. One read-only bundle that reproduces
                    what a mission ran on — plan inputs, selected layers, runtime profile, world transactions,
                    and audit — from durable sources. ROS/Gazebo/RViz/Godot run captures are host-gated and
                    shown honestly as <b>not captured</b>.
                </div>
                <div style={{display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '8px'}}>
                    <span style={{fontSize: '10px', color: C.mute}}>site {m.site}</span>
                    {m.mission ? <span style={{fontSize: '10px', color: C.mute}}>· mission {m.mission}</span> : null}
                    <span style={{flex: '1 1 auto'}} />
                    <span data-stewie-ev-sha title="bundle_sha (attests the assembly)"
                        style={{fontSize: '9px', color: C.cyan, fontFamily: 'monospace'}}>
                        sha {EV.shortSha(m.bundleSha)}
                    </span>
                </div>

                {this.renderAxes(m)}

                {this.section('plan', 'Plan inputs', m.planTxns.length + ' tx · ' + m.reports.length + ' reports',
                    <div>
                        {this.kv(m.planTxns.map((t) => ({title: t.provenance,
                            cells: <span><span style={{color: C.cyan}}>#{t.seq}</span> plan <span style={{fontFamily: 'monospace'}}>{t.planId}</span> · {t.mission}</span>})))}
                        {m.reports.map((r) => (
                            <div key={r.stem} style={{fontSize: '9px', padding: '1px 0'}}>
                                <a href={EV.base().replace('/api', '') + r.pdf} target="_blank" rel="noreferrer"
                                    style={{color: C.cyan}}>▦ {r.stem}.pdf</a>
                                <span style={{color: C.mute}}> · {r.size} · {r.when}</span>
                            </div>
                        ))}
                        {(!m.planTxns.length && !m.reports.length) ?
                            <div style={{fontSize: '10px', color: C.mute}}>no plan persisted yet.</div> : null}
                    </div>)}

                {this.section('layers', 'Selected layers', m.layers.length,
                    <div>
                        {m.freshness ? (
                            <div data-stewie-ev-freshness style={{fontSize: '9px', color: C.dim, marginBottom: '3px'}}>
                                freshness: <span style={{color: m.freshness.provenance_class === 'observed' ? C.ok : C.amber}}>
                                    {m.freshness.provenance_class}</span> · {Math.round((m.freshness.observed_fraction || 0) * 100)}% observed
                                · dem <span style={{fontFamily: 'monospace'}}>{m.freshness.dem_source}</span>
                                {m.freshness.mutated ? ' · mutated' : ''}
                            </div>
                        ) : null}
                        {this.kv(m.layers.map((l) => ({title: l.sourceClass,
                            cells: <span>{l.id} <span style={{color: C.mute}}>({l.domain})</span> · <span style={{color: l.tier === 'high' ? C.ok : (l.tier === 'low' ? C.bad : C.amber)}}>{l.confidence}/{l.tier}</span>{l.releaseExecute ? ' · rel/exec' : ''}</span>})))}
                    </div>)}

                {this.section('profile', 'Runtime profile (RT-01)', m.profiles.length,
                    this.kv(m.profiles.map((p) => ({
                        cells: <span style={{color: p.active ? C.text : C.dim}}>{p.active ? '▶ ' : ''}<b>{p.id}</b> · {p.evidence} · cmd {p.command}{(p.canRelease || p.canExecute) ? ' · release/exec' : ' · no live cmd'}</span>}))))}

                {this.section('world', 'World transactions (DT-03)', m.worldTxns.length,
                    this.kv(m.worldTxns.map((t) => ({title: t.provenance,
                        cells: <span><span style={{color: C.cyan}}>#{t.seq}</span> <span style={{fontFamily: 'monospace'}}>{t.worldSha}</span> · {t.provenance}</span>}))))}

                {this.section('audit', 'Audit trail (EG-07)', m.audit.length,
                    <div>
                        {this.kv(m.audit.map((r) => ({title: r.evidence,
                            cells: <span style={{color: C.dim}}><b style={{color: C.text}}>{r.action}</b> · {r.mode} · {r.before}→<span style={{color: r.after === 'completed' ? C.ok : C.amber}}>{r.after}</span> · {r.when}</span>})))}
                        {m.editSession ? (
                            <div style={{fontSize: '9px', color: C.mute, marginTop: '3px'}}>
                                edit-session {m.editSession.found ?
                                    ('v' + m.editSession.version + ' · ' + (m.editSession.audit || []).length + ' edits') :
                                    'not found (honest)'}
                            </div>
                        ) : null}
                    </div>)}

                {this.section('captures', 'Run captures (host-gated)', m.captures.length, this.renderCaptures(m))}
            </div>
        );
    };
    renderCaptures(m) {
        const ros = m.rosEvidence || {};
        return (
            <div>
                <div style={{fontSize: '9px', color: C.dim, marginBottom: '3px'}}>
                    committed-config evidence: {(ros.lifecycle_nodes || []).length} lifecycle nodes ·
                    {' '}{(ros.gazebo_worlds || []).length} Gazebo worlds ·
                    {' '}{(ros.rviz_displays || []).length} RViz displays
                </div>
                {m.captures.map((cap) => (
                    <div key={cap.kind} data-stewie-ev-capture={cap.kind}
                        style={{fontSize: '9px', padding: '2px 0', display: 'flex', gap: '6px', alignItems: 'baseline'}}>
                        <span style={{color: cap.captured ? C.ok : C.warn, flex: '0 0 auto'}}>
                            {cap.captured ? '● captured' : '○ not captured'}
                        </span>
                        <span style={{color: C.dim, flex: '1 1 auto', whiteSpace: 'nowrap', overflow: 'hidden',
                            textOverflow: 'ellipsis'}} title={cap.reason}>
                            <b style={{color: C.text}}>{cap.kind}</b> — {cap.captured ? (cap.count + ' file(s)') : cap.reason}
                        </span>
                    </div>
                ))}
            </div>
        );
    }
    render() {
        return (
            <SideBar
                icon="info"
                id="MissionEvidence"
                side={this.props.side}
                title="Evidence / Report"
                width="30em"
            >
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

export default connect(() => ({}), {})(MissionEvidence);
