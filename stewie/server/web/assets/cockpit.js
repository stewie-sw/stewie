// ARCH-02: the work-area image's load-failure handler. Was an inline `onerror=` HTML attribute, which
// the tightened CSP (script-src without 'unsafe-inline') forbids. Wired here via addEventListener; this
// external script runs after the DOM is parsed, so the img element already exists.
(function () {
  const wai = document.getElementById("workareaimg");
  if (wai) wai.addEventListener("error", () => {
    const wa = wai.closest("#workarea");
    if (wa) wa.classList.remove("show");
  });
})();

// --- bodies + base imagery -------------------------------------------------------------------
// density [kg/m^3] + g [m/s^2] are a file:// fallback; the served browser reads the sysrev values from
// bodies.json (terrain_authority/bodies.py, single source). Moon/Mars stream from NASA Solar System Treks;
// Earth has no Trek tiles, so it uses NASA GIBS Blue Marble (EPSG4326, no token, same 2x1 geographic
// tiling). All imagery endpoints curl-verified HTTP 200.
const trekUrl = (body, layer, ext = "jpg") =>
  `https://trek.nasa.gov/tiles/${body}/EQ/${layer}/1.0.0/default/default028mm/{z}/{y}/{x}.${ext}`;
// Each body: physics fallback (g/density; served browser uses bodies.json) + a list of imagery LAYERS the
// Layer dropdown switches between. Moon/Mars = NASA Trek (equirectangular 2x1); Earth = Esri World Imagery
// (WebMercator; GIBS EPSG4326 fails Cesium's geographic pyramid). All endpoints curl-verified HTTP 200.
const BODIES = {
  moon: { name: "Moon", radius: 1737400, start: [-89.0, 0], density: 1300, g: 1.62, layers: [
    { name: "LRO WAC (visual)", geographic: true, tile: 256, maxLevel: 8,   // z8 is the native ceiling (z9 -> 404)
      url: trekUrl("Moon", "LRO_WAC_Mosaic_Global_303ppd_v02"), credit: "NASA Trek (LRO WAC, 303 ppd)" },
    // whole-planet alternates (Aaron 2026-06-10: "link in other layers for the entire planet"):
    // ENHANCED TOPOGRAPHIC SET (Aaron 2026-06-10: "ArcGIS fully functional -- enhanced datasets,
    // topographical overlays of the moon first"). Every product TILE-VERIFIED from the real Trek
    // catalog before listing (no guessed IDs).
    { name: "Kaguya TC ortho (high-res visual)", geographic: true, tile: 256, maxLevel: 9,
      url: trekUrl("Moon", "Kaguya_TCortho_Mosaic_Global_4096ppd", "png"), credit: "NASA Trek (Kaguya TC 4096 ppd)" },
    { name: "LOLA color shaded-relief (256 ppd)", geographic: true, tile: 256, maxLevel: 8,
      url: trekUrl("Moon", "LRO_LOLA_ClrShade_Global_256ppd_v06", "png"), credit: "NASA Trek (LOLA 256 ppd)" },
    { name: "LOLA elevation (DEM color)", geographic: true, tile: 256, maxLevel: 7,
      url: trekUrl("Moon", "LRO_LOLA_DEM_Global_128ppd_v04", "png"), credit: "NASA Trek (LOLA DEM)" },
    { name: "LOLA slope (global)", geographic: true, tile: 256, maxLevel: 5,
      url: trekUrl("Moon", "LRO_LOLA_ClrSlope_Global_16ppd", "png"), credit: "NASA Trek (LOLA slope)" },
    { name: "LOLA roughness (global)", geographic: true, tile: 256, maxLevel: 5,
      url: trekUrl("Moon", "LRO_LOLA_ClrRoughness_Global_16ppd", "png"), credit: "NASA Trek (LOLA roughness)" },
    { name: "Diviner avg surface temp", geographic: true, tile: 256, maxLevel: 6,
      url: trekUrl("Moon", "LRO_Diviner_ST_Avg_Clr_Global_32ppd", "png"), credit: "NASA Trek (Diviner)" },
    { name: "LOLA grayscale hillshade", geographic: true, tile: 256, maxLevel: 7,
      url: trekUrl("Moon", "LRO_LOLA_Shade_Global_128ppd_v04", "png"), credit: "NASA Trek (LOLA shade)" },
  ] },
  mars: { name: "Mars", radius: 3396200, start: [0, 0], density: 1500, g: 3.71, layers: [
    { name: "Viking color (visual)", geographic: true, tile: 256, maxLevel: 7,
      url: trekUrl("Mars", "Mars_Viking_MDIM21_ClrMosaic_global_232m"), credit: "NASA Trek (Viking MDIM2.1)" },
    { name: "MOLA color shaded-relief", geographic: true, tile: 256, maxLevel: 7,
      url: trekUrl("Mars", "Mars_MGS_MOLA_ClrShade_merge_global_463m"), credit: "NASA Trek (MOLA elevation)" },
    // ENHANCED MARS SET (tile-verified from the real Trek catalog, same rule as the Moon's):
    { name: "THEMIS day IR (100 m, controlled)", geographic: true, tile: 256, maxLevel: 9,
      url: trekUrl("Mars", "THEMIS_DayIR_ControlledMosaics_100m_v2_oct2018", "png"), credit: "NASA Trek (THEMIS day IR)" },
    { name: "TES albedo (global)", geographic: true, tile: 256, maxLevel: 5,
      url: trekUrl("Mars", "Mars_MGS_TES_Albedo_mosaic_global_7410m", "png"), credit: "NASA Trek (TES albedo)" },
  ] },
  earth: { name: "Earth", radius: 6371000, start: [20.0, 0], density: 1600, g: 9.81, layers: [
    { name: "Esri World Imagery", geographic: false, tile: 256, maxLevel: 18,
      url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      credit: "Esri World Imagery (WebMercator: pinches at the poles past 85°)" },
    // polar-capable geographic layer (the Esri mercator cutoff smears the exact pole):
    { name: "NASA Blue Marble (polar-capable)", geographic: true, tile: 512, maxLevel: 8,
      url: "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/BlueMarble_ShadedRelief_Bathymetry/default/500m/{z}/{y}/{x}.jpeg",
      credit: "NASA GIBS Blue Marble" },
  ] },
};
// grounded IPEx / battery constants: loaded from bodies.json (_ipex, generated from ipex_specs.py ->
// single source of truth). The embedded object is a file:// fallback only (when bodies.json can't be
// fetched); the served browser uses the py-generated values. ipex() resolves preferred-then-fallback.
const IPEX_FALLBACK = { drum_kg: 30, dig_j_per_kg: 4151, battery_j: 4.79e6, dig_rate_kg_hr: 42, recharge_w: 700 };
function ipex() { return (PHY && PHY._ipex) ? PHY._ipex : IPEX_FALLBACK; }
let viewer = null, ellipsoid = null, marker = null, picked = null;

fetch("/healthz").then(r => r.json()).then(h => { const v = document.getElementById("stver");
  if (v) v.textContent = "v" + h.version; }).catch(() => {});   // B0.2 version stamp
function loadBody(key) {
  const b = BODIES[key];
  if (viewer) { viewer.destroy(); viewer = null; }
  // WEB-01: guard BEFORE any Cesium.* reference. If the self-hosted bundle did not load (CSP block,
  // offline, or a 404), `Cesium` is undefined and the line below would throw a ReferenceError OUTSIDE
  // the try/catch. Degrade cleanly to the 2-D site tools instead (same fallback as the no-WebGL path).
  if (typeof window.Cesium === "undefined") {
    const c0 = document.getElementById("cesium");
    if (c0) c0.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:10px;color:#9ab">' +
      '<div style="font-size:13px;opacity:.8">3-D globe unavailable (the map library did not load); using the 2-D site tools.</div>' +
      '<div style="font-size:12px;opacity:.6">The WORK AREA map (bottom right) and the PLAN VIEW canvas (sidebar) are fully functional: ' +
      'click them to set coordinates, queue orders, and plan the mission.</div></div>';
    viewer = null;
    return;
  }
  // v1 uses the default geographic globe: imagery + lat/lon + pan/zoom/tilt are all correct; only the
  // sphere RADIUS is Earth-sized (cosmetic). A true per-body ellipsoid is a refinement (Cesium's custom
  // globe path errors in 1.119). The body radius is kept in BODIES for the future ellipsoid swap.
  ellipsoid = Cesium.Ellipsoid.WGS84;
  try {                                       // B0.1: GPU-less machines must get a usable site map
  viewer = new Cesium.Viewer("cesium", {
    baseLayer: false, baseLayerPicker: false, geocoder: false, timeline: false,
    animation: false, sceneModePicker: false, homeButton: false, navigationHelpButton: false,
    fullscreenButton: false, infoBox: false, selectionIndicator: false,
  });
  } catch (e) {
    const c = document.getElementById("cesium");
    c.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:10px;color:#9ab">' +
      '<div style="font-size:13px;opacity:.8">3-D globe unavailable on this machine (no WebGL) — using the 2-D site tools.</div>' +
      '<div style="font-size:12px;opacity:.6">The WORK AREA map (bottom right) and the PLAN VIEW canvas (sidebar) are fully functional: ' +
      'click them to set coordinates, queue orders, and plan the mission.</div></div>';
    viewer = null;
    return;                                   // sidebar + plan view + planning all work without the globe
  }
  viewer.scene.skyAtmosphere.show = false;       // hide Earth atmosphere (do NOT set =false: Cesium's
                                                 // render loop calls skyAtmosphere.setDynamicLighting()
                                                 // and `false` is "defined" -> TypeError. Keep the object.)
  viewer.scene.globe.showGroundAtmosphere = false;
  viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#1a1a1a");
  const lsel = document.getElementById("layer");          // populate the Layer dropdown for this body
  lsel.innerHTML = "";
  b.layers.forEach((L, i) => { const o = document.createElement("option"); o.value = String(i); o.textContent = L.name; lsel.appendChild(o); });
  lsel.value = "0";
  applyLayer(key, 0);
  picked = null; marker = null;
  flyTo(b.start[0], b.start[1], ellipsoid.maximumRadius * 1.65);   // frame the body larger (less empty black)

  // click to pick a surface coordinate
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((e) => {
    const pickedPin = viewer.scene.pick(e.position);
    if (pickedPin && pickedPin.id && PIN_REFS.has(pickedPin.id)) {   // #64: select a pin
      if (SELECTED_PIN) SELECTED_PIN.point.outlineColor = Cesium.Color.BLACK;
      SELECTED_PIN = pickedPin.id;
      SELECTED_PIN.point.outlineColor = Cesium.Color.fromCssColorString("#39ff14");
      setQ("feature selected — press Delete to remove; in ✎ Edit, click a new spot to MOVE it");
      return;
    }
    if (EDIT.on && SELECTED_PIN) {                          // #64: edit-mode click MOVES the selection
      const cm = viewer.camera.pickEllipsoid(e.position, ellipsoid);
      if (cm) {
        const ca2 = Cesium.Cartographic.fromCartesian(cm, ellipsoid);
        const la2 = Cesium.Math.toDegrees(ca2.latitude), lo2 = Cesium.Math.toDegrees(ca2.longitude);
        fetch(`/dem/site_xy?lat=${la2}&lon=${lo2}`).then((r) => r.json()).then((d2) => {
          if (!d2.ok) { setQ("outside the mapped tile"); return; }
          const ref = PIN_REFS.get(SELECTED_PIN);
          if (ref) { ref.obj.x = d2.x_m; ref.obj.y = d2.y_m; }
          SELECTED_PIN.position = Cesium.Cartesian3.fromDegrees(lo2, la2, 0, ellipsoid);
          if (SELECTED_PIN.label) SELECTED_PIN.label.text =
            (ref && ref.kind === "order" ? `${ref.obj.action} ` : "") + `(${d2.x_m}, ${d2.y_m})`;
          renderQueue(); setQ(`moved to site ${d2.x_m}, ${d2.y_m} m`);
        });
        return;
      }
    }
    if (EDIT.on) {                                         // edit session: clicks DRAW (#40/#41)
      const c0 = viewer.camera.pickEllipsoid(e.position, ellipsoid);
      if (c0) { const ca0 = Cesium.Cartographic.fromCartesian(c0, ellipsoid);
        editPlace(Cesium.Math.toDegrees(ca0.latitude), Cesium.Math.toDegrees(ca0.longitude)); }
      return;
    }
    // #37 (Aaron): clicking the HAWORTH WORK AREA loads the real granular maps into the BIG window
    const picked = viewer.scene.pick(e.position);
    if (picked && picked.id) {                             // a SITE marker jumps to ITS OWN site
      const m = SITE_MARKERS.find((x) => x.ent === picked.id);
      if (m) {
        viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(
          m.site.lon, m.site.lat, 40000, viewer.scene.globe.ellipsoid) });
        setQ(m.site.imported ? `${m.site.label}: DEM imported` :
          `${m.site.label}: no DEM bundle yet (import via the PGDA pipeline)`);
        return;
      }
    }
    // the auto-load is a GO-TO-SITE gesture from afar; once you're zoomed in, clicks ON the
    // square must pass through to normal picking (Aaron: "can select around the haworth square
    // -- just not on top of it").
    const _h = viewer.camera.positionCartographic.height;
    if (picked && picked.id && HAWORTH_ENTITIES.includes(picked.id) && _h > 60000) {
      viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(
        HAWORTH_CENTER.lon, HAWORTH_CENTER.lat, 18000, viewer.scene.globe.ellipsoid) });
      ["dem"].concat(GIS_RASTERS.filter((k) => ["slope", "hazard"].includes(k))).forEach((k) => {
        LAYER_ON[k] = true; applyLayerToggle(k, true);
        const lp = qel("layerpanel");
        if (lp) lp.querySelectorAll("label").forEach((lab) => {
          const t = lab.textContent || "";
          if ((k === "slope" && t.startsWith("Slope")) || (k === "hazard" && t.includes("no-go")) ||
              (k === "dem" && t.includes("DEM"))) lab.querySelector("input").checked = true;
        });
      });
      setQ("HAWORTH WORK AREA loaded: 5 m DEM + slope + hazard on the main map");
      return;
    }
    const c = viewer.camera.pickEllipsoid(e.position, ellipsoid);
    if (!c) return;
    const carto = Cesium.Cartographic.fromCartesian(c, ellipsoid);
    setPicked(Cesium.Math.toDegrees(carto.latitude), Cesium.Math.toDegrees(carto.longitude));
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  // live cursor coordinates (Esri status-bar pattern; Aaron 2026-06-10)
  let _xyTimer = 0;
  handler.setInputAction((e) => {
    const c = viewer.camera.pickEllipsoid(e.endPosition, ellipsoid);
    const el = $("cursorcoord"); if (!el) return;
    if (!c) { el.textContent = ""; return; }
    const ca = Cesium.Cartographic.fromCartesian(c, ellipsoid);
    const lat = Cesium.Math.toDegrees(ca.latitude), lon = Cesium.Math.toDegrees(ca.longitude);
    el.textContent = `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`;
    // site-frame meters when inside the Haworth footprint (throttled; Esri status-bar style)
    if (sel.value === "moon" && HAWORTH_RECT &&
        Cesium.Rectangle.contains(HAWORTH_RECT, ca) && !_xyTimer) {
      _xyTimer = setTimeout(() => { _xyTimer = 0; }, 250);
      fetch(`/dem/site_xy?lat=${lat}&lon=${lon}`).then((r) => r.json()).then((d) => {
        if (d.ok) el.textContent += `  ·  site ${d.x_m} m, ${d.y_m} m`;
      }).catch(() => {});
    }
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

  // audit P1: the SCALE BAR -- meters-per-pixel sampled at screen center, niced to 1/2/5 steps
  function updateScale() {
    const sb = $("scalebar"), sv = $("scaleval");
    const w = viewer.scene.canvas.clientWidth, h = viewer.scene.canvas.clientHeight;
    const a = viewer.camera.pickEllipsoid(new Cesium.Cartesian2(w / 2 - 50, h / 2), ellipsoid);
    const b = viewer.camera.pickEllipsoid(new Cesium.Cartesian2(w / 2 + 50, h / 2), ellipsoid);
    const sb2 = $("scalebar2"), sv2 = $("scaleval2");
    if (!a || !b) { [sb, sb2].forEach((x) => x && (x.style.display = "none"));
      [sv, sv2].forEach((x) => x && (x.textContent = "")); return; }
    // #42: the globe is WGS84-shaped (documented cosmetic shortcut) -- Cartesian distances are
    // Earth-scaled. TRUE meters scale by the body's real radius (lat/lon angles are unaffected).
    const mpp = Cesium.Cartesian3.distance(a, b) / 100.0 * (BODIES[sel.value].radius / 6371008.8);
    const target = mpp * 90;                               // ~90 px of bar
    const pow10 = Math.pow(10, Math.floor(Math.log10(target)));
    const nice = [1, 2, 5, 10].map((k) => k * pow10).find((v) => v >= target) || target;
    const label = nice >= 1000 ? `${(nice / 1000).toFixed(nice >= 10000 ? 0 : 1)} km` : `${nice.toFixed(0)} m`;
    [[sb, sv], [sb2, sv2]].forEach(([bar, val]) => {
      if (!bar) return;
      bar.style.display = "inline-block"; bar.style.width = `${nice / mpp}px`;
      val.textContent = label;
    });
  }
  // UI-15: the overview-locator -- draw the camera's view rectangle on the pip; drag pans.
  function pipDraw() {
    const cv = $("piploc"), img = $("workareaimg");
    if (!cv || !img || !img.complete || !HAWORTH_RECT || sel.value !== "moon") return;
    cv.width = img.clientWidth || 1; cv.height = img.clientHeight || 1;
    const ctx = cv.getContext("2d"); ctx.clearRect(0, 0, cv.width, cv.height);
    const vr = viewer.camera.computeViewRectangle(ellipsoid);
    if (!vr) return;
    // Cesium Rectangle fields are RADIANS -- consistent here (vr is radians too)
    const W = HAWORTH_RECT.west, E = HAWORTH_RECT.east, S = HAWORTH_RECT.south, N = HAWORTH_RECT.north;
    const u = (lon) => (lon - W) / (E - W), v = (lat) => (N - lat) / (N - S);
    // the matplotlib preview has margins: the PLOT box is approx the central 78% (axes labels
    // around it) -- calibrated against the figure's known layout, disclosed approximation
    const M = { l: 0.125, r: 0.04, t: 0.06, b: 0.11 };
    const px = (uu) => (M.l + uu * (1 - M.l - M.r)) * cv.width;
    const py = (vv) => (M.t + vv * (1 - M.t - M.b)) * cv.height;
    const x0 = px(Math.max(0, u(vr.west))), x1 = px(Math.min(1, u(vr.east)));
    const y0 = py(Math.max(0, v(vr.north))), y1 = py(Math.min(1, v(vr.south)));
    if (x1 - x0 >= cv.width * 0.95 && y1 - y0 >= cv.height * 0.95) return;   // zoomed out: no rect
    ctx.strokeStyle = SETTINGS.gridcolor || "#39ff14"; ctx.lineWidth = 2;
    ctx.strokeRect(x0, y0, Math.max(6, x1 - x0), Math.max(6, y1 - y0));
  }
  let PIP_DRAG = false;
  function pipPan(e) {
    const cv = $("piploc"), r = cv.getBoundingClientRect();
    const M = { l: 0.125, r: 0.04, t: 0.06, b: 0.11 };
    let uu = ((e.clientX - r.left) / r.width - M.l) / (1 - M.l - M.r);
    let vv = ((e.clientY - r.top) / r.height - M.t) / (1 - M.t - M.b);
    uu = Math.min(1, Math.max(0, uu)); vv = Math.min(1, Math.max(0, vv));
    // RADIANS -> degrees before fromDegrees (the first cut fed radians in -- camera flew to ~0°)
    const W = Cesium.Math.toDegrees(HAWORTH_RECT.west), E = Cesium.Math.toDegrees(HAWORTH_RECT.east);
    const S = Cesium.Math.toDegrees(HAWORTH_RECT.south), N = Cesium.Math.toDegrees(HAWORTH_RECT.north);
    const lon = W + uu * (E - W), lat = N - vv * (N - S);
    const h = Math.max(4000, viewer.camera.positionCartographic.height);
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(lon, lat, h, ellipsoid) });
  }
  const pipCv = $("piploc");
  if (pipCv) {
    pipCv.addEventListener("pointerdown", (e) => { PIP_DRAG = true; pipCv.setPointerCapture(e.pointerId);
      pipCv.style.cursor = "grabbing"; pipPan(e); });
    pipCv.addEventListener("pointermove", (e) => { if (PIP_DRAG) pipPan(e); });
    pipCv.addEventListener("pointerup", () => { PIP_DRAG = false; pipCv.style.cursor = "grab"; });
  }
  viewer.camera.changed.addEventListener(pipDraw);
  setInterval(pipDraw, 1500);                              // catches img-load + resize
  viewer.camera.changed.addEventListener(updateScale);
  viewer.camera.percentageChanged = 0.01;
  setTimeout(updateScale, 1200);                           // initial paint (camera.changed needs motion)

  // THE PRIMARY SITE ON THE GLOBE: the committed Haworth tile at its true selenographic footprint
  // (server-inverse-projected from the LOLA polar-stereographic bounds; Aaron: "doesn't overlay
  // the haworth site -- this is the primary location").
  fetch("/dem/georef").then((r) => r.json()).then((g) => {
    if (!g.ok || !viewer) return;
    const ll = [];
    g.corners.forEach((p) => { ll.push(p.lon, p.lat); });
    HAWORTH_CENTER = g.center;
    const lats = g.corners.map((p) => p.lat), lons = g.corners.map((p) => p.lon);
    HAWORTH_RECT = Cesium.Rectangle.fromDegrees(Math.min(...lons), Math.min(...lats),
                                                Math.max(...lons), Math.max(...lats));
    applyDefaultsOnceReady();                              // #63: fires once BOTH sides are ready
    HAWORTH_ENTITIES.push(viewer.entities.add({
      name: "Haworth work area",
      // OUTLINE ONLY -- the imagery drape (server-reprojected clean hillshade) carries the
      // picture; this polygon was still painting the OLD matplotlib preview figure on top
      // (the rotated axes Aaron kept seeing -- found via his 2nd screenshot).
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArray(ll, ellipsoid),
        material: Cesium.Color.fromCssColorString("#e8273f").withAlpha(0.04),
        outline: true, outlineColor: Cesium.Color.fromCssColorString("#e8273f"),
      },
    }));
    HAWORTH_ENTITIES.push(viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(g.center.lon, g.center.lat, 0, ellipsoid),
      label: { text: "HAWORTH WORK AREA", font: "11px Orbitron, sans-serif",
               fillColor: Cesium.Color.fromCssColorString("#e8273f"),
               pixelOffset: new Cesium.Cartesian2(0, -18), showBackground: true,
               backgroundColor: Cesium.Color.fromCssColorString("#0a0a0cdd") },
    }));
    setMoonOverlaysVisible(sel.value === "moon");
  }).catch(() => {});
  drawGraticule();                                         // default-on, every body
  // #58: EVERY registry site linked on the globe like Haworth (marker + label; click = jump)
  fetch("/sites").then((r) => r.json()).then((j) => {
    if (!j.ok || !viewer) return;
    j.sites.forEach((s) => {
      if (s.name === "haworth") return;                    // Haworth has the footprint already
      SITE_MARKERS.push({ site: s, ent: viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(s.lon, s.lat, 0, ellipsoid),
        point: { pixelSize: 7, color: Cesium.Color.fromCssColorString(s.imported ? "#3fa34d" : "#e0b300"),
                 outlineColor: Cesium.Color.BLACK, outlineWidth: 1 },
        label: { text: s.label + (s.imported ? "" : " (no DEM)"), font: "10px Orbitron, sans-serif",
                 fillColor: Cesium.Color.fromCssColorString("#c7d2e3"),
                 pixelOffset: new Cesium.Cartesian2(0, -14), showBackground: true,
                 backgroundColor: Cesium.Color.fromCssColorString("#0a0a0cbb"),
                 distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 2.0e6) },
      }) });
    });
  }).catch(() => {});
}
// #40/#41: the QGIS edit session -- camera frozen, clicks draw, explicit done restores.
let EDIT = { on: false, tool: null };
const ANNOTATIONS = [];                                    // note pins {x, y, text} (site frame)
const EDIT_PINS = [];                                      // #61: VISIBLE markers for edit placements
function setEdit(on) {
  EDIT.on = on; EDIT.tool = null;
  const c = viewer && viewer.scene.screenSpaceCameraController;
  if (c) { c.enableRotate = c.enableTranslate = c.enableZoom = c.enableTilt = c.enableLook = !on; }
  $("edittools").style.display = on ? "" : "none";
  $("editmode").style.display = on ? "none" : "";
  if ($("editstate")) $("editstate").textContent = on ? "LOCKED · pick a tool" : "";
}
function dropPin(lat, lon, text, color, ref) {             // #64: pins carry their FEATURE ref
  const pin = viewer.entities.add({
    position: Cesium.Cartesian3.fromDegrees(lon, lat, 0, ellipsoid),
    point: { pixelSize: 8, color: Cesium.Color.fromCssColorString(color),
             outlineColor: Cesium.Color.BLACK, outlineWidth: 1 },
    label: { text, font: "10px Orbitron, sans-serif",
             fillColor: Cesium.Color.fromCssColorString("#c7d2e3"),
             pixelOffset: new Cesium.Cartesian2(0, -14), showBackground: true,
             backgroundColor: Cesium.Color.fromCssColorString("#0a0a0cbb") },
  });
  EDIT_PINS.push(pin);
  if (ref) PIN_REFS.set(pin, ref);
  return pin;
}
const PIN_REFS = new Map();                                // pin entity -> {kind, obj}
let SELECTED_PIN = null;
function deleteSelectedPin() {                             // #64: Delete removes feature + pin
  if (!SELECTED_PIN) return;
  const ref = PIN_REFS.get(SELECTED_PIN);
  if (ref) {
    if (ref.kind === "order") { const i = ORDERS.indexOf(ref.obj); if (i >= 0) ORDERS.splice(i, 1); }
    if (ref.kind === "keepout") { const i = KEEPOUTS.indexOf(ref.obj); if (i >= 0) KEEPOUTS.splice(i, 1); }
    if (ref.kind === "note") { const i = ANNOTATIONS.indexOf(ref.obj); if (i >= 0) ANNOTATIONS.splice(i, 1); }
  }
  viewer.entities.remove(SELECTED_PIN);
  const k = EDIT_PINS.indexOf(SELECTED_PIN); if (k >= 0) EDIT_PINS.splice(k, 1);
  PIN_REFS.delete(SELECTED_PIN); SELECTED_PIN = null;
  renderQueue(); setQ("feature deleted");
}
document.addEventListener("keydown", (e) => {
  if ((e.key === "Delete" || e.key === "Backspace") && SELECTED_PIN &&
      !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
    e.preventDefault(); deleteSelectedPin();
  }
});
async function editPlace(lat, lon) {
  if (!EDIT.tool) { $("editstate").textContent = "LOCKED · pick a tool first"; return; }
  const r = await fetch(`/dem/site_xy?lat=${lat}&lon=${lon}`);
  const d = await r.json();
  if (!d.ok) { $("editstate").textContent = "outside the mapped tile"; return; }
  if (EDIT.tool === "goto") {
    snapshotAuthoring();
    const n = ORDERS.filter((o) => o.kind === "goto").length + 1;
    const wp = { action: `wp${n}`, kind: "goto", x: d.x_m, y: d.y_m };
    ORDERS.push(wp);
    dropPin(lat, lon, `wp${n} (${d.x_m}, ${d.y_m})`, "#e8273f", { kind: "order", obj: wp });
    renderQueue(); $("editstate").textContent = `wp${n} @ site ${d.x_m}, ${d.y_m} m`;
  } else if (EDIT.tool === "keepout") {
    snapshotAuthoring();
    const ko = { x: d.x_m, y: d.y_m, r: 8 };
    KEEPOUTS.push(ko);
    dropPin(lat, lon, `keep-out r8 (${d.x_m}, ${d.y_m})`, "#e0564b", { kind: "keepout", obj: ko });
    if (typeof renderKeepouts === "function") renderKeepouts();
    drawPlan(); $("editstate").textContent = `keep-out @ ${d.x_m}, ${d.y_m} m (r 8)`;
  } else if (EDIT.tool === "note") {
    const text = prompt("note text:") || "";
    if (text) { const an = { x: d.x_m, y: d.y_m, text };
      ANNOTATIONS.push(an);
      dropPin(lat, lon, `📝 ${text.slice(0, 24)}`, "#e0b300", { kind: "note", obj: an });
      $("editstate").textContent = `note @ ${d.x_m}, ${d.y_m} m`; drawPlan(); }
  }
}
// #54 follow-up (Aaron: "default to on -- no matter where we are looking on bodies"): a global
// 10-degree graticule on EVERY body, same color setting as the site grid.
let GRATICULE = [];
const SITE_MARKERS = [];                                   // {site, ent} -- NOT Haworth entities
                                                           // (the bug: markers in HAWORTH_ENTITIES
                                                           // made every site click jump to Haworth)
