/**
 * MissionUserLayer — the user-layers subsystem (#44, the LY-01 clause). Paste a GeoJSON; STEWIE parses it,
 * CRS-VALIDATES it against the lunar frame (userLayers.validateLayerCrs — rejects an Earth-CRS import, the #40
 * trap), and on success adds it as an OL vector layer reprojected to the map CRS (IAU_2015:30135). The
 * promote-to-planning path (a validated layer -> keep-outs via the ED-01 edit-session) is noted as the next
 * increment. Uses the raw OL map (MapUtils.GET_MAP), like Graticule/SiteZoom.
 */
import React from 'react';
import PropTypes from 'prop-types';
import {connect} from 'react-redux';
import GeoJSON from 'ol/format/GeoJSON';
import VectorLayer from 'ol/layer/Vector';
import VectorSource from 'ol/source/Vector';
import CircleStyle from 'ol/style/Circle';
import Fill from 'ol/style/Fill';
import Stroke from 'ol/style/Stroke';
import Style from 'ol/style/Style';
import SideBar from 'qwc2/components/SideBar';
import MapUtils from 'qwc2/utils/MapUtils';
import UL from '../mission/userLayers';

const BTN = {border: '1px solid #26262c', borderRadius: '3px', padding: '5px 8px', cursor: 'pointer', fontSize: '0.85em'};

class MissionUserLayer extends React.Component {
    static propTypes = {
        side: PropTypes.string
    };
    static defaultProps = {
        side: 'right'
    };
    state = {
        text: '',
        status: null
    };
    _layers = [];

    onAdd = () => {
        const p = UL.parseUserLayer(this.state.text);
        if (!p.ok) { this.setState({status: {ok: false, msg: p.error}}); return; }
        const v = UL.validateLayerCrs(p.geojson);
        if (!v.ok) { this.setState({status: {ok: false, msg: v.warning, crs: v.crs}}); return; }
        const map = MapUtils.getHook(MapUtils.GET_MAP);
        if (!map) { this.setState({status: {ok: false, msg: 'map not ready'}}); return; }
        const dataProj = (v.crs && v.crs.indexOf('30135') >= 0) ? 'IAU_2015:30135' : 'IAU_2015:30100';
        let feats;
        try {
            feats = new GeoJSON().readFeatures(p.geojson, {dataProjection: dataProj, featureProjection: 'IAU_2015:30135'});
        } catch (e) { this.setState({status: {ok: false, msg: 'read features: ' + e.message}}); return; }
        const layer = new VectorLayer({source: new VectorSource({features: feats}), zIndex: 9000, style: this._style()});
        map.addLayer(layer);
        this._layers.push(layer);
        // frame the view on the added features
        try {
            const ext = layer.getSource().getExtent();
            if (ext && isFinite(ext[0])) { map.getView().fit(ext, {padding: [60, 60, 60, 60], maxZoom: 9}); }
        } catch (e) { /* fit is best-effort */ }
        this.setState({status: {ok: true, crs: v.crs || 'IAU_2015:30100 (assumed)',
            msg: 'Added ' + p.featureCount + ' feature(s).' + (v.warning ? ' ' + v.warning : '')}});
    };

    clear = () => {
        const map = MapUtils.getHook(MapUtils.GET_MAP);
        if (map) { this._layers.forEach((l) => map.removeLayer(l)); }
        this._layers = [];
        this.setState({status: {ok: true, msg: 'Cleared user layers.'}});
    };

    _style() {
        return new Style({
            stroke: new Stroke({color: '#4db6d4', width: 2}),
            fill: new Fill({color: 'rgba(77, 182, 212, 0.15)'}),
            image: new CircleStyle({radius: 5, fill: new Fill({color: '#4db6d4'}), stroke: new Stroke({color: '#0a0a0c', width: 1})})
        });
    }

    componentWillUnmount() { this.clear(); }

    renderBody() {
        const {status} = this.state;
        return (
            <div style={{padding: '0.75em', fontSize: '0.85em'}}>
                <div style={{color: '#8a9096', fontSize: '0.76em', marginBottom: '6px'}}>
                    Paste a GeoJSON to add as a user layer. STEWIE validates its CRS against the lunar frame (IAU_2015) and rejects an Earth-CRS import.
                </div>
                <textarea
                    onChange={(e) => this.setState({text: e.target.value})}
                    placeholder={'{"type":"FeatureCollection","features":[…]}'}
                    style={{width: '100%', height: '9em', background: '#141417', color: '#e6e8ea', border: '1px solid #26262c', borderRadius: '3px', fontFamily: 'monospace', fontSize: '11px', padding: '6px', boxSizing: 'border-box', resize: 'vertical'}}
                    value={this.state.text}
                />
                <div style={{display: 'flex', gap: '6px', marginTop: '6px'}}>
                    <button onClick={this.onAdd} style={{...BTN, flex: 2, color: '#e6e8ea', background: '#17171b'}}>Validate + add</button>
                    <button onClick={this.clear} style={{...BTN, flex: 1, color: '#8a9096', background: '#101013'}}>Clear</button>
                </div>
                {status ? (
                    <div style={{marginTop: '8px', padding: '6px 8px', borderRadius: '3px', background: status.ok ? '#0f1611' : '#1a1012', color: status.ok ? '#7fe0a8' : '#ff8a8a', fontSize: '0.78em'}}>
                        {status.crs ? (<div style={{color: '#8a9096', fontSize: '0.92em', marginBottom: '2px'}}>CRS: {status.crs}</div>) : null}
                        {status.msg}
                    </div>
                ) : null}
                <div style={{marginTop: '0.7em', color: '#6a6a78', fontSize: '0.72em'}}>
                    Promote-to-planning (a validated user layer → keep-outs via the ED-01 edit-session) is the next increment.
                </div>
            </div>
        );
    }

    render() {
        return (
            <SideBar
                icon="draw"
                id="MissionUserLayer"
                side={this.props.side}
                title="User Layer"
                width="26em"
            >
                {() => ({body: this.renderBody()})}
            </SideBar>
        );
    }
}

export default connect(() => ({}), {})(MissionUserLayer);
