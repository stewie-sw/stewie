/**
 * MissionAssets — the STEWIE Asset Library bound into the lunar IDE ([REQ:GW-04],
 * artemis.stewie.space/ide/). A durable-asset REGISTRY, SEPARATE from the visible map layers.
 *
 * REBIND, not invent: it fetches the backend's own durable-asset manifest (/api/library — a PUBLIC
 * map-data read like /world/layer-catalog), groups it by type with the pure module
 * js/mission/assetLibrary.js, and shows one grouped, collapsible, SEARCHABLE tree of missions /
 * structure templates / reports / terrain-memory / observed-twin journals / DEM bundles, each row
 * carrying its PROVENANCE + created + size. Selecting a row INSPECTS it (the manifest record +
 * provenance, never the sensitive payload); the row also EXPORTS the asset descriptor (JSON) and links
 * the auth-gated payload (report PDF / mission orders) + the RECOVER route for a recoverable asset.
 *
 * Honesty: the panel shows only what the backend genuinely persists (an empty store -> an empty
 * library, no placeholder). The sensitive payload (mission orders, report bytes) is auth-gated, so on
 * the keyless public /ide/ the panel browses the manifest + provenance and links the gated payload
 * rather than inlining it.
 *
 * Registration:
 *   - js/appConfig.js    -> pluginsDef.plugins.MissionAssetsPlugin
 *   - static/config.json -> plugins.common [{"name": "MissionAssets"}] + a TopBar menu item
 *                           {"key": "MissionAssets", "title": "Asset Library", "icon": "folder"}
 */
import React from 'react';

import PropTypes from 'prop-types';
import {connect} from 'react-redux';

import SideBar from 'qwc2/components/SideBar';

import AL from '../mission/assetLibrary';   // pure asset-library bridge (window.STEWIE_ASSET_LIBRARY)

// provenance/namespace accent (badge colour only).
const NS_COLOR = {
    live: '#39c6ff', world: '#4fd1ff', derived: '#e0b300', prior: '#7a8290', sandbox: '#c58cff'
};

