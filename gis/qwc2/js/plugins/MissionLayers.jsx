/**
 * MissionLayers — the STEWIE mission LAYER CATALOG bound into the lunar IDE's layer panel
 * (artemis.stewie.space/ide/). Design T6 (design/STEWIE_LUNAR_PLATFORM_DESIGN_2026-07-06.md §D).
 *
 * REBIND, not rewrite: it fetches the backend's own 65-row semantic catalog (/api/world/layer-catalog),
 * groups it by `domain` (terrain/hazard/physics/traffic/mission/design/...) with the pure module
 * js/mission/catalogLayers.js (which follows contents_tree.js's group-by semantics), and shows one
 * grouped, collapsible, toggleable tree with per-row PROVENANCE (source_class) + planning/release
 * eligibility carried straight from the catalog. Toggling a SERVABLE row adds/removes a real QWC2
 * `image` layer (the /api/layers/globe/{kind}.png drape, declared in IAU_2015:30100 so OpenLayers
 * reprojects it onto the 30135 map) — so the raster RENDERS on the map AND appears as a toggleable
 * row in the stock QWC2 LayerTree. The base .qgz theme layers + MissionHUD are untouched.
 *
 * Honesty: only the 16 backend globe kinds (dem/slope/hazard/illumination/incidence/psr/grid + the
 * costmap cost/blocking analysis drapes + the six T12 PHYSICS (TM) terramechanics-spine drapes
 * bearing/sinkage/slip_risk/traction_margin/energy_cost/excavation_resistance + the TW-11 traffic
 * traversal-compaction drape) are servable; every other catalog row is shown WITHOUT a map layer (no raster
 * endpoint on the live backend — physics.compaction re-labels the SAME TrafficMemory Dr under the Physics
 * group, so it is not doubled) and the panel says so rather than fabricating a layer. (cost + blocking + the
 * 6 physics drapes added 2026-07-06; the traffic drape added 2026-07-07; live after a backend rebuild.)
 *
 * Registration:
 *   - js/appConfig.js       -> pluginsDef.plugins.MissionLayersPlugin
 *   - static/config.json    -> plugins.common [{"name": "MissionLayers"}] + a TopBar menu item
 *                              {"key": "MissionLayers", "title": "Mission Layers", "icon": "layers"}
 */
import React from 'react';

import PropTypes from 'prop-types';
import {connect} from 'react-redux';

import {addLayer, removeLayer} from 'qwc2/actions/layers';
import SideBar from 'qwc2/components/SideBar';

import CL from '../mission/catalogLayers';   // pure catalog->layer bridge (window.STEWIE_CATALOG_LAYERS)

const SITE = 'haworth';   // the theme's authoritative site; the globe drape + bbox follow it (T6 default)

// provenance accent per coarse source_class token (badge colour only).
const PROV_COLOR = {
    live: '#39ff14', sim: '#8a5cff', replay: '#8a5cff', observed: '#4fd1ff', reconciled: '#4fd1ff',
    measured: '#4fd1ff', released: '#39c6ff', derived: '#e0b300', estimated: '#e0b300',
    learned: '#e0b300', belief: '#ff9d3c', forecast: '#c58cff', user: '#c7d2e3', prior: '#7a8290'
};

// [REQ:GW-03] per-layer UNCERTAINTY accent: the source_class-implied confidence TIER colour (high = measured/
// trustworthy cyan, medium = computed amber, low = predicted orange, n/a = muted). Distinct from the
// provenance badge so a reader sees both "where it came from" and "how much to trust it".
const TIER_COLOR = {high: '#4fd1ff', medium: '#e0b300', low: '#ff9d3c', 'n/a': '#7a8290', unknown: '#7a8290'};