function drawGraticule() {
  if (!viewer) return;
  GRATICULE.forEach((e) => viewer.entities.remove(e));
  GRATICULE = [];
  if (LAYER_ON.grid === false) return;
  const col = Cesium.Color.fromCssColorString(SETTINGS.gridcolor || "#39ff14").withAlpha(0.25);
  for (let lat = -80; lat <= 80; lat += 10) {
    const pts = [];
    for (let lon = -180; lon <= 180; lon += 5) pts.push(lon, lat);
    GRATICULE.push(viewer.entities.add({ polyline: {
      positions: Cesium.Cartesian3.fromDegreesArray(pts, ellipsoid),
      width: 1, material: col } }));
  }
  for (let lon = -180; lon < 180; lon += 10) {
    const pts = [];
    for (let lat = -85; lat <= 85; lat += 5) pts.push(lon, lat);
    GRATICULE.push(viewer.entities.add({ polyline: {
      positions: Cesium.Cartesian3.fromDegreesArray(pts, ellipsoid),
      width: 1, material: col } }));
  }
}
let HAWORTH_CENTER = null;
let HAWORTH_RECT = null;                                   // Cesium.Rectangle of the tile footprint
const GLOBE_LAYERS = {};                                   // key -> Cesium ImageryLayer on the BIG map
const HAWORTH_ENTITIES = [];                               // the footprint polygon + label (MOON-ONLY)
function setMoonOverlaysVisible(on) {                      // body-scope: Haworth exists on the Moon
  HAWORTH_ENTITIES.forEach((e) => { e.show = on; });
  if (!on) Object.keys(GLOBE_LAYERS).forEach((k) => globeLayer(k, "", false));
}

// #51 (Aaron): basemaps STACK -- multiple simultaneous imagery layers with per-layer opacity,
// independent of the analysis layers. The dropdown ADDS; cards manage the stack.
const BASEMAP_STACK = [];                                  // [{idx, layer}]
function applyLayer(key, idx, stack) {
  const L = BODIES[key].layers[idx];
  if (!stack) {                                            // body (re)load: reset to this base
    viewer.imageryLayers.removeAll();
    BASEMAP_STACK.length = 0;
    Object.keys(GLOBE_LAYERS).forEach((k) => delete GLOBE_LAYERS[k]);
  }
  if (BASEMAP_STACK.some((b) => b.idx === idx)) return;    // already stacked
  const o = { url: L.url, maximumLevel: L.maxLevel, tileWidth: L.tile, tileHeight: L.tile, credit: L.credit };
  if (L.geographic)
    o.tilingScheme = new Cesium.GeographicTilingScheme({ numberOfLevelZeroTilesX: 2, numberOfLevelZeroTilesY: 1 });
  const lyr = viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider(o));
  BASEMAP_STACK.push({ idx, layer: lyr });
  if (!stack && BODIES[key] === BODIES.moon && HAWORTH_RECT) {
    globeLayer("dem", "/dem/hillshade.png", LAYER_ON.dem !== false);
    GIS_RASTERS.forEach((k) => { if (LAYER_ON[k]) applyLayerToggle(k, true); });
  }
  renderWorkbench();
}

function flyTo(lat, lon, height) {
  const h = height || ellipsoid.maximumRadius * 0.4;
  viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(lon, lat, h, ellipsoid), duration: 1.2 });
}

function setPicked(lat, lon) {
  picked = { lat, lon };
  document.getElementById("out").textContent = `picked  lat ${lat.toFixed(3)}°  lon ${lon.toFixed(3)}°`;
  if (marker) viewer.entities.remove(marker);
  marker = viewer.entities.add({
    position: Cesium.Cartesian3.fromDegrees(lon, lat, 0, ellipsoid),
    point: { pixelSize: 11, color: Cesium.Color.CYAN, outlineColor: Cesium.Color.BLACK, outlineWidth: 2 },
  });
}

// --- UI wiring -------------------------------------------------------------------------------
const sel = document.getElementById("body");
for (const [k, v] of Object.entries(BODIES)) {
  const o = document.createElement("option"); o.value = k; o.textContent = v.name; sel.appendChild(o);
}
const $ = (id) => document.getElementById(id);

// SEC-04: HTML-escape a server- or user-derived string before it is interpolated into an innerHTML
// template (option lists, labels, error text). Escaping &<>"' neutralizes both element injection and
// double/single-quoted attribute breakout, so an `<img onerror>`-style value renders as inert text.
// (New DOM construction should still prefer the el() builder below; esc() hardens the existing sinks.)
const _ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => _ESC[c]); }

// S-02: safe DOM builder. Server data (operator emails, roles, mission math labels) is NEVER
// concatenated into innerHTML/attributes -- it goes in via textContent / setAttribute, so an
// `<img onerror>`-style value renders as inert text. el(tag, {props/attrs}, ...children).
function el(tag, attrs, ...children) {
  const n = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "text") n.textContent = v;
    else if (k === "style") n.setAttribute("style", v);
    else if (k === "class") n.className = v;
    else if (k === "html") throw new Error("el(): innerHTML is forbidden (S-02)");
    else if (k.startsWith("on") && typeof v === "function") n[k] = v;
    else if (k.startsWith("data-") || k === "colspan" || k === "title" || k === "disabled")
      n.setAttribute(k, v);
    else n.setAttribute(k, v);            // value/type/etc. -- still via setAttribute, never HTML
  }
  for (const c of children) {
    if (c == null) continue;
    n.appendChild(typeof c === "string" || typeof c === "number"
      ? document.createTextNode(String(c)) : c);
  }
  return n;
}

// --- view tabs: swap the stage between Plan (globe) / Perception (render) / Metrics (telemetry) / Report.
// The globe (#cesium) stays mounted under the panes (no Cesium re-init); the active pane covers it.
let VIEW = "plan";
const VIEW_PANE = { perception: "renderpanel", metrics: "execview", nav: "navview", report: "pane-report",
                    validation: "pane-validation", api: "pane-api", server: "pane-server", config: "pane-config",
                    admin: "pane-admin", settings: "pane-settings" };
const _PANE_LOADED = {};
const SYSTEM_VIEWS = ["validation", "api", "server", "config"];
let LAST_SYSTEM_VIEW = "server";
function setView(name) {
  if (name === "system") name = LAST_SYSTEM_VIEW;          // #55: the cluster remembers its sub-tab
  if (SYSTEM_VIEWS.includes(name)) LAST_SYSTEM_VIEW = name;
  VIEW = name;
  document.querySelectorAll(".vtab").forEach((b) => b.classList.toggle("active",
    b.dataset.view === name || (b.dataset.view === "system" && SYSTEM_VIEWS.includes(name))));
  let sysbar = document.getElementById("sysbar");
  if (SYSTEM_VIEWS.includes(name)) {
    if (!sysbar) {
      sysbar = document.createElement("div");
      sysbar.id = "sysbar";
      sysbar.style.cssText = "position:absolute;top:6px;right:12px;z-index:40;display:flex;gap:4px";
      SYSTEM_VIEWS.forEach((v) => {
        const b = document.createElement("button");
        b.className = "site"; b.style.fontSize = "10px";
        b.textContent = v.toUpperCase(); b.dataset.sys = v;
        b.onclick = () => setView(v);
        sysbar.appendChild(b);
      });
      document.getElementById("viewarea").appendChild(sysbar);
    }
    sysbar.style.display = "flex";
    sysbar.querySelectorAll("button").forEach((b) =>
      b.style.borderColor = b.dataset.sys === name ? "var(--accent)" : "var(--line)");
  } else if (sysbar) { sysbar.style.display = "none"; }
  for (const [v, id] of Object.entries(VIEW_PANE)) $(id).classList.toggle("active", v === name);
  if (name === "plan") { showSiteDem(); if (viewer) viewer.resize(); }   // restore the Plan inset + keep globe crisp
  else $("workarea").classList.remove("show");                            // the inset belongs to the Plan tab
  // the EDIT toolbar is a PLAN tool (Aaron's System screenshot: it stacked on the sub-bar)
  const et = document.getElementById("edittoolbar");
  if (et) et.style.display = (name === "plan") ? "flex" : "none";
  const sb = document.getElementById("scalebox");          // the scale belongs to the map
  if (sb) sb.style.display = (name === "plan") ? "block" : "none";
  if (name !== "plan" && EDIT.on) setEdit(false);          // leaving Plan ends the edit session
  loadPane(name);
}
document.querySelectorAll(".vtab").forEach((b) => { b.onclick = () => setView(b.dataset.view); });

// ---- UI-1/UI-2 (PRD 16.5): operator display settings, persisted ------------------------------
function applySettings(s) {
  document.body.classList.toggle("light", s.theme === "light");
  document.documentElement.style.setProperty("--fontpx", s.fontpx + "px");
  const t = $("set-theme"), f = $("set-font"), fv = $("set-fontv");
  if (t) t.value = s.theme;
  if (f) f.value = s.fontpx;
  if (fv) fv.textContent = s.fontpx + " px";
}
function getCookie(name) {                                // SEC-01: read a readable cookie (e.g. the CSRF token)
  const m = document.cookie.match("(?:^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
  return m ? decodeURIComponent(m[1]) : "";
}
function apiHeaders(extra) {
  // SEC-01: the operator session is an HttpOnly cookie (sent automatically, same-origin), NOT a token in
  // localStorage. Mutating requests echo the readable CSRF cookie back as a double-submit header. An
  // automation key, when present, is held IN MEMORY only (AUTH.apikey) and never persisted.
  const h = Object.assign({ "Content-Type": "application/json" }, extra || {});
  const csrf = getCookie("stewie_csrf");
  if (csrf) h["X-CSRF-Token"] = csrf;
  if (AUTH.apikey) h["X-API-Key"] = AUTH.apikey;
  return h;
}
function loadSettings() {
  let s = { theme: "dark", fontpx: 13 };                  // SEC-01: no credential fields persisted
  try { s = { ...s, ...(JSON.parse(localStorage.getItem("stewie_settings") || "{}")) }; } catch (e) {}
  return s;
}
function saveSettings(s) {
  // SEC-01: never persist credentials -- strip any token/key before writing to localStorage.
  try { const { optoken, apikey, ...safe } = s || {};
    localStorage.setItem("stewie_settings", JSON.stringify(safe)); } catch (e) {}
}
// UI-5: stamp an element as freshly-updated; the 5 s sweeper walks every stamped element and
// applies the P4 thresholds (fresh < 20 s, stale < 60 s, dead beyond).
function markFresh(el) { if (el) { el.dataset.fresh = "ok"; el.dataset.freshTs = String(Date.now()); } }
setInterval(() => {
  document.querySelectorAll("[data-fresh]").forEach((el) => {
    const age = (Date.now() - parseInt(el.dataset.freshTs || "0", 10)) / 1000;
    el.dataset.fresh = age < 20 ? "ok" : (age < 60 ? "stale" : "dead");
  });
}, 5000);

// S-1 (GIS pathway): collapsible sidebar sections -- each h3 + its block becomes <details>,
// default COLLAPSED except the active workflow step (Build queue); open-state persisted.
(function buildContents() {                                // S-2: the ArcGIS Contents pane
  const tgt = document.getElementById("contents-pane"); if (!tgt) return;
  const lp = document.getElementById("layerpanel");
  const sc = document.getElementById("suncap");
  if (lp) tgt.appendChild(lp);                             // live nodes move WITH their handlers
  if (sc) tgt.appendChild(sc);
})();

(function collapseSidebar() {
  // BUGFIX (Aaron, twice): the sections are wrapped in <section> tags -- the old walker looked
  // for bare H3 children of the panel, found none, and silently did NOTHING. Walk the sections.
  const panel = document.getElementById("panel"); if (!panel) return;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("stewie_sections") || "{}"); } catch (e) {}
  // split on EVERY h3 (Aaron's catch: sections hold MULTIPLE h3 groups -- Site/Catalog/Telemetry
  // were riding inside another group's collapsible instead of getting their own)
  panel.querySelectorAll("section").forEach((sec) => {
    if (!sec.querySelector("h3")) return;
    const kids = Array.from(sec.childNodes);
    sec.textContent = "";
    let det = null, body = null;
    kids.forEach((node) => {
      if (node.tagName === "H3") {
        det = document.createElement("details");
        const key = node.textContent.trim().slice(0, 28);
        det.open = saved[key] !== undefined ? !!saved[key] : /queue|plan —/i.test(key);
        const sum = document.createElement("summary");
        sum.appendChild(node);
        det.appendChild(sum);
        body = document.createElement("div");
        det.appendChild(body);
        det.addEventListener("toggle", () => {
          saved[key] = det.open;
          try { localStorage.setItem("stewie_sections", JSON.stringify(saved)); } catch (e) {}
        });
        sec.appendChild(det);
      } else if (body) {
        body.appendChild(node);
      } else {
        sec.appendChild(node);                             // pre-h3 content stays put
      }
    });
  });
  // SUB-collapsibles (Aaron): the .step labels inside a group (4-Plan's A..F) become nested
  // <details>; authoring steps B/C open by default, the rest closed; state persisted.
  panel.querySelectorAll("details > div").forEach((groupBody) => {
    if (!groupBody.querySelector(".step")) return;
    const kids = Array.from(groupBody.childNodes);
    groupBody.textContent = "";
    let det = null, body = null;
    kids.forEach((node) => {
      if (node.classList && node.classList.contains("step")) {
        det = document.createElement("details");
        det.className = "substep";
        const key = "sub:" + node.textContent.trim().slice(0, 18);
        det.open = saved[key] !== undefined ? !!saved[key] : /^(B|C)/.test(node.textContent.trim());
        const sum = document.createElement("summary");
        sum.appendChild(node);
        det.appendChild(sum);
        body = document.createElement("div");
        det.appendChild(body);
        det.addEventListener("toggle", () => {
          saved[key] = det.open;
          try { localStorage.setItem("stewie_sections", JSON.stringify(saved)); } catch (e) {}
        });
        groupBody.appendChild(det);
      } else if (body) {
        body.appendChild(node);
      } else {
        groupBody.appendChild(node);
      }
    });
  });
})();

const SETTINGS = loadSettings();
// SEC-01 migration: delete any legacy bearer token / raw API key an OLDER build persisted in
// localStorage. The session is now an HttpOnly cookie; credentials never touch localStorage again.
(function scrubLegacyCreds() {
  try {
    const raw = JSON.parse(localStorage.getItem("stewie_settings") || "{}");
    if ("optoken" in raw || "apikey" in raw) {
      delete raw.optoken; delete raw.apikey;
      localStorage.setItem("stewie_settings", JSON.stringify(raw));
    }
  } catch (e) {}
  delete SETTINGS.optoken; delete SETTINGS.apikey;        // and from the in-memory copy
})();