class MissionAssets extends React.Component {
    static propTypes = {
        /** The side of the application on which to display the sidebar. */
        side: PropTypes.string
    };
    static defaultProps = {
        side: 'left'
    };
    state = {
        assets: null,      // full loaded manifest (array)
        counts: null,      // {type -> n}
        error: null,
        q: '',             // client-side search box
        collapsed: {},     // typeId -> true
        selected: null,    // the inspected asset record
        selKey: null       // "type/id" of the inspected row
    };
    componentDidMount() {
        AL.fetchLibrary().then((d) => {
            const assets = (d && d.assets) || [];
            this.setState({assets, counts: AL.counts(assets)});
        }).catch((e) => this.setState({error: 'library: ' + e.message}));
    }
    onSearch = (ev) => { this.setState({q: ev.target.value}); };
    toggleGroup = (gid) => {
        this.setState((s) => ({collapsed: {...s.collapsed, [gid]: !s.collapsed[gid]}}));
    };
    isGroupOpen(gid) {
        if (gid in this.state.collapsed) return !this.state.collapsed[gid];
        return true;   // sections open by default
    }
    select = (a) => {
        const key = a.type + '/' + a.id;
        if (this.state.selKey === key) { this.setState({selected: null, selKey: null}); return; }
        // show the loaded record immediately, then refine with the inspect endpoint's detail
        this.setState({selected: a, selKey: key});
        AL.fetchAsset(a.type, a.id).then((d) => {
            if (this.state.selKey === key && d && d.asset) this.setState({selected: d.asset});
        }).catch(() => {});
    };
    exportAsset = (a, ev) => {
        if (ev) { ev.preventDefault(); ev.stopPropagation(); }
        const url = AL.exportUrl(a.type, a.id);
        if (typeof window !== 'undefined') window.open(url, '_blank');
    };
    renderRow(a) {
        const key = a.type + '/' + a.id;
        const active = this.state.selKey === key;
        const nsCol = NS_COLOR[a.namespace] || '#7a8290';
        return (
            <div key={key} data-stewie-asset={key}>
                <div
                    onClick={() => this.select(a)}
                    style={{display: 'flex', alignItems: 'center', gap: '6px', padding: '3px 0 3px 8px',
                        fontSize: '11px', cursor: 'pointer', color: active ? '#e6edf6' : '#c7d2e3',
                        background: active ? '#141822' : 'transparent'}}
                    title={a.provenance}
                >
                    <span style={{flex: '1 1 auto', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>
                        {a.title || a.id}
                    </span>
                    <span style={{
                        fontSize: '8px', letterSpacing: '.02em', padding: '0 3px', borderRadius: '3px',
                        border: '1px solid ' + nsCol + '55', color: nsCol, flex: '0 0 auto'
                    }} title={'namespace: ' + a.namespace}>{a.namespace}</span>
                    <span style={{fontSize: '9px', color: '#565b66', flex: '0 0 auto', minWidth: '46px', textAlign: 'right'}}>
                        {AL.humanSize(a.size_bytes)}
                    </span>
                    <button
                        data-stewie-export={key}
                        onClick={(ev) => this.exportAsset(a, ev)}
                        style={{flex: '0 0 auto', fontSize: '9px', color: '#8a93a3', background: 'transparent',
                            border: '1px solid #2a2a36', borderRadius: '3px', cursor: 'pointer', padding: '0 4px'}}
                        title="export the asset descriptor (JSON)"
                    >⤓</button>
                </div>
                {active ? this.renderDetail(a) : null}
            </div>
        );
    }
    renderDetail(a) {
        const d = a.detail || {};
        const lines = Object.keys(d).map((k) => k + ': ' + JSON.stringify(d[k]));
        return (
            <div style={{margin: '1px 0 6px 20px', padding: '5px 8px', fontSize: '9px', color: '#8a93a3',
                lineHeight: 1.5, borderLeft: '2px solid #2a2a36', background: '#0d0f15'}}>
                <div><span style={{color: '#6f7684'}}>provenance:</span> {a.provenance}</div>
                {a.created ? <div><span style={{color: '#6f7684'}}>created:</span> {AL.humanTime(a.created)}</div> : null}
                {lines.length ? <div><span style={{color: '#6f7684'}}>detail:</span> {lines.join(' · ')}</div> : null}
                <div style={{marginTop: '4px', display: 'flex', gap: '10px', flexWrap: 'wrap'}}>
                    <a href={AL.exportUrl(a.type, a.id)} onClick={(ev) => this.exportAsset(a, ev)}
                        style={{color: '#4fd1ff', cursor: 'pointer'}}>⤓ export descriptor</a>
                    {a.payload_href ? (
                        <a href={AL.base() + a.payload_href} target="_blank" rel="noreferrer"
                            style={{color: '#39c6ff'}}>↗ payload (auth-gated)</a>
                    ) : null}
                    {a.recoverable ? (
                        <span style={{color: '#39ff14'}} title={'POST ' + AL.base() + '/library/' + a.type + '/' + a.id
                            + '/recover (operator+, restores a soft-deleted copy)'}>↺ recoverable</span>
                    ) : null}
                </div>
            </div>
        );
    }
    renderGroup(group) {
        const open = this.isGroupOpen(group.id);
        return (
            <div key={group.id} style={{borderTop: '1px solid #1c1c26'}}>
                <div onClick={() => this.toggleGroup(group.id)}
                    style={{display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer',
                        padding: '5px 2px', fontWeight: 600, fontSize: '11px', color: '#aeb8c6', userSelect: 'none'}}>
                    <span style={{width: '10px', color: '#7a8290'}}>{open ? '▾' : '▸'}</span>
                    <span style={{color: '#7a8290'}}>{group.glyph}</span>
                    <span style={{flex: '1 1 auto'}}>{group.label}</span>
                    <span style={{fontSize: '9px', color: '#39c6ff'}}>{group.rows.length}</span>
                </div>
                {open ? group.rows.map((a) => this.renderRow(a)) : null}
            </div>
        );
    }
    renderBody = () => {
        const s = this.state;
        const wrapStyle = {background: '#0a0a0c', color: '#c7d2e3', padding: '8px', font: '11px system-ui, sans-serif'};
        const filtered = AL.filterAssets(s.assets || [], s.q);
        const tree = AL.groupByType(filtered);
        const total = (s.assets || []).length;
        return (
            <div style={wrapStyle}>
                <div style={{fontSize: '10px', color: '#8a93a3', marginBottom: '6px', lineHeight: 1.4}}>
                    STEWIE durable-asset registry · <b>/api/library</b>. Missions, structure templates,
                    reports, terrain memory, observed-twin journals, and DEM bundles — separate from the
                    visible map layers. Each row traces to <b>provenance</b>; select to inspect, <b>⤓</b> to
                    export the descriptor. Sensitive payloads (orders, report bytes) stay auth-gated.
                </div>
                <input
                    data-stewie-asset-search
                    onChange={this.onSearch}
                    placeholder="search assets (id / title / provenance)…"
                    style={{width: '100%', boxSizing: 'border-box', marginBottom: '6px', padding: '4px 6px',
                        fontSize: '11px', color: '#e6edf6', background: '#12151d', border: '1px solid #2a2a36',
                        borderRadius: '4px'}}
                    type="text"
                    value={s.q}
                />
                {s.counts ? (
                    <div style={{fontSize: '10px', color: '#c7d2e3', marginBottom: '6px'}}>
                        <b style={{color: '#39c6ff'}}>{filtered.length}</b>
                        {s.q ? ' of ' + total : ''} durable assets
                        {s.q ? '' : (' · ' + AL.TYPES.filter((t) => s.counts[t.id])
                            .map((t) => s.counts[t.id] + ' ' + t.id).join(' · '))}
                    </div>
                ) : null}
                {s.error ? (
                    <div style={{fontSize: '10px', color: '#e0564b', marginBottom: '6px'}}>error: {s.error}</div>
                ) : null}
                {s.assets ? (
                    tree.length ? tree.map((g) => this.renderGroup(g)) : (
                        <div style={{fontSize: '11px', color: '#7a8290', padding: '8px 0'}}>
                            {s.q ? 'no assets match “' + s.q + '”.' : 'no durable assets persisted yet.'}
                        </div>
                    )
                ) : (
                    <div style={{fontSize: '11px', color: '#7a8290', padding: '8px 0'}}>loading library…</div>
                )}
            </div>
        );
    };
    render() {
        return (
            <SideBar
                icon="folder"
                id="MissionAssets"
                side={this.props.side}
                title="Asset Library"
                width="26em"
            >
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

export default connect(() => ({}), {})(MissionAssets);