class MissionLayers extends React.Component {
    static propTypes = {
        addLayer: PropTypes.func,
        /** All map layers (from the QWC2 store) — used to reflect which mission rasters are active. */
        layers: PropTypes.array,
        removeLayer: PropTypes.func,
        /** The side of the application on which to display the sidebar. */
        side: PropTypes.string
    };
    static defaultProps = {
        side: 'left',
        layers: []
    };
    state = {
        tree: null,        // grouped catalog tree (CL.groupCatalog)
        legend: null,      // /layers/legend payload
        terramech: null,   // /world/terramechanics-layers (physics-layer provenance)
        freshness: null,   // [REQ:GW-06] /world/layer-manifest -> per-layer freshness/provenance
        summary: null,     // {total, servable, nonServable}
        error: null,
        collapsed: {}      // domainId -> true (default: base/terrain/hazard/physics/traffic expanded)
    };
    constructor(props) {
        super(props);
        this.bbox = null;          // shared geographic bbox (selenographic degrees) — site-scoped, fetched once
        this.bboxPending = null;   // in-flight bbox promise (de-dupes concurrent toggles)
    }
    componentDidMount() {
        // Fetch the catalog + legend + physics-layer provenance + traffic state. The catalog drives the
        // whole tree; the rest annotate it. Failures are surfaced honestly (no silent empty panel).
        CL.fetchCatalog().then((cat) => {
            const tree = CL.groupCatalog(cat);
            this.setState({tree, summary: CL.servableSummary(tree)});
        }).catch((e) => this.setState({error: 'layer-catalog: ' + e.message}));
        CL.fetchLegend().then((legend) => this.setState({legend})).catch(() => {});
        CL.fetchTerramechanics().then((tm) => this.setState({terramech: tm})).catch(() => {});
        // [REQ:GW-06] the REAL per-site freshness/provenance (DT-05 observed-twin coverage + dem_source
        // provenance) for the layer tree, from the PUBLIC /world/layer-manifest projection (the auth-gated
        // /world 401s for the keyless public /ide/). Failures degrade SILENTLY to "no freshness yet" — the
        // catalog tree still renders — so a backend that predates this route never reds the panel.
        CL.fetchLayerManifest(SITE)
            .then((m) => this.setState({freshness: CL.freshnessFromManifest(m)}))
            .catch(() => {});
        // NOTE: /world/traffic-layer (the auth-gated absolute-Dr + bearing-uplift readout) is deliberately
        // NOT probed here — the traffic map layer is the PUBLIC /layers/globe/traffic.png drape (TW-11),
        // bound like every other globe kind from the catalog's SERVABLE map (traffic.compaction -> traffic).
        // Servability is known statically from the catalog, so no network probe is needed.
    }
    layerId(row) { return 'stewie-mission:' + row.id; }
    isActive(row) {
        const id = this.layerId(row);
        return (this.props.layers || []).some((l) => l.id === id);
    }
    ensureBbox() {
        // The geographic bbox is the same for every globe kind of a site, so fetch it once and reuse.
        if (this.bbox) return Promise.resolve(this.bbox);
        if (this.bboxPending) return this.bboxPending;
        this.bboxPending = CL.fetchBbox('dem', {site: SITE}).then((bb) => {
            if (!bb || bb.ok === false) throw new Error(bb && bb.error ? bb.error : 'bbox unavailable');
            this.bbox = bb;
            this.bboxPending = null;
            return bb;
        }).catch((e) => { this.bboxPending = null; throw e; });
        return this.bboxPending;
    }
    toggle = (row) => {
        if (!row.servable) return;
        const id = this.layerId(row);
        if (this.isActive(row)) {
            this.props.removeLayer(id);
            return;
        }
        this.ensureBbox().then((bb) => {
            const layer = CL.imageLayerFor(row, bb, {site: SITE});
            if (layer) this.props.addLayer(layer);
        }).catch((e) => this.setState({error: row.id + ': ' + e.message}));
    };
    toggleGroup = (gid) => {
        this.setState((s) => ({collapsed: {...s.collapsed, [gid]: !s.collapsed[gid]}}));
    };
    isGroupOpen(gid) {
        if (gid in this.state.collapsed) return !this.state.collapsed[gid];
        return ['base', 'terrain', 'hazard', 'physics', 'traffic'].includes(gid);   // operational groups open by default
    }
    renderChips(row) {
        const chip = (txt, on, onColor) => (
            <span key={txt} style={{
                fontSize: '8px', letterSpacing: '.03em', padding: '0 3px', borderRadius: '3px',
                border: '1px solid ' + (on ? onColor : '#2a2a36'),
                color: on ? onColor : '#565b66', background: on ? onColor + '22' : 'transparent'
            }}>{txt}</span>
        );
        // [REQ:GW-03] eligibility DIFFERENTIATION, made explicit as display / planning / release-execute.
        // `disp` is always lit (every catalog layer is display-eligible — it renders in the tree); a
        // DISPLAY-ONLY layer therefore shows only `disp` lit while a planning layer lights `plan` too and a
        // releasable one lights `rel` — so a display-only row is visibly distinct from a planning-eligible one.
        return (
            <span style={{display: 'inline-flex', gap: '3px', flex: '0 0 auto'}}>
                {chip('disp', true, '#8a93a3')}
                {chip('plan', row.planningEligible, '#39c6ff')}
                {chip('rel', row.releaseEligible, '#39ff14')}
            </span>
        );
    }
    // [REQ:GW-03] the per-layer UNCERTAINTY readout: the source_class-implied confidence class + tier, carried
    // on every catalog row (from the backend `confidence`, else derived locally from the same real source_class
    // — never a fabricated number). For a CONDITIONAL layer (a live-measurement token over a prior/derived
    // baseline, e.g. a `prior/observed` DEM) the high tier only holds once the site is freshly observed, so
    // when the site's real freshness is prior/unobserved we show the honest DOWNGRADED baseline confidence
    // (prior -> reference, forecast -> predicted) rather than overstating it as measured.
    renderConfidence(row) {
        let c = row.confidence;
        if (!c || !c.cls) return null;
        const f = this.state.freshness;
        const notFresh = !f || f.provClass !== 'observed';
        const downgraded = !!c.conditional && notFresh;
        if (downgraded) c = CL.confidenceBaseline(c.basis || row.sourceClass);
        const col = TIER_COLOR[c.tier] || '#7a8290';
        const title = 'confidence (source_class-implied uncertainty): ' + c.cls + ' / ' + c.tier
            + ' · basis ' + (c.basis || row.sourceClass || 'n/a')
            + (row.confidence.conditional
                ? ' · measured-grade only when freshly observed'
                    + (downgraded ? ' — this site is prior/unobserved, so shown as its baseline' : '')
                : '');
        return (
            <span style={{
                fontSize: '8px', letterSpacing: '.02em', padding: '0 3px', borderRadius: '3px',
                border: '1px solid ' + col + '55', color: col, flex: '0 0 auto', whiteSpace: 'nowrap',
                display: 'inline-flex', alignItems: 'center', gap: '2px'
            }} title={title}>
                <span aria-hidden>◈</span>{c.cls}{downgraded ? '~' : ''}
            </span>
        );
    }
    renderLegend(row) {
        if (!row.servable) return null;
        const entry = CL.legendFor(row, this.state.legend);
        if (!entry) return null;
        const txt = entry.text || entry.ramp || entry.sweep || entry.sun || '';
        // categorical layers (the blocking-reason grid) enumerate reason -> hex colour: render swatches
        const reasons = Array.isArray(entry.reasons) ? entry.reasons : null;
        // the TW-11 traffic drape enumerates a SEQUENTIAL Dr ramp band -> hex colour (loose -> paved): swatches
        const bands = Array.isArray(entry.bands) ? entry.bands : null;
        if (!txt && !reasons && !bands) return null;
        return (
            <div style={{margin: '1px 0 4px 26px', fontSize: '9px', color: '#8a93a3', lineHeight: 1.35}}>
                {txt}
                {reasons ? (
                    <div style={{display: 'flex', flexWrap: 'wrap', gap: '3px 8px', marginTop: '3px'}}>
                        {reasons.map((r) => (
                            <span key={r.reason} style={{display: 'inline-flex', alignItems: 'center', gap: '3px'}}>
                                <span style={{width: '9px', height: '9px', borderRadius: '2px', flex: '0 0 auto',
                                    background: r.hex, border: '1px solid #00000066'}} />
                                {String(r.reason).replace(/_/g, ' ')}
                            </span>
                        ))}
                    </div>
                ) : null}
                {bands ? (
                    <div style={{display: 'flex', flexWrap: 'wrap', gap: '3px 8px', marginTop: '3px'}}>
                        {bands.map((band) => (
                            <span key={band.dr} style={{display: 'inline-flex', alignItems: 'center', gap: '3px'}}
                                title={'Dr ' + band.dr + ' — ' + (band.label || '')}>
                                <span style={{width: '9px', height: '9px', borderRadius: '2px', flex: '0 0 auto',
                                    background: band.hex, border: '1px solid #ffffff33'}} />
                                {band.dr}
                            </span>
                        ))}
                    </div>
                ) : null}
            </div>
        );
    }
    // [REQ:GW-06] the REAL freshness + provenance readout for a servable row, from the per-site
    // /world/layer-manifest (DT-05 enrichment). Every servable globe layer is derived from the same site
    // DEM at the same observed-twin coverage, so the freshness (observed coverage) + provenance (dem_source
    // id + observed|prior class) are the shared, honest state of that DEM-derived layer — not a fabricated
    // per-layer timestamp. Returns null (renders nothing) when the manifest is unavailable, so the panel
    // degrades gracefully rather than inventing a freshness.
    renderFreshness(row) {
        if (!row.servable) return null;
        const f = this.state.freshness;
        if (!f) return null;
        const fresh = f.provClass === 'observed';
        const col = fresh ? '#4fd1ff' : '#6f7684';          // observed = cyan (measured); prior = muted
        const pct = (typeof f.observedPct !== 'number') ? null : f.observedPct + '% obs';
        return (
            <div style={{margin: '0 0 3px 26px', fontSize: '8px', color: '#6f7684', display: 'flex',
                alignItems: 'center', flexWrap: 'wrap', gap: '4px', lineHeight: 1.3}}
            title={'freshness: ' + (fresh ? 'observed twin' : 'prior DEM, no fresh observation')
                + (pct ? ' (' + pct + ' of the site observed)' : '') + ' · provenance (dem_sources): '
                + (f.demSource || 'n/a')}>
                <span aria-hidden style={{color: col}}>◷</span>
                <span style={{color: col, letterSpacing: '.02em'}}>{f.provClass}</span>
                {pct ? <span style={{color: '#565b66'}}>· {pct}</span> : null}
                {f.demSource ? (
                    <span style={{color: '#565b66', fontFamily: 'ui-monospace, monospace'}}>· {f.demSource}</span>
                ) : <span style={{color: '#565b66'}}>· n/a</span>}
                {f.mutated ? <span style={{color: '#ff9d3c'}}>· built v{f.asBuiltVersion}</span> : null}
            </div>
        );
    }
    // The terramechanics-spine terms a derived layer is COMPUTED FROM (/world/terramechanics-layers),
    // shown as real provenance on the physics/terrain/traffic rows that declare it.
    terramechFor(row) {
        const tm = this.state.terramech;
        if (!tm || !tm.derived_layers) return null;
        const d = tm.derived_layers.filter((x) => x.layer === row.id)[0];
        return (d && d.from_terms && d.from_terms.length) ? d.from_terms.join(', ') : null;
    }
    renderRow(row) {
        const active = row.servable && this.isActive(row);
        const provCol = PROV_COLOR[row.provClass] || '#7a8290';
        const rowStyle = {
            display: 'flex', alignItems: 'center', gap: '6px', padding: '3px 0 3px 6px',
            fontSize: '11px', opacity: row.servable ? 1 : 0.55
        };
        return (
            <div key={row.id} data-stewie-row={row.id}>
                <div style={rowStyle} title={row.purpose + ' — ' + row.type + ' · ' + row.sourceClass}>
                    {row.servable ? (
                        <input
                            checked={active}
                            data-stewie-cb={row.id}
                            onChange={() => this.toggle(row)}
                            style={{flex: '0 0 auto', cursor: 'pointer'}}
                            type="checkbox"
                        />
                    ) : (
                        <span style={{flex: '0 0 auto', width: '13px', textAlign: 'center', color: '#565b66'}}>·</span>
                    )}
                    <span style={{flex: '1 1 auto', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                        cursor: row.servable ? 'pointer' : 'default', color: active ? '#e6edf6' : '#c7d2e3'}}
                    onClick={() => this.toggle(row)}>
                        {row.label}
                        <span style={{color: '#565b66', fontSize: '9px'}}> · {row.type}</span>
                    </span>
                    <span style={{
                        fontSize: '8px', letterSpacing: '.02em', padding: '0 3px', borderRadius: '3px',
                        border: '1px solid ' + provCol + '55', color: provCol, flex: '0 0 auto', whiteSpace: 'nowrap'
                    }} title={'provenance (source_class): ' + row.sourceClass}>{row.sourceClass}</span>
                    {this.renderConfidence(row)}
                    {this.renderChips(row)}
                </div>
                {this.renderFreshness(row)}
                {active ? this.renderLegend(row) : null}
                {(() => {
                    const terms = this.terramechFor(row);
                    return terms ? (
                        <div style={{margin: '0 0 3px 26px', fontSize: '8px', color: '#6f7684'}}>
                            from terramechanics: {terms}
                        </div>
                    ) : null;
                })()}
            </div>
        );
    }
    renderGroup(group) {
        const nServ = group.rows.filter((r) => r.servable).length;
        const open = this.isGroupOpen(group.id);
        return (
            <div key={group.id} style={{borderTop: '1px solid #1c1c26'}}>
                <div
                    onClick={() => this.toggleGroup(group.id)}
                    style={{display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer',
                        padding: '5px 2px', fontWeight: 600, fontSize: '11px', color: '#aeb8c6', userSelect: 'none'}}
                >
                    <span style={{width: '10px', color: '#7a8290'}}>{open ? '▾' : '▸'}</span>
                    <span style={{flex: '1 1 auto'}}>{group.name}</span>
                    <span style={{fontSize: '9px', color: nServ ? '#39ff14' : '#565b66'}}>
                        {nServ}/{group.rows.length} raster
                    </span>
                </div>
                {open ? group.rows.map((r) => this.renderRow(r)) : null}
            </div>
        );
    }
    renderBody = () => {
        const wrapStyle = {
            background: '#0a0a0c', color: '#c7d2e3', padding: '8px',
            font: '11px system-ui, sans-serif', '--txt': '#c7d2e3', '--line': '#2a2a36'
        };
        const s = this.state;
        // The Traffic group's compaction/cost/traversability rows drape as globe rasters (TW-11 traffic +
        // AS-11 cost/blocking); the remaining traffic.* rows (cost_local/backlink) have no raster endpoint.
        // If a backend ever serves NONE of them, report the gap from the grouped tree rather than faking one.
        const trafficGroup = (s.tree || []).filter((g) => g.id === 'traffic')[0];
        const trafficNote = trafficGroup && trafficGroup.rows.every((r) => !r.servable)
            ? 'traffic.* (TW-11): ' + trafficGroup.rows.length + ' catalog rows, 0 served as rasters on this '
              + 'backend — shown, not rendered.'
            : null;
        return (
            <div style={wrapStyle}>
                <div style={{fontSize: '10px', color: '#8a93a3', marginBottom: '6px', lineHeight: 1.4}}>
                    STEWIE mission layer catalog · <b>/api/world/layer-catalog</b>. Grouped by domain;
                    badge = provenance (source_class); <b>◈ pill = confidence</b> (source_class-implied
                    per-layer uncertainty: measured / derived / reference / predicted); chips =
                    <b> disp / plan / rel</b> eligibility (a display-only layer lights only <b>disp</b>).
                    Checked rows drape the backend raster onto the map (reprojected to the lunar CRS).
                    Under each servable row: <b>◷ freshness</b> — the real observed-twin coverage of this
                    site + dem_sources provenance (<b>/api/world/layer-manifest</b>, DT-05).
                </div>
                {s.summary ? (
                    <div style={{fontSize: '10px', color: '#c7d2e3', marginBottom: '6px'}}>
                        <b style={{color: '#39ff14'}}>{s.summary.servable}</b> of {s.summary.total} catalog
                        layers are servable as map rasters (16 backend globe kinds); the rest are catalog-only.
                    </div>
                ) : null}
                {s.error ? (
                    <div style={{fontSize: '10px', color: '#e0564b', marginBottom: '6px'}}>error: {s.error}</div>
                ) : null}
                {s.tree ? s.tree.map((g) => this.renderGroup(g)) : (
                    <div style={{fontSize: '11px', color: '#7a8290', padding: '8px 0'}}>loading catalog…</div>
                )}
                {trafficNote ? (
                    <div style={{marginTop: '10px', fontSize: '9px', color: '#ff9d3c', borderTop: '1px solid #1c1c26', paddingTop: '6px'}}>
                        {trafficNote}
                    </div>
                ) : null}
            </div>
        );
    };
    render() {
        return (
            <SideBar
                icon="layers"
                id="MissionLayers"
                side={this.props.side}
                title="Mission Layers"
                width="26em"
            >
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

export default connect((state) => ({
    layers: state.layers.flat
}), {
    addLayer: addLayer,
    removeLayer: removeLayer
})(MissionLayers);