// #65 (Aaron): the lander stays placed (per-browser + rides the mission document) and the
// rover's last executed pose is remembered. Declared EARLY -- wiring below reads these at load.
let LANDER_P = { x: 0, y: 0 };
try { Object.assign(LANDER_P, JSON.parse(localStorage.getItem("stewie_lander") || "{}")); } catch (e) {}
let LAST_POSE = null;
try { LAST_POSE = JSON.parse(localStorage.getItem("stewie_last_pose") || "null"); } catch (e) {}
function setLander(x, y) {
  LANDER_P.x = Math.round(x * 10) / 10; LANDER_P.y = Math.round(y * 10) / 10;
  if (typeof LANDER !== "undefined") { LANDER.x = LANDER_P.x; LANDER.y = LANDER_P.y; }
  try { localStorage.setItem("stewie_lander", JSON.stringify(LANDER_P)); } catch (e) {}
  if (typeof drawPlan === "function") drawPlan();
}
function recordPose(x, y) {
  LAST_POSE = { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10, ts: Date.now() };
  try { localStorage.setItem("stewie_last_pose", JSON.stringify(LAST_POSE)); } catch (e) {}
  const el = $("lastpose");
  if (el) el.textContent = `rover last known: ${LAST_POSE.x}, ${LAST_POSE.y} m`;
}
applySettings(SETTINGS);
if ($("set-theme")) $("set-theme").onchange = () => {
  SETTINGS.theme = $("set-theme").value; saveSettings(SETTINGS); applySettings(SETTINGS);
};
if ($("set-apikey")) {
  $("set-apikey").value = "";                             // SEC-01: never prefilled from storage
  // SEC-01: the automation key lives IN MEMORY for this session only (never written to localStorage).
  $("set-apikey").onchange = () => { AUTH.apikey = $("set-apikey").value.trim(); };
}

// ---- #117: operator access (sign in / request access / set password) + the director admin panel ----
// SEC-01: apikey is an in-memory automation key (never persisted); the operator session is a cookie.
const AUTH = { role: null, identity: null, apikey: "" };
function authMsg(t, ok) { const m = $("auth-msg"); if (m) { m.textContent = t || "";
  m.style.color = ok ? "var(--accent)" : "var(--bad,#ff6b6b)"; } }
function authMode(mode) {
  ["login", "register", "setpw"].forEach((k) => { const el = $("auth-" + k);
    if (el) el.style.display = (k === mode) ? "flex" : "none"; });
  const lt = $("auth-tab-login"), rt = $("auth-tab-register"), tabs = $("auth-tabs");
  if (lt && rt) { lt.classList.toggle("active", mode === "login"); rt.classList.toggle("active", mode === "register"); }
  if (tabs) tabs.style.display = (mode === "setpw") ? "none" : "flex";
  authMsg("");
}
function openAuth(mode) { const m = $("authmodal"); if (!m) return; m.style.display = "flex"; authMode(mode || "login"); }
function closeAuth() { const m = $("authmodal"); if (m) m.style.display = "none"; }
let _authPromptTs = 0;
function flashSignInNeeded() {                            // a 401 surfaced -> nudge sign-in (debounced)
  // SEC-01: a live session shows as the readable CSRF cookie; an automation key lives in memory.
  if (getCookie("stewie_csrf") || AUTH.apikey) return;    // already have creds -> the 401 is something else
  const now = Date.now(); if (now - _authPromptTs < 8000) return; _authPromptTs = now;
  openAuth("login"); authMsg("Sign in to perform this action.", true);
}
(function wrapFetch() {                                    // observe 401s on same-origin API calls; no behavior change
  const of = window.fetch;
  window.fetch = async function (...a) {
    const res = await of.apply(this, a);
    try { const u = typeof a[0] === "string" ? a[0] : ((a[0] && a[0].url) || "");
      if (res.status === 401 && u.charAt(0) === "/") flashSignInNeeded(); } catch (e) {}
    return res;
  };
})();
async function refreshAuthState() {
  const st = $("set-opstate");
  // SEC-01: the session is an HttpOnly cookie -- we cannot read it, but the readable CSRF cookie (set
  // and cleared alongside it) tells us a session likely exists. With neither that nor an in-memory key,
  // skip /auth/me so an unauthenticated load does not pop the sign-in prompt via the 401 observer.
  if (!getCookie("stewie_csrf") && !AUTH.apikey) {
    AUTH.role = null; AUTH.identity = null;
    if (st) st.textContent = "not signed in";
    const av = $("vtab-admin"); if (av) av.style.display = "none"; return; }
  try {
    const r = await fetch("/auth/me", { headers: apiHeaders() });
    if (!r.ok) throw 0;
    const j = await r.json(); AUTH.role = j.role; AUTH.identity = j.identity;
    if (st) st.textContent = "signed in: " + j.identity + " (" + j.role + ")";
    const av = $("vtab-admin"); if (av) av.style.display = (j.role === "director") ? "inline-block" : "none";
  } catch (e) { AUTH.role = null; AUTH.identity = null;
    if (st) st.textContent = "not signed in";
    const av = $("vtab-admin"); if (av) av.style.display = "none"; }
}
async function doLogin() {
  const email = $("auth-email").value.trim(), pass = $("auth-pass").value;
  if (!email) { authMsg("email required"); return; }
  const headers = { "Content-Type": "application/json" }, body = { email };
  if (pass) { body.password = pass; }
  else if (AUTH.apikey) { headers["X-API-Key"] = AUTH.apikey; }   // bootstrap: in-memory deploy key, no password yet
  else { authMsg("enter your password, or for first-time setup save the deploy key under 'automation key' below"); return; }
  // SEC-01: the server sets the HttpOnly session + CSRF cookies on success; we DON'T store the token.
  const r = await fetch("/auth/login", { method: "POST", headers, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (r.ok && j.ok) {
    SETTINGS.opemail = email; saveSettings(SETTINGS); AUTH.role = j.role;
    if (j.must_set_password) { $("auth-setpw-who").textContent = j.operator; openAuth("setpw");
      authMsg("Signed in; set a password to finish.", true); }
    else { authMsg("Signed in.", true); await refreshAuthState(); setTimeout(closeAuth, 500); }
  } else { authMsg(j.error || ("sign-in refused (" + r.status + ")")); }
}
async function doRegister() {
  const email = $("auth-remail").value.trim(), p = $("auth-rpass").value, p2 = $("auth-rpass2").value;
  if (p !== p2) { authMsg("passwords do not match"); return; }
  const r = await fetch("/auth/register", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password: p }) });
  const j = await r.json().catch(() => ({}));
  if (r.ok && j.ok) authMsg("Request received — a director will approve your account.", true);
  else authMsg(j.error || ("registration refused (" + r.status + ")"));
}
async function doSetPassword() {
  const p = $("auth-newpass").value, p2 = $("auth-newpass2").value;
  if (p !== p2) { authMsg("passwords do not match"); return; }
  const r = await fetch("/auth/password", { method: "POST", headers: apiHeaders(),
    body: JSON.stringify({ new_password: p }) });
  const j = await r.json().catch(() => ({}));
  if (r.ok && j.ok) { authMsg("Password set.", true); await refreshAuthState(); setTimeout(closeAuth, 600); }
  else authMsg(j.error || ("could not set password (" + r.status + ")"));
}
(function wireAuth() {
  const bind = (id, fn) => { const e = $(id); if (e) e.onclick = fn; };
  bind("auth-tab-login", () => authMode("login"));
  bind("auth-tab-register", () => authMode("register"));
  bind("auth-do-login", doLogin);
  bind("auth-do-register", doRegister);
  bind("auth-do-setpw", doSetPassword);
  bind("auth-dismiss", (ev) => { ev.preventDefault(); closeAuth(); });
  // SEC-01: the automation key is held in memory for THIS session only (never written to localStorage).
  bind("auth-save-key", () => { AUTH.apikey = $("auth-apikey").value.trim();
    if ($("set-apikey")) $("set-apikey").value = AUTH.apikey; authMsg("Automation key set for this session.", true); });
  bind("set-account", () => openAuth("login"));
  fetch("/auth/config").then((r) => r.json()).then((c) => {
    if (!c.operator_login) { const b = $("set-account"); if (b) b.disabled = true; }
    if (!c.registration_open) { const t = $("auth-tab-register"); if (t) t.style.display = "none"; }
  }).catch(() => {});
})();
async function renderAdmin() {
  const rows = $("adminrows"); if (!rows) return;
  try {
    const r = await fetch("/admin/operators", { headers: apiHeaders() });
    if (!r.ok) { rows.replaceChildren(el("tr", null, el("td", { colspan: "5", style: "opacity:.6" }, "director sign-in required"))); return; }
    const ops = (await r.json()).operators || [];
    rows.replaceChildren();
    if (!ops.length) {
      rows.appendChild(el("tr", null, el("td", { colspan: "5", style: "opacity:.6" }, "no accounts yet")));
    } else {
      // S-02: build each row from DOM nodes; the server-supplied email/role/status enter only via
      // textContent and data-* attributes (el()), so an `<img onerror>` email is rendered as text.
      for (const o of ops) {
        const ll = o.last_login ? new Date(o.last_login * 1000).toLocaleString() : "—";
        const flip = o.role === "director" ? "operator" : "director";
        const mkbtn = (act, label, extra) =>
          el("button", { "class": "site", "data-act": act, "data-email": o.email, ...(extra || {}) }, label);
        const actCell = el("td", { style: "display:flex;gap:4px;flex-wrap:wrap" });
        if (o.status === "pending") actCell.appendChild(mkbtn("approve", "approve"));
        actCell.appendChild(mkbtn("role", "→" + flip, { "data-role": flip }));
        if (o.status !== "revoked") actCell.appendChild(mkbtn("revoke", "revoke"));
        actCell.appendChild(mkbtn("reset", "reset pw"));
        actCell.appendChild(mkbtn("delete", "delete"));
        const sc = o.status === "active" ? "var(--accent)" : (o.status === "pending" ? "#e0a800" : "var(--muted)");
        rows.appendChild(el("tr", null,
          el("td", null, o.email),
          el("td", null, o.role),
          el("td", null, el("span", { "class": "badge", style: "color:" + sc }, o.status)),
          el("td", null, ll),
          actCell));
      }
    }
    rows.querySelectorAll("button[data-act]").forEach((b) =>
      b.onclick = () => adminAction(b.dataset.act, b.dataset.email, b.dataset.role));
  } catch (e) {
    rows.replaceChildren(el("tr", null, el("td", { colspan: "5", style: "opacity:.6" }, "unavailable")));
  }
  try {
    const e = await fetch("/events?n=40", { headers: apiHeaders() });
    if (e.ok) { const evs = (await e.json()).events || [];
      $("adminaudit").textContent = evs.map((x) => new Date(x.ts * 1000).toLocaleTimeString() +
        "  " + x.actor + "  " + x.action + "  " + (x.target || "")).join("\n") || "—"; }
  } catch (e) {}
}
async function adminAction(act, email, role) {
  let url, body = null, method = "POST";
  if (act === "approve") { url = "/admin/operators/approve"; body = { email, role: "operator" }; }
  else if (act === "role") { url = "/admin/operators/role"; body = { email, role }; }
  else if (act === "revoke") { if (!confirm("Revoke " + email + "?")) return; url = "/admin/operators/revoke"; body = { email }; }
  else if (act === "reset") { const np = prompt("New password for " + email + " (min 10 chars):"); if (!np) return;
    url = "/admin/operators/reset"; body = { email, new_password: np }; }
  else if (act === "delete") { if (!confirm("Delete " + email + "? This cannot be undone.")) return;
    url = "/admin/operators/" + encodeURIComponent(email); method = "DELETE"; }
  else return;
  const opt = { method, headers: apiHeaders() }; if (body) opt.body = JSON.stringify(body);
  const r = await fetch(url, opt); const j = await r.json().catch(() => ({}));
  if (!r.ok) alert(j.detail || j.error || ("failed (" + r.status + ")"));
  renderAdmin();
}
if ($("admin-refresh")) $("admin-refresh").onclick = renderAdmin;
{ const av = $("vtab-admin"); if (av) av.addEventListener("click", () => setTimeout(renderAdmin, 0)); }
refreshAuthState();
if ($("set-font")) $("set-font").oninput = () => {
  SETTINGS.fontpx = parseInt($("set-font").value, 10); saveSettings(SETTINGS); applySettings(SETTINGS);
};

// lazy-load the engineer/dev/intern panes the first time shown (Server refreshes live each open). All read
// real server endpoints; on file:// or a down server they keep their empty state (no fabricated content).
async function loadPane(name) {
  try {
    if (name === "api") {
      if (!_PANE_LOADED.api) { $("apiframe").src = "/docs"; _PANE_LOADED.api = true; }   // FastAPI Swagger
    } else if (name === "validation" && !_PANE_LOADED.validation) {
      _PANE_LOADED.validation = true;
      const d = await (await fetch("/figures")).json();
      const vs = $("valselect");
      if (d.ok && d.figures.length) {
        vs.innerHTML = d.figures.map((f) => `<option value="${esc(f.url)}">${esc(f.key)}</option>`).join("");  // SEC-04
        $("valempty").style.display = "none";
        const show = () => { $("valimg").src = vs.value; $("valimg").style.display = "block"; };
        vs.onchange = show; show();
      }
    } else if (name === "server") {                                       // live ops view: refresh every open
      const [h, m] = await Promise.all([fetch("/healthz").then((r) => r.json()),
                                        fetch("/metrics").then((r) => r.json())]);
      $("srvout").textContent = "health\n" + JSON.stringify(h, null, 2)
                              + "\n\nmetrics\n" + JSON.stringify(m, null, 2);
    } else if (name === "config" && !_PANE_LOADED.config) {
      _PANE_LOADED.config = true;
      const c = await (await fetch("/config/full")).json();   // #61: the organized one-call state
      const cards = $("cfgcards"); cards.innerHTML = "";
      const card = (title, rows) => {
        const d = document.createElement("div");
        d.style.cssText = "border:1px solid var(--line);border-radius:8px;padding:9px 12px;min-width:200px;font-size:11px;line-height:1.7";
        d.innerHTML = `<b style="font-family:Orbitron,system-ui;font-size:10px;letter-spacing:.1em">${title}</b><br>` +
          rows.map(([k, v]) => `<span style="color:var(--muted)">${k}</span> ${v}`).join("<br>");
        cards.appendChild(d);
      };
      const yn = (b) => b ? "✅" : "—";
      card("SERVER", [["version", c.server.version], ["data dir", c.server.data_dir],
                      ["backup dir", c.server.backup_dir]]);
      card("AUTH", [["API key", yn(c.auth.api_key_set)], ["operator login", yn(c.auth.operator_login)],
                    ["Tailscale trust", yn(c.auth.trust_tailscale)],
                    ["", '<span style="opacity:.6">flags only — secrets never leave the server</span>']]);
      card("DATA", [["sites", `${c.data.sites_imported}/${c.data.sites_total} imported`],
                    ["SPICE kernels", yn(c.data.spice_available)],
                    ["twin snapshots", c.data.twin_snapshots]]);
      $("cfgout").textContent = JSON.stringify(c.overlay, null, 2);
    }
  } catch (e) { /* server not reachable (file://) -> panes keep their placeholder/empty state */ }
}
$("srvrefresh").onclick = () => loadPane("server");

// ---- Navigation view (P1.4): ARGUS estimator surface + articulation-parallax relocalization -----
function navDrawTrajectory(est, base) {
  const cv = $("navplot"), g = cv.getContext("2d");
  g.clearRect(0, 0, cv.width, cv.height);
  const all = est.concat(base), xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
  const minx = Math.min(...xs), maxx = Math.max(...xs), miny = Math.min(...ys), maxy = Math.max(...ys);
  const pad = 26, s = Math.min((cv.width - 2 * pad) / Math.max(1e-6, maxx - minx),
                               (cv.height - 2 * pad) / Math.max(1e-6, maxy - miny));
  const X = (x) => pad + (x - minx) * s, Y = (y) => cv.height - pad - (y - miny) * s;
  const line = (path, color, w) => {
    g.strokeStyle = color; g.lineWidth = w; g.beginPath();
    path.forEach((p, i) => (i ? g.lineTo(X(p[0]), Y(p[1])) : g.moveTo(X(p[0]), Y(p[1]))));
    g.stroke();
  };
  line(base, "#e0a23a", 2); line(est, "#36d1dc", 2);
  g.font = "10px system-ui"; g.fillStyle = "#36d1dc"; g.fillText("— fused estimate", pad, 14);
  g.fillStyle = "#e0a23a"; g.fillText("— dead reckoning", pad + 104, 14);
}
async function navRun() {
  const seg = $("navseg").value, kf = +$("navkf").value || 30;
  $("navrun").disabled = true; $("navrun").textContent = "… running";
  try {
    const r = await fetch("/slam", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ segment: seg, n_keyframes: kf }) });
    const b = await r.json();
    if (!b.ok) { $("navempty").style.display = "none";
      $("navstats").innerHTML = `<span style="color:#e8273f">${esc(b.error || "estimator unavailable")}</span>`;  // SEC-04
      $("navloo").textContent = ""; return; }
    $("navempty").style.display = "none";
    navDrawTrajectory(b.trajectory_xy, b.baseline_xy);
    $("navstats").innerHTML = `fused ATE <b>${b.ate_aligned_m} m</b> · abs drift <b>${b.abs_max_err_m} m</b>`
      + ` vs baseline <b>${b.baseline_abs_max_err_m} m</b> · <b style="color:var(--accent)">${b.reduction_x}× tighter</b>`;
    $("navloo").innerHTML = "leave-one-out (drift increase when removed): "
      + Object.entries(b.leave_one_out).map(([k, v]) => `${k} <b>+${v.contribution_m} m</b>`).join(" · ");
  } catch (e) { $("navstats").innerHTML = `<span style="color:#e8273f">server unreachable</span>`; }
  finally { $("navrun").disabled = false; $("navrun").textContent = "▶ Run estimator"; }
}
async function navCompare() {                          // P3.1: shared-testbed head-to-head (modeled at reported σ)
  const seg = $("navseg").value, kf = +$("navkf").value || 30;
  $("navcmp").disabled = true; $("navcmp").textContent = "… comparing";
  try {
    const r = await fetch("/slam/compare", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ segment: seg, n_keyframes: kf, n_seeds: 8 }) });
    const b = await r.json();
    if (!b.ok) { $("navcmpout").innerHTML = `<span style="color:#e8273f">${esc(b.error || "comparison unavailable")}</span>`; return; }  // SEC-04
    const rows = Object.entries(b.comparison);
    const worst = Math.max(...rows.map(([, v]) => v.mean_m));
    $("navcmpout").innerHTML = "<b>shared-testbed head-to-head</b> — absolute drift, one trajectory, one metric:<br>"
      + rows.map(([k, v]) => {
          const w = Math.max(2, Math.round(180 * v.mean_m / worst));
          const cls = k.includes("ARGUS") ? "#36d1dc" : k.includes("ShadowNav") ? "#e0a23a" : "#888";
          return `<div style="margin:3px 0"><span style="display:inline-block;width:230px">${k}</span>`
            + `<span style="display:inline-block;height:9px;width:${w}px;background:${cls};vertical-align:middle"></span> `
            + `<b>${v.mean_m} m</b> ±${v.ci95_m}</div>`;
        }).join("")
      + `<div style="color:var(--muted);margin-top:3px">${b.modeled} · n=${b.n_seeds} seeds</div>`;
  } catch (e) { $("navcmpout").innerHTML = `<span style="color:#e8273f">server unreachable</span>`; }
  finally { $("navcmp").disabled = false; $("navcmp").textContent = "⚖ Compare approaches"; }
}
function navGate() {                                  // #97 perception gate: should_relocalize(sigma, moving)
  const sig = +$("navsig").value, stand = $("navstand").checked, armed = sig > 2.0 && stand;
  $("navgate").innerHTML = armed
    ? `<span style="color:#36d1dc">● ARMED</span> — σ ${sig.toFixed(1)} m > 2.0 m tolerance, standstill`
    : `<span style="color:var(--muted)">○ not armed</span> — ${stand ? "σ within tolerance (no fix needed)" : "needs a standstill maneuver"}`;
  $("navreloc").disabled = !armed;
  return armed;
}
function navDrawFix(res) {                             // top-down DEM-frame plot of the real fix
  const cv = $("navcov"), g = cv.getContext("2d"); g.clearRect(0, 0, cv.width, cv.height);
  const pts = res.landmarks_xy.concat([res.fix_xy, res.true_xy, res.seed_xy]);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const minx = Math.min(...xs), maxx = Math.max(...xs), miny = Math.min(...ys), maxy = Math.max(...ys);
  const pad = 26, s = Math.min((cv.width - 2 * pad) / Math.max(0.5, maxx - minx),
                               (cv.height - 2 * pad) / Math.max(0.5, maxy - miny));
  const X = (x) => pad + (x - minx) * s, Y = (y) => cv.height - pad - (y - miny) * s;
  g.fillStyle = "#667";                                // matched landmarks (DEM coordinates)
  res.landmarks_xy.forEach((p) => { g.beginPath(); g.arc(X(p[0]), Y(p[1]), 2, 0, 2 * Math.PI); g.fill(); });
  g.strokeStyle = "#36d1dc"; g.lineWidth = 1.5;        // covariance around the fix
  g.beginPath(); g.arc(X(res.fix_xy[0]), Y(res.fix_xy[1]), Math.max(3, res.fix_sigma_m * s), 0, 2 * Math.PI); g.stroke();
  const dot = (p, c) => { g.fillStyle = c; g.beginPath(); g.arc(X(p[0]), Y(p[1]), 4, 0, 2 * Math.PI); g.fill(); };
  dot(res.seed_xy, "#e0a23a"); dot(res.fix_xy, "#36d1dc");      // drifted prior (amber), recovered fix (cyan)
  g.strokeStyle = "#3ad17a"; g.lineWidth = 2;          // truth (green cross)
  const tx = X(res.true_xy[0]), ty = Y(res.true_xy[1]);
  g.beginPath(); g.moveTo(tx - 5, ty); g.lineTo(tx + 5, ty); g.moveTo(tx, ty - 5); g.lineTo(tx, ty + 5); g.stroke();
  g.fillStyle = "#9aa"; g.font = "10px system-ui"; g.fillText("● landmarks  ● drift  ● fix  ✛ true  (DEM frame, m)", 6, 14);
}
async function navReloc() {                            // REAL measured fix on the committed render-pair
  if (!navGate()) return;
  const sig = +$("navsig").value;
  $("navreloc").disabled = true; $("navreloc").textContent = "… capturing";
  try {
    const r = await fetch("/localize/render", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ camera: "front_left", drift_m: sig }) });
    const b = await r.json();
    if (!b.ok) { $("navcovstat").innerHTML = `<span style="color:#e8273f">${esc(b.error)}</span>`; return; }  // SEC-04
    navDrawFix(b);
    $("navcovstat").innerHTML = `<b>real fix</b> (render-pair) · error <b>${b.error_m} m</b> from ${b.drift_m} m drift`
      + ` · σ ${b.fix_sigma_m} m · ${b.n_inliers}/${b.n_features} inliers · features `
      + `${b.range_span_m[0]}–${b.range_span_m[1]} m (inside the TRL-5 rig range) · coordinates in the DEM frame`;
  } catch (e) { $("navcovstat").innerHTML = `<span style="color:#e8273f">server unreachable</span>`; }
  finally { $("navreloc").disabled = false; $("navreloc").textContent = "⌖ Relocalize"; navGate(); }
}
if ($("navrun")) {
  $("navrun").onclick = navRun;
  $("navcmp").onclick = navCompare;
  $("navreloc").onclick = navReloc;
  ["navsig", "navstand"].forEach((id) => { const el = $(id); if (el) { el.oninput = navGate; el.onchange = navGate; } });
  navGate();
}

