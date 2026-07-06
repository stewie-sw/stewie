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

  // =========================================================================
  // MISSION AUTHORING (Phase-2) — place cut/dig + fill/build orders on the map,
  // submit them to the REAL STEWIE mission backend (same-origin /api/plan, which
  // nginx proxies to the FastAPI planner), and draw the REAL returned plan.
  //
  // Coordinate frames:
  //   * The map is IAU_2015:30135 (polar stereographic metres).
  //   * The planner works in an ORDER FRAME: metres East/North from the site's
  //     flattest-anchor origin. A map click -> selenographic lon/lat (proj4) ->
  //     backend /api/dem/site_xy (absolute tile metres) -> order (x,y) = tile - anchor.
  //   * To draw the returned order-frame route back on the map we build a small
  //     LOCAL AFFINE (order -> 30135) once per site from three /api/dem/site_lonlat
  //     samples; verified accurate to < 0.02 m over the work area.
  // =========================================================================
  var API = '/api';
  var mission = {
    site: 'haworth', anchor: null, affine: null, activeKind: null,
    footprint: 60, depth: 0.4, orders: []
  };

  var KIND_COLOR = { cut: '#e0563a', fill: '#4fd1ff' };

  // Order-queue markers (pending, pre-plan) and the rendered plan (routes + sites + charger).
  var orderSource = new ol.source.Vector();
  var orderLayer = new ol.layer.Vector({ source: orderSource, zIndex: 20 });
  var planSource = new ol.source.Vector();
  var planLayer = new ol.layer.Vector({ source: planSource, zIndex: 19 });
  map.addLayer(planLayer);
  map.addLayer(orderLayer);

  function orderMarkerStyle(feature) {
    var kind = feature.get('kind');
    var color = KIND_COLOR[kind] || '#ffd24a';
    return new ol.style.Style({
      image: new ol.style.RegularShape({
        points: kind === 'cut' ? 4 : 3,               // cut = square, fill = triangle
        radius: 7, angle: kind === 'cut' ? Math.PI / 4 : 0,
        fill: new ol.style.Fill({ color: color }),
        stroke: new ol.style.Stroke({ color: '#0a0d12', width: 1.5 })
      }),
      text: new ol.style.Text({
        text: String(feature.get('label') || ''), offsetY: -14,
        font: '600 11px system-ui, sans-serif',
        fill: new ol.style.Fill({ color: '#e8edf4' }),
        stroke: new ol.style.Stroke({ color: '#000', width: 3 })
      })
    });
  }
  orderLayer.setStyle(orderMarkerStyle);

  // --- Affine: order-frame (m) -> 30135 (m), built from 3 backend samples ----
  function calibrateAffine(site, anchor) {
    var pts = [[0, 0], [100, 0], [0, 100]];
    return Promise.all(pts.map(function (p) {
      var tx = anchor[0] + p[0], ty = anchor[1] + p[1];
      return fetch(API + '/dem/site_lonlat?site=' + encodeURIComponent(site) + '&x=' + tx + '&y=' + ty)
        .then(function (r) { if (!r.ok) throw new Error('site_lonlat HTTP ' + r.status); return r.json(); })
        .then(function (j) {
          if (!j.ok) throw new Error(j.error || 'site_lonlat failed');
          return ol.proj.transform([j.lon, j.lat], 'IAU_2015:30100', proj30135);
        });
    })).then(function (m) {
      var m0 = m[0], m1 = m[1], m2 = m[2];
      return {
        M: [(m1[0] - m0[0]) / 100, (m2[0] - m0[0]) / 100,
            (m1[1] - m0[1]) / 100, (m2[1] - m0[1]) / 100],
        t: [m0[0], m0[1]]
      };
    });
  }
  function orderToMap(aff, ox, oy) {
    return [aff.t[0] + aff.M[0] * ox + aff.M[1] * oy,
            aff.t[1] + aff.M[2] * ox + aff.M[3] * oy];
  }

  var hintEl = document.getElementById('au-hint');
  function setHint(msg, isErr) { hintEl.textContent = msg; hintEl.classList.toggle('err', !!isErr); }

  function flyToWorkArea() {
    if (!mission.affine) return;
    view.animate({ center: orderToMap(mission.affine, 0, 0), resolution: 0.5, duration: 500 });
  }

  // --- Site select: fetch anchor georef + calibrate. `fly` (a deliberate user action:
  // changing the site, or first activating a tool) zooms to the work area; on initial
  // load we calibrate WITHOUT touching the view, so the viewer's site-cluster landing
  // view (and its pins) is unchanged.
  function selectSite(site, fly) {
    mission.site = site;
    mission.anchor = null; mission.affine = null;
    mission.orders = []; refreshQueue(); planSource.clear();
    document.getElementById('au-result').innerHTML = '';
    setHint('Loading ' + site + ' work-area frame…');
    return fetch(API + '/dem/georef?site=' + encodeURIComponent(site))
      .then(function (r) { if (!r.ok) throw new Error('georef HTTP ' + r.status); return r.json(); })
      .then(function (j) {
        if (!j.ok || !j.anchor_xy) throw new Error(j.error || 'no anchor for site');
        mission.anchor = j.anchor_xy;
        return calibrateAffine(site, j.anchor_xy);
      })
      .then(function (aff) {
        mission.affine = aff;
        if (fly) flyToWorkArea();
        setHint('Pick a tool, then click the map near the work area to place an order.');
      })
      .catch(function (e) { setHint('Could not load site frame: ' + e.message, true); });
  }

  // --- Tool selection --------------------------------------------------------
  var cutBtn = document.getElementById('au-cut');
  var fillBtn = document.getElementById('au-fill');
  function setTool(kind) {
    mission.activeKind = (mission.activeKind === kind) ? null : kind;
    cutBtn.classList.toggle('active-cut', mission.activeKind === 'cut');
    fillBtn.classList.toggle('active-fill', mission.activeKind === 'fill');
    if (mission.activeKind) {
      // First time an operator starts authoring, drop into the work area (deliberate action).
      if (view.getResolution() > 3) flyToWorkArea();
      setHint('Click the map to place a ' + (kind === 'cut' ? 'CUT (dig)' : 'FILL (build)') +
        ' order. Click the tool again to stop placing.');
    } else {
      setHint('Placing off. Pick a tool to place more orders, or Plan the mission.');
    }
  }
  cutBtn.addEventListener('click', function () { setTool('cut'); });
  fillBtn.addEventListener('click', function () { setTool('fill'); });
  document.getElementById('au-fp').addEventListener('change', function () {
    mission.footprint = Math.max(1, parseFloat(this.value) || 60);
  });
  document.getElementById('au-depth').addEventListener('change', function () {
    mission.depth = Math.max(0.05, parseFloat(this.value) || 0.4);
  });
  document.getElementById('au-site').addEventListener('change', function () { selectSite(this.value, true); });

  // --- Placement: map click -> /api/dem/site_xy -> order (x,y) ----------------
  function placeOrder(coord) {
    if (!mission.activeKind || !mission.anchor) return;
    var kind = mission.activeKind, fp = mission.footprint, dp = mission.depth;
    var ll = ol.proj.transform(coord, proj30135, 'IAU_2015:30100');   // [lon, lat]
    var url = API + '/dem/site_xy?site=' + encodeURIComponent(mission.site) +
      '&lat=' + ll[1] + '&lon=' + ll[0];
    setHint('Converting click to the ' + mission.site + ' order frame…');
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j.ok) { setHint('Placement failed: ' + (j.error || 'site_xy'), true); return; }
        var ox = Math.round((j.x_m - mission.anchor[0]) * 10) / 10;
        var oy = Math.round((j.y_m - mission.anchor[1]) * 10) / 10;
        mission.orders.push({
          action: kind + ' ' + (mission.orders.length + 1), kind: kind,
          x: ox, y: oy, footprint_m2: fp, depth_m: dp, coord: coord
        });
        refreshQueue();
        setHint('Placed ' + kind + ' at order (' + ox + ', ' + oy + ') m. ' +
          mission.orders.length + ' order(s) queued.');
      })
      .catch(function (e) { setHint('Placement request failed: ' + e.message, true); });
  }

  // --- Order queue rendering -------------------------------------------------
  var queueEl = document.getElementById('au-queue');
  var planBtn = document.getElementById('au-plan');
  function refreshQueue() {
    queueEl.innerHTML = '';
    mission.orders.forEach(function (o, i) {
      var li = document.createElement('li');
      var sw = document.createElement('span'); sw.className = 'q-sw ' + o.kind;
      var txt = document.createElement('span'); txt.className = 'q-txt';
      txt.textContent = o.kind + ' (' + o.x + ', ' + o.y + ') · ' + o.footprint_m2 + ' m² · ' + o.depth_m + ' m';
      var del = document.createElement('span'); del.className = 'q-del'; del.textContent = '×';
      del.title = 'remove'; del.addEventListener('click', function () {
        mission.orders.splice(i, 1); refreshQueue();
      });
      li.appendChild(sw); li.appendChild(txt); li.appendChild(del);
      queueEl.appendChild(li);
    });
    planBtn.disabled = mission.orders.length === 0;
    // Redraw pending order markers from the stored click coordinates.
    orderSource.clear();
    mission.orders.forEach(function (o, i) {
      var f = new ol.Feature({ geometry: new ol.geom.Point(o.coord) });
      f.set('kind', o.kind); f.set('label', String(i + 1));
      orderSource.addFeature(f);
    });
  }

  document.getElementById('au-clear').addEventListener('click', function () {
    mission.orders = []; refreshQueue(); planSource.clear();
    document.getElementById('au-result').innerHTML = '';
    setHint('Cleared. Pick a tool and click the map to place orders.');
  });

  // --- Plan submit -----------------------------------------------------------
  function fmtDur(s) {
    s = Math.round(s);
    if (s < 3600) return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
    var h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    if (h < 48) return h + 'h ' + m + 'm';
    return (s / 86400).toFixed(1) + ' days';
  }
  function fmtEnergy(j) {
    var kwh = j / 3.6e6;
    if (kwh < 1) return (j / 1e3).toFixed(0) + ' kJ';
    if (kwh < 1000) return kwh.toFixed(1) + ' kWh';
    return (kwh / 1000).toFixed(2) + ' MWh';
  }
  function fmtMass(kg) { return kg >= 1000 ? (kg / 1000).toFixed(1) + ' t' : kg.toFixed(0) + ' kg'; }

  function runPlan() {
    if (!mission.orders.length) { setHint('Add at least one order first.', true); return; }
    var payload = {
      name: 'artemis-web mission', body: 'moon', site: mission.site,
      algorithm: 'nearest', objective: 'time',
      orders: mission.orders.map(function (o) {
        return { action: o.action, kind: o.kind, x: o.x, y: o.y,
                 footprint_m2: o.footprint_m2, depth_m: o.depth_m };
      })
    };
    planBtn.disabled = true; planBtn.textContent = 'Planning…';
    document.getElementById('au-result').innerHTML = '<div class="r-kv">Running planner on the real DEM…</div>';
    return fetch(API + '/plan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (b) { return { status: r.status, body: b }; }); })
      .then(function (res) {
        planBtn.disabled = false; planBtn.textContent = 'Plan mission';
        if (!res.body || !res.body.ok) {
          var err = (res.body && res.body.error) || ('HTTP ' + res.status);
          document.getElementById('au-result').innerHTML =
            '<div class="r-head r-bad">Plan rejected</div><div class="r-reasons">' + err + '</div>';
          return res.body;
        }
        renderPlan(res.body);
        return res.body;
      })
      .catch(function (e) {
        planBtn.disabled = false; planBtn.textContent = 'Plan mission';
        document.getElementById('au-result').innerHTML =
          '<div class="r-head r-bad">Plan request failed</div><div class="r-reasons">' + e.message + '</div>';
      });
  }
  planBtn.addEventListener('click', runPlan);

  // --- Render the REAL returned plan on the map + in the panel ---------------
  function renderPlan(resp) {
    planSource.clear();
    var aff = mission.affine;
    var pir = resp.plan_ir || {};
    var routeStyle = new ol.style.Style({
      stroke: new ol.style.Stroke({ color: '#ffd24a', width: 2.5,
        lineDash: pir.feasible === false ? [6, 5] : undefined })
    });
    var haulStyle = new ol.style.Style({
      stroke: new ol.style.Stroke({ color: '#8fb8ff', width: 2, lineDash: [2, 4] })
    });
    (pir.actions || []).forEach(function (a) {
      if (a.op === 'GoTo' && a.waypoints && a.waypoints.length > 1) {
        var line = a.waypoints.map(function (w) { return orderToMap(aff, w[0], w[1]); });
        var f = new ol.Feature({ geometry: new ol.geom.LineString(line) });
        f.setStyle(routeStyle); planSource.addFeature(f);
      } else if (a.op === 'CutHaulFill' && a.site && a.dest) {
        var s = orderToMap(aff, a.site[0], a.site[1]);
        var d = orderToMap(aff, a.dest[0], a.dest[1]);
        var hf = new ol.Feature({ geometry: new ol.geom.LineString([s, d]) });
        hf.setStyle(haulStyle); planSource.addFeature(hf);
      }
    });
    // Charger (order origin 0,0) marker.
    var charger = new ol.Feature({ geometry: new ol.geom.Point(orderToMap(aff, 0, 0)) });
    charger.setStyle(new ol.style.Style({
      image: new ol.style.RegularShape({ points: 4, radius: 6, angle: 0,
        fill: new ol.style.Fill({ color: '#7fe0a8' }),
        stroke: new ol.style.Stroke({ color: '#0a0d12', width: 1.5 }) }),
      text: new ol.style.Text({ text: 'charger', offsetY: 14, font: '600 10px system-ui',
        fill: new ol.style.Fill({ color: '#7fe0a8' }), stroke: new ol.style.Stroke({ color: '#000', width: 3 }) })
    }));
    planSource.addFeature(charger);

    // Fit to the plan (work-area scale) so the route is visible.
    var ext = planSource.getExtent();
    if (ext && isFinite(ext[0])) view.fit(ext, { padding: [60, 60, 60, 60], maxZoom: 20, duration: 400 });

    // Summary panel from the REAL response (plan_result + totals).
    var pr = resp.plan_result || {}, t = resp.totals || {};
    var feasible = resp.feasible;
    var rows = [];
    rows.push('<div class="r-head ' + (feasible ? 'r-ok' : 'r-bad') + '">' +
      (feasible ? '✓ Feasible plan' : '✗ Infeasible plan') + '</div>');
    rows.push(kv('Orders', pr.n_orders != null ? pr.n_orders : mission.orders.length));
    rows.push(kv('Vehicles', pr.vehicles != null ? pr.vehicles : 1));
    rows.push(kv('Makespan', fmtDur(pr.makespan_s || t.makespan_s || t.time_s || 0)));
    rows.push(kv('Energy', fmtEnergy(pr.energy_j || t.energy_J || 0)));
    rows.push(kv('Mass moved', fmtMass(pr.mass_moved_kg != null ? pr.mass_moved_kg
      : (t.cut_kg || 0) + (t.fill_kg || 0))));
    rows.push(kv('Distance', ((t.distance_m || 0) / 1000).toFixed(2) + ' km'));
    rows.push(kv('Recharges', pr.recharges != null ? pr.recharges : (t.charges || 0)));
    rows.push(kv('Drum cycles', pr.drum_cycles != null ? pr.drum_cycles : (t.drum_cycles || 0)));
    rows.push(kv('Algorithm', pr.resolved_algorithm || t.resolved_algorithm || t.algorithm || '—'));
    if (!feasible && (resp.infeasible_reasons || []).length) {
      rows.push('<div class="r-reasons">' + resp.infeasible_reasons.join('<br>') + '</div>');
    }
    if (resp.pdf) {
      rows.push('<a class="r-pdf" href="' + API + resp.pdf + '" target="_blank" rel="noopener">' +
        '↓ Mission report (PDF)</a>');
    }
    document.getElementById('au-result').innerHTML = rows.join('');
    setHint('Plan rendered on the map. Route = gold, haul = blue-dashed, charger = green.');
  }
  function kv(k, v) { return '<div class="r-kv"><span>' + k + '</span><b>' + v + '</b></div>'; }

  // Placement fires on a genuine map click when a tool is active (kept separate from
  // the MA-01 readout handler so the point-value readout is unchanged).
  map.on('singleclick', function (evt) { placeOrder(evt.coordinate); });

  // Initialise on the default site WITHOUT flying (preserve the site-cluster landing view).
  selectSite(mission.site, false);
  document.getElementById('au-site').value = mission.site;

  // Authoring handles for the headless verification harness (same code paths as the UI).
  window.stewieAuthor = {
    setSite: selectSite, setTool: setTool,
    placeAt: function (coord) { placeOrder(coord); },
    plan: runPlan, state: mission
  };

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
