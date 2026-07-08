/**
 * Graticule — a toggleable lunar planning grid for the STEWIE IDE (#40). A single map button cycles
 * off -> selenographic lon/lat -> polar metric km grid. Lines are built by the pure ../mission/graticule.js
 * module and reprojected proj4 IAU_2015:30100 -> IAU_2015:30135, so the selenographic meridians/parallels
 * curve correctly in the polar-stereographic view (NOT OL's Earth-datum built-in Graticule) and the km grid
 * is straight in the metric frame. Steel-cyan (the brand crescent accent), line-placed labels.
 *
 * Map-only plugin: grabs the raw OL map via MapUtils.GET_MAP (the same hook SiteZoom/MissionPlan use) and
 * add/removeLayer directly -- a graticule is an OL-native vector overlay, not a QWC2 catalog layer.
 */
import React from 'react';
import PropTypes from 'prop-types';
import Feature from 'ol/Feature';
import LineString from 'ol/geom/LineString';
import VectorLayer from 'ol/layer/Vector';
import {transform} from 'ol/proj';
import VectorSource from 'ol/source/Vector';
import Fill from 'ol/style/Fill';
import Stroke from 'ol/style/Stroke';
import Style from 'ol/style/Style';
import Text from 'ol/style/Text';
import MapButton from 'qwc2/components/MapButton';
import MapUtils from 'qwc2/utils/MapUtils';
import G from '../mission/graticule.js';

const MODES = ['off', 'selenographic', 'metric'];
const GEO = 'IAU_2015:30100';
const MAP = 'IAU_2015:30135';
const TIPS = {
    off: 'Graticule: off (click for selenographic lon/lat)',
    selenographic: 'Graticule: selenographic lon/lat (click for polar km grid)',
    metric: 'Graticule: polar metric km grid (click to hide)'
};

class Graticule extends React.Component {
    static propTypes = {
        position: PropTypes.number
    };
    static defaultProps = {
        position: 6
    };
    state = {
        mode: 'off'
    };
    _layer = null;

    cycle = () => {
        const next = MODES[(MODES.indexOf(this.state.mode) + 1) % MODES.length];
        this._apply(next);
        this.setState({mode: next});
    };

    _apply(mode) {
        const map = MapUtils.getHook(MapUtils.GET_MAP);
        if (!map) {
            return;
        }
        if (this._layer) {
            map.removeLayer(this._layer);
            this._layer = null;
        }
        if (mode === 'off') {
            return;
        }
        const rp = (lon, lat) => transform([lon, lat], GEO, MAP);
        const lines = mode === 'selenographic'
            ? G.selenographic(rp, {lonStep: 30, latStep: 5, latMin: -88, latMax: -55, latSample: 0.5, lonSample: 2})
            : G.kmGrid({stepKm: 50, halfKm: 400});
        const src = new VectorSource();
        lines.forEach((l) => {
            const f = new Feature(new LineString(l.coords));
            f.set('label', l.label);
            src.addFeature(f);
        });
        this._layer = new VectorLayer({
            source: src,
            zIndex: 10000,
            style: (f) => new Style({
                stroke: new Stroke({color: 'rgba(77, 182, 212, 0.5)', width: 1}),   // brand steel-cyan #4db6d4
                text: new Text({
                    text: f.get('label'),
                    font: '10px sans-serif',
                    fill: new Fill({color: '#9fd0dc'}),
                    stroke: new Stroke({color: '#0a0a0c', width: 2}),
                    placement: 'line',
                    overflow: true
                })
            })
        });
        map.addLayer(this._layer);
    }

    componentWillUnmount() {
        const map = MapUtils.getHook(MapUtils.GET_MAP);
        if (map && this._layer) {
            map.removeLayer(this._layer);
        }
    }

    render() {
        return (
            <MapButton
                active={this.state.mode !== 'off'}
                icon="grid"
                onClick={this.cycle}
                position={this.props.position}
                tooltip={TIPS[this.state.mode]}
            />
        );
    }
}

export default Graticule;