// PHYSICS loaded from bodies.json (the sim's sysrev-sourced terrain_authority/bodies.py) -> single source
// of truth. phys() prefers the loaded body terramechanics; falls back to embedded BODIES if the file
// isn't served (e.g. file://). So choosing a body LOADS that body's correct terramechanics.
let PHY = null;
function phys(key) {
  const p = PHY && PHY[key], b = BODIES[key];
  return {
    label: b.name,
    g: p ? p.g : b.g,
    density: p ? p.bulk_density : b.density,
    cohesion_pa: p ? p.cohesion_pa : null,
    friction_deg: p ? p.friction_deg : null,
    bekker: p ? p.bekker : null,
    regime: p ? p.bekker_regime : null,
    confidence: p ? p.confidence : null,
  };
}
function showTerra() {
  const p = phys(sel.value);
  const bk = p.bekker ? `Bekker kφ ${(p.bekker.k_phi / 1000).toFixed(0)}k·kc ${p.bekker.k_c}·n ${p.bekker.n}` : "Bekker —";
  const pw = PHY && PHY[sel.value] && PHY[sel.value].ipex_power;   // gravity-SWAPPED IPEx power for this body
  $("terra").textContent =
    `terramechanics  g ${p.g} m/s² · ρ ${p.density} kg/m³`
    + (p.cohesion_pa != null ? ` · c ${p.cohesion_pa} Pa` : "")
    + (p.friction_deg != null ? ` · φ ${p.friction_deg}°` : "")
    + ` · ${bk}` + (p.regime ? ` · ${p.regime}` : "")
    + (pw ? `  ·  IPEx power (g-scaled) drive ${pw.drive_power_w} W (15° ${pw.drive_power_15deg_w} W) · `
            + `system ${pw.system_power_w} W [thermal-survival ${pw.thermal_survival_w}+avionics ${pw.avionics_w}+comms ${pw.comms_w} W]`
            + (pw.thermal_by_env_w && Object.keys(pw.thermal_by_env_w).length
               ? `  ·  heater/env: ${Object.entries(pw.thermal_by_env_w).map(([e, w]) => `${e.replace(/^(lunar|mars)_/, "")} ${w}W`).join(", ")}` : "") : "")
    + (PHY ? "" : "  (fallback — serve bodies.json)");
}

// estimate the regolith a build order moves, using the SELECTED BODY's loaded terramechanics:
// volume = footprint*depth; mass = volume*density; weight = mass*g; drum loads @30 kg;
// excavation energy @4151 J/kg vs a 4.79 MJ battery charge; dig time @42 kg/hr.
// #26: the reusable info popover -- ⓘ toggles a positioned card whose content a render
// function refreshes ON CHANGE (Aaron: "should the 40 m³ be in an info bubble that updates?").
const POPOVERS = {};
function popover(id, anchorEl, renderFn) {
  POPOVERS[id] = renderFn;
  let pop = document.getElementById("pop-" + id);
  if (!pop) {
    pop = document.createElement("div");
    pop.id = "pop-" + id;
    pop.style.cssText = "display:none;position:absolute;z-index:60;background:rgba(10,10,12,.97);" +
      "border:1px solid var(--accent);border-radius:8px;padding:10px 12px;font-size:11px;" +
      "line-height:1.6;max-width:300px;box-shadow:0 6px 24px rgba(0,0,0,.5)";
    document.body.appendChild(pop);
  }
  anchorEl.onclick = (e) => {
    e.stopPropagation();
    const showing = pop.style.display !== "none";
    document.querySelectorAll('[id^="pop-"]').forEach((p2) => { p2.style.display = "none"; });
    if (!showing) {
      pop.innerHTML = renderFn();
      const r = anchorEl.getBoundingClientRect();
      pop.style.left = Math.min(r.left, innerWidth - 320) + "px";
      pop.style.top = (r.bottom + 6 + scrollY) + "px";
      pop.style.display = "block";
    }
  };
}
function refreshPopovers() {                               // open popovers refresh on change
  document.querySelectorAll('[id^="pop-"]').forEach((p2) => {
    if (p2.style.display !== "none") {
      const id = p2.id.slice(4);
      if (POPOVERS[id]) p2.innerHTML = POPOVERS[id]();
    }
  });
}
document.addEventListener("click", () => {
  document.querySelectorAll('[id^="pop-"]').forEach((p2) => { p2.style.display = "none"; });
});
let LAST_EST = null;
function estimate() {
  const p = phys(sel.value);
  const padW = +$("padW").value, padL = +$("padL").value, cut = +$("cut").value, bermH = +$("bermH").value;
  const ix = ipex();                                       // IPEx constants (bodies.json _ipex, py source)
  const cutVol = padW * padL * cut;                         // m^3
  const cutMass = cutVol * p.density;                       // kg
  const weightN = cutMass * p.g;                            // N (weight on THIS body)
  const bermArea = bermH > 0 ? cutMass / (bermH * p.density) : 0;   // mass-balanced berm footprint [m^2]
  const drumLoads = Math.ceil(cutMass / ix.drum_kg);
  const energyJ = cutMass * ix.dig_j_per_kg;               // excavation energy (dominant term)
  const charges = energyJ / ix.battery_j, hrs = cutMass / ix.dig_rate_kg_hr;
  // the KEY line + the structured breakdown behind a live ⓘ (Aaron's feasibility-layout note)
  const rw = (ix.recharge_w || 700), perChargeH = ix.battery_j / rw / 3600;
  const rechargeH = charges * perChargeH;
  LAST_EST = { cutVol, cutMass, weightN, bermArea, drumLoads, energyJ, charges, hrs, bermH, p,
               rw, perChargeH, rechargeH };
  $("est").innerHTML = "";
  const summary = document.createElement("span");
  summary.textContent = `${(cutMass / 1000).toFixed(1)} t · ${charges.toFixed(1)} charges · ~${Math.round(hrs + rechargeH).toLocaleString()} h incl. recharge `;
  const info = document.createElement("button");
  info.textContent = "ⓘ details";
  info.style.cssText = "background:none;border:1px solid var(--line);border-radius:4px;color:var(--accent);cursor:pointer;font-size:10px;padding:1px 6px";
  $("est").append(summary, info);
  popover("est", info, () => {
    const e2 = LAST_EST;
    const row = (k, v) => `<tr><td style="color:var(--muted);padding-right:10px">${k}</td><td style="text-align:right">${v}</td></tr>`;
    return `<b>Feasibility breakdown</b><table style="width:100%;border-collapse:collapse;margin-top:4px">` +
      row("excavated volume", `${e2.cutVol.toFixed(0)} m³`) +
      row(`mass (ρ = ${e2.p.density} kg/m³)`, `${(e2.cutMass / 1000).toFixed(1)} t`) +
      row(`weight @ ${e2.p.g} m/s²`, `${(e2.weightN / 1000).toFixed(0)} kN`) +
      row("drum loads", e2.drumLoads.toLocaleString()) +
      row(`berm footprint @ ${e2.bermH} m`, `${e2.bermArea.toFixed(0)} m²`) +
      row("dig energy", `${(e2.energyJ / 1e6).toFixed(1)} MJ`) +
      row("battery charges", e2.charges.toFixed(1)) +
      row("dig time", `~${Math.round(e2.hrs).toLocaleString()} h`) +
      row("recharge time", `~${Math.round(e2.rechargeH).toLocaleString()} h (${e2.charges.toFixed(0)} × ${e2.perChargeH.toFixed(1)} h @ ${e2.rw} W [CALIB])`) +
      row("<b>mission timeline</b>", `<b>~${Math.round(e2.hrs + e2.rechargeH).toLocaleString()} h</b>`) +
      `</table><div style="opacity:.6;margin-top:4px">dig-energy basis: ${LAST_EST ? "4151" : ""} J/kg (excavation mechanics
      — cutting + drum + losses; ~8,600× the pure m·g·h lift floor). The sandbox is DIG-dominant by
      design; the solver in 5·Plan adds travel + slip + recharge routing per leg. Updates live.</div>`;
  });
  refreshPopovers();
  return { body: sel.value, padW, padL, cut_m: cut, bermH_m: bermH, cutVol_m3: cutVol, cutMass_kg: cutMass,
           weight_N: weightN, bermArea_m2: bermArea, drumLoads, energy_MJ: energyJ / 1e6,
           batteryCharges: charges, digHours: hrs, terramechanics: p };
}

function showSiteDem() {                                   // auto-show the real Haworth 5 m work-area DEM on Moon
  const wa = document.getElementById("workarea");
  if (VIEW === "plan" && sel.value === "moon") {
    document.getElementById("workareaimg").src = "/dem/hillshade.png"; wa.classList.add("show");
  } else { wa.classList.remove("show"); }                 // the inset belongs to the Plan tab only
}
// the work-area inset is collapsible -- a thin tap bar so it never blocks a phone screen. Default
// collapsed on mobile (no saved preference); the choice persists per browser.
(function waCollapse() {
  const wa = $("workarea"), cap = $("wa-cap"), caret = $("wa-caret");
  if (!wa || !cap) return;
  let saved = null; try { saved = localStorage.getItem("stewie_wa_collapsed"); } catch (e) {}
  const start = saved !== null ? saved === "1" : (window.innerWidth <= 860);
  const paint = (c) => { wa.classList.toggle("collapsed", c); if (caret) caret.textContent = c ? "▸" : "▾"; };
  paint(start);
  cap.onclick = () => { const c = !wa.classList.contains("collapsed"); paint(c);
    try { localStorage.setItem("stewie_wa_collapsed", c ? "1" : "0"); } catch (e) {} };
})();
sel.onchange = () => {
  switchWorkset(CURRENT_BODY, sel.value); CURRENT_BODY = sel.value;   // per-body documents
  loadBody(sel.value); showTerra(); estimate(); showSiteDem();
  setMoonOverlaysVisible(sel.value === "moon");            // Haworth is a MOON feature (bugfix 2026-06-10)
};
$("layer").onchange = () => applyLayer(sel.value, +$("layer").value, true);   // ADD to the basemap stack (#51)
$("terrainfo").onclick = () => $("terra").classList.toggle("show");     // terramechanics on demand (updates per body)

// click the Haworth DEM inset to plan + render that area (the select-area -> render loop)
let LAST_RENDER_UV = null, RERENDER_T = 0;
function scheduleAutoRender() {                            // #33: planning edits re-render the LAST area
  if (!LAST_RENDER_UV) return;
  // SEC-01: skip quietly when not signed in (no session cookie + no in-memory key) so the auto path
  // does not spam the 401 sign-in prompt.
  if (!getCookie("stewie_csrf") && !AUTH.apikey) return;
  const cb = $("autorender"); if (cb && !cb.checked) return;
  clearTimeout(RERENDER_T);
  RERENDER_T = setTimeout(() => renderArea(LAST_RENDER_UV.u, LAST_RENDER_UV.v, { quiet: true }), 1500);
}
// UI-15: single-drag = locator pan (the canvas above captures it); DOUBLE-click = render area
$("piploc") && ($("piploc").ondblclick = (e) => {
  const r = e.target.getBoundingClientRect();
  const u = (e.clientX - r.left) / r.width, v = (e.clientY - r.top) / r.height;
  renderArea(u, v, {});
});
$("workareaimg").onclick = (e) => {
  const r = e.target.getBoundingClientRect();
  const u = (e.clientX - r.left) / r.width, v = (e.clientY - r.top) / r.height;
  renderArea(u, v, {});
};
async function renderArea(u, v, opts) {
  LAST_RENDER_UV = { u, v };
  if (!opts.quiet) setView("perception");                  // swap to the Perception pane to show the render
  $("rpempty").style.display = "none";
  $("rpstatus").textContent = "rendering BEFORE / AFTER in Godot (~40 s)…";
  $("rpimg").style.display = "none"; $("rpvol").textContent = "";
  try {
    const rbody = { u, v, pad_frac: 0.5 };                 // T6.3: same sun as the GIS shadow layer
    if ($("sunauto") && $("sunauto").checked && $("suntime"))
      rbody.mission_t_s = Math.round(parseFloat($("suntime").value) * 86400);
    const res = await fetch("/render", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify(rbody) });
    const j = await res.json();
    if (res.status === 401) {                              // actionable, like every other 401 path
      $("rpstatus").innerHTML = "⚠ API key required for rendering — paste it in <b>⚙ Settings</b> (the server key lives in deploy/.env)";
      if (!opts.quiet) setView("settings");
      return;
    }
    if (!j.ok) { $("rpstatus").textContent = "render unavailable: " + (j.error || res.status); return; }
    $("rpvol").textContent = ` — cut ${j.cut_vol_m3} m³ / fill ${j.fill_vol_m3} m³ (${j.extent_m} m window)`;
    $("rpimg").src = j.figure + "?t=" + Date.now(); $("rpimg").style.display = "block"; $("rpstatus").textContent = "";
    markFresh($("rpimg"));                                 // UI-5: the camera tile gets a freshness border
  } catch (err) { $("rpstatus").textContent = "render error: " + err; }
}
// P3: the Validate-gates button renders the full G1/G2 EVIDENCE (real-sensor ATE, stereo covariance
// + held-out coverage + depth, the honest evidence scope, and the next gate) from the dated artifact.
function renderGateEvidence(j) {
  const e = j.evidence || {}, el = $("gateevidence"); if (!el) return;
  const f = (x, u, d) => (x == null ? "—" : (+x).toFixed(d == null ? 2 : d) + (u || ""));
  const ok = (s) => `<span style="color:#7CE0A6">${s}</span>`;
  el.innerHTML =
    `<div style="border:1px solid var(--line);border-radius:8px;padding:10px;margin-top:8px;font-size:11px;line-height:1.7;font-variant-numeric:tabular-nums">
       <div style="font-family:Orbitron,system-ui;letter-spacing:.08em;font-size:10px;color:var(--accent);margin-bottom:6px">RELEASE GATES — EVIDENCE <small style="color:var(--muted)">(${e.evidence_mode || "?"})</small></div>
       <div><b>G1</b> ${ok(j.g1)} · contracts ${e.g1_contract_checks_pass}/${e.g1_contract_checks_total} PASS · real Katwijk dead-reckon ATE <b>${f(e.g1_ate_m, " m")}</b> over ${f(e.g1_eval_track_m, " m", 1)} · sim baseline ${f(e.g1_baseline_raw_m, " m")} raw / ${f(e.g1_baseline_aligned_m, " m")} aligned</div>
       <div><b>G2</b> ${ok(j.g2)} · stereo covariance σ <b>${f(e.g2_sigma_px, " px")}</b> · held-out 3σ coverage <b>${f(e.g2_coverage_3sigma, "", 3)}</b> · depth ${f(e.g2_median_depth_m, " m")} ± ${f(e.g2_sigma_depth_m, " m", 3)}</div>
       <div style="color:var(--muted);margin-top:4px">${e.g2_evidence_scope || ""}</div>
       <div style="margin-top:4px">frozen baseline ${j.byte_identical_to_frozen ? ok("byte-identical ✓") : '<span style="color:#e0556a">DIVERGED ✗</span>'} · artifact <code>${j.latest_artifact}</code></div>
       <div style="color:var(--muted);margin-top:4px"><b>next gate:</b> ${e.next_gate || ""}</div>
       <div style="margin-top:6px;color:var(--muted)">Full evidence (head-to-head, cross-dataset generalization, photometric depth pass, the executed notebooks): <a href="https://stewie-sw.github.io/stewie/" target="_blank" rel="noopener">documentation ↗</a></div>
     </div>`;
}
[["admsnap", "/admin/twin/snapshot", (j) => "snapshot: " + j.snapshot.split("/").pop()],
 ["admret", "/admin/twin/retention", (j) => `retention: ${j.removed.length} removed`],
 ["admrep", "/admin/backup/replicate", (j) => "replicated ✓"],
 ["admgate", "/admin/gates/validate", (j) => {
   renderGateEvidence(j);
   return `G1 ${j.g1.split(" ")[0]} · G2 ${j.g2.split(" ")[0]} · frozen ${j.byte_identical_to_frozen ? "byte-identical ✓" : "DIVERGED ✗"}`;
 }],
].forEach(([id, url, fmt]) => {
  const b = $(id); if (!b) return;
  b.onclick = async () => {
    b.disabled = true; $("admout").textContent = "…";
    try {
      const r = await fetch(url, { method: "POST", headers: apiHeaders() });
      const j = await r.json();
      $("admout").textContent = r.status === 401 ? "⚠ sign in (⚙ Settings)" : (j.ok ? fmt(j) : (j.error || r.status));
    } catch (e) { $("admout").textContent = "failed: " + e; }
    b.disabled = false;
  };
});
// #25: the live CG / stability side-profile (server physics: /twin/cg)
let CG_T = 0;
function cgSchedule() { clearTimeout(CG_T); CG_T = setTimeout(cgUpdate, 200); }
async function cgUpdate() {
  const F = +$("cgF").value, B = +$("cgB").value, Fk = +$("cgFk").value, Bk = +$("cgBk").value, P = +$("cgP").value || 0;
  $("cgFv").textContent = F + "°"; $("cgBv").textContent = B + "°";
  $("cgFkv").textContent = Fk + " kg"; $("cgBkv").textContent = Bk + " kg";
  let d = null;
  try { d = await (await fetch(`/twin/cg?front_deg=${F}&back_deg=${B}&front_kg=${Fk}&back_kg=${Bk}&pitch_deg=${P}`)).json(); }
  catch (e) { return; }
  if (!d || !d.ok) return;
  const cv = $("cgcanvas"), ctx = cv.getContext("2d");
  ctx.fillStyle = "#0a0a0c"; ctx.fillRect(0, 0, cv.width, cv.height);
  const cx = cv.width / 2, gy = cv.height - 22, S = 180;   // px per meter (side profile)
  ctx.strokeStyle = "#3a3f4a"; ctx.beginPath(); ctx.moveTo(10, gy); ctx.lineTo(cv.width - 10, gy); ctx.stroke();
  // wheels at ±wheelbase/2 (0.20 m), body, arms at their angles, drums as filled circles ∝ load
  const wx = 0.20 * S, wr = 0.18 * S * 0.45;
  [[-wx], [wx]].forEach(([x]) => { ctx.strokeStyle = "#9ab"; ctx.beginPath();
    ctx.arc(cx + x, gy - wr, wr, 0, 7); ctx.stroke(); });
  ctx.fillStyle = "#1a1e26"; ctx.strokeStyle = "#9ab";
  ctx.fillRect(cx - wx, gy - wr * 2.4, wx * 2, wr * 1.2); ctx.strokeRect(cx - wx, gy - wr * 2.4, wx * 2, wr * 1.2);
  const ay = gy - wr * 1.8;
  [[1, F, Fk, "#4f9cff"], [-1, B, Bk, "#e07b39"]].forEach(([sgn, deg, kg, col]) => {
    const a = deg * Math.PI / 180, L = 0.28 * S;
    const x0 = cx + sgn * wx, x1 = x0 + sgn * L * Math.cos(a), y1 = ay - L * Math.sin(a);
    ctx.strokeStyle = col; ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.moveTo(x0, ay); ctx.lineTo(x1, y1); ctx.stroke(); ctx.lineWidth = 1;
    const drumR = 0.4371 / 2 * S;                          // the REAL large-drum radius [BDS Table 1]
    ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x1, y1, drumR, 0, 7);
    ctx.globalAlpha = Math.min(0.85, 0.12 + kg / 30 * 0.6); ctx.fill();   // fill density ∝ load
    ctx.globalAlpha = 1; ctx.beginPath(); ctx.arc(x1, y1, drumR, 0, 7); ctx.stroke();
  });
  // THE CG marker (red) at (dx, height)
  const cgx = cx + d.cg_dx_m * S, cgy = gy - d.cg_height_m * S;
  ctx.strokeStyle = "#e8273f"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(cgx, cgy, 6, 0, 7); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(cgx - 9, cgy); ctx.lineTo(cgx + 9, cgy); ctx.moveTo(cgx, cgy - 9); ctx.lineTo(cgx, cgy + 9); ctx.stroke();
  ctx.lineWidth = 1;
  const riskCol = d.risk === "ok" ? "#3fa34d" : (d.risk === "warn" ? "#e0b300" : "#e8273f");
  $("cgout").innerHTML = `CG <b>${(d.cg_dx_m * 100).toFixed(1)} cm</b> fwd · height <b>${(d.cg_height_m * 100).toFixed(1)} cm</b> · ` +
    `tip margin <b style="color:${riskCol}">${d.margin_deg.toFixed(1)}°</b> (${d.binding_axis}) · risk <b style="color:${riskCol}">${d.risk.toUpperCase()}</b>`;
}
["cgF", "cgB", "cgFk", "cgBk", "cgP"].forEach((id) => { const el = $(id); if (el) el.addEventListener("input", cgSchedule); });
setTimeout(cgUpdate, 1500);

