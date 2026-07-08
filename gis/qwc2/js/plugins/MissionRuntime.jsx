/**
 * MissionRuntime — the Runtime Context rail (RT-01, surface-the-backend inc2b). Binds the PUBLIC
 * /runtime/profiles registry and shows the 7 execution environments a mission can run in, each with its
 * command authority (evidence-only / bounded-sim / live-command), release + execute eligibility, and evidence
 * class. Site-independent (fetches once on mount). READ-ONLY: it explains WHAT a profile may do; it never
 * commands anything -- command authority lives behind the auth-gated /rc/* POSTs.
 */
import React from 'react';
import PropTypes from 'prop-types';
import {connect} from 'react-redux';
import SideBar from 'qwc2/components/SideBar';
import RT from '../mission/runtimeClient';   // pure runtime-profile bridge (window.STEWIE_RUNTIME)

const CMD_COLOR = {none: '#8a9096', bounded: '#e6b800', full: '#ff6b6b'};   // none=safe / bounded=caution / full=live-danger

class MissionRuntime extends React.Component {
    static propTypes = {
        side: PropTypes.string
    };
    static defaultProps = {
        side: 'right'
    };
    state = {
        model: null,
        error: null
    };
    componentDidMount() {
        RT.fetchProfiles()
            .then((d) => this.setState({model: RT.buildProfilesModel(d)}))
            .catch((e) => this.setState({error: 'runtime: ' + e.message}));
    }
    renderBody() {
        const {model, error} = this.state;
        if (error) {
            return (<div style={{padding: '0.75em', color: '#ff6b6b'}}>{error}</div>);
        }
        if (!model) {
            return (<div style={{padding: '0.75em', color: '#8a9096'}}>Loading runtime profiles…</div>);
        }
        if (!model.ok) {
            return (<div style={{padding: '0.75em', color: '#ff6b6b'}}>{model.error}</div>);
        }
        return (
            <div style={{padding: '0.75em', fontSize: '0.85em'}}>
                <div style={{color: '#8a9096', textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: '0.72em', marginBottom: '5px'}}>
                    Runtime profiles · {model.count} environments
                </div>
                {model.profiles.map((p) => (
                    <div key={p.id} style={{padding: '4px 0', borderBottom: '1px solid #17171b'}}>
                        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline'}}>
                            <span style={{color: '#e6e8ea', fontWeight: 600}}>{p.id}</span>
                            <span style={{color: (p.release || p.execute) ? '#ff6b6b' : '#8a9096', fontSize: '0.74em'}}>{p.authority}</span>
                        </div>
                        <div style={{color: '#8a9096', fontSize: '0.73em'}}>
                            command: <span style={{color: CMD_COLOR[p.command] || '#8a9096'}}>{p.command}</span>
                            {p.release ? ' · can release' : ''}{p.execute ? ' · can execute' : ''}
                            {p.evidence ? ' · evidence: ' + p.evidence : ''}
                        </div>
                        {p.desc ? (<div style={{color: '#6a6a78', fontSize: '0.71em'}}>{p.desc}</div>) : null}
                    </div>
                ))}
                <div style={{marginTop: '0.6em', color: '#8a9096', fontSize: '0.72em'}}>
                    From the live /runtime/profiles registry (RT-01). Only hil / field_test / live_rover carry live command authority; SIL / twin / replay / sim rehearse + produce evidence but never command the real rover.
                </div>
            </div>
        );
    }
    render() {
        return (
            <SideBar
                icon="cog"
                id="MissionRuntime"
                side={this.props.side}
                title="Runtime Context"
                width="24em"
            >
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

export default connect(() => ({}), {})(MissionRuntime);
