/* STEWIE — Artemis South Pole web map viewer.
 * OpenLayers 10 in lunar polar-stereographic IAU_2015:30135. Base terrain from the
 * STEWIE QGIS Server WMS (same-origin /ows/, proxied to the qgis-server container);
 * site pins/footprints from the IAU_2015:30100 GeoJSON, reprojected client-side.
 * Self-contained: OL + proj4 are vendored locally (vendor/), no CDN, no Earth basemap.
 */
(function () {
  'use strict';

  // --- Lunar CRS registration (Moon 2015 sphere, R = 1737400 m) -------------
  // 30135 = polar stereographic (lat_0=-90); 30100 = selenographic lon/lat.
  proj4.defs('IAU_2015:30135',
    '+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=1737400 +units=m +no_defs');
  proj4.defs('IAU_2015:30100',
    '+proj=longlat +R=1737400 +no_defs');
  ol.proj.proj4.register(proj4);

  var proj30135 = ol.proj.get('IAU_2015:30135');
  // Full data extent of the shared-core project: the continuous LOLA LDEM_75S
  // basemap is a ~915 km square (pole-centred, covers ~75-90S), so it dominates
  // the project's IAU_2015:30135 BoundingBox and lets the viewer show the whole
  // south-polar moon. The 8 site DEMs sit inside this, near the pole (0,0).
  var FULL_EXTENT = [-457440, -457440, 457440, 457440];
  proj30135.setExtent(FULL_EXTENT);
  proj30135.setWorldExtent(FULL_EXTENT);

  // Cluster of the 8 Artemis III candidate-site DEMs [minx, miny, maxx, maxy] (30135 m).
  var SITE_CLUSTER = [-123400, -66100, 94000, 132000];

  var OWS = '/ows/';   // same-origin; nginx proxies to http://qgis-server:80/ows/
  var MAP_PARAM = '/io/data/code/gis/stewie_south_pole.qgz';   // in-container project path

  var SITES = ['Site01', 'Site04', 'Site06', 'Site07', 'Site11', 'Site20', 'Site23', 'Site42'];

  // WMS LAYERS are drawn bottom -> top. Per site: Hillshade then DEM, matching the
  // verified QGIS-Desktop proof render (the project's DEM color ramp blends over the
  // shaded relief). Haworth 1 m first (broad backdrop).
  // NB: the Haworth DEM layer's WMS Name is "Haworth DEM (1 m)" (from GetCapabilities),
  // not "Haworth DEM" — an unknown layer name makes QGIS 400 the whole GetMap.
  var terrainLayerNames = ['Haworth Hillshade', 'Haworth DEM (1 m)'];
  SITES.forEach(function (s) { terrainLayerNames.push(s + ' Hillshade', s + ' DEM'); });
  var slopeLayerNames = SITES.map(function (s) { return s + ' Slope'; });
  var hillshadeLayerNames = ['Haworth Hillshade'].concat(
    SITES.map(function (s) { return s + ' Hillshade'; }));

  // MA-01 value-readout: the queryable raster layers (WMS Names, verified against
  // GetCapabilities). GetFeatureInfo returns the real Float32 pixel value ("Band 1")
  // of each. DEM = elevation (m), Slope = steepness (deg). Haworth 1 m DEM first, then
  // the 8 site DEMs; the LOLA "South Polar Basemap" is a HILLSHADE (0-255 shaded-relief
  // DN, NOT metres) used only as honest out-of-DEM context.
  var demLayerNames = ['Haworth DEM (1 m)'].concat(SITES.map(function (s) { return s + ' DEM'; }));
  var readoutQueryLayers = demLayerNames.concat(slopeLayerNames, ['South Polar Basemap']);

  var statusEl = document.getElementById('status');
  var pending = 0;
  function setStatus(msg, isErr) {
    statusEl.textContent = msg;
    statusEl.classList.toggle('err', !!isErr);
  }

  function wmsSource(layerCsv, label) {
    var src = new ol.source.ImageWMS({
      url: OWS,
      projection: proj30135,
      ratio: 1,
      crossOrigin: null,   // same origin
      params: {
        'MAP': MAP_PARAM,
        'LAYERS': layerCsv,
        'VERSION': '1.3.0',
        'FORMAT': 'image/png',
        'DPI': 96,
        'STYLES': ''
      }
    });
    // Wire load lifecycle so a genuinely blank/failed WMS surfaces instead of looking "clean".
    src.on('imageloadstart', function () { pending++; setStatus('Rendering lunar terrain…'); });
    src.on('imageloadend', function () { pending--; if (pending <= 0) setStatus('LOLA/LROC terrain · IAU_2015:30135 · pan & zoom the pole'); });
    src.on('imageloaderror', function () {
      pending--;
      setStatus('WMS error loading "' + label + '" — check /ows/ proxy to qgis-server', true);
    });
    return src;
  }

  // Continuous south-polar moon basemap (LOLA LDEM_75S hillshade COG) — a single
  // QGIS WMS layer, drawn UNDER everything so the map reads as a whole moon, not
  // 8 DEMs floating on black. Default ON. Local COG (no serve-time egress).
  var basemapLayer = new ol.layer.Image({ source: wmsSource('South Polar Basemap', 'Basemap'), visible: true });
  var terrainLayer = new ol.layer.Image({ source: wmsSource(terrainLayerNames.join(','), 'Terrain'), visible: true });
  var hillshadeLayer = new ol.layer.Image({ source: wmsSource(hillshadeLayerNames.join(','), 'Hillshade'), visible: false });
  var slopeLayer = new ol.layer.Image({ source: wmsSource(slopeLayerNames.join(','), 'Slope'), visible: false });

  // --- Site vectors (pins + footprints), reprojected 30100 -> 30135 ---------
  // Fetch + parse manually: passing dataProjection explicitly to readFeatures OVERRIDES
  // the file's `crs` member (urn:ogc:def:crs:IAU_2015::30100), which OL can't resolve to a
  // transform and would otherwise leave the geometries in raw lon/lat degrees.
  var vectorSource = new ol.source.Vector();
  fetch('data/artemis_sites.geojson')
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function (gj) {
      var feats = new ol.format.GeoJSON().readFeatures(gj, {
        dataProjection: 'IAU_2015:30100',
        featureProjection: 'IAU_2015:30135'
      });
      vectorSource.addFeatures(feats);
    })
    .catch(function (e) {
      setStatus('Could not load site vectors (data/artemis_sites.geojson): ' + e.message, true);
    });

  var pinFill = new ol.style.Fill({ color: '#ffd24a' });
  var pinStroke = new ol.style.Stroke({ color: '#14181f', width: 1.5 });
  var footStroke = new ol.style.Stroke({ color: '#4fd1ff', width: 1.5 });
  var footFill = new ol.style.Fill({ color: 'rgba(79,209,255,0.08)' });

  function siteStyle(feature) {
    var geom = feature.getGeometry().getType();
    if (geom === 'Point') {
      return new ol.style.Style({
        image: new ol.style.Circle({ radius: 6, fill: pinFill, stroke: pinStroke }),
        text: new ol.style.Text({
          text: feature.get('site') || '',
          offsetY: -15,
          font: '600 12px system-ui, sans-serif',
          fill: new ol.style.Fill({ color: '#ffe9a8' }),
          stroke: new ol.style.Stroke({ color: '#000', width: 3 })
        })
      });
    }
    return new ol.style.Style({ stroke: footStroke, fill: footFill });
  }

  var vectorLayer = new ol.layer.Vector({
    source: vectorSource,
    style: siteStyle,
    zIndex: 10
  });

  // --- Map + view -----------------------------------------------------------
  var view = new ol.View({
    projection: proj30135,
    center: [0, 30000],
    resolution: 200,
    extent: [-520000, -520000, 520000, 520000],
    showFullExtent: true
  });

  var map = new ol.Map({
    target: 'map',
    layers: [basemapLayer, terrainLayer, hillshadeLayer, slopeLayer, vectorLayer],
    view: view,
    controls: [
      new ol.control.Zoom(),
      new ol.control.ScaleLine({ units: 'metric' }),
      new ol.control.Attribution({ collapsible: true })
    ]
  });

  // Frame the site cluster (pole 0,0 is inside it) once layout is known.
  map.once('postrender', function () {
    view.fit(SITE_CLUSTER, { padding: [48, 48, 48, 48], maxZoom: 12 });
  });

  // --- Click popup ----------------------------------------------------------
  var popup = document.getElementById('popup');
  var popupSite = document.getElementById('popup-site');
  var popupBody = document.getElementById('popup-body');
  var overlay = new ol.Overlay({
    element: popup,
    autoPan: { animation: { duration: 200 } },
    stopEvent: true
  });
  map.addOverlay(overlay);

  document.getElementById('popup-close').addEventListener('click', function () {
    popup.style.display = 'none';
    overlay.setPosition(undefined);
  });

  function fmt(n) { return (typeof n === 'number') ? n.toLocaleString('en-US', { maximumFractionDigits: 0 }) : n; }

  // --- MA-01 click-anywhere value readout -----------------------------------
  // On any map click, a same-origin WMS GetFeatureInfo (application/json, so QGIS
  // returns the numeric pixel value, not a rendered colour) samples the DEM + slope +
  // basemap under the click and shows the REAL elevation/slope + both-CRS coordinates.
  var readoutEl = document.getElementById('readout');
  var readoutBody = document.getElementById('readout-body');

  function ro(n, dp) { return (typeof n === 'number' && isFinite(n)) ? n.toFixed(dp) : '—'; }
  function siteKeyOf(demId) {
    var m = demId.match(/^Site\d+/);
    return m ? m[0] : (demId.indexOf('Haworth') === 0 ? 'Haworth' : demId);
  }

  var readoutSeq = 0;   // monotonic guard so a stale in-flight response can't overwrite a newer click
  function renderReadout(o) {
    var rows = [];
    if (o.loading) {
      rows.push('<div class="ro-line ro-elev ro-dim">Sampling…</div>');
    } else if (o.error) {
      rows.push('<div class="ro-line ro-err">Readout error: ' + o.error + '</div>');
    } else if (o.demId != null) {
      rows.push('<div class="ro-line ro-elev">Elevation <b>' + ro(o.elev, 2) + '</b> m</div>');
      if (o.slope != null) {
        rows.push('<div class="ro-line">Slope <b>' + ro(o.slope, 2) + '</b>°</div>');
      } else {
        rows.push('<div class="ro-line ro-dim">Slope — (no slope layer for ' + siteKeyOf(o.demId) + ')</div>');
      }
      rows.push('<div class="ro-line ro-dim">from <b>' + o.demId + '</b></div>');
    } else {
      rows.push('<div class="ro-line ro-elev ro-nodem">No high-res DEM here</div>');
      if (o.basemap != null) {
        rows.push('<div class="ro-line ro-dim">LOLA basemap shaded-relief <b>' + ro(o.basemap, 0) +
          '</b> <span class="ro-dim">(0–255 DN, not elevation)</span></div>');
      }
    }
    rows.push('<div class="ro-coord">x/y <b>' + Math.round(o.coord[0]) + '</b>, <b>' + Math.round(o.coord[1]) +
      '</b> m <span class="ro-dim">30135</span></div>');
    rows.push('<div class="ro-coord">lon/lat <b>' + o.lonlat[0].toFixed(4) + '</b>°, <b>' + o.lonlat[1].toFixed(4) +
      '</b>° <span class="ro-dim">30100 selenographic</span></div>');
    readoutBody.innerHTML = rows.join('');
  }

  function sampleAt(coordinate) {
    var res = view.getResolution();
    var half = 50 * res;   // 101x101 window; centre pixel I=50,J=50 lands on the click
    var bbox = [coordinate[0] - half, coordinate[1] - half, coordinate[0] + half, coordinate[1] + half];
    var lonlat = ol.proj.transform(coordinate, proj30135, 'IAU_2015:30100');
    var params = new URLSearchParams({
      MAP: MAP_PARAM,
      SERVICE: 'WMS', VERSION: '1.3.0', REQUEST: 'GetFeatureInfo',
      CRS: 'IAU_2015:30135',
      LAYERS: readoutQueryLayers.join(','),
      QUERY_LAYERS: readoutQueryLayers.join(','),
      BBOX: bbox.join(','),
      WIDTH: '101', HEIGHT: '101', I: '50', J: '50',
      INFO_FORMAT: 'application/json', FEATURE_COUNT: '1', STYLES: ''
    });
    var seq = ++readoutSeq;
    renderReadout({ loading: true, coord: coordinate, lonlat: lonlat });
    fetch(OWS + '?' + params.toString())
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (gj) {
        if (seq !== readoutSeq) return;   // superseded by a newer click
        var vals = {};
        (gj.features || []).forEach(function (f) {
          var b = f.properties && f.properties['Band 1'];
          if (b != null && b !== '') { var v = parseFloat(b); if (isFinite(v)) vals[f.id] = v; }
        });
        var out = { coord: coordinate, lonlat: lonlat };
        for (var i = 0; i < demLayerNames.length; i++) {
          if (demLayerNames[i] in vals) { out.demId = demLayerNames[i]; out.elev = vals[out.demId]; break; }
        }
        if (out.demId != null) {
          var slopeId = siteKeyOf(out.demId) + ' Slope';
          if (slopeId in vals) out.slope = vals[slopeId];
        } else if ('South Polar Basemap' in vals) {
          out.basemap = vals['South Polar Basemap'];
        }
        renderReadout(out);
      })
      .catch(function (e) {
        if (seq !== readoutSeq) return;
        renderReadout({ coord: coordinate, lonlat: lonlat, error: e.message });
      });
  }

  map.on('singleclick', function (evt) {
    sampleAt(evt.coordinate);
    var hits = [];
    map.forEachFeatureAtPixel(evt.pixel, function (f) { hits.push(f); },
      { layerFilter: function (l) { return l === vectorLayer; }, hitTolerance: 6 });
    // Prefer the site pin (Point) over its footprint polygon when both are under the cursor.
    var found = hits.find(function (f) { return f.getGeometry().getType() === 'Point'; }) || hits[0];
    if (!found) { popup.style.display = 'none'; overlay.setPosition(undefined); return; }
    var p = found.getProperties();
    popupSite.textContent = p.site || 'Artemis site';
    var rows = [];
    if (p.dem_min_m != null && p.dem_max_m != null) {
      rows.push('<div class="kv">Elevation: <b>' + fmt(p.dem_min_m) + '</b> to <b>' + fmt(p.dem_max_m) + '</b> m</div>');
    }
    if (p.center_lat != null && p.center_lon != null) {
      rows.push('<div class="kv">Center: <b>' + p.center_lat.toFixed(2) + '°</b> lat, <b>' + p.center_lon.toFixed(2) + '°</b> lon</div>');
    }
    if (p.area_km2 != null) rows.push('<div class="kv">DEM extent: <b>' + fmt(p.area_km2) + '</b> km²</div>');
    if (p.source) rows.push('<div class="kv" style="margin-top:5px;font-size:11px;">' + p.source + '</div>');
    popupBody.innerHTML = rows.join('');
    popup.style.display = 'block';
    // Anchor to the site pin centroid if available, else the click point.
    var geom = found.getGeometry();
    var anchor = (geom.getType() === 'Point') ? geom.getCoordinates() : evt.coordinate;
    overlay.setPosition(anchor);
  });

  map.on('pointermove', function (evt) {
    if (evt.dragging) return;
    var hit = map.hasFeatureAtPixel(evt.pixel, { layerFilter: function (l) { return l === vectorLayer; }, hitTolerance: 6 });
    map.getTargetElement().style.cursor = hit ? 'pointer' : '';
  });

  // --- Layer switcher (built from a small config) ---------------------------
  var LAYER_UI = [
    { layer: vectorLayer, name: 'Artemis sites (pins + footprints)', swatch: 'pin', on: true },
    { layer: terrainLayer, name: 'Terrain — DEM + Hillshade', swatch: 'ramp', on: true },
    { layer: slopeLayer, name: 'Slope (steepness)', swatch: '#e0563a', on: false },
    { layer: hillshadeLayer, name: 'Hillshade only', swatch: '#8a94a0', on: false },
    { layer: basemapLayer, name: 'South-polar moon basemap (LOLA)', swatch: '#8a8f96', on: true }
  ];

  var list = document.getElementById('layer-list');
  LAYER_UI.forEach(function (cfg, i) {
    cfg.layer.setVisible(cfg.on);
    var row = document.createElement('label');
    row.className = 'layer-row';
    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = cfg.on;
    cb.addEventListener('change', function () { cfg.layer.setVisible(cb.checked); });
    var sw = document.createElement('span');
    sw.className = 'swatch';
    if (cfg.swatch === 'ramp') {
      sw.style.background = 'linear-gradient(90deg,#4a6b8a,#e8d9a0,#7a2d2d)';
    } else if (cfg.swatch === 'pin') {
      sw.style.background = '#ffd24a'; sw.style.borderRadius = '50%';
      sw.style.border = '1.5px solid #14181f';
    } else {
      sw.style.background = cfg.swatch;
    }
    var nm = document.createElement('span');
    nm.className = 'name';
    nm.textContent = cfg.name;
    row.appendChild(cb); row.appendChild(sw); row.appendChild(nm);
    list.appendChild(row);
  });

  // Legend appended under the switcher.
  var legend = document.createElement('div');
  legend.className = 'legend';
  legend.innerHTML =
    '<div class="title">Elevation (DEM color ramp)</div>' +
    '<div class="rampbar"></div>' +
    '<div class="ramplabels"><span>low</span><span>high</span></div>' +
    '<div class="vrow"><span class="pin-dot"></span> Site DEM center pin</div>' +
    '<div class="vrow"><span class="foot-box"></span> Site DEM footprint</div>' +
    '<div class="hint">Click a pin for elevation range &amp; coordinates. ' +
    'Authoritative terrain in polar-stereographic IAU_2015:30135, over a continuous ' +
    'LOLA LDEM_75S shaded-relief basemap (75–90°S). Zoom out to see the whole ' +
    'south-polar moon; the site DEMs sit near the pole.</div>';
  list.appendChild(legend);

  // Global error surface so a JS fault is not silently "clean".
  window.addEventListener('error', function (e) {
    setStatus('Viewer error: ' + (e.message || e.type), true);
  });

  // Debug/testability handle (the OL map instance + key layers). Harmless read-only
  // reference, standard for map apps; used by the headless verification harness.
  window.stewieMap = map;
  window.stewieLayers = {
    basemap: basemapLayer, terrain: terrainLayer, slope: slopeLayer,
    hillshade: hillshadeLayer, sites: vectorLayer
  };
  // MA-01 readout sampler — exposed for the headless verification harness.
  window.stewieSampleAt = sampleAt;
})();