async function refreshEvents() {
  try {
    const j = await (await fetch("/events?n=40")).json();
    const ol = $("evlist"); if (!ol) return;
    ol.innerHTML = "";
    (j.events || []).forEach((e) => {
      const li = document.createElement("li");
      const t = new Date(e.ts * 1000).toLocaleTimeString();
      li.textContent = `${t} · ${e.actor} · ${e.action} ${e.target}`;
      ol.appendChild(li);
    });
  } catch (err) { /* offline */ }
}
if ($("evrefresh")) $("evrefresh").onclick = refreshEvents;
refreshEvents();
(async function loadSites() {
  try {
    const j = await (await fetch("/sites")).json();
    const sl = $("sitesel"); if (!sl || !j.ok) return;
    sl.innerHTML = j.sites.map((s) =>                                                              // SEC-04
      `<option value="${esc(s.name)}|${s.lat},${s.lon}" data-imported="${s.imported ? 1 : 0}" ${s.name === "haworth" ? "selected" : ""}>` +
      `${esc(s.label)}${s.imported ? " ✓DEM" : " (no DEM yet)"}</option>`).join("");
    sl.onchange = () => {
      const opt = sl.options[sl.selectedIndex];
      const [nm, ll] = sl.value.split("|"); const [la, lo] = ll.split(",").map(Number);
      CURRENT_SITE = opt.dataset.imported === "1" ? nm : "haworth";   // REG-01: plan on the chosen imported site
      if (sel.value !== "moon") { sel.value = "moon"; sel.onchange(); }
      setTimeout(() => { if (viewer) viewer.camera.setView({ destination:
        Cesium.Cartesian3.fromDegrees(lo, la, 90000, viewer.scene.globe.ellipsoid) }); }, 800);
      setQ(sl.options[sl.selectedIndex].text.includes("✓DEM")
        ? "site has an imported DEM bundle -- full planning available"
        : "no DEM bundle imported for this site yet (registry: stewie/specs/sites.py; import via the dem_import pipeline)");
    };
  } catch (e) { /* offline */ }
})();
$("landset").onclick = () => { setLander(+$("landx").value || 0, +$("landy").value || 0);
  setQ(`lander placed at (${LANDER_P.x}, ${LANDER_P.y}) — persists + saves with the mission`); };
if ($("landx")) { $("landx").value = LANDER_P.x; $("landy").value = LANDER_P.y; }
$("wpadd").onclick = () => {
  snapshotAuthoring();
  const n = ORDERS.filter((o) => o.kind === "goto").length + 1;
  const wp = { action: `wp${n}`, kind: "goto", x: +$("wpx").value || 0, y: +$("wpy").value || 0 };
  ORDERS.push(wp); renderQueue();
  setQ(`wp${n} @ (${wp.x}, ${wp.y}) m (typed)`);
};
if (LAST_POSE && $("lastpose")) $("lastpose").textContent = `rover last known: ${LAST_POSE.x}, ${LAST_POSE.y} m`;
$("qreset").onclick = () => {
  if (!confirm("Clear the queue, keep-outs, path, and annotations?")) return;
  ORDERS.length = 0; KEEPOUTS.length = 0; ANNOTATIONS.length = 0;
  SELECTED_ORDER = -1; LAST_ROUTES.length = 0;
  EDIT_PINS.forEach((e) => viewer && viewer.entities.remove(e)); EDIT_PINS.length = 0;
  renderQueue(); setQ("plan reset");
};
if ($("drawerbtn")) {
  $("drawerbtn").onclick = () => document.getElementById("panel").classList.toggle("open");
  // tapping the map closes the drawer (mobile pattern)
  document.getElementById("cesium").addEventListener("pointerdown", () => {
    const p2 = document.getElementById("panel");
    if (innerWidth <= 860 && p2.classList.contains("open")) p2.classList.remove("open");
  });
}
$("editmode").onclick = () => setEdit(true);
$("editdone").onclick = () => setEdit(false);
document.querySelectorAll(".etool").forEach((b) => {
  b.onclick = () => { EDIT.tool = b.dataset.tool;
    $("editstate").textContent = `LOCKED · ${b.dataset.tool} armed — click the map`; };
});
$("rpclose").onclick = () => setView("plan");
["padW", "padL", "cut", "bermH"].forEach((id) => $(id).addEventListener("input", estimate));
$("go").onclick = () => {
  const lat = parseFloat($("lat").value), lon = parseFloat($("lon").value);
  if (!isNaN(lat) && !isNaN(lon)) { setPicked(lat, lon); flyTo(lat, lon); }
};
$("site").onclick = () => {
  if (!picked) { $("out").textContent = "click the surface or enter a coord first"; return; }
  const order = estimate();
  // build-site spec handed to the sim's DEM loader / WorkSite realizer (next integration).
  const spec = { body: sel.value, lat: picked.lat, lon: picked.lon, half_extent_km: 5, order };
  // self-describing (Aaron: "what is this up here") -- the picked site + the FEASIBILITY
  // SANDBOX echo (section 4's pad/cut/berm numbers at that site)
  $("out").textContent =
    `site ${picked.lat.toFixed(3)}°, ${picked.lon.toFixed(3)}° (${BODIES[sel.value].name}) · ` +
    `sandbox est: ${(order.cutMass_kg / 1000).toFixed(1)} t / ${order.batteryCharges.toFixed(1)} charges`;
  console.log("build_order", JSON.stringify(spec));
  window.dispatchEvent(new CustomEvent("buildsite", { detail: spec }));
};

// ---- build queue -> POST /plan -> open the mission-control report -----------------------------
// Orders are in the planner's LOCAL SITE FRAME (meters, charger at 0,0); the globe pick selects the
// site, the queue places orders around it in meters (no fake lat/lon->meter projection). Planning
// needs the server (fetch /plan): run `python3 server.py` and open the printed URL.
const ORDERS = [];
const KEEPOUTS = [];                                          // discrete obstacles {x,y,r} (local m); hauls route around
// PER-BODY WORKING SETS (Aaron 2026-06-10: "if I build something on earth it doesn't plot on the
// moon?"): orders/keep-outs/routes are a per-body document; switching body saves the current set
// and loads the target's. (S-4 generalizes this into named mission documents.)
const WORKSETS = {};
let SELECTED_ORDER = -1;                                   // S-2: the selected feature (highlighted)
function switchWorkset(fromBody, toBody) {
  if (fromBody === toBody) return;
  WORKSETS[fromBody] = { orders: ORDERS.slice(), keepouts: KEEPOUTS.slice(),
                         routes: (typeof LAST_ROUTES !== "undefined" ? LAST_ROUTES.slice() : []) };
  const w = WORKSETS[toBody] || { orders: [], keepouts: [], routes: [] };
  ORDERS.length = 0; w.orders.forEach((o) => ORDERS.push(o));
  KEEPOUTS.length = 0; w.keepouts.forEach((k) => KEEPOUTS.push(k));
  if (typeof LAST_ROUTES !== "undefined") { LAST_ROUTES.length = 0; w.routes.forEach((r) => LAST_ROUTES.push(r)); }
  if (typeof renderQueue === "function") renderQueue();
  if (typeof drawPlan === "function") drawPlan();
  if (typeof marker !== "undefined" && marker && viewer) { viewer.entities.remove(marker); marker = null; }
}
let CURRENT_BODY = "moon";
const qel = (id) => document.getElementById(id);
// UI-6 (operator D1: "warnings/errors/info messages wanted"): the ALERT RAIL.
// One chokepoint: alertMsg(severity, text). setQ stays the quiet status line; anything
// warn/error-shaped ALSO lands on the rail (timestamped, severity-typed, capped 80).
const ALERTS = [];
function alertMsg(sev, text) {
  ALERTS.unshift({ t: Date.now(), sev, text: String(text).slice(0, 200) });
  if (ALERTS.length > 80) ALERTS.pop();
  renderAlerts();
}
function renderAlerts() {
  const rail = document.getElementById("alertrail"); if (!rail) return;
  const badge = document.getElementById("alertbadge");
  const nWarn = ALERTS.filter((a) => a.sev !== "info").length;
  if (badge) { badge.textContent = nWarn ? String(nWarn) : ""; badge.style.display = nWarn ? "" : "none"; }
  if (rail.style.display === "none") return;
  const col = { info: "var(--muted)", warn: "#e0b300", error: "#e8273f" };
  rail.querySelector("ol").innerHTML = ALERTS.map((a) =>
    `<li style="border-left:3px solid ${col[a.sev] || col.info};padding:3px 8px;margin:3px 0;font-size:11px">` +
    `<span style="opacity:.55;font-variant-numeric:tabular-nums">${new Date(a.t).toLocaleTimeString()}</span> ` +
    `<b style="color:${col[a.sev] || col.info};font-size:9px;letter-spacing:.08em">${a.sev.toUpperCase()}</b> ` +
    `${a.text.replace(/</g, "&lt;")}</li>`).join("");
}
const setQ = (m) => {
  qel("qstatus").textContent = m;
  const s = String(m);
  if (/^⚠|error|fail|refus|invalid|denied|outside|DIVERGED/i.test(s)) alertMsg("warn", s);
};
function mkbtn(t, fn) { const b = document.createElement("button"); b.textContent = t; b.onclick = fn; return b; }
function renderKeepouts() {
  const ol = qel("kolist"); ol.innerHTML = "";
  KEEPOUTS.forEach((k, i) => {
    const li = document.createElement("li");
    const g = document.createElement("span"); g.className = "g";
    g.textContent = `obstacle @ ${k.x},${k.y} · r ${k.r} m`;
    li.appendChild(g);
    li.appendChild(mkbtn("✕", () => { KEEPOUTS.splice(i, 1); renderKeepouts(); }));
    ol.appendChild(li);
  });
  drawPlan();
}
qel("koadd").onclick = () => {
  const x = +qel("kox").value, y = +qel("koy").value, r = +qel("kor").value;
  if (!(r > 0)) { setQ("keep-out radius must be > 0"); return; }
  KEEPOUTS.push({ x, y, r }); renderKeepouts();
  setQ(`${KEEPOUTS.length} keep-out obstacle(s); hauls will route around them`);
};
function moveOrder(i, d) {
  const j = i + d; if (j < 0 || j >= ORDERS.length) return;
  [ORDERS[i], ORDERS[j]] = [ORDERS[j], ORDERS[i]]; renderQueue();
}
// UI-14: authoring history -- snapshot BEFORE each mutation; Ctrl+Z / ↶ restores.
const HISTORY = [];
function snapshotAuthoring() {
  HISTORY.push(JSON.stringify({ o: ORDERS, k: KEEPOUTS, a: ANNOTATIONS }));
  if (HISTORY.length > 60) HISTORY.shift();
  const h = $("qhist"); if (h) h.textContent = HISTORY.length ? `${HISTORY.length} undo` : "";
}
function undoAuthoring() {
  const last = HISTORY.pop(); if (!last) { setQ("nothing to undo"); return; }
  const d = JSON.parse(last);
  ORDERS.length = 0; d.o.forEach((x) => ORDERS.push(x));
  KEEPOUTS.length = 0; d.k.forEach((x) => KEEPOUTS.push(x));
  ANNOTATIONS.length = 0; (d.a || []).forEach((x) => ANNOTATIONS.push(x));
  SELECTED_ORDER = -1;
  renderQueue(); setQ("undone");
  const h = $("qhist"); if (h) h.textContent = HISTORY.length ? `${HISTORY.length} undo` : "";
}
let QSORT = { key: null, dir: 1 };                          // UI-14: column sort (display-only)
function renderQueue() {
  const tb = qel("qtable"); tb.innerHTML = "";
  const cols = [["#", null], ["kind", "kind"], ["action", "action"], ["x", "x"], ["y", "y"],
                ["m²", "footprint_m2"], ["depth", "depth_m"], ["", null]];
  const tr = document.createElement("tr");
  cols.forEach(([label, key]) => {
    const th = document.createElement("th");
    th.textContent = label + (QSORT.key === key && key ? (QSORT.dir > 0 ? " ▲" : " ▼") : "");
    th.style.cssText = "text-align:left;color:var(--muted);font-weight:600;border-bottom:1px solid var(--line);padding:2px 5px" + (key ? ";cursor:pointer" : "");
    if (key) th.onclick = () => { QSORT = { key, dir: QSORT.key === key ? -QSORT.dir : 1 }; renderQueue(); };
    tr.appendChild(th);
  });
  tb.appendChild(tr);
  const view = ORDERS.map((o, i) => [o, i]);
  if (QSORT.key) view.sort(([a], [b]) => {
    const av = a[QSORT.key] ?? "", bv = b[QSORT.key] ?? "";
    return (av < bv ? -1 : av > bv ? 1 : 0) * QSORT.dir;
  });
  const fx = (v) => v === undefined ? "—" : Number(v).toFixed(1).replace(/\.0$/, "");
  view.forEach(([o, i]) => {
    const row = document.createElement("tr");
    row.style.cssText = "border-bottom:1px solid rgba(255,255,255,.04);cursor:pointer" +
      (i === SELECTED_ORDER ? ";outline:1px solid var(--accent)" : "");
    const cells = [String(i + 1), o.kind, o.action || "", fx(o.x), fx(o.y),
                   o.kind === "goto" ? "—" : fx(o.footprint_m2), o.kind === "goto" ? "—" : fx(o.depth_m)];
    cells.forEach((c) => { const td = document.createElement("td");
      td.textContent = c; td.style.padding = "2px 5px"; row.appendChild(td); });
    const ctl = document.createElement("td"); ctl.style.whiteSpace = "nowrap";
    ctl.append(mkbtn("⌖", () => { $("qx").value = o.x; $("qy").value = o.y;
        SELECTED_ORDER = i; drawPlan(); renderQueue(); }),
      mkbtn("▲", () => { snapshotAuthoring(); moveOrder(i, -1); }),
      mkbtn("▼", () => { snapshotAuthoring(); moveOrder(i, 1); }),
      mkbtn("✕", () => { snapshotAuthoring(); ORDERS.splice(i, 1); SELECTED_ORDER = -1; renderQueue(); }));
    row.appendChild(ctl);
    row.onclick = (e) => { if (e.target.tagName !== "BUTTON") { SELECTED_ORDER = i; drawPlan(); renderQueue(); } };
    tb.appendChild(row);
  });
  setQ(ORDERS.length ? `${ORDERS.length} order(s) queued` : "queue empty");
  drawPlan();
  scheduleAutoRender();                                    // #33: edits flow to the Godot render
}
function addOrder(o) { snapshotAuthoring(); ORDERS.push(o); renderQueue(); }
if ($("alertbtn")) $("alertbtn").onclick = () => {
  const r = $("alertrail");
  r.style.display = r.style.display === "none" ? "block" : "none";
  renderAlerts();
};
if ($("qundo")) $("qundo").onclick = undoAuthoring;
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" &&
      !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
    e.preventDefault(); undoAuthoring();
  }
});

// ---- LAYER SYSTEM: select / load / unload map overlays (imagery, dem, topology, hazard, excavation, lander) ----
const LAYER_ON = { imagery: true, dem: true, topology: false, hazard: true, excavation: true, lander: true };
let LANDER = { name: "Nova-C", x: LANDER_P.x, y: LANDER_P.y, footprint_m: 4.6, n_legs: 6 };   // delivery lander (persisted position, #65)
async function loadLayers() {
  try {
    const d = await (await fetch("/layers")).json();
    const panel = qel("layerpanel"); if (!panel) return;
    panel.innerHTML = "<b style=\"margin-right:4px\">LAYERS</b>";
    d.layers.forEach((L) => {
      const lid = L.id || L.key;                             // server rasters use `key`
      LAYER_ON[lid] = !!L.default;
      const lab = document.createElement("label"); lab.style.cssText = "display:inline-flex;gap:3px;align-items:center;cursor:pointer";
      const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = !!L.default;
      cb.onchange = () => { LAYER_ON[lid] = cb.checked; applyLayerToggle(lid, cb.checked); drawPlan(); };
      lab.appendChild(cb); lab.appendChild(document.createTextNode(L.name));
      LAYERS_LOADED = true;                                  // (set per row; cheap + monotonic)
      if (["topology", "excavation", "lander"].includes(lid)) {
        const tag = document.createElement("span");
        tag.textContent = "plan"; tag.title = "draws on the PLAN canvas (section 4) and the work-area inset";
        tag.style.cssText = "font-size:8px;color:var(--dim);border:1px solid var(--line);border-radius:3px;padding:0 3px";
        lab.appendChild(tag);
      }
      panel.appendChild(lab);
    });
  } catch (e) { /* serverless preview keeps the defaults */ }
  applyDefaultsOnceReady();                                // #63: the other ready side
}
const GIS_RASTERS = ["slope", "hazard", "illumination", "psr", "grid"];
// #63 (Aaron's bug: layers need an off/on cycle): the default-layer application raced --
// the georef .then() read LAYER_ON before loadLayers() had populated it (or vice versa).
// Both sides now call this gate; it fires once when BOTH are ready.
let LAYERS_LOADED = false, DEFAULTS_APPLIED = false;
function applyDefaultsOnceReady() {
  if (DEFAULTS_APPLIED || !LAYERS_LOADED || !HAWORTH_RECT) return;
  DEFAULTS_APPLIED = true;
  globeLayer("dem", "", LAYER_ON.dem !== false);
  GIS_RASTERS.forEach((k) => { if (LAYER_ON[k]) applyLayerToggle(k, true); });
}   // computed from the REAL Haworth DEM server-side
// the BIG-MAP layer path (Aaron: "layers only load in the pip window -- need it on the large
// screen"): each raster becomes a Cesium imagery layer clipped to the true Haworth footprint.
async function globeLayer(key, _url, on) {
  if (!viewer || !HAWORTH_RECT) return;
  if (GLOBE_LAYERS[key]) { viewer.imageryLayers.remove(GLOBE_LAYERS[key], true); delete GLOBE_LAYERS[key]; }
  if (!on) return;
  // server-REPROJECTED geographic drape in the layer's OWN bbox (the rotated-tile fix)
  const qs = sunQS();
  try {
    const bb = await (await fetch(`/layers/globe/${key}/bbox?` + qs)).json();
    if (!bb.ok) { console.error("layer bbox failed:", key, bb); return; }
    // fromUrl = the supported modern-Cesium path (the constructor-with-url form is deprecated);
    // errors surface to the console instead of a silent swallow (the old catch hid failures).
    const prov = await Cesium.SingleTileImageryProvider.fromUrl(
      `/layers/globe/${key}.png?` + qs,
      { rectangle: Cesium.Rectangle.fromDegrees(bb.west, bb.south, bb.east, bb.north) });
    GLOBE_LAYERS[key] = viewer.imageryLayers.addImageryProvider(prov);
    if (LAYER_OPACITY[key]) GLOBE_LAYERS[key].alpha = LAYER_OPACITY[key] / 100;   // slider persists
    // Aaron: the reference grid must sit ON TOP of every DEM/analysis drape
    if (GLOBE_LAYERS.grid) viewer.imageryLayers.raiseToTop(GLOBE_LAYERS.grid);
  } catch (e) { console.error("globe layer failed:", key, e); alertMsg("error", `layer ${key} failed: ${e}`); }
}
const BOOT_V = Date.now();                                 // per-pageload cache-bust for layer images
function sunQS() {
  const gc = "&color=" + encodeURIComponent((SETTINGS.gridcolor || "#39ff14").replace("#", ""));
  if (qel("sunauto") && qel("sunauto").checked)            // AUTO: mission time -> real solar geometry server-side
    return `mission_t_s=${Math.round(parseFloat(qel("suntime").value) * 86400)}&b=${BOOT_V}` + gc;
  return `sun_el=${qel("sunel").value}&sun_az=${qel("sunaz").value}&b=${BOOT_V}` + gc;
}
function flyToWorkArea() {                                 // audit P1: toggles give FEEDBACK -- fly to where the layer lives
  if (!viewer || !HAWORTH_CENTER) return;
  const h = viewer.camera.positionCartographic.height;
  const c = Cesium.Cartographic.fromCartesian(viewer.camera.position, viewer.scene.globe.ellipsoid);
  const far = h > 120000 ||
    Math.abs(Cesium.Math.toDegrees(c.latitude) - HAWORTH_CENTER.lat) > 1.5;
  // setView (instant): animated flyTo tweens never progress in this viewer config
  if (far) viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(
    HAWORTH_CENTER.lon, HAWORTH_CENTER.lat, 30000, viewer.scene.globe.ellipsoid) });
}
function applyLayerToggle(id, on) {                          // load/unload the raster layers (vector layers redraw)
  if (id === "dem") {
    const wa = qel("workarea"); if (wa) wa.style.display = on ? "" : "none";
    globeLayer("dem", "", on);                               // the GLOBE drape obeys the checkbox too
    if (on) flyToWorkArea();
  }
  if (id === "imagery" && viewer && viewer.imageryLayers && viewer.imageryLayers.length) viewer.imageryLayers.get(0).show = on;
  if (id === "grid") drawGraticule();                      // the global graticule follows the toggle
  if (GIS_RASTERS.includes(id)) {
    renderLegend();
    const im = qel("ovl_" + id);
    if (im) {
      if (on) { im.src = `/layers/raster/${id}.png?` + sunQS(); im.style.display = "block"; }
      else { im.style.display = "none"; }
    }
    globeLayer(id, `/layers/raster/${id}.png?` + sunQS(), on);   // AND on the big map
    if (on) flyToWorkArea();                                 // a work-area layer you can't see = a dead checkbox
  }
}
// TerriaJS workbench pattern (OSS survey): every ACTIVE layer = a card with its legend,
// opacity, zoom-to, and remove -- the controls live WITH the layer, not in a global box.
const LAYER_OPACITY = {};
function renderWorkbench() {
  const wb = $("workbench"); if (!wb || !LEGEND) return;
  wb.innerHTML = "";
  const CARDS = {
    dem:  { name: "Haworth 5 m DEM", text: (LEGEND.dem || {}).text || "" },
    slope: { name: "Slope", text: LEGEND.slope.ramp, sw: "#7bd07b→#ff5544" },
    hazard: { name: "Hazard / no-go", text: LEGEND.hazard.text, sw: "#e8273f" },
    illumination: { name: "Shadow (mission-time sun)", text: LEGEND.illumination.text, sw: "#5577dd" },
    psr: { name: "Permanently shadowed regions", text: LEGEND.psr.text, sw: "#9966dd" },
    grid: { name: "Site grid", text: "site-frame meters: 100 m minor / 500 m major (labels: inset axes + cursor readout)", sw: "#39ff14", colorpick: true },
  };
  BASEMAP_STACK.forEach((bm, bi) => {                      // #51: basemap cards (stack + opacity)
    const L = BODIES[sel.value].layers[bm.idx]; if (!L) return;
    const card = document.createElement("div");
    card.style.cssText = "border:1px solid var(--line);border-radius:6px;padding:6px 8px;margin:4px 0;font-size:10px;line-height:1.45";
    const head = document.createElement("div"); head.style.cssText = "display:flex;align-items:center;gap:6px";
    const ttl = document.createElement("b"); ttl.textContent = "🗺 " + L.name; head.appendChild(ttl);
    if (BASEMAP_STACK.length > 1) {
      const rm = document.createElement("button"); rm.textContent = "✕"; rm.title = "remove basemap";
      rm.style.cssText = "margin-left:auto;background:none;border:1px solid var(--line);border-radius:4px;color:var(--txt);cursor:pointer;font-size:10px";
      rm.onclick = () => { viewer.imageryLayers.remove(bm.layer, true); BASEMAP_STACK.splice(bi, 1); renderWorkbench(); };
      head.appendChild(rm);
    }
    card.appendChild(head);
    const op = document.createElement("input");
    op.type = "range"; op.min = "10"; op.max = "100"; op.value = String(Math.round((bm.layer.alpha ?? 1) * 100));
    op.style.cssText = "display:block;box-sizing:border-box;width:100%;margin:3px 0 0"; op.title = "basemap opacity";
    op.oninput = () => { bm.layer.alpha = +op.value / 100; };
    card.appendChild(op);
    wb.appendChild(card);
  });
  Object.keys(CARDS).forEach((k) => {
    if (!LAYER_ON[k]) return;
    const c = CARDS[k];
    const card = document.createElement("div");
    card.style.cssText = "border:1px solid var(--line);border-radius:6px;padding:6px 8px;margin:4px 0;font-size:10px;line-height:1.45";
    const head = document.createElement("div");
    head.style.cssText = "display:flex;align-items:center;gap:6px";
    if (c.sw && !c.sw.includes("→")) {
      const dot = document.createElement("span");
      dot.style.cssText = `width:8px;height:8px;border-radius:2px;background:${c.sw};display:inline-block`;
      head.appendChild(dot);
    }
    const ttl = document.createElement("b"); ttl.textContent = c.name; head.appendChild(ttl);
    const zoom = document.createElement("button"); zoom.textContent = "⌖"; zoom.title = "zoom to the work area";
    zoom.style.cssText = "margin-left:auto;background:none;border:1px solid var(--line);border-radius:4px;color:var(--txt);cursor:pointer;font-size:10px";
    zoom.onclick = () => flyToWorkArea();
    const rm = document.createElement("button"); rm.textContent = "✕"; rm.title = "remove the layer";
    rm.style.cssText = zoom.style.cssText;
    rm.onclick = () => {
      LAYER_ON[k] = false; applyLayerToggle(k, false);
      const lp = qel("layerpanel");
      if (lp) lp.querySelectorAll("input[type=checkbox]").forEach((cb) => {
        const t = cb.parentElement.textContent || "";
        if ((k === "dem" && t.includes("DEM")) || (k === "slope" && t.startsWith("Slope")) ||
            (k === "hazard" && t.includes("no-go")) || (k === "illumination" && t.includes("Shadow")) ||
            (k === "psr" && t.includes("PSR"))) cb.checked = false;
      });
      renderWorkbench();
    };
    head.appendChild(zoom); head.appendChild(rm);
    card.appendChild(head);
    const leg = document.createElement("div"); leg.style.opacity = ".75"; leg.textContent = c.text;
    card.appendChild(leg);
    if (c.colorpick) {                                     // #54 follow-up: operator-chosen grid color
      const cp = document.createElement("input");
      cp.type = "color"; cp.value = SETTINGS.gridcolor || "#39ff14";
      cp.title = "grid line color"; cp.style.cssText = "width:100%;height:18px;margin-top:3px;border:none;background:none;cursor:pointer";
      cp.oninput = () => { SETTINGS.gridcolor = cp.value; saveSettings(SETTINGS);
        applyLayerToggle("grid", true); };
      card.appendChild(cp);
    }
    if (k !== "dem") {                                     // opacity (the globe imagery layer)
      const op = document.createElement("input");
      op.type = "range"; op.min = "10"; op.max = "100"; op.value = String(LAYER_OPACITY[k] || 100);
      op.style.cssText = "display:block;box-sizing:border-box;width:100%;margin:3px 0 0";
      op.title = "layer opacity";
      op.oninput = () => {
        LAYER_OPACITY[k] = +op.value;
        if (GLOBE_LAYERS[k]) GLOBE_LAYERS[k].alpha = op.value / 100;
        const im = qel("ovl_" + k); if (im) im.style.opacity = String(op.value / 100);
      };
      card.appendChild(op);
    }
    wb.appendChild(card);
  });
}
let LEGEND = null;
async function renderLegend() {                            // audit P1: physics-fed legends per active layer
  const box = $("legendbox"); if (!box) return;
  if (!LEGEND) { try { LEGEND = await (await fetch("/layers/legend")).json(); } catch (e) { return; } }
  const rows = [];
  if (LAYER_ON.slope) rows.push(`<span style="color:#7bd07b">■</span>→<span style="color:#ff5544">■</span> slope: ${LEGEND.slope.ramp}`);
  if (LAYER_ON.hazard) rows.push(`<span style="color:#e8273f">■</span> hazard: no-go &gt;${LEGEND.hazard.nogo_deg}° (tested) · <span style="color:#e0b300">■</span> penalty &gt;${LEGEND.hazard.penalty_deg}° · rocks &gt;${(LEGEND.hazard.obstacle_m*100).toFixed(1)} cm`);
  if (LAYER_ON.illumination) rows.push(`<span style="color:#5577dd">■</span> ${LEGEND.illumination.text}`);
  if (LAYER_ON.psr) rows.push(`<span style="color:#9966dd">■</span> ${LEGEND.psr.text}`);
  box.innerHTML = rows.join("<br>");
  renderWorkbench();                                       // the cards carry the legends now
}
function refetchSun() { GIS_RASTERS.forEach((k) => { if (LAYER_ON[k]) applyLayerToggle(k, true); }); renderLegend(); }
["sunel", "sunaz"].forEach((sid) => { const el = qel(sid); if (el) el.oninput = () => {
  qel("sunelv").textContent = qel("sunel").value + "\u00b0";
  qel("sunazv").textContent = qel("sunaz").value + "\u00b0";
  refetchSun();
}; });
if (qel("suntime")) qel("suntime").oninput = () => {
  qel("suntimev").textContent = "day " + parseFloat(qel("suntime").value).toFixed(1);
  refetchSun();
};
if (qel("sunauto")) qel("sunauto").onchange = () => {
  const auto = qel("sunauto").checked;
  qel("sunel").disabled = auto; qel("sunaz").disabled = auto; qel("suntime").disabled = !auto;
  refetchSun();
};
loadLayers();

