/**
 * MissionTerramech — the Analyze ▸ Terramechanics inspector (the council's "surface the backend the frontend
 * discards", increment 1). It binds the PUBLIC /world/terramechanics-layers spine and shows the physics-
 * computation decomposition for the active work site: the authority backend (tier2_numpy) + every derived
 * layer (terrain.slope, physics.bearing/sinkage/slip_risk, ...) with the TERMS it is computed from. Reads the
 * GW-02 shared workspace site + re-loads on a site pick. (The 3 physics-authority tiers + route_terms +
 * runtime rail come next -- those endpoints are auth-gated and need a public projection.)
 */
import React from 'react';
import PropTypes from 'prop-types';
import {connect} from 'react-redux';
import SideBar from 'qwc2/components/SideBar';
import TM from '../mission/terramechClient';   // pure terramechanics-spine bridge (window.STEWIE_TERRAMECH)
import WS from '../mission/workspace.js';        // GW-02: the shared workspace-context store (active site)

class MissionTerramech extends React.Component {
    static propTypes = {
        side: PropTypes.string
    };
    static defaultProps = {
        side: 'right'
    };
    state = {
        model: null,
        authority: null,
        error: null,
        site: WS.site()
    };
    componentDidMount() {
        this.load();
        this._unsubWS = WS.subscribe((s) => { if (s.site !== this.state.site) { this.setState({site: s.site}, this.load); } });
    }
    componentWillUnmount() { if (this._unsubWS) { this._unsubWS(); } }
    load = () => {
        this.setState({model: null, authority: null, error: null});
        const site = this.state.site;   // #57: drop a resolve whose site is no longer active (stale wrong-site race)
        TM.fetchSpine(site)
            .then((d) => { if (WS.site() !== site) { return; } this.setState({model: TM.buildSpineModel(d)}); })
            .catch((e) => { if (WS.site() !== site) { return; } this.setState({error: 'terramechanics: ' + e.message}); });
        // The physics-authority registry is site-independent + supplementary -> degrade silently if it fails.
        TM.fetchAuthority()
            .then((d) => this.setState({authority: TM.buildAuthorityModel(d)}))
            .catch(() => {});
    };
    renderAuthority() {
        const {authority} = this.state;
        if (!authority || !authority.ok) { return null; }
        return (
            <div style={{marginBottom: '0.85em'}}>
                <div style={{color: '#8a9096', textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: '0.72em', marginBottom: '4px'}}>Physics authority · {authority.count} backends</div>
                {authority.backends.map((b) => (
                    <div key={b.id} style={{padding: '3px 0', borderBottom: '1px solid #17171b'}}>
                        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline'}}>
                            <span style={{color: '#e6e8ea', fontWeight: 600}}>{b.id}</span>
                            <span style={{color: b.release ? '#4db6d4' : '#8a9096', fontSize: '0.74em'}}>{b.tier}</span>
                        </div>
                        <div style={{color: '#8a9096', fontSize: '0.73em'}}>
                            {['planning', 'rehearsal', 'release', 'execute'].filter((k) => b[k]).join(' · ') || 'no lifecycle authority'}
                            {b.conserves ? ' · conserves mass' : ''}
                        </div>
                        {b.refusal ? (<div style={{color: '#c98a8a', fontSize: '0.71em'}}>{b.refusal}</div>) : null}
                    </div>
                ))}
            </div>
        );
    }
    renderBody() {
        const {model, error, site} = this.state;
        if (error) {
            return (<div style={{padding: '0.75em', color: '#ff6b6b'}}>{error}</div>);
        }
        if (!model) {
            return (<div style={{padding: '0.75em', color: '#8a9096'}}>{this.renderAuthority()}Loading terramechanics spine…</div>);
        }
        if (!model.ok) {
            return (<div style={{padding: '0.75em', color: '#ff6b6b'}}>{this.renderAuthority()}{model.error}</div>);
        }
        const groups = {};
        model.layers.forEach((l) => { (groups[l.group] = groups[l.group] || []).push(l); });
        return (
            <div style={{padding: '0.75em', fontSize: '0.85em'}}>
                {this.renderAuthority()}
                <div style={{marginBottom: '0.7em'}}>
                    <div style={{color: '#8a9096', textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: '0.72em'}}>Authority backend</div>
                    <div style={{color: '#4db6d4', fontWeight: 700}}>{model.backend || 'unknown'}</div>
                    <div style={{color: '#8a9096', fontSize: '0.76em'}}>{model.count} derived layers on the {site} DEM</div>
                </div>
                {Object.keys(groups).sort().map((g) => (
                    <div key={g} style={{marginBottom: '0.5em'}}>
                        <div style={{color: '#9fd0dc', fontWeight: 600, borderBottom: '1px solid #26262c', paddingBottom: '2px', marginBottom: '3px'}}>{g}</div>
                        {groups[g].map((l) => (
                            <div key={l.layer} style={{padding: '3px 0', borderBottom: '1px solid #17171b'}}>
                                <div style={{color: '#e6e8ea'}}>{l.name}</div>
                                <div style={{color: '#8a9096', fontSize: '0.78em'}}>
                                    from {l.terms.length ? l.terms.join(', ') : '(raw term)'}
                                    {l.computed.length ? ' · computes ' + l.computed.join(', ') : ''}
                                </div>
                            </div>
                        ))}
                    </div>
                ))}
                <div style={{marginTop: '0.6em', color: '#8a9096', fontSize: '0.72em'}}>
                    Physics decomposition from the live /world/terramechanics-layers spine. Click a map cell → the Inspector shows the per-cell term values.
                </div>
            </div>
        );
    }
    render() {
        return (
            <SideBar
                icon="measure"
                id="MissionTerramech"
                side={this.props.side}
                title="Terramechanics"
                width="24em"
            >
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

export default connect(() => ({}), {})(MissionTerramech);