// ---- PLAN VIEW: a top-down local-frame view of the queue (orders + keep-outs + charger) + click-to-place ----
let _placeXY = null;                                       // last click-to-place marker (local metres)
function _planExtent() {
  const xs = [0], ys = [0];                                // include the charger at (0,0)
  ORDERS.forEach((o) => { const h = Math.sqrt(o.footprint_m2) / 2; xs.push(o.x - h, o.x + h); ys.push(o.y - h, o.y + h); });
  KEEPOUTS.forEach((k) => { xs.push(k.x - k.r, k.x + k.r); ys.push(k.y - k.r, k.y + k.r); });
  if (_placeXY) { xs.push(_placeXY.x); ys.push(_placeXY.y); }
  let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (x1 - x0 < 1) { x0 -= 10; x1 += 10; } if (y1 - y0 < 1) { y0 -= 10; y1 += 10; }
  const px = Math.max(5, (x1 - x0) * 0.15), py = Math.max(5, (y1 - y0) * 0.15);
  return { x0: x0 - px, x1: x1 + px, y0: y0 - py, y1: y1 + py };
}
function _planXform(cv, ext) {
  const W = cv.width, H = cv.height;
  const s = Math.min(W / (ext.x1 - ext.x0), H / (ext.y1 - ext.y0));
  const ox = (W - s * (ext.x1 - ext.x0)) / 2, oy = (H - s * (ext.y1 - ext.y0)) / 2;
  return { s, ox, oy, X: (wx) => ox + (wx - ext.x0) * s, Y: (wy) => H - (oy + (wy - ext.y0) * s) };
}
let LAST_ROUTES = [];                                      // item 3: routes from the last /plan response, drawn on the 2D canvas
// #29: the branded feature glyphs -- ONE drawing function so map, queue, and legend agree.
function drawGlyph(ctx, kind, x, y, r) {
  r = r || 5;
  ctx.save();
  if (kind === "cut") {                                    // drum-down chevron (excavate)
    ctx.strokeStyle = "#4f9cff"; ctx.lineWidth = 1.6;
    ctx.beginPath(); ctx.moveTo(x - r, y - r * 0.5); ctx.lineTo(x, y + r * 0.7);
    ctx.lineTo(x + r, y - r * 0.5); ctx.stroke();
  } else if (kind === "fill") {                            // berm mound
    ctx.strokeStyle = "#e07b39"; ctx.lineWidth = 1.6;
    ctx.beginPath(); ctx.arc(x, y + r * 0.4, r, Math.PI, 0); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x - r, y + r * 0.4); ctx.lineTo(x + r, y + r * 0.4); ctx.stroke();
  } else if (kind === "goto") {                            // waypoint node
    ctx.fillStyle = "#e8273f"; ctx.beginPath(); ctx.arc(x, y, r * 0.8, 0, 7); ctx.fill();
  } else if (kind === "keepout") {                         // exclusion ring
    ctx.strokeStyle = "#e8273f"; ctx.lineWidth = 1.6; ctx.setLineDash([3, 2]);
    ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.stroke(); ctx.setLineDash([]);
  } else if (kind === "charger") {                         // power bolt (square + tick)
    ctx.fillStyle = "#3fa34d"; ctx.fillRect(x - r * 0.6, y - r * 0.6, r * 1.2, r * 1.2);
    ctx.strokeStyle = "#0a0a0c"; ctx.lineWidth = 1.4;
    ctx.beginPath(); ctx.moveTo(x + r * 0.3, y - r * 0.5); ctx.lineTo(x - r * 0.2, y + r * 0.1);
    ctx.lineTo(x + r * 0.2, y + r * 0.1); ctx.lineTo(x - r * 0.3, y + r * 0.6); ctx.stroke();
  }
  ctx.restore();
}

function drawPlan() {
  const cv = qel("plancanvas"); if (!cv) return;
  const ctx = cv.getContext("2d"), W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H); ctx.fillStyle = "#05060c"; ctx.fillRect(0, 0, W, H);
  const ext = _planExtent(), tf = _planXform(cv, ext), X = tf.X, Y = tf.Y, s = tf.s;
  // #48 (Aaron): TERRAIN UNDER THE FEATURES -- the work-area hillshade (site frame 0..640 m)
  // drawn beneath the vectors so authoring has real context.
  const wai = qel("workareaimg");
  if (LAYER_ON.dem !== false && wai && wai.complete && wai.naturalWidth) {
    const x0 = X(0), y0 = Y(640), x1 = X(640), y1 = Y(0);  // site Y is up; canvas Y is down
    ctx.save(); ctx.globalAlpha = 0.55;
    ctx.drawImage(wai, x0, y0, x1 - x0, y1 - y0);
    ctx.restore();
  }
  if (LAYER_ON.hazard) KEEPOUTS.forEach((k) => {           // hazard layer: keep-outs = red discs
    ctx.fillStyle = "rgba(224,86,75,.22)"; ctx.strokeStyle = "#e0564b"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(X(k.x), Y(k.y), Math.max(2, k.r * s), 0, 7); ctx.fill(); ctx.stroke();
  });
  LAST_ROUTES.forEach((rt) => {                            // item 3: planned terrain-following haul routes
    const wp = rt.waypoints || [];
    if (rt.reached && wp.length >= 2) {                    // routed leg -> green polyline through the waypoints
      ctx.strokeStyle = "#3fa34d"; ctx.lineWidth = 1.5; ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(X(wp[0][0]), Y(wp[0][1]));
      for (let i = 1; i < wp.length; i++) ctx.lineTo(X(wp[i][0]), Y(wp[i][1]));
      ctx.stroke();
    } else if (rt.from_xy && rt.to_xy) {                   // blocked leg -> red dashed (route NOT driven)
      ctx.strokeStyle = "#e0564b"; ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(X(rt.from_xy[0]), Y(rt.from_xy[1]));
      ctx.lineTo(X(rt.to_xy[0]), Y(rt.to_xy[1])); ctx.stroke(); ctx.setLineDash([]);
    }
  });
  // S-3: the authored PATH (goto waypoints as a red polyline with numbered nodes)
  const wps = ORDERS.filter((o) => o.kind === "goto");
  if (wps.length) {
    ctx.strokeStyle = "#e8273f"; ctx.lineWidth = 1.5; ctx.setLineDash([5, 3]);
    ctx.beginPath();
    wps.forEach((w, k) => { const x = X(w.x), y = Y(w.y); k ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke(); ctx.setLineDash([]);
    wps.forEach((w, k) => {
      ctx.fillStyle = "#e8273f"; ctx.beginPath(); ctx.arc(X(w.x), Y(w.y), 4, 0, 7); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = "8px system-ui"; ctx.textAlign = "center";
      ctx.fillText(String(k + 1), X(w.x), Y(w.y) + 2.5);
    });
  }
  if (LAYER_ON.excavation) ORDERS.forEach((o, i) => {      // excavation layer: cut (blue) / fill (orange) squares
    const half = Math.max(2, Math.sqrt(o.footprint_m2) / 2 * s);
    ctx.fillStyle = o.kind === "cut" ? "rgba(79,156,255,.30)" : "rgba(224,123,57,.30)";
    ctx.strokeStyle = o.kind === "cut" ? "#4f9cff" : "#e07b39"; ctx.lineWidth = 1;
    ctx.fillRect(X(o.x) - half, Y(o.y) - half, half * 2, half * 2);
    ctx.strokeRect(X(o.x) - half, Y(o.y) - half, half * 2, half * 2);
    if (i === SELECTED_ORDER) {                            // S-2: selection highlight (brand red)
      ctx.strokeStyle = "#e8273f"; ctx.lineWidth = 2;
      ctx.strokeRect(X(o.x) - half - 3, Y(o.y) - half - 3, half * 2 + 6, half * 2 + 6);
    }
    drawGlyph(ctx, o.kind, X(o.x), Y(o.y) - half - 6, 5);  // the kind glyph above the square
    ctx.fillStyle = "#c7d2e3"; ctx.font = "9px system-ui"; ctx.textAlign = "center";
    ctx.fillText(String(i + 1), X(o.x), Y(o.y) + 3);
  });
  drawGlyph(ctx, "charger", X(0), Y(0), 6);                // charger (branded glyph)
  if (LAYER_ON.lander) {                                   // lander layer: TO-SCALE hexagon+legs at its location
    const fr = Math.max(3, LANDER.footprint_m / 2 * s), lx = X(LANDER.x), ly = Y(LANDER.y);
    ctx.strokeStyle = "#ffd166"; ctx.fillStyle = "rgba(255,209,102,.16)"; ctx.lineWidth = 1.4;
    for (let k = 0; k < LANDER.n_legs; k++) {              // legs (slightly beyond the body footprint)
      const a = Math.PI / 6 + k * 2 * Math.PI / LANDER.n_legs;
      ctx.beginPath(); ctx.moveTo(lx, ly); ctx.lineTo(lx + Math.cos(a) * fr * 1.3, ly + Math.sin(a) * fr * 1.3); ctx.stroke();
    }
    ctx.beginPath();                                        // hexagonal body, to true footprint
    for (let k = 0; k < 6; k++) { const a = Math.PI / 6 + k * Math.PI / 3, xx = lx + Math.cos(a) * fr, yy = ly + Math.sin(a) * fr; k ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy); }
    ctx.closePath(); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#ffd166"; ctx.font = "8px system-ui"; ctx.textAlign = "center";
    ctx.fillText(LANDER.name + " (" + LANDER.footprint_m + " m)", lx, ly - fr - 3);
  }
  if (_placeXY) {                                          // the click-to-place crosshair
    ctx.strokeStyle = "#4f9cff"; ctx.lineWidth = 1; const cx = X(_placeXY.x), cy = Y(_placeXY.y);
    ctx.beginPath(); ctx.arc(cx, cy, 5, 0, 7); ctx.moveTo(cx - 8, cy); ctx.lineTo(cx + 8, cy);
    ctx.moveTo(cx, cy - 8); ctx.lineTo(cx, cy + 8); ctx.stroke();
  }
}
let PATH_MODE = false, PATH_N = 0;
qel("pathmode").onclick = () => {
  PATH_MODE = true; PATH_N = ORDERS.filter((o) => o.kind === "goto").length;
  qel("pathmode").style.display = "none"; qel("pathdone").style.display = "";
  qel("pathinfo").textContent = "click waypoints in order";
};
qel("pathdone").onclick = () => {
  PATH_MODE = false;
  qel("pathmode").style.display = ""; qel("pathdone").style.display = "none";
  qel("pathinfo").textContent = "";
};
// #29: drag-to-move -- grab any authored feature and re-place it (the audit's P2)
let DRAG = null;
function _canvasToWorld(e) {
  const cv = qel("plancanvas"), r = cv.getBoundingClientRect();
  const px = (e.clientX - r.left) / r.width * cv.width, py = (e.clientY - r.top) / r.height * cv.height;
  const ext = _planExtent(), tf = _planXform(cv, ext);
  return { wx: ext.x0 + (px - tf.ox) / tf.s, wy: ext.y0 + ((cv.height - py) - tf.oy) / tf.s,
           tol: 8 / tf.s };
}
qel("plancanvas").addEventListener("pointerdown", (e) => {
  const { wx, wy, tol } = _canvasToWorld(e);
  let best = -1, bd = tol;
  ORDERS.forEach((o, i) => {
    const d = Math.hypot(o.x - wx, o.y - wy);
    if (d < bd) { bd = d; best = i; }
  });
  if (best >= 0) {
    DRAG = { i: best, moved: false };
    SELECTED_ORDER = best;
    qel("plancanvas").setPointerCapture(e.pointerId);
  }
});
qel("plancanvas").addEventListener("pointermove", (e) => {
  if (!DRAG) return;
  const { wx, wy } = _canvasToWorld(e);
  const o = ORDERS[DRAG.i];
  o.x = Math.round(wx * 10) / 10; o.y = Math.round(wy * 10) / 10;
  DRAG.moved = true;
  drawPlan();
});
qel("plancanvas").addEventListener("pointerup", (e) => {
  if (DRAG && DRAG.moved) {
    const o = ORDERS[DRAG.i];
    setQ(`moved ${o.kind} "${o.action}" to (${o.x}, ${o.y})`);
    renderQueue();
    DRAG = null;
    e.stopImmediatePropagation?.();
    SUPPRESS_CLICK = true;
    return;
  }
  DRAG = null;
});
let SUPPRESS_CLICK = false;
qel("plancanvas").onclick = (e) => {                       // canvas px -> local metres -> the x,y inputs
  if (SUPPRESS_CLICK) { SUPPRESS_CLICK = false; return; }  // a drag just ended -- not a click
  const cv = qel("plancanvas"), r = cv.getBoundingClientRect();
  const px = (e.clientX - r.left) / r.width * cv.width, py = (e.clientY - r.top) / r.height * cv.height;
  const ext = _planExtent(), tf = _planXform(cv, ext);
  const wx = ext.x0 + (px - tf.ox) / tf.s, wy = ext.y0 + ((cv.height - py) - tf.oy) / tf.s;
  if (PATH_MODE) {                                         // S-3: each click = a sequenced waypoint
    snapshotAuthoring();
    PATH_N += 1;
    ORDERS.push({ action: `wp${PATH_N}`, kind: "goto", x: Math.round(wx), y: Math.round(wy) });
    qel("pathinfo").textContent = `${PATH_N} waypoint(s)`;
    renderQueue(); return;
  }
  _placeXY = { x: Math.round(wx), y: Math.round(wy) };
  qel("qx").value = _placeXY.x; qel("qy").value = _placeXY.y;
  setQ(`placed ${_placeXY.x}, ${_placeXY.y} m — pick a kind/structure + Add to queue it`);
  drawPlan();
};
qel("qadd").onclick = () => addOrder({
  action: qel("qlabel").value || (qel("qkind").value === "cut" ? "Cut" : "Fill"),
  kind: qel("qkind").value, x: +qel("qx").value, y: +qel("qy").value,
  footprint_m2: +qel("qfoot").value, depth_m: +qel("qdepth").value,
});
qel("qfrompad").onclick = () => {                          // convenience: pad estimator -> a cut + a balanced fill
  const padW = +$("padW").value, padL = +$("padL").value, cut = +$("cut").value, bermH = +$("bermH").value;
  const x = +qel("qx").value, y = +qel("qy").value, p = phys(sel.value);
  addOrder({ action: "Pad cut", kind: "cut", x, y, footprint_m2: padW * padL, depth_m: cut });
  if (bermH > 0) {
    const mass = padW * padL * cut * p.density;
    addOrder({ action: "Berm fill", kind: "fill", x: x + 10, y: y + 10,
               footprint_m2: +(mass / (bermH * p.density)).toFixed(1), depth_m: bermH });
  }
};
qel("qstruct").onclick = async () => {                     // place a named structure -> mass-balanced orders (P2)
  try {
    const res = await fetch("/structure", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ name: qel("struct").value, x: +qel("qx").value, y: +qel("qy").value }) });
    const j = await res.json();
    if (!j.ok) { setQ("structure error: " + j.error); return; }
    j.orders.forEach(addOrder);
    setQ(`added ${j.orders.length} order(s) from ${qel("struct").value}`);
  } catch (e) { setQ("structure failed — run server.py (" + e + ")"); }
};
// precedence text "Grade road > Build berm, Dig pit > Fill" -> [[before, after], ...] (I9)
function parsePrec() {
  return (qel("qprec").value || "").split(",").map(s => s.trim()).filter(Boolean)
    .map(s => s.split(">").map(x => x.trim())).filter(p => p.length === 2 && p[0] && p[1]);
}
qel("sesstart").onclick = async () => {                  // B3: operator/director training session
  if (!ORDERS.length) { setQ("add at least one order first"); return; }
  const b = qel("sesstart"); b.disabled = true; b.textContent = "⏳ running session…";
  try {
    const res = await fetch("/session/start", { method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({ name: `${BODIES[sel.value].name} session`, body: sel.value,
        charger: [0, 0], orders: ORDERS, keepouts: KEEPOUTS,
        profile: qel("seslink").value }) });
    const j = await res.json();
    if (!j.ok) { setQ("session error: " + (j.error || res.status)); return; }
    const o = qel("sesout"); o.style.display = "block";
    o.innerHTML = `session <code>${j.session_id.slice(0, 8)}</code> · ${j.n_legs} legs · ` +
      `<a href="${j.operator_url}" target="_blank">operator view</a> · ` +
      `<a href="${j.debrief_url}" target="_blank">debrief</a> · ` +
      `<a href="/session/${j.session_id}/summary" target="_blank">summary</a>` +
      ` <span style="opacity:.7">(debrief + summary need the director key when auth is on)</span>`;
    // #80: the trainer SCORECARD (A-board KPIs) rendered inline -- director also sees truth divergence
    try {
      const sb = await (await fetch(`/session/${j.session_id}/scorecard`, { headers: apiHeaders() })).json();
      if (sb.ok) {
        const b = sb.scorecard;
        const chip = (k, v) => `<span style="border:1px solid var(--line);border-radius:6px;padding:3px 8px;margin:2px;display:inline-block;font-size:11px"><span style="color:var(--muted)">${k}</span> <b style="font-variant-numeric:tabular-nums">${v}</b></span>`;
        o.innerHTML += `<div style="margin-top:8px"><b style="font-family:Orbitron,system-ui;font-size:10px;letter-spacing:.08em">TRAINER SCORECARD</b><br>` +
          chip("objectives", `${b.completed ? "✓" : "✗"} ${b.objectives_total}`) +
          chip("legs delivered", `${b.legs_delivered}/${b.legs_total}`) +
          chip("comm delivered", `${(b.comm_delivered_frac * 100).toFixed(0)}%`) +
          chip("recharges", b.recharges) + chip("replans", b.replans) +
          chip("stranded", b.stranded_packets) + chip("energy", `${b.energy_MJ} MJ`) +
          (b.energy_divergence_J !== undefined ? chip("⚠ divergence (truth)", `${b.energy_divergence_J} J`) : "") +
          `</div>`;
      }
    } catch (e) { /* scorecard optional */ }
    setQ("session ready — operator link is the trainee view; scorecard below");
  } catch (e) { setQ("session error: " + e); }
  finally { b.disabled = false; b.textContent = "🎓 Start session"; }
};

qel("qplan").onclick = async () => {
  if (!ORDERS.length) { setQ("add at least one order first"); return; }
  const pb = qel("qplan"); pb.disabled = true; pb.textContent = "⏳ planning + rendering report…";   // B0.4
  setQ("planning…");
  try {
    const res = await fetch("/plan", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ name: `${BODIES[sel.value].name} build`, body: sel.value, charger: [0, 0],
        orders: ORDERS, algorithm: qel("qalgo").value, objective: qel("qobj").value, precedence: parsePrec(),
        keepouts: KEEPOUTS, ...fleet(), ...site() }) });
    const j = await res.json();
    if (res.status === 401) { setQ("⚠ API key required: paste it in ⚙ Settings (server key lives in deploy/.env)"); setView("settings"); return; }
    if (!j.ok) { setQ("error: " + j.error); return; }
    const t = j.totals;
    if ($("conops")) $("conops").textContent =
      `CONOPS PLANNED · ${t.trips ?? "—"} trips · ${t.drum_cycles ?? 0} drum cycles · ` +
      `${t.cut_passes ?? 1} cut pass${(t.cut_passes ?? 1) > 1 ? "es" : ""}`;
    LAST_ROUTES = t.routes || []; drawPlan();              // item 3: overlay the planned routes on the 2D canvas
    // #56: the dashboard strip -- the last plan's headline numbers, chips on the Report pane
    const ds = $("dashstrip");
    if (ds) {
      const chip = (k, v) => `<span style="border:1px solid var(--line);border-radius:6px;padding:5px 10px;font-size:11px"><span style="color:var(--muted)">${k}</span> <b style="font-variant-numeric:tabular-nums">${v}</b></span>`;
      const hz = (t.hazard_violations || []).length;
      if (hz) alertMsg("warn", `plan has ${hz} hazard flag(s): legs crossing freshly built terrain (repose-angle edges)`);
      alertMsg("info", `plan solved: ${(t.energy_J / 1e6).toFixed(1)} MJ · ${(t.time_s / 3600).toFixed(1)} h · ${t.resolved_algorithm || t.algorithm}`);
      ds.innerHTML =
        chip("moved", `${((t.cut_kg + (t.fill_kg || 0)) / 1000).toFixed(1)} t`) +
        chip("energy", `${(t.energy_J / 1e6).toFixed(1)} MJ`) +
        chip("recharges", t.recharges ?? "—") +
        chip("duration", `${(t.time_s / 3600).toFixed(1)} h`) +
        chip("hazard flags", hz ? `⚠ ${hz}` : "0") +
        chip("solver", t.resolved_algorithm || t.algorithm || "—");
      ds.style.display = "flex";
      // UI-17: the ROUTE HERO (the authored plan view, enlarged) + the ACTIVITY GANTT
      const db = $("dashboards");
      if (db) {
        db.style.display = "flex";
        const hero = $("routehero"), hc = hero.getContext("2d");
        hc.fillStyle = "#05060c"; hc.fillRect(0, 0, hero.width, hero.height);
        const src = qel("plancanvas");
        if (src) hc.drawImage(src, 0, 0, hero.width, hero.height);
        drawGantt((j.timeline && j.timeline.frames) || []);   // timeline = {frames, duration_s, ...}
      }
      // #74: the per-trip math worksheet (Aaron: "never assume")
      fetch("/plan/math", { method: "POST", headers: apiHeaders(),
        body: JSON.stringify({ name: "math", body: sel.value, charger: [0, 0],
          orders: ORDERS, algorithm: qel("qalgo").value, objective: qel("qobj").value,
          precedence: parsePrec(), keepouts: KEEPOUTS, ...fleet(), ...site() }) })
        .then((r) => r.json()).then((mj) => {
          if (!mj.ok) return;
          const ms = $("mathsheet"), mb = $("mathbody"); if (!mb) return;
          const c = mj.constants;
          // S-02: build the worksheet from DOM nodes -- the leg kind/label and per-term name/value
          // (which can derive from user-supplied order labels) enter only via textContent.
          mb.replaceChildren();
          mb.appendChild(el("div", { style: "opacity:.7;margin-bottom:6px" },
            `constants: DIG ${c.DIG_J_PER_KG} J/kg · DRIVE ${c.DRIVE_J_PER_M} J/m · speed ${c.DRIVE_SPEED_MS} m/s · dig-rate ${c.DIG_RATE_KG_S} kg/s · g ${c.g_m_s2} m/s²`));
          mj.legs.forEach((lg) => {
            if (!lg.terms.length) return;
            const tbody = el("table", { style: "width:100%;border-collapse:collapse;margin-top:2px" });
            lg.terms.forEach((t) => {
              tbody.appendChild(el("tr", null,
                el("td", { style: "color:var(--muted);padding-right:8px" }, t.name),
                el("td", { style: "font-family:monospace" }, `${t.substituted} ${t.unit}`)));
            });
            mb.appendChild(el("div", { style: "border-left:3px solid var(--line);padding:3px 8px;margin:4px 0" },
              el("b", null, `${lg.kind} · ${lg.label}`), tbody));
          });
          ms.style.display = "block";
        }).catch(() => {});
    }
    const v = j.validation || {};
    const vtag = (v.feasible ? " · ✓ authority-validated" : (v.mass_conserved !== undefined ? " · ⚠ infeasible" : ""))
      // P0 as-built acceptance: flatness of the executed surface measured on the REAL terrain (not a flat mantle)
      + (v.as_built_on_real_dem ? ` · as-built ${(v.as_built_flatness_rmse_m * 100).toFixed(1)} cm `
          + `${v.as_built_pass ? "✓" : `✗ (>${(v.as_built_tol_m * 100).toFixed(0)} cm)`}` : "");
    // I10: hauls routed around real-DEM hazards — show detour over straight lines + any blocked legs
    const rtag = t.routed_haul ? ` · haul +${(t.haul_detour_frac * 100).toFixed(1)}% around hazards`
                 + (t.blocked_legs ? ` (⚠ ${t.blocked_legs} blocked)` : "") : "";
    // show the chosen algorithm (resolved, if 'auto') + objective + any precedence honored
    const atag = ` · ${t.algorithm === t.resolved_algorithm ? t.algorithm : t.algorithm + "→" + t.resolved_algorithm}`
      + `/${t.objective}` + (t.n_precedence ? ` · ${t.n_precedence} precedence` : "");
    // single-charge range ("true distance before recharge"): slope+slip-adjusted if a DEM was used
    const e = j.endurance || {};
    const erng = e.range_slopeslip_km != null ? e.range_slopeslip_km : e.range_flat_reserve_km;
    const etag = erng != null ? ` · range ${erng.toFixed(0)} km/charge` : "";
    // closed-loop autonomy + the AutoNav onboard estimate (perception) uncertainty, folded into /plan
    const au = j.autonomy || {};
    const autag = au.completed !== undefined
      ? ` · autonomy ${au.completed ? "✓" : "⚠"} ${au.recharges}rch/${au.replans}rpl, SoC ${(au.final_soc * 100).toFixed(0)}%, slip ${au.max_slip}` : "";
    const pc = j.perception || {};
    const ptag = pc.pose_sigma_m != null
      ? ` · est ±${pc.pose_sigma_m} m pose (${pc.map_fixes} map fixes`
        + (pc.observe_more_before_dig ? `, ${pc.observe_more_before_dig} observe-more` : "")
        + `), drum ±${pc.drum_fill_uncertainty_pct}%` : "";
    // P6 map channel (LAC §10): worksite coverage the executed route observed (onboard-observability tier)
    const mtag = pc.map_coverage != null
      ? ` · map ${(pc.map_coverage * 100).toFixed(0)}% covered`
        + (pc.map_observe_more_before_dig ? ` (${pc.map_observe_more_before_dig} survey-first)` : "") : "";
    // discrete keep-out obstacles: hauls routed around them; flag any build placed inside one
    const ktag = t.n_keepouts ? ` · ${t.n_keepouts} keep-out${t.keepout_conflicts ? ` (⚠ ${t.keepout_conflicts} build on obstacle)` : ""}` : "";
    // K11c: continuous survival/idle power (an [ASSUMPTION] term) when modelled
    const stag = t.survival_energy_J > 0 ? ` · +${(t.survival_energy_J / 1e6).toFixed(1)} MJ survival [assumption]` : "";
    // MV: multi-vehicle fleet -> parallel makespan + space-time deconfliction
    const ftag = t.vehicles > 1
      ? ` · ${t.vehicles} rovers, makespan ${(t.makespan_s / 3600).toFixed(1)} h, ${t.vehicle_conflicts} conflicts` : "";
    setQ(`report ready · cut ${(t.cut_kg / 1000).toFixed(1)}t → fill ${(t.fill_kg / 1000).toFixed(1)}t · `
         + `${(t.energy_J / 1e6).toFixed(1)} MJ · ${t.charges} recharges${ftag}${etag}${atag}${rtag}${ktag}${stag}${vtag}${autag}${ptag}${mtag}`);
    LAST_TIMELINE = j.timeline || null;                    // P5: enable execute + watch
    LAST_PLAN_IR = j.plan_ir || null;                      // the executable plan IR (download via ⤓ Plan IR)
    LAST_ORDERS = ORDERS.slice(); LAST_KEEPOUTS = KEEPOUTS.slice();
    qel("qexec").disabled = !LAST_TIMELINE;
    qel("reportframe").src = j.pdf;                        // embed the mission-control PDF in the Report pane
    qel("reportframe").classList.add("show");
    qel("reportopen").href = j.pdf;                        // ...with an "open in tab" escape hatch
    qel("reportempty").style.display = "none";
    setView("report");
  } catch (e) { setQ("plan failed. start the server: python3 server.py  (" + e + ")"); }
  finally { const pb = qel("qplan"); pb.disabled = false; pb.textContent = "Plan mission → open report"; }
};

// ---- import / export plans (round-trippable designer files) ------------------------------------
// a PROFILE = the full planning config snapshot (body, soil, fleet, orders, site, optimization).
function currentPlan() {
  return { body: sel.value, orders: ORDERS, keepouts: KEEPOUTS, precedence: qel("qprec").value,
           algorithm: qel("qalgo").value, objective: qel("qobj").value, ...fleet(), ...site() };
}
function restoreProfile(p) {                                // set the WHOLE UI from a profile object
  if (!Array.isArray(p.orders)) throw new Error("no orders[] in profile");
  ORDERS.length = 0; p.orders.forEach((o) => ORDERS.push(o));
  KEEPOUTS.length = 0; if (Array.isArray(p.keepouts)) p.keepouts.forEach((k) => KEEPOUTS.push(k));
  renderKeepouts();
  if (p.body && BODIES[p.body]) { sel.value = p.body; sel.dispatchEvent(new Event("change")); }
  if (p.precedence != null) qel("qprec").value = p.precedence;
  if (p.algorithm) qel("qalgo").value = p.algorithm;
  if (p.objective) qel("qobj").value = p.objective;
  if (p.vehicle && qel("vehicle")) qel("vehicle").value = p.vehicle;
  if (qel("vehcount") && p.vehicles) qel("vehcount").value = p.vehicles;
  if (qel("soil")) qel("soil").value = p.soil || "";
  if (qel("lat") && p.lat != null) qel("lat").value = p.lat;
  if (qel("lon") && p.lon != null) qel("lon").value = p.lon;
  if (Array.isArray(p.tools))
    document.querySelectorAll("#tools input").forEach((c) => { c.checked = p.tools.includes(c.value); });
  if (typeof syncKinds === "function") syncKinds();
  renderQueue();
}
qel("qexport").onclick = () => {
  const blob = new Blob([JSON.stringify(currentPlan(), null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${sel.value}_plan_${ORDERS.length}orders.json`;
  a.click(); URL.revokeObjectURL(a.href);
  setQ(`exported ${ORDERS.length} orders`);
};
qel("qplanir").onclick = () => {                         // download the machine-executable plan IR
  if (!LAST_PLAN_IR) { setQ("plan a mission first — the Plan IR comes from /plan"); return; }
  const blob = new Blob([JSON.stringify(LAST_PLAN_IR, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `plan_${LAST_PLAN_IR.plan_id || "ir"}.json`;
  a.click(); URL.revokeObjectURL(a.href);
  setQ(`exported plan IR ${LAST_PLAN_IR.plan_id} (${LAST_PLAN_IR.actions.length} actions)`);
};
qel("qcmds").onclick = async () => {                      // #66: the plan as a reusable RC command tape
  if (!ORDERS.length) { setQ("add orders first — commands come from the plan"); return; }
  try {
    const r = await fetch("/plan/commands", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ name: "cmds", body: sel.value, charger: [0, 0], orders: ORDERS,
        algorithm: qel("qalgo").value, objective: qel("qobj").value, ...fleet(), ...site() }) });
    const d = await r.json();
    if (!d.ok) { setQ("commands: " + (d.error || d.detail)); return; }
    const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = "rc_commands.json"; a.click(); URL.revokeObjectURL(a.href);
    setQ(`exported ${d.commands.length} RC commands (reusable GoTo tape)`);
  } catch (e) { setQ("commands failed: " + e); }
};
qel("qimport").onclick = () => qel("qfile").click();
qel("qfile").onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  try { restoreProfile(JSON.parse(await f.text())); setQ(`imported ${ORDERS.length} orders from ${f.name}`); }
  catch (err) { setQ("import failed: " + err.message); }
  e.target.value = "";
};
// server-side profiles: save the current config, list + load saved ones
async function refreshProfiles() {
  try {
    const d = await (await fetch("/profiles")).json();
    if (d && d.ok) qel("profload").innerHTML = d.profiles.map((n) => `<option>${esc(n)}</option>`).join("");
  } catch (err) { /* server not up */ }
}
qel("profsave").onclick = async () => {
  const name = (qel("profname").value || "").trim();
  if (!name) { setQ("name the profile first"); return; }
  try {
    const j = await (await fetch("/profile", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ name, profile: currentPlan() }) })).json();
    if (j.ok) { setQ(`saved profile '${j.name}'`); refreshProfiles(); } else { setQ("save failed: " + j.error); }
  } catch (err) { setQ("save failed (start the server): " + err); }
};
qel("profloadbtn").onclick = async () => {
  const slug = qel("profload").value; if (!slug) { setQ("no saved profiles"); return; }
  try {
    const j = await (await fetch("/profile/" + encodeURIComponent(slug))).json();
    if (j.profile) { restoreProfile(j.profile); setQ(`loaded profile '${j.name}'`); }
    else { setQ("load failed: " + (j.error || "")); }
  } catch (err) { setQ("load failed: " + err); }
};

// ---- P5: execute + watch — animate the planned timeline top-down with a telemetry HUD ----------
// #31: the control-room status rail -- per-channel chips + sparklines (exec-fed; chips carry
// the packet-channel names the runtime emits: imu/wheel/power/camera/thermal/pose).
const TELE_CH = ["pose", "wheel", "power", "drum", "camera", "thermal"];
const TELE_BUF = { batt: [], mass: [], slip: [] };
function teleChip(ch, text, ok) {
  const rail = qel("telerail"); if (!rail) return;
  let el = rail.querySelector(`[data-ch="${ch}"]`);
  if (!el) {
    el = document.createElement("span");
    el.dataset.ch = ch;
    el.style.cssText = "font-size:9px;font-family:Orbitron,system-ui;letter-spacing:.06em;padding:2px 6px;border:1px solid var(--line);border-radius:4px";
    rail.appendChild(el);
  }
  el.textContent = `${ch.toUpperCase()} ${text}`;
  el.style.color = ok ? "var(--txt)" : "#e0564b";
  el.style.borderColor = ok ? "var(--line)" : "#e0564b";
  if (typeof markFresh === "function") markFresh(el);
}
function teleSpark() {
  const cv = qel("telespark"); if (!cv) return;
  const ctx = cv.getContext("2d");
  ctx.fillStyle = "#0a0a0c"; ctx.fillRect(0, 0, cv.width, cv.height);
  const series = [["batt", "#e8273f"], ["mass", "#e07b39"], ["slip", "#4f9cff"]];
  series.forEach(([k, col]) => {
    const buf = TELE_BUF[k]; if (buf.length < 2) return;
    const mx = Math.max(...buf, 1e-9);
    ctx.strokeStyle = col; ctx.lineWidth = 1; ctx.beginPath();
    buf.forEach((v, i) => {
      const x = i / (buf.length - 1) * (cv.width - 4) + 2;
      const y = cv.height - 3 - (v / mx) * (cv.height - 8);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  });
}
function telePush(batt, mass, slip) {
  TELE_BUF.batt.push(batt); TELE_BUF.mass.push(mass); TELE_BUF.slip.push(slip);
  Object.values(TELE_BUF).forEach((b) => { if (b.length > 240) b.shift(); });
  teleSpark();
}
// UI-17: the activity Gantt -- one lane per phase kind, bars at [t0, t1], battery curve under.
function drawGantt(tl) {
  const cv = $("gantt"); if (!cv) return;
  const ctx = cv.getContext("2d");
  ctx.fillStyle = "#05060c"; ctx.fillRect(0, 0, cv.width, cv.height);
  if (!tl.length) {
    ctx.fillStyle = "#9ab"; ctx.font = "12px system-ui";
    ctx.fillText("plan a mission to populate the activity timeline", 16, 28);
    return;
  }
  const kinds = [...new Set(tl.map((p) => p.phase))];
  const COLORS = { drive: "#4f9cff", dig: "#e8273f", cut: "#e8273f", dump: "#e07b39",
                   fill: "#e07b39", haul: "#9966dd", recharge: "#3fa34d", goto: "#7bd0d0" };
  const T = Math.max(...tl.map((p) => p.t1)), L = 86, R = 12, TOP = 16;
  const laneH = Math.min(34, (cv.height - 110) / Math.max(1, kinds.length));
  const X = (t) => L + (t / T) * (cv.width - L - R);
  ctx.font = "10px Orbitron, system-ui"; ctx.textBaseline = "middle";
  kinds.forEach((k, i) => {
    const y = TOP + i * laneH;
    ctx.fillStyle = "#9ab"; ctx.textAlign = "right";
    ctx.fillText(k.toUpperCase().slice(0, 9), L - 8, y + laneH / 2);
    ctx.strokeStyle = "rgba(255,255,255,.05)";
    ctx.beginPath(); ctx.moveTo(L, y + laneH); ctx.lineTo(cv.width - R, y + laneH); ctx.stroke();
    tl.filter((p) => p.phase === k).forEach((p) => {
      ctx.fillStyle = COLORS[k] || "#c7d2e3";
      ctx.globalAlpha = .85;
      ctx.fillRect(X(p.t0), y + 4, Math.max(2, X(p.t1) - X(p.t0)), laneH - 8);
      ctx.globalAlpha = 1;
    });
  });
  // the battery curve under the lanes
  const by0 = TOP + kinds.length * laneH + 14, bh = cv.height - by0 - 26;
  ctx.strokeStyle = "#3a3f4a";
  ctx.strokeRect(L, by0, cv.width - L - R, bh);
  ctx.strokeStyle = "#e8273f"; ctx.lineWidth = 1.5; ctx.beginPath();
  tl.forEach((p, i) => {
    const y0 = by0 + (1 - p.batt0_frac) * bh, y1 = by0 + (1 - p.batt1_frac) * bh;
    if (i === 0) ctx.moveTo(X(p.t0), y0); else ctx.lineTo(X(p.t0), y0);
    ctx.lineTo(X(p.t1), y1);
  });
  ctx.stroke(); ctx.lineWidth = 1;
  ctx.fillStyle = "#9ab"; ctx.textAlign = "right";
  ctx.fillText("BATT", L - 8, by0 + bh / 2);
  // the time axis
  ctx.textAlign = "center";
  for (let h = 0; h <= T / 3600; h += Math.max(1, Math.round(T / 3600 / 6))) {
    ctx.fillText(`${h}h`, X(h * 3600), cv.height - 12);
  }
}
let LAST_TIMELINE = null, LAST_ORDERS = [], LAST_KEEPOUTS = [], LAST_PLAN_IR = null, EXEC_RAF = 0;
let EXEC_SPEEDUP = 60;                                     // sim seconds per wall-clock second (B0.3: mutable)
let EXEC_PAUSED = false;
function execExtent(tl, orders) {
  // world bounds covering the charger, every order site, and every route waypoint -> canvas transform
  const xs = [tl.charger[0]], ys = [tl.charger[1]];
  orders.forEach(o => { xs.push(o.x); ys.push(o.y); });
  tl.frames.forEach(f => { xs.push(f.x0, f.x1); ys.push(f.y0, f.y1); });
  let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const padx = Math.max(5, (x1 - x0) * 0.12), pady = Math.max(5, (y1 - y0) * 0.12);
  return { x0: x0 - padx, x1: x1 + padx, y0: y0 - pady, y1: y1 + pady };
}
function execDraw(tl, orders, ext, cv, simT) {
  markFresh(cv);                                           // UI-5: the telemetry canvas freshness
  if ($("conops") && tl && tl.length) {                    // UI-8: live cycle position during playback
    let done = 0;
    for (const e of tl) if ((e.t ?? 0) <= simT) done++;
    $("conops").textContent = `CONOPS EXEC · event ${Math.min(done, tl.length)}/${tl.length}`;
  }
  const ctx = cv.getContext("2d"), W = cv.width, H = cv.height;
  const sx = W / (ext.x1 - ext.x0), sy = H / (ext.y1 - ext.y0), s = Math.min(sx, sy);
  const ox = (W - s * (ext.x1 - ext.x0)) / 2, oy = (H - s * (ext.y1 - ext.y0)) / 2;
  const X = wx => ox + (wx - ext.x0) * s, Y = wy => H - (oy + (wy - ext.y0) * s);   // y up
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "#05060c"; ctx.fillRect(0, 0, W, H);
  // keep-out obstacles (the route bends around these): hatched red discs in the local frame
  LAST_KEEPOUTS.forEach(k => {
    ctx.fillStyle = "rgba(224,86,75,.22)"; ctx.strokeStyle = "#e0564b"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(X(k.x), Y(k.y), k.r * s, 0, 7); ctx.fill(); ctx.stroke();
  });
  // order footprints (cut = blue, fill = orange) as squares sized by area
  orders.forEach((o, i) => {
    const half = Math.sqrt(o.footprint_m2) / 2 * s;
    ctx.fillStyle = o.kind === "cut" ? "rgba(79,156,255,.28)" : "rgba(224,123,57,.28)";
    ctx.strokeStyle = o.kind === "cut" ? "#4f9cff" : "#e07b39"; ctx.lineWidth = 1;
    ctx.fillRect(X(o.x) - half, Y(o.y) - half, half * 2, half * 2);
    ctx.strokeRect(X(o.x) - half, Y(o.y) - half, half * 2, half * 2);
    ctx.fillStyle = "#cfd8e3"; ctx.font = "11px system-ui";              // B0.4 order labels
    ctx.fillText(`${i + 1}. ${o.kind}`, X(o.x) - half + 4, Y(o.y) - half + 14);
  });
  // item 3d: the planned terrain-following route(s), same geometry the 2D plan canvas shows (links the
  // route into the playback view; routed = dashed green, blocked = dashed red). The rover marker below
  // follows the time/energy timeline forecast.
  LAST_ROUTES.forEach(rt => {
    const wp = rt.waypoints || [];
    if (rt.reached && wp.length >= 2) {
      ctx.strokeStyle = "rgba(63,163,77,.5)"; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(X(wp[0][0]), Y(wp[0][1]));
      for (let i = 1; i < wp.length; i++) ctx.lineTo(X(wp[i][0]), Y(wp[i][1]));
      ctx.stroke(); ctx.setLineDash([]);
    } else if (rt.from_xy && rt.to_xy) {
      ctx.strokeStyle = "rgba(224,86,75,.6)"; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(X(rt.from_xy[0]), Y(rt.from_xy[1])); ctx.lineTo(X(rt.to_xy[0]), Y(rt.to_xy[1]));
      ctx.stroke(); ctx.setLineDash([]);
    }
  });
  // driven route so far (solid) + remaining (faint)
  ctx.lineWidth = 1.5;
  tl.frames.forEach(f => {
    if (f.phase !== "drive") return;
    const done = simT >= f.t1;
    ctx.strokeStyle = done ? "#6ee7a8" : "rgba(110,231,168,.25)";
    ctx.beginPath(); ctx.moveTo(X(f.x0), Y(f.y0)); ctx.lineTo(X(f.x1), Y(f.y1)); ctx.stroke();
  });
  // charger
  ctx.fillStyle = "#ffd166"; ctx.beginPath(); ctx.arc(X(tl.charger[0]), Y(tl.charger[1]), 4, 0, 7); ctx.fill();
  // rover marker at the interpolated position for simT
  const fr = tl.frames.find(f => simT >= f.t0 && simT <= f.t1) || tl.frames[tl.frames.length - 1];
  const u = fr.t1 > fr.t0 ? (simT - fr.t0) / (fr.t1 - fr.t0) : 1;
  const rx = fr.x0 + (fr.x1 - fr.x0) * u, ry = fr.y0 + (fr.y1 - fr.y0) * u;
  ctx.fillStyle = fr.phase === "charge" ? "#ffd166" : fr.phase === "dig" ? "#e07b39" : "#fff";
  ctx.beginPath(); ctx.arc(X(rx), Y(ry), 5, 0, 7); ctx.fill();
  ctx.strokeStyle = "#0b0e17"; ctx.lineWidth = 1.5; ctx.stroke();
  return fr;
}
function runExecution() {
  const tl = LAST_TIMELINE; if (!tl || !tl.frames.length) return;
  cancelAnimationFrame(EXEC_RAF);
  setView("metrics");                                       // swap to the Metrics pane for the telemetry playback
  qel("execempty").style.display = "none";
  qel("execspeed").textContent = ` ${EXEC_SPEEDUP}×`;
  const cv = qel("execcanvas"), ext = execExtent(tl, LAST_ORDERS);
  const dur = tl.duration_s; let simT = 0, prevWall = null;
  const fmtT = s => { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return `${h}h ${m}m`; };
  function frame(now) {
    if (prevWall === null) prevWall = now;
    if (!EXEC_PAUSED) simT += (now - prevWall) / 1000 * EXEC_SPEEDUP;   // B0.3 pause
    prevWall = now;
    if (simT > dur) simT = dur;
    const fr = execDraw(tl, LAST_ORDERS, ext, cv, simT);
    qel("excphase").textContent = fr.phase;
    qel("exctime").textContent = `${fmtT(simT)} / ${fmtT(dur)}`;
    const u = fr.t1 > fr.t0 ? (simT - fr.t0) / (fr.t1 - fr.t0) : 1;
    qel("excpos").textContent = `${(fr.x0 + (fr.x1 - fr.x0) * u).toFixed(0)}, ${(fr.y0 + (fr.y1 - fr.y0) * u).toFixed(0)} m`;
    qel("excmass").textContent = `${(fr.cum_mass_kg / 1000).toFixed(2)} t`;
    const bf = fr.batt0_frac + (fr.batt1_frac - fr.batt0_frac) * u;
    qel("excbattfill").style.width = `${Math.max(0, bf * 100).toFixed(0)}%`;
    qel("excbattfill").style.background = bf < 0.2 ? "#e0564b" : "var(--accent)";
    qel("excbattlbl").textContent = `${(bf * 100).toFixed(0)}%`;
    if ((frame._n = (frame._n || 0) + 1) % 15 === 0) {     // #31: feed the rail ~4x/s
      telePush(bf, fr.cum_mass_kg, fr.slip || 0);
      teleChip("pose", `${(fr.x0 + (fr.x1 - fr.x0) * u).toFixed(0)},${(fr.y0 + (fr.y1 - fr.y0) * u).toFixed(0)}`, true);
      teleChip("power", `${(bf * 100).toFixed(0)}%`, bf > 0.2);
      teleChip("wheel", fr.phase, true);
      teleChip("drum", `${(fr.cum_mass_kg / 1000).toFixed(2)}t`, true);
    }
    if (simT < dur) EXEC_RAF = requestAnimationFrame(frame);
    else {
      qel("excphase").textContent = "complete";
      recordPose(fr.x1, fr.y1);                            // #65: where the rover ENDED
    }
  }
  EXEC_RAF = requestAnimationFrame(frame);
}
qel("qexec").onclick = runExecution;
qel("execpause").onclick = () => { EXEC_PAUSED = !EXEC_PAUSED; qel("execpause").textContent = EXEC_PAUSED ? "▶" : "⏸"; };
qel("execspd").onclick = () => { EXEC_SPEEDUP = EXEC_SPEEDUP === 10 ? 60 : EXEC_SPEEDUP === 60 ? 600 : 10;
  qel("execspeed").textContent = ` ${EXEC_SPEEDUP}×`; };
qel("execclose").onclick = () => { cancelAnimationFrame(EXEC_RAF); setView("plan"); };

// ---- compare algorithms: POST /compare -> a table sorted by the chosen objective --------------
qel("qcompare").onclick = async () => {
  if (!ORDERS.length) { setQ("add at least one order first"); return; }
  const obj = qel("qobj").value;
  setQ(`comparing algorithms by ${obj}…`);
  try {
    const res = await fetch("/compare", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ name: "compare", body: sel.value, charger: [0, 0], orders: ORDERS, objective: obj, precedence: parsePrec(), ...fleet() }) });
    const j = await res.json();
    if (!j.ok) { setQ("compare error: " + j.error); return; }
    const fmt = { time_s: v => (v / 3600).toFixed(1) + " h", energy_J: v => (v / 1e6).toFixed(1) + " MJ",
      avg_power_w: v => v.toFixed(0) + " W", distance_m: v => (v / 1000).toFixed(2) + " km",
      charges: v => v.toFixed(0), mass_kg: v => (v / 1000).toFixed(1) + " t" };
    const cols = ["algorithm", "time_s", "energy_J", "avg_power_w", "distance_m", "charges", "mass_kg"];
    const head = "<tr>" + cols.map(c => `<th style="text-align:left;color:var(--muted)">${c.replace('_s','').replace('_J','').replace('_w','').replace('_m','').replace('_kg','')}</th>`).join("") + "</tr>";
    const rows = j.rows.map((r, i) => "<tr>" + cols.map(c => {
      if (c === "algorithm") return `<td><b>${r.algorithm}${i === 0 ? " ★" : ""}${r.pareto ? " ⬩" : ""}</b></td>`;
      return `<td>${r.error ? "—" : fmt[c](r[c])}</td>`;
    }).join("") + "</tr>").join("");
    const t = qel("cmptable"); t.innerHTML = head + rows; t.style.display = "table";
    setQ(`compared ${j.rows.length} algorithms by ${obj} (★ best, ⬩ Pareto-optimal); pick one in the dropdown to plan it`);
  } catch (e) { setQ("compare failed — run server.py (" + e + ")"); }
};

// ---- drum-fill sensing: POST /sense (motor-current observable -> inferred mass + offload) ------
// The "sensor noise" checkbox is the noise toggle: unchecked = OFF (deterministic), checked = seeded.
async function senseDrum() {
  const kg = +qel("drumkg").value, noise = qel("drumnoise").checked ? 0.15 : 0.0;
  try {
    const res = await fetch("/sense", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ true_mass_kg: kg, noise_frac: noise, seed: 1 }) });
    const j = await res.json();
    if (!j.ok) { qel("drumout").textContent = "error: " + j.error; return; }
    qel("drumout").textContent =
      `${j.current_a.toFixed(2)} A → inferred ${j.inferred_kg.toFixed(1)} kg `
      + `±${(j.uncertainty_frac * 100).toFixed(1)}% (${j.lower_kg.toFixed(1)}–${j.upper_kg.toFixed(1)}) `
      + (j.offload ? "· OFFLOAD → process" : "· keep digging");
    teleChip("drum", `${j.inferred_kg.toFixed(1)} kg`, true);
  } catch (e) { qel("drumout").textContent = "— start the server: python3 server.py"; }
}
["drumkg", "drumnoise"].forEach((id) => qel(id).addEventListener("input", senseDrum));

// Fleet: vehicle + mounted tools (from bodies.json _vehicles/_tools, the py source). The effective
// capabilities (base vehicle + mounted tools) gate which order kinds are offered -- e.g. sinter only
// appears when a sinter tool is mounted (it is a separate entity, not on the IPEx excavator).
function fleet() {
  const tools = [...document.querySelectorAll("#tools input:checked")].map((c) => c.value);
  const soil = qel("soil") ? qel("soil").value : "";        // "" -> the body's own regolith
  const vehicles = Math.max(1, parseInt(qel("vehcount").value, 10) || 1);   // MV: fleet size (>1 = multi)
  return { vehicle: (qel("vehicle").value || "ipex"), tools, vehicles, ...(soil ? { soil } : {}) };
}
// M11: when a site lat/lon is set (typed or picked), send it so the plan anchors there (else the
// planner uses the auto flattest site). Only Moon's Haworth DEM is georeferenced for this today.
let CURRENT_SITE = "haworth";                            // REG-01: the imported site the planner targets
function site() {
  const lat = parseFloat(qel("lat").value), lon = parseFloat(qel("lon").value);
  const out = { site: CURRENT_SITE };
  if (Number.isFinite(lat) && Number.isFinite(lon)) { out.lat = lat; out.lon = lon; }
  return out;
}
function fleetCaps() {
  const v = (PHY && PHY._vehicles) ? PHY._vehicles[qel("vehicle").value] : null;
  const caps = new Set((v && v.capabilities) ? v.capabilities : ["drive", "excavate", "haul", "dump", "compact"]);
  if (PHY && PHY._tools) for (const t of fleet().tools) { const td = PHY._tools[t]; if (td) caps.add(td.capability); }
  return caps;
}
function syncKinds() {
  const caps = fleetCaps(), kind = qel("qkind"), cur = kind.value;
  const opts = [["cut", "excavate"], ["fill", "dump"], ["sinter", "sinter"]].filter(([, c]) => caps.has(c));
  kind.innerHTML = opts.map(([k]) => `<option value="${k}">${k}</option>`).join("");
  if (opts.some(([k]) => k === cur)) kind.value = cur;
  const fc = qel("fleetcaps");
  fc.innerHTML = "";
  const sumr = document.createElement("span");
  sumr.textContent = `${caps.size} capabilities `;
  const info = document.createElement("button");
  info.textContent = "ⓘ vehicle"; info.style.cssText = "background:none;border:1px solid var(--line);border-radius:4px;color:var(--accent);cursor:pointer;font-size:10px;padding:1px 6px";
  fc.append(sumr, info);
  popover("fleet", info, () => {
    const v = (PHY && PHY._vehicles) ? PHY._vehicles[qel("vehicle").value] : null;
    if (!v) return "<i>registry unavailable</i>";
    const row = (k, val) => `<tr><td style="color:var(--muted);padding-right:10px">${k}</td><td style="text-align:right">${val}</td></tr>`;
    return `<b>${v.label}</b><table style="width:100%;border-collapse:collapse;margin-top:4px">` +
      row("capabilities", [...caps].sort().join(", ")) +
      row("dry mass", `${v.dry_mass_kg} kg`) + row("wheels", v.n_wheels) +
      row("drum capacity", `${v.drum_capacity_kg} kg`) +
      row("drive power", `${v.drive_power_w} W`) +
      row("dig energy", `${v.dig_energy_j_per_kg} J/kg`) +
      `</table><div style="opacity:.6;margin-top:4px">registry values (provenance-tagged in stewie/specs/vehicles.py)</div>`;
  });
  refreshPopovers();
}
function populateFleet() {
  if (!PHY || !PHY._vehicles) return;
  qel("vehicle").innerHTML = Object.entries(PHY._vehicles)
    .map(([k, v]) => `<option value="${esc(k)}">${esc(v.label)}</option>`).join("");   // SEC-04
  qel("tools").innerHTML = "tools: " + (PHY._tools ? Object.entries(PHY._tools)
    .map(([k, t]) => `<label><input type="checkbox" value="${esc(k)}"> ${esc(t.label)}</label>`).join(" ") : "none");
  if (qel("soil")) {                                          // soil model = any body's regolith (default: this body's)
    const bodies = Object.keys(PHY).filter((k) => !k.startsWith("_"));
    qel("soil").innerHTML = '<option value="">(body default)</option>'
      + bodies.map((k) => `<option value="${esc(k)}">${esc(PHY[k].label || k)} soil</option>`).join("");
  }
  [...document.querySelectorAll("#tools input")].forEach((c) => c.addEventListener("change", syncKinds));
  qel("vehicle").addEventListener("change", syncKinds);
  syncKinds();
}

// load the py-generated terramechanics + IPEx constants (single source); graceful on file://
fetch("/bodies.json").then((r) => (r.ok ? r.json() : null)).then((d) => {
  if (d) { PHY = d; showTerra(); estimate(); populateFleet(); }
}).catch(() => {});
refreshProfiles();                                            // populate the saved-profiles dropdown
// ---- S-4: the Catalog (saved missions + custom structure templates) ---------------------------
async function refreshCatalog() {
  try {
    const ms = await (await fetch("/missions")).json();
    const ol = $("mslist"); ol.innerHTML = "";
    (ms.missions || []).forEach((m) => {
      const li = document.createElement("li");
      li.append(`${m.title || m.name} · ${m.body} · ${m.n_orders} orders `,
        mkbtn("⤓ load", async () => {
          const d = (await (await fetch(`/missions/${m.name}`)).json()).doc;
          if (!d) return;
          if (d.body && d.body !== sel.value) { sel.value = d.body; sel.onchange(); }
          ORDERS.length = 0; (d.orders || []).forEach((o) => ORDERS.push(o));
          KEEPOUTS.length = 0; (d.keepouts || []).forEach((k) => KEEPOUTS.push(k));
          if ($("msnotes")) $("msnotes").value = d.note || "";
          if (d.lander) { setLander(d.lander.x || 0, d.lander.y || 0);
            if ($("landx")) { $("landx").value = LANDER_P.x; $("landy").value = LANDER_P.y; } }
          renderQueue(); setQ(`loaded mission "${m.title || m.name}"`);
        }),
        mkbtn("✕", async () => {
          await fetch(`/missions/${m.name}`, { method: "DELETE", headers: apiHeaders() });
          refreshCatalog();
        }));
      ol.appendChild(li);
    });
    const st = await (await fetch("/structures/custom")).json();
    const sl = $("stlist"); sl.innerHTML = "";
    (st.structures || []).forEach((s) => {
      const li = document.createElement("li");
      li.append(`${s.title || s.name} · ${s.n_entries} parts `,
        mkbtn("⤓ place", async () => {
          const x = +$("qx").value || 0, y = +$("qy").value || 0;
          const ex = await (await fetch(`/structures/custom/${s.name}/expand?x=${x}&y=${y}`)).json();
          if (ex.ok) { ex.orders.forEach((o) => ORDERS.push(o)); renderQueue();
            setQ(`placed "${s.name}" at (${x}, ${y})`); }
        }),
        mkbtn("✕", async () => {
          await fetch(`/structures/custom/${s.name}`, { method: "DELETE", headers: apiHeaders() });
          refreshCatalog();
        }));
      sl.appendChild(li);
    });
  } catch (e) { /* offline preview */ }
}
$("mssave").onclick = async () => {
  const name = $("msname").value.trim(); if (!name) { setQ("name the mission first"); return; }
  const r = await fetch(`/missions/${encodeURIComponent(name)}`, { method: "POST",
    headers: apiHeaders(), body: JSON.stringify({ body: sel.value, orders: ORDERS,
      keepouts: KEEPOUTS, precedence: parsePrec(), note: $("msnotes") ? $("msnotes").value : "",
      lander: { x: LANDER_P.x, y: LANDER_P.y } }) });
  if (r.status === 401) { setQ("⚠ API key required: ⚙ Settings"); setView("settings"); return; }
  setQ((await r.json()).ok ? `saved mission "${name}"` : "save failed"); refreshCatalog();
};
$("stsave").onclick = async () => {
  const name = $("stname").value.trim(); if (!name) { setQ("name the template first"); return; }
  const work = ORDERS.filter((o) => o.kind !== "goto");
  if (!work.length) { setQ("queue some orders first -- the template captures them relative to the first"); return; }
  const ox = work[0].x, oy = work[0].y;
  const kind_list = work.map((o) => ({ kind: o.kind, dx: o.x - ox, dy: o.y - oy,
    footprint_m2: o.footprint_m2, depth_m: o.depth_m }));
  const r = await fetch(`/structures/custom/${encodeURIComponent(name)}`, { method: "POST",
    headers: apiHeaders(), body: JSON.stringify({ kind_list }) });
  if (r.status === 401) { setQ("⚠ API key required: ⚙ Settings"); setView("settings"); return; }
  setQ((await r.json()).ok ? `template "${name}" saved` : "template save failed"); refreshCatalog();
};
refreshCatalog();

// lazy: /sense is auth-gated -- fire on first user interaction, not page load (401-on-load fix)
qel("drumkg").addEventListener("focus", () => senseDrum(), { once: true });

window.addEventListener("resize", () => { if (viewer) viewer.resize(); });  // globe follows window size

// item 5: populate the sample-mission dropdown + load a bundled tutorial mission into the queue
fetch("/sample_missions").then(r => r.json()).then(j => {
  if (!j || !j.ok) return;
  const ss = qel("qsample");
  j.samples.forEach(s => { const o = document.createElement("option"); o.value = s.name; o.textContent = s.name; ss.appendChild(o); });
}).catch(() => {});
qel("qloadsample").onclick = async () => {
  const name = qel("qsample").value; if (!name) return;
  try {
    const m = await (await fetch("/sample_mission/" + name)).json();
    ORDERS.length = 0; (m.orders || []).forEach(o => ORDERS.push(o));
    KEEPOUTS.length = 0; (m.keepouts || []).forEach(k => KEEPOUTS.push(k));
    LAST_ROUTES = [];
    if (m.body) sel.value = m.body;
    renderQueue(); renderKeepouts(); drawPlan();
    setQ("loaded tutorial mission: " + name + " — press Plan mission");
  } catch (e) { setQ("sample load failed: " + e); }
};

loadBody("moon"); estimate(); renderQueue(); renderKeepouts(); setView("plan");
