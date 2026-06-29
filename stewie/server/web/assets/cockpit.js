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

// ICON-SET: paint the production-grade monochrome SVG glyphs onto the icon-only toolbar buttons. The
// markup carries the title= + aria-label= (tooltip + a11y name); this fills the visual glyph from
// web/assets/icons.js. CSP-safe: STEWIE_ICONS.icon() returns inline <svg> markup, not script. A button
// keeping a word label (ToolBox / keep-out circle / Settings / the alert badge) has an empty
// <span class="ic-slot"> the glyph drops into; a pure icon button gets its innerHTML set directly.
(function initToolbarIcons() {
  var ICONS = (typeof window !== "undefined") && window.STEWIE_ICONS;
  if (!ICONS) return;                                       // module not loaded -> leave aria-label text
  // id -> icon name for the pure icon-only buttons (no retained word label).
  var DIRECT = {
    plan3dfly: "fly", plan3dcoords: "coords", plan3dplot: "plot", plan3dmeasure: "measure",
    plan3dplotclear: "clear", editdel: "delete",
  };
  for (var id in DIRECT) {
    var b = document.getElementById(id);
    if (b) b.innerHTML = ICONS.icon(DIRECT[id]);
  }
  // etool buttons are addressed by data-tool (no id).
  var ETOOL = { note: "note", box: "box", measure: "measure" };
  for (var tool in ETOOL) {
    var et = document.querySelector('.etool[data-tool="' + tool + '"]');
    if (et) et.innerHTML = ICONS.icon(ETOOL[tool]);
  }
  // buttons that keep a word label: drop the glyph into the leading .ic-slot span.
  var SLOTTED = [["editmode", "edit"], ["alertbtn", "alert"]];
  var keepoutBtn = document.querySelector('.etool[data-tool="keepout"]');
  if (keepoutBtn) { var ks = keepoutBtn.querySelector(".ic-slot"); if (ks) ks.innerHTML = ICONS.icon("keepout"); }
  var settingsItem = document.querySelector('.profitem[data-view="settings"]');
  if (settingsItem) { var ss = settingsItem.querySelector(".ic-slot"); if (ss) ss.innerHTML = ICONS.icon("settings"); }
  SLOTTED.forEach(function (pair) {
    var el = document.getElementById(pair[0]);
    if (el) { var slot = el.querySelector(".ic-slot"); if (slot) slot.innerHTML = ICONS.icon(pair[1]); }
  });
  // execpause boots showing the pause glyph (running state); the toggle (below) swaps pause<->play.
  var ep = document.getElementById("execpause");
  if (ep) ep.innerHTML = ICONS.icon("pause");
})();

// UX-04 (WAI-ARIA tabs): the view switcher is a tablist, the panes are tabpanels, and Left/Right/Home/
// End move + activate between tabs (the active tab carries tabindex 0, the rest -1 -- set in setView).
(function initTabsA11y() {
  const tl = document.getElementById("viewtabs");
  if (tl) {
    tl.setAttribute("role", "tablist");
    tl.setAttribute("aria-label", "Cockpit views");
    tl.addEventListener("keydown", (e) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
      const tabs = [...tl.querySelectorAll(".vtab")].filter((b) => b.offsetParent !== null);
      let i = tabs.indexOf(document.activeElement);
      if (i < 0) i = 0;
      e.preventDefault();
      const j = e.key === "ArrowRight" ? (i + 1) % tabs.length
        : e.key === "ArrowLeft" ? (i - 1 + tabs.length) % tabs.length
        : e.key === "Home" ? 0 : tabs.length - 1;
      tabs[j].focus(); tabs[j].click();                    // activate-on-focus (the cockpit's tabs are cheap)
    });
  }
  document.querySelectorAll(".pane").forEach((p) => p.setAttribute("role", "tabpanel"));
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
  // GI-02: the globe is now rendered at the SELECTED body's true radius (Moon 1737.4 km / Mars 3389.5 km;
  // Earth WGS84), not the Earth-sized default. Built via Cesium 1.119's supported per-body path: set
  // Ellipsoid.default + pass the `ellipsoid` Viewer option BEFORE construction (NOT the custom-Globe path
  // that errored in 1.119 and black-screened the prior rewrite). Sourced radii live in globe_ellipsoid.js.
  // Degrade to WGS84 if that helper did not load, so the globe never black-screens on a missing asset.
  const bodyEll = (window.STEWIE_GLOBE && window.STEWIE_GLOBE.bodyEllipsoid)
    ? window.STEWIE_GLOBE.bodyEllipsoid(Cesium, key) : null;
  ellipsoid = bodyEll || Cesium.Ellipsoid.WGS84;
  try { Cesium.Ellipsoid.default = ellipsoid; } catch (e) { /* older Cesium: per-body via Viewer option below */ }
  try {                                       // B0.1: GPU-less machines must get a usable site map
  viewer = new Cesium.Viewer("cesium", {
    baseLayer: false, baseLayerPicker: false, geocoder: false, timeline: false,
    animation: false, sceneModePicker: false, homeButton: false, navigationHelpButton: false,
    fullscreenButton: false, infoBox: false, selectionIndicator: false,
    ellipsoid: ellipsoid,
    // G6 (#252): retain the WebGL drawing buffer so scene.canvas.toDataURL() can capture the map (the
    // "capture map" PNG export). Minor per-frame cost; required -- without it toDataURL yields a blank image.
    contextOptions: { webgl: { preserveDrawingBuffer: true } },
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
  // GI-02: with a per-body (non-WGS84) ellipsoid, Cesium does NOT build a skyAtmosphere (it is the Earth-
  // specific atmosphere model), so scene.skyAtmosphere is undefined -> guard before .show (it threw here).
  // When present (Earth), keep the object and set .show=false (do NOT set the property =false: Cesium's
  // render loop calls skyAtmosphere.setDynamicLighting() and `false` is "defined" -> TypeError).
  if (viewer.scene.skyAtmosphere) viewer.scene.skyAtmosphere.show = false;
  viewer.scene.globe.showGroundAtmosphere = false;
  viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#1a1a1a");
  viewer.canvas.style.cursor = "crosshair";      // #169: crosshair over the map (Cesium reverts to grab during a drag, then back)
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
    // #178: clicking the FIRST vertex of an in-progress polygon CLOSES it (the GIS close-the-ring gesture).
    // Must run before pin-selection, since the first vertex carries a selectable marker.
    if (EDIT.on && EDIT.tool === "poly" && POLY_PTS && POLY_PTS.length >= 3 &&
        pickedPin && pickedPin.id && POLY_PTS[0] && pickedPin.id === POLY_PTS[0].pin) {
      closePolygon(); return;
    }
    if (pickedPin && pickedPin.id && PIN_REFS.has(pickedPin.id)) {   // #64: select a pin
      if (SELECTED_PIN) SELECTED_PIN.point.outlineColor = Cesium.Color.BLACK;
      SELECTED_PIN = pickedPin.id;
      SELECTED_PIN.point.outlineColor = Cesium.Color.fromCssColorString("#39ff14");
      setQ("feature selected — press Delete to remove; in Edit, click a new spot to MOVE it");
      return;
    }
    if (EDIT.on && SELECTED_PIN) {                          // #64: edit-mode click MOVES the selection
      const cm = viewer.camera.pickEllipsoid(e.position, ellipsoid);
      if (cm) {
        const ca2 = Cesium.Cartographic.fromCartesian(cm, ellipsoid);
        const la2 = Cesium.Math.toDegrees(ca2.latitude), lo2 = Cesium.Math.toDegrees(ca2.longitude);
        fetch(`/dem/site_xy?lat=${la2}&lon=${lo2}&site=${encodeURIComponent(CURRENT_SITE)}`).then((r) => r.json()).then((d2) => {
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

  // live cursor coordinates (Esri status-bar pattern; Aaron 2026-06-10) + #169 floating over-cursor readout (toggleable)
  let _xyTimer = 0;
  handler.setInputAction((e) => {
    const el = $("cursorcoord"), fl = $("cursorxy");
    // #audit-1 (root fix): the live cursor coords belong to the PLAN map only. Gate the handler on the
    // active view so it can't re-show the readout while the operator is in Validate/Execute/etc. (the
    // previous one-shot hide in setView was overwritten by the next mouse-move).
    if (VIEW !== "plan") { if (el) el.textContent = ""; if (fl) fl.style.display = "none"; return; }
    const on = !$("coordtoggle") || $("coordtoggle").checked;        // #169: toggle the live coordinate readout
    if (!on) { if (el) el.textContent = ""; if (fl) fl.style.display = "none"; return; }
    const c = viewer.camera.pickEllipsoid(e.endPosition, ellipsoid);
    if (!c) { if (el) el.textContent = ""; if (fl) fl.style.display = "none"; return; }
    const ca = Cesium.Cartographic.fromCartesian(c, ellipsoid);
    const lat = Cesium.Math.toDegrees(ca.latitude), lon = Cesium.Math.toDegrees(ca.longitude);
    const txt = `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`;
    if (el) el.textContent = txt;
    if (fl) {                                                        // #169: float the readout next to the cursor
      const r = viewer.canvas.getBoundingClientRect();
      fl.textContent = txt;
      fl.style.left = `${r.left + e.endPosition.x + 14}px`;
      fl.style.top = `${r.top + e.endPosition.y + 14}px`;
      fl.style.display = "block";
    }
    // site-frame meters when inside the Haworth footprint (throttled; Esri status-bar style)
    if (sel.value === "moon" && HAWORTH_RECT &&
        Cesium.Rectangle.contains(HAWORTH_RECT, ca) && !_xyTimer) {
      _xyTimer = setTimeout(() => { _xyTimer = 0; }, 250);
      fetch(`/dem/site_xy?lat=${lat}&lon=${lon}&site=${encodeURIComponent(CURRENT_SITE)}`).then((r) => r.json()).then((d) => {
        if (d.ok) { const t2 = `${txt}  ·  site ${d.x_m} m, ${d.y_m} m`;
          if (el) el.textContent = t2; if (fl) fl.textContent = t2; }
      }).catch(() => {});
    }
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
  // #169: hide the floating readout when the cursor leaves the MAP AREA. Bind to the stable #viewarea
  // container, not viewer.canvas: the Cesium MOUSE_MOVE only fires over the canvas, and the canvas's own
  // `mouseleave` is missed on fast/overlay exits -- so the readout used to freeze on the pointer over the
  // left nav sidebar. #viewarea bounds the whole map region, so leaving it (onto the sidebar) clears both.
  const _mapArea = $("viewarea") || viewer.canvas;
  _mapArea.addEventListener("mouseleave", () => {
    if ($("cursorxy")) $("cursorxy").style.display = "none";
    if ($("cursorcoord")) $("cursorcoord").textContent = "";
  });
  if ($("coordtoggle")) $("coordtoggle").onchange = () => {
    if (!$("coordtoggle").checked) { if ($("cursorxy")) $("cursorxy").style.display = "none";
      if ($("cursorcoord")) $("cursorcoord").textContent = ""; }
  };

  // audit P1: the SCALE BAR -- meters-per-pixel sampled at screen center, niced to 1/2/5 steps
  function updateScale() {
    const sb = $("scalebar"), sv = $("scaleval");
    const w = viewer.scene.canvas.clientWidth, h = viewer.scene.canvas.clientHeight;
    const a = viewer.camera.pickEllipsoid(new Cesium.Cartesian2(w / 2 - 50, h / 2), ellipsoid);
    const b = viewer.camera.pickEllipsoid(new Cesium.Cartesian2(w / 2 + 50, h / 2), ellipsoid);
    const sb2 = $("scalebar2"), sv2 = $("scaleval2");
    if (!a || !b) { [sb, sb2].forEach((x) => x && (x.style.display = "none"));
      [sv, sv2].forEach((x) => x && (x.textContent = "")); return; }
    // GI-02: the globe is now rendered at the SELECTED body's true radius (per-body ellipsoid), so the
    // pickEllipsoid Cartesian distance is already in TRUE body meters -- no Earth-ratio rescale needed
    // (the prior `* radius/6371008.8` correction would now double-count and mis-scale the bar).
    const mpp = Cesium.Cartesian3.distance(a, b) / 100.0;
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
    const RECT = WORK_AREA_RECT || HAWORTH_RECT;            // GIS-WA1: the inset image IS the work area now
    if (!cv || !img || !img.complete || !RECT || sel.value !== "moon") return;
    cv.width = img.clientWidth || 1; cv.height = img.clientHeight || 1;
    const ctx = cv.getContext("2d"); ctx.clearRect(0, 0, cv.width, cv.height);
    const vr = viewer.camera.computeViewRectangle(ellipsoid);
    if (!vr) return;
    // Cesium Rectangle fields are RADIANS -- consistent here (vr is radians too)
    const W = RECT.west, E = RECT.east, S = RECT.south, N = RECT.north;
    const u = (lon) => (lon - W) / (E - W), v = (lat) => (N - lat) / (N - S);
    // GIS-WA1: the inset is the CLEAN work-area raster now (no matplotlib axis margins) -> no inset offset
    const M = { l: 0, r: 0, t: 0, b: 0 };
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
    const RECT = WORK_AREA_RECT || HAWORTH_RECT;            // GIS-WA1: pan over the work area (the inset's true extent)
    const M = { l: 0, r: 0, t: 0, b: 0 };                   // clean work-area raster: no axis margins
    let uu = ((e.clientX - r.left) / r.width - M.l) / (1 - M.l - M.r);
    let vv = ((e.clientY - r.top) / r.height - M.t) / (1 - M.t - M.b);
    uu = Math.min(1, Math.max(0, uu)); vv = Math.min(1, Math.max(0, vv));
    // RADIANS -> degrees before fromDegrees (the first cut fed radians in -- camera flew to ~0°)
    const W = Cesium.Math.toDegrees(RECT.west), E = Cesium.Math.toDegrees(RECT.east);
    const S = Cesium.Math.toDegrees(RECT.south), N = Cesium.Math.toDegrees(RECT.north);
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
  loadSiteFootprint();   // REG-01: (re)draw the selected site's footprint + rect (re-runnable on site change)
  drawGraticule();                                         // default-on, every body
  // #58: EVERY registry site linked on the globe like Haworth (marker + label; click = jump)
  fetch("/sites").then((r) => r.json()).then((j) => {
    if (!j.ok || !viewer) return;
    j.sites.forEach((s) => {
      if (s.name === "haworth") return;                    // Haworth has the footprint already
      SITE_MARKERS.push({ site: s, ent: viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(s.lon, s.lat, 0, ellipsoid),
        point: { pixelSize: 5, color: Cesium.Color.fromCssColorString(s.imported ? "#3fa34d" : "#e0b300"),
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
const LANDMARKS = [];                                      // #178/#174: named reference points {x, y, name, lat, lon} -- placed survey markers the locator measures distance FROM
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
    point: { pixelSize: 5, color: Cesium.Color.fromCssColorString(color),   // #pin-size (Aaron 2026-06-16: "dots too large, not precise enough") -- a smaller dot + black outline pinpoints the placed feature
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
let LANDER_PIN = null;                                     // #lander-pin: the single globe marker (unique)
let ROVER_PIN = null;                                      // #174: the single rover-position marker (unique)
function dropKeepoutCircle(lat, lon, r, ref) {             // #178: a VISIBLE circular barrier on the globe (not a dot)
  const red = Cesium.Color.fromCssColorString("#e0564b");
  const ent = viewer.entities.add({
    position: Cesium.Cartesian3.fromDegrees(lon, lat, 0, ellipsoid),
    point: { pixelSize: 4, color: red, outlineColor: Cesium.Color.BLACK, outlineWidth: 1 },
    ellipse: { semiMajorAxis: r, semiMinorAxis: r, height: 0, material: red.withAlpha(0.22),
               outline: true, outlineColor: red.withAlpha(0.9), outlineWidth: 2 },
    label: { text: `keep-out r${r} m`, font: "10px Orbitron, sans-serif",
             fillColor: Cesium.Color.fromCssColorString("#c7d2e3"), pixelOffset: new Cesium.Cartesian2(0, -14),
             showBackground: true, backgroundColor: Cesium.Color.fromCssColorString("#0a0a0cbb") },
  });
  EDIT_PINS.push(ent);
  if (ref) PIN_REFS.set(ent, ref);
  return ent;
}
function dropBoxKeepout(lat0, lon0, lat1, lon1, ref) {     // #178: a VISIBLE rectangular barrier on the globe
  const red = Cesium.Color.fromCssColorString("#e0564b");
  const w = Math.min(lon0, lon1), e = Math.max(lon0, lon1), s = Math.min(lat0, lat1), n = Math.max(lat0, lat1);
  const ent = viewer.entities.add({
    position: Cesium.Cartesian3.fromDegrees((w + e) / 2, (s + n) / 2, 0, ellipsoid),
    rectangle: { coordinates: Cesium.Rectangle.fromDegrees(w, s, e, n), height: 0,
                 material: red.withAlpha(0.22), outline: true, outlineColor: red.withAlpha(0.9) },
    label: { text: "box keep-out", font: "10px Orbitron, sans-serif",
             fillColor: Cesium.Color.fromCssColorString("#c7d2e3"), pixelOffset: new Cesium.Cartesian2(0, -10),
             showBackground: true, backgroundColor: Cesium.Color.fromCssColorString("#0a0a0cbb") },
  });
  EDIT_PINS.push(ent);
  if (ref) PIN_REFS.set(ent, ref);
  return ent;
}
function dropPolyKeepout(latlons, ref) {                   // #178: a VISIBLE polygon barrier on the globe
  const red = Cesium.Color.fromCssColorString("#e0564b");
  const flat = []; latlons.forEach(([la, lo]) => flat.push(lo, la));
  const cy = latlons.reduce((a, p) => a + p[0], 0) / latlons.length;
  const cx = latlons.reduce((a, p) => a + p[1], 0) / latlons.length;
  const ent = viewer.entities.add({
    position: Cesium.Cartesian3.fromDegrees(cx, cy, 0, ellipsoid),
    polygon: { hierarchy: Cesium.Cartesian3.fromDegreesArray(flat), height: 0,
               material: red.withAlpha(0.22), outline: true, outlineColor: red.withAlpha(0.9) },
    label: { text: "⬡ poly keep-out", font: "10px Orbitron, sans-serif",
             fillColor: Cesium.Color.fromCssColorString("#c7d2e3"), pixelOffset: new Cesium.Cartesian2(0, -10),
             showBackground: true, backgroundColor: Cesium.Color.fromCssColorString("#0a0a0cbb") },
  });
  EDIT_PINS.push(ent);
  if (ref) PIN_REFS.set(ent, ref);
  return ent;
}
function clearPolyDraft() {                                // #178: drop the in-progress polygon's temp markers + outline
  if (POLY_PTS) POLY_PTS.forEach((v) => {
    if (v.pin && viewer) { viewer.entities.remove(v.pin); PIN_REFS.delete(v.pin);
      const pi = EDIT_PINS.indexOf(v.pin); if (pi >= 0) EDIT_PINS.splice(pi, 1); } });
  if (POLY_LINE && viewer) { viewer.entities.remove(POLY_LINE); POLY_LINE = null; }
  POLY_PTS = null;
}
function closePolygon() {                                  // #178: finalize the in-progress polygon into a keep-out
  if (!(POLY_PTS && POLY_PTS.length >= 3)) return false;
  const pts = POLY_PTS.map((v) => [v.x, v.y]), latlons = POLY_PTS.map((v) => [v.lat, v.lon]);
  clearPolyDraft();
  snapshotAuthoring();
  const ko = { points: pts };
  KEEPOUTS.push(ko);
  dropPolyKeepout(latlons, { kind: "keepout", obj: ko });
  if (typeof renderKeepouts === "function") renderKeepouts();
  drawPlan();
  $("editstate").textContent = `⬡ polygon keep-out (${pts.length} vertices)`;
  return true;
}
function deleteSelectedPin() {                             // #64: Delete removes feature + pin
  if (!SELECTED_PIN) return;
  const ref = PIN_REFS.get(SELECTED_PIN);
  if (ref) {
    if (ref.kind === "order") { const i = ORDERS.indexOf(ref.obj); if (i >= 0) ORDERS.splice(i, 1); }
    if (ref.kind === "keepout") { const i = KEEPOUTS.indexOf(ref.obj); if (i >= 0) KEEPOUTS.splice(i, 1); }
    if (ref.kind === "note") { const i = ANNOTATIONS.indexOf(ref.obj); if (i >= 0) ANNOTATIONS.splice(i, 1); }
    if (ref.kind === "landmark") { const i = LANDMARKS.indexOf(ref.obj); if (i >= 0) LANDMARKS.splice(i, 1); persistDraft(); }
  }
  viewer.entities.remove(SELECTED_PIN);
  const k = EDIT_PINS.indexOf(SELECTED_PIN); if (k >= 0) EDIT_PINS.splice(k, 1);
  if (SELECTED_PIN === LANDER_PIN) LANDER_PIN = null;      // #lander-pin: don't leave a dangling reference
  if (SELECTED_PIN === ROVER_PIN) ROVER_PIN = null;        // #174: likewise the unique rover marker
  PIN_REFS.delete(SELECTED_PIN); SELECTED_PIN = null;
  renderQueue(); if (typeof updateLocator === "function") updateLocator(); setQ("feature deleted");
}
document.addEventListener("keydown", (e) => {
  // UX-04: Escape closes the open auth dialog (the role=dialog aria-modal contract).
  const am = document.getElementById("authmodal");
  if (e.key === "Escape" && am && am.style.display !== "none" && am.style.display !== "") {
    e.preventDefault(); closeAuth(); return;
  }
  if ((e.key === "Delete" || e.key === "Backspace") && SELECTED_PIN &&
      !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
    e.preventDefault(); deleteSelectedPin();
  }
});
let MEASURE_A = null;                                       // #178: the distance-measure tool's first-click anchor
let BOX_A = null;                                           // #178: the box-keepout tool's first-corner anchor {x,y,lat,lon,pin}
let POLY_PTS = null;                                        // #178: the polygon-keepout tool's growing vertex list [{x,y,lat,lon,pin}]
let POLY_LINE = null;                                       // #178: the in-progress polygon's growing outline entity
async function editPlace(lat, lon) {
  if (!EDIT.tool) { $("editstate").textContent = "LOCKED · pick a tool first"; return; }
  const r = await fetch(`/dem/site_xy?lat=${lat}&lon=${lon}&site=${encodeURIComponent(CURRENT_SITE)}`);
  const d = await r.json();
  if (!d.ok) { $("editstate").textContent = "outside the mapped tile"; return; }
  if (EDIT.tool === "goto") {
    snapshotAuthoring();
    const n = ORDERS.filter((o) => o.kind === "goto").length + 1;
    const wp = { action: `wp${n}`, kind: "goto", x: d.x_m, y: d.y_m };
    ORDERS.push(wp);
    // #4 (Aaron: "wp1(2310,8165) doesn't correspond to coords"): label the pin with UNITS + frame + the
    // real lat/lon so it's self-explanatory -- x/y are metres East/North in the site-local frame.
    dropPin(lat, lon, `wp${n} · ${d.x_m} m E, ${d.y_m} m N (site) · ${Number(lat).toFixed(3)}°, ${Number(lon).toFixed(3)}°`,
            "#e8273f", { kind: "order", obj: wp });
    renderQueue(); $("editstate").textContent = `wp${n} @ site-frame ${d.x_m} m E, ${d.y_m} m N (${Number(lat).toFixed(3)}°, ${Number(lon).toFixed(3)}°)`;
  } else if (EDIT.tool === "keepout") {
    // #178 (Aaron: "keep-out is just a dot — can't create a circle barrier"): an adjustable-radius
    // circular barrier, drawn as a real translucent circle on the globe (not a dot). Radius from the
    // ToolBox r field; hauls already route around circle keep-outs of any radius (planner-side).
    snapshotAuthoring();
    const r = Math.max(1, +($("koradius") ? $("koradius").value : 25) || 25);
    const ko = { x: d.x_m, y: d.y_m, r };
    KEEPOUTS.push(ko);
    dropKeepoutCircle(lat, lon, r, { kind: "keepout", obj: ko });
    if (typeof renderKeepouts === "function") renderKeepouts();
    drawPlan(); $("editstate").textContent = `keep-out circle keep-out @ ${d.x_m}, ${d.y_m} m (r ${r} m)`;
  } else if (EDIT.tool === "box") {
    // #178 (Aaron: "can't select a box"): a two-click axis-aligned RECTANGULAR barrier. First click
    // anchors a corner; the second completes the box {x0,y0,x1,y1} (site metres). The planner rasterizes
    // the rectangle impassable (point_in_keepout / _apply_keepouts), so hauls route around it.
    if (!BOX_A) {
      const pin = dropPin(lat, lon, "▭ corner", "#e0564b", { kind: "boxcorner" });
      BOX_A = { x: d.x_m, y: d.y_m, lat: Number(lat), lon: Number(lon), pin };
      $("editstate").textContent = `box: corner @ ${d.x_m}, ${d.y_m} m — click the opposite corner`;
    } else {
      if (BOX_A.pin && viewer) { viewer.entities.remove(BOX_A.pin); PIN_REFS.delete(BOX_A.pin);
        const pi = EDIT_PINS.indexOf(BOX_A.pin); if (pi >= 0) EDIT_PINS.splice(pi, 1); }   // drop the temp corner marker
      snapshotAuthoring();
      const ko = { x0: Math.min(BOX_A.x, d.x_m), y0: Math.min(BOX_A.y, d.y_m),
                   x1: Math.max(BOX_A.x, d.x_m), y1: Math.max(BOX_A.y, d.y_m) };
      KEEPOUTS.push(ko);
      dropBoxKeepout(BOX_A.lat, BOX_A.lon, Number(lat), Number(lon), { kind: "keepout", obj: ko });
      if (typeof renderKeepouts === "function") renderKeepouts();
      drawPlan();
      $("editstate").textContent = `box keep-out [${ko.x0}, ${ko.y0}]–[${ko.x1}, ${ko.y1}] m`;
      BOX_A = null;
    }
  } else if (EDIT.tool === "poly") {
    // #178: a multi-click arbitrary POLYGON barrier. Each click adds a vertex; clicking near the FIRST
    // vertex (with >= 3 vertices) closes it. The planner rasterizes the polygon impassable so hauls
    // route around it (point_in_keepout / _apply_keepouts handle {points}).
    if (POLY_PTS && POLY_PTS.length >= 3 &&
        Math.hypot(d.x_m - POLY_PTS[0].x, d.y_m - POLY_PTS[0].y) < 25) {        // close on near-first-vertex (fallback)
      closePolygon();
    } else {
      if (!POLY_PTS) POLY_PTS = [];
      const pin = dropPin(lat, lon, `▪ v${POLY_PTS.length + 1}`, "#e0564b", { kind: "polyvertex" });
      POLY_PTS.push({ x: d.x_m, y: d.y_m, lat: Number(lat), lon: Number(lon), pin });
      if (POLY_LINE && viewer) { viewer.entities.remove(POLY_LINE); POLY_LINE = null; }
      if (POLY_PTS.length >= 2) {                                              // redraw the growing outline
        const flat = []; POLY_PTS.forEach((v) => flat.push(v.lon, v.lat));
        POLY_LINE = viewer.entities.add({ polyline: { positions: Cesium.Cartesian3.fromDegreesArray(flat),
          width: 2, material: Cesium.Color.fromCssColorString("#e0564b") } });
      }
      $("editstate").textContent = `polygon: ${POLY_PTS.length} vertex(es)` +
        (POLY_PTS.length >= 3 ? " — click near the first vertex to close" : " — keep clicking to add vertices");
    }
  } else if (EDIT.tool === "note") {
    const text = prompt("note text:") || "";
    if (text) { const an = { x: d.x_m, y: d.y_m, text };
      ANNOTATIONS.push(an);
      dropPin(lat, lon, `${text.slice(0, 24)}`, "#e0b300", { kind: "note", obj: an });
      $("editstate").textContent = `note @ ${d.x_m}, ${d.y_m} m`; drawPlan(); }
  } else if (EDIT.tool === "lander") {
    // #3 (Aaron: "no way to place lander"): click-to-place the lander on the map (mirrors the typed
    // landx/landy + Place control). setLander persists it + saves with the mission; the lander layer +
    // its 100 m ring (#161) redraw via drawPlan, and the typed inputs stay in sync.
    setLander(d.x_m, d.y_m);
    if ($("landx")) { $("landx").value = LANDER_P.x; $("landy").value = LANDER_P.y; }
    // Aaron 2026-06-16 ("cant place lander"): the lander branch never dropped a GLOBE marker the way the
    // goto/keepout/note tools do, so a click gave no on-map feedback -- it felt like nothing happened.
    // Drop a single pin at the clicked lat/lon (replace the prior one so the lander stays unique).
    if (LANDER_PIN && viewer) { viewer.entities.remove(LANDER_PIN); PIN_REFS.delete(LANDER_PIN);
      const li = EDIT_PINS.indexOf(LANDER_PIN); if (li >= 0) EDIT_PINS.splice(li, 1); }
    LANDER_PIN = dropPin(lat, lon, `lander ${LANDER_P.x}, ${LANDER_P.y} m`, "#39ff14", { kind: "lander" });
    drawPlan(); $("editstate").textContent = `lander @ site-frame ${d.x_m} m E, ${d.y_m} m N (${Number(lat).toFixed(3)}°, ${Number(lon).toFixed(3)}°)`;
  } else if (EDIT.tool === "rover") {
    // #174 (Aaron: "why can't I place the location of the rover?"): click-to-place the rover's known
    // position. recordPose persists it (stewie_last_pose) + refreshes the locator (distances FROM it).
    recordPose(d.x_m, d.y_m);
    if (ROVER_PIN && viewer) { viewer.entities.remove(ROVER_PIN); PIN_REFS.delete(ROVER_PIN);
      const ri = EDIT_PINS.indexOf(ROVER_PIN); if (ri >= 0) EDIT_PINS.splice(ri, 1); }
    ROVER_PIN = dropPin(lat, lon, `rover ${LAST_POSE.x}, ${LAST_POSE.y} m`, "#ff9d3f", { kind: "rover" });
    $("editstate").textContent = `rover @ site-frame ${d.x_m} m E, ${d.y_m} m N (${Number(lat).toFixed(3)}°, ${Number(lon).toFixed(3)}°)`;
  } else if (EDIT.tool === "measure") {
    // #178: click two points -> the site-frame metric distance between them. The order frame is metres
    // E/N (the meaningful planning distance), so it is just the Euclidean delta of the two site_xy hits.
    if (!MEASURE_A) {
      MEASURE_A = { x: d.x_m, y: d.y_m };
      dropPin(lat, lon, "measure from", "#5577dd", { kind: "measure" });
      $("editstate").textContent = `measure: anchor @ ${d.x_m}, ${d.y_m} m — click the second point`;
    } else {
      const dist = Math.hypot(d.x_m - MEASURE_A.x, d.y_m - MEASURE_A.y);
      dropPin(lat, lon, `measure ${dist.toFixed(1)} m`, "#5577dd", { kind: "measure" });
      const msg = `distance ${dist.toFixed(1)} m  (Δ ${(d.x_m - MEASURE_A.x).toFixed(1)} m E, ${(d.y_m - MEASURE_A.y).toFixed(1)} m N)`;
      $("editstate").textContent = msg; setQ(msg);
      MEASURE_A = null;
    }
  } else if (EDIT.tool === "landmark") {
    // #178/#174: a named reference point (survey marker). Persists across reload + the locator
    // measures distance FROM it. Stores both site-frame metres and geographic lat/lon.
    const name = (prompt("landmark name (e.g. 'Lander', 'Charge Pad', 'Crater Rim'):") || "").trim();
    if (name) {
      const lm = { x: d.x_m, y: d.y_m, name, lat: Number(lat), lon: Number(lon) };
      LANDMARKS.push(lm);
      dropPin(lat, lon, `plot ${name}`, "#3fb6ff", { kind: "landmark", obj: lm });
      persistDraft();
      if (typeof updateLocator === "function") updateLocator();   // #174: new landmark -> refresh distances
      $("editstate").textContent = `plot landmark "${name}" @ ${d.x_m} m E, ${d.y_m} m N`;
      setQ(`landmark "${name}" placed (${LANDMARKS.length} total) — the locator can measure distance from it`);
    }
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
let WORK_AREA_RECT = null;                                 // GIS-WA1: Cesium.Rectangle of the [0,WORK_AREA_M]^2 work area (the inset image's true extent)
let WORK_AREA_ANCHOR = [0, 0];                             // #audit-2b: the work area's TRUE origin (flattest-anchor, tile-m) from /dem/georef -- the rect draws HERE, not the tile corner
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
  // #audit-2: a map click writes the site lat/lon inputs, so the next plan RE-ANCHORS the work area there
  // (the M11 backend re-anchor already consumes #lat/#lon); previously only manual typing moved the work area.
  const _la = document.getElementById("lat"), _lo = document.getElementById("lon");
  if (_la) _la.value = lat.toFixed(4);
  if (_lo) _lo.value = lon.toFixed(4);
  document.getElementById("out").textContent = `picked  lat ${lat.toFixed(3)}°  lon ${lon.toFixed(3)}°`;
  if (marker) viewer.entities.remove(marker);
  marker = viewer.entities.add({
    position: Cesium.Cartesian3.fromDegrees(lon, lat, 0, ellipsoid),
    point: { pixelSize: 7, color: Cesium.Color.CYAN, outlineColor: Cesium.Color.BLACK, outlineWidth: 2 },
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
// FS-24: esc() now lives in htmlesc.js (window.STEWIE_HTMLESC); thin binding alias preserves behaviour.
const esc = window.STEWIE_HTMLESC.esc;

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
let _validateSub = "nav";        // VALIDATE tab: which sub-view (nav|perception) is shown; setView('validate') uses it
const VIEW_PANE = { perception: "renderpanel", metrics: "execview", nav: "navview", report: "pane-report",
                    rehearse: "pane_rehearse",                            // REHEARSE: candidate-compare review surface
                    release: "pane_release",                              // RELEASE: director sign-off (/executive/release-plan)
                    fleet: "pane_fleet",                                  // FS-03: the Fleet work area
                    construction: "pane_construction", models: "pane_models",  // FS-03: Construction + Models work areas
                    trainer: "pane_trainer",                            // TR-02/03/04: the Trainer work area
                    validation: "pane-validation", api: "pane-api", server: "pane-server", config: "pane-config",
                    evidence: "pane-evidence", admin: "pane-admin", settings: "pane-settings" };
const _PANE_LOADED = {};
const SYSTEM_VIEWS = ["validation", "api", "server", "config", "evidence"];
let LAST_SYSTEM_VIEW = "server";
// UX-05: the planning sidebar (#panel) is a PLAN tool -- auto-collapse it off the Plan view (the stage
// gets the room) and restore it on return. A manual toggle (the drawer button on desktop) PINS the
// user's explicit choice in localStorage and overrides the auto behaviour. Mobile keeps the existing
// slide-over drawer, so collapse is desktop-only.
let SIDEBAR_PIN = null;                                   // null = auto; "open" / "collapsed" = pinned
try { SIDEBAR_PIN = localStorage.getItem("stewie_sidebar_pin"); } catch (e) {}
function applySidebar(view) {
  const panel = document.getElementById("panel"); if (!panel) return;
  if (innerWidth <= 860) { panel.classList.remove("collapsed"); return; }   // mobile = slide-over, not collapse
  // tab-contextual (#131/#132): the left panel stays OPEN on every workspace tab (its content swaps per
  // tab via #ctx-<view>); it only auto-collapses on a System sub-view that has no contextual block.
  // council #4: rehearse + release were missing -> the sidebar (with the wizard Done/Next/Reset controls)
  // COLLAPSED on those two spine tabs, dead-ending the operator with no way to advance the wizard. Keep it open.
  const HAS_CTX = ["plan", "rehearse", "nav", "perception", "release", "metrics", "report"].includes(view);
  const collapsed = SIDEBAR_PIN === "open" ? false
    : SIDEBAR_PIN === "collapsed" ? true
      : !HAS_CTX;
  panel.classList.toggle("collapsed", collapsed);
}
// #240: empty-state jump buttons -- any [data-go] control switches to that view. One delegated,
// CSP-clean listener (no inline onclick); setView is a hoisted declaration so this is safe above it.
document.addEventListener("click", (e) => {
  const j = e.target.closest && e.target.closest("[data-go]");
  if (j) { e.preventDefault(); setView(j.getAttribute("data-go")); }
});

function setView(name) {
  if (name === "system") name = LAST_SYSTEM_VIEW;          // #55: the cluster remembers its sub-tab
  if (name === "validate") name = _validateSub || "nav";   // VALIDATE: delegate to the last/default sub-view
  if (SYSTEM_VIEWS.includes(name)) LAST_SYSTEM_VIEW = name;
  VIEW = name;
  document.querySelectorAll(".vtab").forEach((b) => {       // UX-04: tab semantics + selected state
    const sel = b.dataset.view === name
      || (b.dataset.view === "validate" && (name === "nav" || name === "perception"))   // VALIDATE owns nav+perception
      || (b.dataset.view === "system" && SYSTEM_VIEWS.includes(name));
    b.classList.toggle("active", sel);
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", sel ? "true" : "false");
    b.tabIndex = sel ? 0 : -1;                              // roving tabindex (WAI-ARIA tabs pattern)
  });
  const vsub = document.getElementById("validate-subtabs");   // VALIDATE: show the sub-tab strip + mark the sub
  if (vsub) {
    const inVal = (name === "nav" || name === "perception");
    vsub.style.display = inVal ? "flex" : "none";
    if (inVal) {
      _validateSub = name;
      vsub.querySelectorAll(".vsub").forEach((b) => b.classList.toggle("active", b.dataset.sub === name));
    }
  }
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
  if (name === "nav" && typeof navDrawMission === "function") navDrawMission(LAST_LOCALIZATION);  // #nav-mission: live est-vs-truth
  if (name === "nav" && typeof navDrawDrive === "function") navDrawDrive(LAST_DRIVE || {});       // council #238: drive-preview empty-state (or replay the last drive)
  if (name === "metrics" && typeof renderScorecardBoard === "function") renderScorecardBoard();   // TR-01: re-show the last A-board
  if (name === "metrics" && typeof paintExecIdle === "function") paintExecIdle();   // council #238: honest empty-state on the idle Execute canvas
  // tab-contextual left workspace (#131/#132): show THIS tab's context block, hide the others
  const CTX = { plan: "ctx-plan", nav: "ctx-nav", perception: "ctx-perception", metrics: "ctx-metrics", report: "ctx-report" };
  document.querySelectorAll(".ctxblock").forEach((bk) => { bk.hidden = (bk.id !== CTX[name]); });
  // the EDIT toolbar is a PLAN tool (Aaron's System screenshot: it stacked on the sub-bar)
  const et = document.getElementById("edittoolbar");
  if (et) et.style.display = (name === "plan") ? "flex" : "none";
  const sb = document.getElementById("scalebox");          // the scale belongs to the map
  if (sb) sb.style.display = (name === "plan") ? "block" : "none";
  const p3b = document.getElementById("plan3dbar");        // the 3D-path toggle is a PLAN-map tool (z-index above panes)
  if (p3b) p3b.style.display = (name === "plan") ? "flex" : "none";
  const p3s = document.getElementById("plan3dstats");
  if (p3s && name !== "plan") p3s.style.display = "none";
  const p3c = document.getElementById("plan3dcoord");      // the 3D plotting HUD is a PLAN-map tool too
  if (p3c && name !== "plan") p3c.style.display = "none";
  if (name !== "plan") {                                   // #audit-1: clear the floating + header cursor coords off-Plan
    const cxy = document.getElementById("cursorxy"); if (cxy) cxy.style.display = "none";
    const cc = document.getElementById("cursorcoord"); if (cc) cc.textContent = "";
  }
  if (name !== "plan" && EDIT.on) setEdit(false);          // leaving Plan ends the edit session
  applySidebar(name);                                      // UX-05: collapse off-Plan / restore on Plan
  loadPane(name);
  if (name === "perception" && typeof loadPanorama === "function") loadPanorama();  // #183 shadow-nav surround
  if (name === "perception" && typeof loadPointCloud === "function") loadPointCloud();  // #145 stereo points
  if (typeof renderStepper === "function") renderStepper();  // pipeline spine: reflect the active view
  if (typeof renderCtxSummaries === "function") renderCtxSummaries();  // live per-tab left-block content
}

// #183/#79 Perception pane: load the REAL served 8-cam panorama + overlay the shadow-nav landmarks
// (each tagged with the azimuth bearing an Navigation pose-graph factor consumes). Honest empty state when
// no render egress is present (a GPU-less deploy ships the committed crater_boulders sample).
let PANO_LOADED = false;
function applyPanoMarks() {
  const ov = $("panooverlay");
  if (ov) ov.style.display = ($("panomarks") && $("panomarks").checked) ? "" : "none";
}
async function loadPanorama() {
  const stage = $("panostage"), empty = $("panoempty");
  if (!stage) return;
  try {
    const r = await fetch("assets/perception/landmarks.json", { cache: "no-cache" });
    if (!r.ok) throw new Error("no manifest");
    const m = await r.json();
    const cams = m.cameras || [], lms = m.landmarks || [];
    const nc = cams.length || 1, W = m.width || 2048, H = m.height || 192;
    $("panoimg").src = "assets/perception/panorama.png?v=" + (m.full_width || 0);
    // camera tile dividers + per-tile heading label (the panorama is 8 FOV tiles ordered by heading)
    $("panoticks").innerHTML = cams.map((c, i) => {
      const cx = ((i + 0.5) / nc * 100).toFixed(2), lx = (i / nc * 100).toFixed(2);
      return `<div style="position:absolute;left:${lx}%;top:0;height:9999px;border-left:1px solid rgba(120,160,255,.22)"></div>`
        + `<div style="position:absolute;left:${cx}%;top:1px;transform:translateX(-50%);font-size:8px;color:#7fa8ff;text-shadow:0 0 3px #000">${Math.round(c.heading_deg)}&deg;</div>`;
    }).join("");
    // shadow-nav landmark markers (dot + azimuth-bearing label) at their panorama pixel positions
    $("panooverlay").innerHTML = lms.map((l) => {
      const lf = (l.x / W * 100).toFixed(2), tp = (l.y / H * 100).toFixed(2);
      return `<div style="position:absolute;left:${lf}%;top:${tp}%;transform:translate(-50%,-50%)">`
        + `<div style="width:10px;height:10px;border:1.5px solid #ffd479;border-radius:50%;box-shadow:0 0 4px #000"></div>`
        + `<div style="position:absolute;left:11px;top:-3px;white-space:nowrap;font-size:8px;color:#ffd479;text-shadow:0 0 3px #000">${l.bearing_deg}&deg;</div></div>`;
    }).join("");
    $("panometa").textContent = ` · ${nc} cams · ${lms.length} landmarks · ${m.full_width || "?"}×${m.full_height || "?"}px source`;
    $("panolist").innerHTML = "<b>Shadow-nav bearings (Navigation measurements):</b> "
      + lms.slice(0, 12).map((l) => `<span style="color:#ffd479">${l.bearing_deg}&deg;</span><span style="opacity:.55">/c${Math.round(l.contrast)}</span>`).join(" · ")
      + `<br><span style="opacity:.7">${m.note || ""}</span>`;
    stage.style.display = ""; empty.style.display = "none";
    applyPanoMarks();
    PANO_LOADED = true;
  } catch (e) {
    stage.style.display = "none"; empty.style.display = "";
  }
}
document.addEventListener("DOMContentLoaded", () => {
  const cb = document.getElementById("panomarks");
  if (cb) cb.addEventListener("change", applyPanoMarks);
});

// #145 Perception pane: load the REAL served front-stereo point cloud (obs_map_producer ->
// SGBM -> reprojectImageTo3D -> world points). Honest empty state when no render egress exists.
async function loadPointCloud() {
  const img = $("pcimg"), empty = $("pcempty");
  if (!img) return;
  try {
    const r = await fetch("assets/perception/pointcloud.json", { cache: "no-cache" });
    if (!r.ok) throw new Error("no manifest");
    const m = await r.json();
    img.src = "assets/perception/pointcloud.png?v=" + (m.n_points || 0);
    const xr = m.x_range_m || [0, 0], zr = m.z_range_m || [0, 0], er = m.elev_range_m || [0, 0];
    $("pcmeta").textContent = ` · ${(m.n_points || 0).toLocaleString()} pts · ${(m.baseline_m || 0).toFixed(3)} m baseline`;
    $("pclist").innerHTML = "<b>Back-projected world points:</b> "
      + `X ${xr[0].toFixed(1)}…${xr[1].toFixed(1)} m · Z ${zr[0].toFixed(1)}…${zr[1].toFixed(1)} m · `
      + `elevation ${er[0].toFixed(2)}…${er[1].toFixed(2)} m (median ${(m.elev_median_m || 0).toFixed(3)} m) · `
      + `max depth ${m.max_depth_m} m · 1&sigma; &asymp; ${m.precision_1sigma_m} m`
      + `<br><span style="opacity:.7">${m.note || ""}</span>`;
    img.style.display = ""; empty.style.display = "none";
  } catch (e) {
    img.style.display = "none"; empty.style.display = "";
  }
}

// FS-03 Fleet pane: render the REAL vehicle-registry roster (/fleet, fetched once) + the LIVE
// per-vehicle allocation / makespan / space-time conflicts from the last plan (LAST_TOTALS, re-read on
// every open so it tracks the latest /plan). All HTML built by the pure fleet_render.js module (CSP-safe:
// no inline script). Honest empty states: the roster shows the registry-down message if /fleet fails; the
// allocation shows "plan a mission" until a plan with vehicles_detail exists. No fabricated data.
let _FLEET_ROSTER = null;
async function loadFleet() {
  const FR = window.STEWIE_FLEET_RENDER;
  const rosterEl = $("fleetroster"), planEl = $("fleetplan");
  if (!FR || !rosterEl || !planEl) return;
  if (!_FLEET_ROSTER) {                                   // fetch the registry once (it is static config)
    try {
      const r = await fetch("/fleet", { headers: apiHeaders() });
      if (r.ok) _FLEET_ROSTER = await r.json();
      else rosterEl.innerHTML = '<div class="empty">Fleet roster unavailable (HTTP ' + r.status
        + (r.status === 401 || r.status === 403 ? " — operator+ sign-in required" : "") + ").</div>";
    } catch (e) {
      rosterEl.innerHTML = '<div class="empty">Fleet roster unavailable (' + esc(String(e)) + ").</div>";
    }
  }
  if (_FLEET_ROSTER) rosterEl.innerHTML = FR.fleetRosterHTML(_FLEET_ROSTER, esc);
  planEl.innerHTML = FR.fleetPlanHTML(LAST_TOTALS, esc);  // live per-vehicle allocation from the last plan
}

// REHEARSE (mission-ops screen 2): POST the CURRENT build queue to /resync/compare (the conserved
// forward_compare ensemble: each candidate solver input is re-simulated faster-than-realtime, returning
// ranked futures with measured wall_s/energy/feasibility), then render the candidate cards side-by-side
// FEASIBILITY FIRST via the pure rehearse_render.js module (CSP-safe). Director-gated server-side; an
// honest empty state shows when there is no queue. No fabricated data -- every number is from the planner.
async function loadRehearse() {
  const RR = window.STEWIE_REHEARSE_RENDER;
  const host = $("rehearsecards");
  if (!RR || !host) return;
  if (!ORDERS.length) {                                     // honest empty state -- no plan to rehearse
    host.innerHTML = RR.rehearseCardsHTML(null, esc);
    return;
  }
  host.innerHTML = '<div class="empty">Re-simulating candidate futures…</div>';
  try {
    const objective = (qel("qobj") && qel("qobj").value) || "duration";
    const mission = { name: `${BODIES[sel.value].name} rehearsal`, body: sel.value, charger: [0, 0],
      orders: ORDERS, keepouts: KEEPOUTS, precedence: parsePrec(),
      max_traverse_slope_deg: +(qel("qslope") ? qel("qslope").value : 25), ...fleet(), ...site() };
    const r = await fetch("/resync/compare", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ mission, candidates: ["nearest", "two_opt"], objective }) });
    if (r.status === 401 || r.status === 403) {
      host.innerHTML = '<div class="empty">Rehearse &amp; compare is director-only. Sign in with a '
        + "director key (the forward-compare ensemble sees truth).</div>";
      return;
    }
    const j = await r.json();
    if (!j.ok) { host.innerHTML = '<div class="empty">Forward-compare error: ' + esc(j.error || r.status) + "</div>"; return; }
    host.innerHTML = RR.rehearseCardsHTML(j, esc);
  } catch (e) {
    host.innerHTML = '<div class="empty">Forward-compare failed — is the server running? (' + esc(String(e)) + ")</div>";
  }
}

// FS-03 Construction pane: render the REAL build catalog (/construction, fetched once -- static templates)
// + the acceptance criteria, plus the LIVE as-built verdict from the last plan (LAST_VALIDATION, re-read on
// every open so it tracks the latest /plan). All HTML built by the pure construction_render.js module
// (CSP-safe). Honest empty states: catalog shows the catalog-down message if /construction fails; the
// as-built result shows "plan a mission" until a plan validation exists. No fabricated data.
let _CONSTRUCTION = null;
async function loadConstruction() {
  const CR = window.STEWIE_CONSTRUCTION_RENDER;
  const catEl = $("constructioncatalog"), accEl = $("constructionacceptance");
  if (!CR || !catEl || !accEl) return;
  if (!_CONSTRUCTION) {                                   // fetch the catalog once (it is static config)
    try {
      const r = await fetch("/construction", { headers: apiHeaders() });
      if (r.ok) _CONSTRUCTION = await r.json();
      else catEl.innerHTML = '<div class="empty">Build catalog unavailable (HTTP ' + r.status
        + (r.status === 401 || r.status === 403 ? " — operator+ sign-in required" : "") + ").</div>";
    } catch (e) {
      catEl.innerHTML = '<div class="empty">Build catalog unavailable (' + esc(String(e)) + ").</div>";
    }
  }
  if (_CONSTRUCTION) {
    catEl.innerHTML = CR.constructionCatalogHTML(_CONSTRUCTION, esc);
    accEl.innerHTML = CR.constructionAcceptanceHTML(_CONSTRUCTION, LAST_VALIDATION, esc);  // live as-built from last plan
  }
  if ($("tmrecord")) $("tmrecord").onclick = recordTerrainMemory;   // W3: Terrain Memory record action
  loadTerrainMemory();                                              // W3: the site's authoritative world state
}

// W3 (Terrain Memory): the Construction pane's authoritative world-state readout -- how much the chosen
// site's terrain has changed across every recorded mission (GET /twin/terrain/{site}). The terrain
// "remembers" what IPEx built; the operator folds the current build queue into it via recordTerrainMemory.
async function loadTerrainMemory() {
  const el = $("terrainmem"); if (!el) return;
  try {
    const r = await fetch(`/twin/terrain/${encodeURIComponent(CURRENT_SITE)}`, { headers: apiHeaders() });
    if (!r.ok) { el.innerHTML = `<div class="empty">Terrain memory unavailable (HTTP ${r.status}).</div>`; return; }
    const t = await r.json();
    if (!t.recorded) {
      el.innerHTML = `<div class="empty">No terrain changes recorded for <b>${esc(CURRENT_SITE)}</b> yet — `
        + "record a plan below and the site starts remembering what was built.</div>";
      return;
    }
    const miss = (t.missions || []).map(esc).join(", ") || "—";
    el.innerHTML = `<b>${esc(CURRENT_SITE)}</b> · v${t.version} · `
      + (t.chain_valid ? "chain ✓" : "<span style='color:#e8273f'>chain ✗</span>") + "<br>"
      + `cells changed <b>${(t.cells_changed || 0).toLocaleString()}</b> · net volume <b>${(t.net_volume_m3 || 0).toFixed(2)} m³</b><br>`
      + `deepest cut <b>${((t.max_cut_m || 0) * 100).toFixed(1)} cm</b> · highest build <b>${((t.max_fill_m || 0) * 100).toFixed(1)} cm</b><br>`
      + `missions: ${miss}`;
  } catch (e) { el.innerHTML = `<div class="empty">Terrain memory unavailable (${esc(String(e))}).</div>`; }
}

async function recordTerrainMemory() {
  if (!ORDERS.length) { setQ("⚠ add build orders first — nothing to record into terrain memory"); return; }
  if (!window.confirm(`Record the ${ORDERS.length} queued order(s) into ${CURRENT_SITE}'s terrain memory? `
      + "The site will remember this build, and a future plan can target the remembered surface.")) return;
  const mission = { name: `${BODIES[sel.value].name} build`, body: sel.value, charger: [0, 0],
    orders: ORDERS, keepouts: KEEPOUTS, ...fleet(), ...site() };
  try {
    const r = await fetch(`/twin/terrain/${encodeURIComponent(CURRENT_SITE)}`, { method: "POST",
      headers: apiHeaders(), body: JSON.stringify({ mission }) });
    const b = await r.json().catch(() => ({}));
    if (r.status === 403) { setQ("refused — recording terrain memory is operator+"); return; }
    if (!r.ok) { setQ(`record failed: ${b.detail || b.error || ("HTTP " + r.status)}`); return; }
    setQ(`terrain memory updated → v${b.version}${b.clipped ? " (part clipped off-site)" : ""}`);
    loadTerrainMemory();
  } catch (e) { setQ("record failed — run server.py (" + e + ")"); }
}

// FS-03 Models pane: render the REAL model + config registries (/models, fetched once): the deployable
// system-profile registry (sha256 + VERIFIED), the vehicle + body registries with provenance, and the
// ML-01 deployment-ready governance + §25.3 no-command-path status. All HTML built by the pure
// models_render.js module (CSP-safe). Honest empty state if /models fails. No fabricated data.
let _MODELS = null;
async function loadModels() {
  const MR = window.STEWIE_MODELS_RENDER;
  const pEl = $("modelsprofiles"), rEl = $("modelsregistries"), gEl = $("modelsgovernance");
  if (!MR || !pEl || !rEl || !gEl) return;
  if (!_MODELS) {                                         // fetch the registries once (static config)
    try {
      const r = await fetch("/models", { headers: apiHeaders() });
      if (r.ok) _MODELS = await r.json();
      else pEl.innerHTML = '<div class="empty">Model registries unavailable (HTTP ' + r.status
        + (r.status === 401 || r.status === 403 ? " — operator+ sign-in required" : "") + ").</div>";
    } catch (e) {
      pEl.innerHTML = '<div class="empty">Model registries unavailable (' + esc(String(e)) + ").</div>";
    }
  }
  if (_MODELS) {
    pEl.innerHTML = MR.modelsProfilesHTML(_MODELS, esc);
    rEl.innerHTML = MR.modelsRegistriesHTML(_MODELS, esc);
    gEl.innerHTML = MR.modelsGovernanceHTML(_MODELS, esc);
  }
}

// TR-02/03/04 Trainer pane: render the three boards from REAL recorded sessions. All HTML built by the
// pure trainer_boards.js module (CSP-safe). TR-03 PROGRAM = leaderboard + history over /trainer/history
// (the persisted scorecards). TR-02 DIRECTOR truth board = the believed-vs-true divergence (director-only;
// the server omits the truth block + the section is hidden for non-directors). TR-04 DEBRIEF scrubber =
// step a recorded run seen-vs-estimated-vs-truth via /session/.../debrief (director-only). Honest empty
// states throughout (no fabricated runs); a non-director simply sees fewer boards.
let _TRAINER_HISTORY = null;       // last /trainer/history payload (drives PROGRAM + truth + the sel list)
let _TRAINER_DEBRIEF = null;       // last loaded /session/.../debrief payload (the scrubber's run)
let _TRAINER_STEP = 0;             // the scrubber's current leg index
async function loadTrainer() {
  const TB = window.STEWIE_TRAINER_BOARDS;
  const progEl = $("trainerprogram");
  if (!TB || !progEl) return;
  try {
    const r = await fetch("/trainer/history", { headers: apiHeaders() });
    if (r.ok) { _TRAINER_HISTORY = await r.json(); }
    else {
      progEl.innerHTML = '<div class="empty">Session history unavailable (HTTP ' + r.status
        + (r.status === 401 || r.status === 403 ? " — operator+ sign-in required" : "") + ").</div>";
      return;
    }
  } catch (e) {
    progEl.innerHTML = '<div class="empty">Session history unavailable (' + esc(String(e)) + ").</div>";
    return;
  }
  progEl.innerHTML = TB.programBoardHTML(_TRAINER_HISTORY, esc);
  // TR-02 director truth board: only shown to a director (the server flags is_director on the payload)
  const truthWrap = $("trainertruthwrap"), truthEl = $("trainertruth");
  if (truthWrap && truthEl) {
    const isDir = _TRAINER_HISTORY && _TRAINER_HISTORY.is_director === true;
    truthWrap.style.display = isDir ? "block" : "none";
    if (isDir) truthEl.innerHTML = TB.truthBoardHTML(_TRAINER_HISTORY, esc);
  }
  // TR-04 scrubber session picker: populate from the recorded sessions (the debrief route is director-only,
  // so a non-director picking a session gets the honest "director-only" empty state when it 401s).
  const sel = $("trainerdebriefsel");
  if (sel) {
    const sessions = (_TRAINER_HISTORY && _TRAINER_HISTORY.sessions) || [];
    const prev = sel.value;
    sel.innerHTML = sessions.length
      ? sessions.map((s) => `<option value="${esc(s.session_id)}">${esc(s.session_id.slice(0, 8))}`
          + ` · ${esc(String(s.profile || "?"))}</option>`).join("")
      : '<option value="">no recorded sessions</option>';
    if (sessions.some((s) => s.session_id === prev)) sel.value = prev;   // keep the user's pick across refresh
  }
}
async function loadTrainerDebrief(sid) {
  const TB = window.STEWIE_TRAINER_BOARDS, dbEl = $("trainerdebrief"), note = $("trainerdebriefnote");
  if (!TB || !dbEl || !sid) return;
  try {
    const r = await fetch(`/session/${encodeURIComponent(sid)}/debrief`, { headers: apiHeaders() });
    if (r.status === 401 || r.status === 403) {
      _TRAINER_DEBRIEF = null;
      dbEl.innerHTML = '<div class="empty">The debrief scrubber (seen-vs-estimated-vs-truth) is '
        + "director-only (MO-04). Sign in as a director to step through a recorded run.</div>";
      _syncScrubberControls();
      return;
    }
    if (!r.ok) {
      _TRAINER_DEBRIEF = null;
      dbEl.innerHTML = '<div class="empty">Debrief unavailable (HTTP ' + r.status
        + "; the live session may have been evicted — re-run it from the Plan tab).</div>";
      _syncScrubberControls();
      return;
    }
    _TRAINER_DEBRIEF = await r.json();
    _TRAINER_STEP = 0;
  } catch (e) {
    _TRAINER_DEBRIEF = null;
    dbEl.innerHTML = '<div class="empty">Debrief unavailable (' + esc(String(e)) + ").</div>";
  }
  _renderScrubber();
}
function _renderScrubber() {
  const TB = window.STEWIE_TRAINER_BOARDS, dbEl = $("trainerdebrief"), note = $("trainerdebriefnote");
  if (!TB || !dbEl) return;
  dbEl.innerHTML = TB.debriefScrubberHTML(_TRAINER_DEBRIEF, _TRAINER_STEP, esc);
  const n = (_TRAINER_DEBRIEF && _TRAINER_DEBRIEF.legs) ? _TRAINER_DEBRIEF.legs.length : 0;
  if (note) note.textContent = n ? `${n} legs recorded` : "";
  _syncScrubberControls();
}
function _syncScrubberControls() {
  const slider = $("trainerstep"), back = $("trainerstepback"), fwd = $("trainerstepfwd");
  const n = (_TRAINER_DEBRIEF && _TRAINER_DEBRIEF.legs) ? _TRAINER_DEBRIEF.legs.length : 0;
  if (slider) { slider.max = Math.max(0, n - 1); slider.value = _TRAINER_STEP; slider.disabled = n < 1; }
  if (back) back.disabled = n < 1 || _TRAINER_STEP <= 0;
  if (fwd) fwd.disabled = n < 1 || _TRAINER_STEP >= n - 1;
}

document.querySelectorAll(".vtab").forEach((b) => { b.onclick = () => setView(b.dataset.view); });
document.querySelectorAll("#validate-subtabs .vsub").forEach((b) => { b.onclick = () => setView(b.dataset.sub); });  // VALIDATE sub-tabs
// FS-20: System / Settings / Admin live in the profile menu (off the work-area tab bar), role-gated:
// Settings everyone, System operator+, Admin director. The items reuse setView -> same pane switch.
// FS-24: role-ladder rank now lives in role_rank.js (window.STEWIE_ROLE_RANK); thin binding alias.
const _rrank = window.STEWIE_ROLE_RANK.rrank;
function gateChrome(role) {
  const sys = $("prof-system"), adm = $("prof-admin");
  if (sys) sys.style.display = (_rrank(role) >= _rrank("operator")) ? "block" : "none";  // System: operator+
  if (adm) adm.style.display = (role === "director") ? "block" : "none";                 // Admin: director
  // FS-03: role-gate the work-area tabs that declare a minimum role (the Fleet tab is operator+). Same
  // ladder + fail-closed semantics as the chrome above; a sub-operator never sees the fleet command surface.
  document.querySelectorAll(".vtab[data-minrole]").forEach((b) => {
    const ok = _rrank(role) >= _rrank(b.dataset.minrole);
    b.style.display = ok ? "" : "none";
    if (!ok && b.dataset.view === VIEW) setView("plan");   // bounce a demoted operator off the gated tab
  });
}
(function wireProfile() {
  const btn = $("profbtn"), menu = $("profmenu"); if (!btn || !menu) return;
  const close = () => { menu.style.display = "none"; btn.setAttribute("aria-expanded", "false"); };
  btn.onclick = (e) => { e.stopPropagation();
    const open = menu.style.display !== "none";
    menu.style.display = open ? "none" : "block";
    btn.setAttribute("aria-expanded", open ? "false" : "true"); };
  menu.querySelectorAll(".profitem[data-view]").forEach((it) => {
    it.onclick = () => { setView(it.dataset.view); close(); }; });
  document.addEventListener("click", (e) => {
    if (menu.style.display !== "none" && !menu.contains(e.target) && !btn.contains(e.target)) close(); });
})();

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
// FS-17: SINGLE command-authority window. The production operator flow is ONE cockpit; any second
// tab/window is READ-ONLY engineering/debug context -- it must NOT hold independent command authority
// (it cannot emit rover commands). One tab claims authority in localStorage with a heartbeat; tabs that
// find a FRESH claim from another tab go read-only and disable the command controls ([data-cmd-authority]).
// The `storage` event + a BroadcastChannel keep tabs in sync live; localStorage is the durable arbiter.
// If the authority tab closes, its claim goes stale (> TTL) and a read-only tab may TAKE OVER (an explicit
// operator action, never a silent promotion of a hidden window). body.dataset.cmdrole = owner|readonly.
const CMD_AUTH = (function () {
  const KEY = "stewie_cmd_authority", TTL = 6000, BEAT = 2000;
  const ID = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : (String(Date.now()) + Math.random());
  let isOwner = false;
  let bc = null;
  try { bc = new BroadcastChannel("stewie_cmd_authority"); } catch (e) { bc = null; }
  const readClaim = () => { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } };
  const fresh = (c) => !!(c && (Date.now() - (c.ts || 0)) < TTL);
  const writeClaim = () => { try { localStorage.setItem(KEY, JSON.stringify({ id: ID, ts: Date.now() })); } catch (e) {} };
  function apply() {
    if (document.body) document.body.dataset.cmdrole = isOwner ? "owner" : "readonly";
    const banner = document.getElementById("cmd-readonly-banner");
    if (banner) banner.style.display = isOwner ? "none" : "";
    document.querySelectorAll("[data-cmd-authority]").forEach((el) => {
      el.disabled = !isOwner;
      el.title = isOwner ? (el.dataset.cmdTitle || el.title || "")
        : "Read-only window -- another cockpit holds command authority";
    });
  }
  function become(owner) { if (owner !== isOwner) { isOwner = owner; apply(); } else { apply(); } }
  function evaluate() {                                    // the durable localStorage claim is the arbiter
    const c = readClaim();
    if (!fresh(c)) { writeClaim(); become(true); if (bc) bc.postMessage({ t: "claim", id: ID }); }
    else { become(c.id === ID); }
  }
  function start() {
    evaluate();
    const tk = document.getElementById("cmd-takeover");
    if (tk) tk.onclick = () => { takeOver(); try { setQ("command authority taken over by this window"); } catch (e) {} };
    window.addEventListener("storage", (e) => { if (e.key === KEY) become(((readClaim() || {}).id === ID) && fresh(readClaim())); });
    if (bc) bc.onmessage = (ev) => { const m = ev.data || {}; if (m.t === "claim" && m.id !== ID) become((readClaim() || {}).id === ID && fresh(readClaim())); else if (m.t === "release") evaluate(); };
    setInterval(() => { if (isOwner) writeClaim(); else evaluate(); }, BEAT);
    window.addEventListener("beforeunload", () => { if (isOwner) { try { localStorage.removeItem(KEY); } catch (e) {} if (bc) bc.postMessage({ t: "release", id: ID }); } });
  }
  function takeOver() { writeClaim(); become(true); if (bc) bc.postMessage({ t: "claim", id: ID }); }
  return { start, takeOver, isOwner: () => isOwner };
})();
// FS-17: command-authority gate -- a command action calls this FIRST; a read-only window is refused.
function guardCommand(label) {
  if (CMD_AUTH.isOwner()) return true;
  try { setQ((label ? label + ": " : "") + "this window is READ-ONLY -- another cockpit holds command authority"); } catch (e) {}
  return false;
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
    const state = age < 20 ? "ok" : (age < 60 ? "stale" : "dead");
    el.dataset.fresh = state;
    // A11Y (WCAG 1.4.1): the border colour is mirrored by a text state so the
    // freshness is not conveyed by colour alone -- a CSS ::after corner label
    // shows it visually; this annotation exposes the same word to assistive tech
    // and on hover. No behaviour change beyond the label.
    const label = state === "ok" ? "data live" : (state === "stale" ? "data stale" : "data stale (no recent update)");
    el.setAttribute("aria-label", label);
    el.setAttribute("title", label);
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

// FS-21: drag-to-reorder the sidebar panes; the order persists per operator (localStorage). Runs right
// after collapseSidebar() built the <details> panes. VIEW preference ONLY -- the panes keep their ids +
// handlers as they move, so reordering changes no control, contract, command authority, or role/AG gate.
(function wirePanelLayout() {
  const L = window.STEWIE_PANEL_LAYOUT; if (!L) return;
  const panel = document.getElementById("panel"); if (!panel) return;
  const panes = Array.prototype.slice.call(panel.querySelectorAll("section > details"));
  if (panes.length < 2) return;
  const host = panes[0].parentElement;                     // re-home every pane into the first section
  const keyOf = (d) => { const s = d.querySelector("summary"); return s ? s.textContent.trim().slice(0, 28) : ""; };
  panes.forEach((d) => { d.dataset.pane = keyOf(d); });
  const current = panes.map((d) => d.dataset.pane);        // the default (build) order, for reset
  let saved = [];
  try { saved = JSON.parse(localStorage.getItem(L.KEY) || "[]"); } catch (e) {}
  const apply = (order) => order.forEach((k) => {
    const d = panes.find((x) => x.dataset.pane === k); if (d) host.appendChild(d); });   // appendChild = move
  apply(L.mergeOrder(saved, current));
  const persist = () => {
    const ord = Array.prototype.slice.call(host.querySelectorAll(":scope > details")).map((d) => d.dataset.pane);
    try { localStorage.setItem(L.KEY, JSON.stringify(ord)); } catch (e) {}
  };
  // canonical DnD reorder: the pane the dragged one should drop BEFORE (nearest below the cursor)
  const dragAfter = (y) => {
    const els = Array.prototype.slice.call(host.querySelectorAll(":scope > details:not(.dragging)"));
    let best = { off: -Infinity, el: null };
    els.forEach((c) => { const b = c.getBoundingClientRect(); const off = y - b.top - b.height / 2;
      if (off < 0 && off > best.off) best = { off, el: c }; });
    return best.el;
  };
  let dragEl = null;
  panes.forEach((d) => {
    const sum = d.querySelector("summary"); if (!sum) return;
    const grip = document.createElement("span");
    grip.className = "pane-grip"; grip.textContent = "⠿"; grip.title = "drag to reorder this pane";
    grip.setAttribute("draggable", "true"); grip.setAttribute("aria-hidden", "true");
    grip.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); });   // never toggle the pane
    grip.addEventListener("dragstart", (e) => { dragEl = d; d.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move"; try { e.dataTransfer.setData("text/plain", d.dataset.pane); } catch (x) {} });
    grip.addEventListener("dragend", () => { if (dragEl) dragEl.classList.remove("dragging"); dragEl = null; persist(); });
    sum.insertBefore(grip, sum.firstChild);
  });
  host.addEventListener("dragover", (e) => { if (!dragEl) return; e.preventDefault();
    const after = dragAfter(e.clientY);
    if (after == null) host.appendChild(dragEl); else host.insertBefore(dragEl, after); });
  // reset-to-default (always available, surfaced in Settings): forget the saved order + restore build order
  window.resetPanelLayout = () => { try { localStorage.removeItem(L.KEY); } catch (e) {} apply(current); };

  // FS-21 (named layouts): a layout is a VIEW snapshot = pane ORDER + each pane's COLLAPSED state. Capture
  // reads the live DOM; apply restores order (via the same appendChild move) then sets each <details>.open.
  // Nothing gated is read or written here -- panes keep their ids + handlers, so this changes no command
  // authority (the FS-21 invariant). captureLayout/applyLayout are exposed so the dropdown UI (below) can
  // snapshot + restore without re-implementing the DOM walk.
  const collapsedNow = () => {
    const c = {};
    panes.forEach((d) => { c[d.dataset.pane] = !d.open; });   // collapsed = NOT open
    return c;
  };
  window.captureLayout = () => ({
    order: Array.prototype.slice.call(host.querySelectorAll(":scope > details")).map((d) => d.dataset.pane),
    collapsed: collapsedNow()
  });
  window.applyLayout = (snap) => {
    if (!snap) return;
    apply(L.mergeOrder(snap.order || [], current));          // restore order (new panes never hidden)
    const col = snap.collapsed || {};
    panes.forEach((d) => { if (Object.prototype.hasOwnProperty.call(col, d.dataset.pane)) d.open = !col[d.dataset.pane]; });
  };
})();

// FS-21 extension (user customization): per-operator TOP-TAB order, the same drag-to-reorder discipline as
// the sidebar. VIEW preference ONLY -- reordering a tab never changes its data-view (setView keys on that),
// its visibility tier (gateChrome still gates it), command authority, or any access gate. A plain click
// still switches tabs (native draggable does not suppress click); a drag reorders. Persisted in
// localStorage; window.resetTabOrder restores the build-default ConOps spine.
(function wireTabLayout() {
  const L = window.STEWIE_PANEL_LAYOUT; if (!L) return;
  const KEY = "stewie_tab_order";
  const nav = document.getElementById("viewtabs"); if (!nav) return;
  const tabs = Array.prototype.slice.call(nav.querySelectorAll(".vtab"));
  if (tabs.length < 2) return;
  const keyOf = (b) => b.dataset.view;
  const current = tabs.map(keyOf);                              // build-default order (for reset)
  const byKey = (k) => tabs.find((b) => keyOf(b) === k);
  const chrome = nav.querySelector("#alertbtn");               // tabs sit BEFORE the alert/badge/account chrome
  const place = (b) => { if (b) { if (chrome) nav.insertBefore(b, chrome); else nav.appendChild(b); } };
  const apply = (order) => L.mergeOrder(order, current).forEach((k) => place(byKey(k)));
  let saved = [];
  try { saved = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (e) {}
  apply(saved);
  const persist = () => {
    const ord = Array.prototype.slice.call(nav.querySelectorAll(".vtab")).map(keyOf);
    try { localStorage.setItem(KEY, JSON.stringify(ord)); } catch (e) {}
  };
  const dropBefore = (x) => {                                  // the VISIBLE tab nearest right of the cursor
    const els = Array.prototype.slice.call(nav.querySelectorAll(".vtab:not(.dragging)"))
      .filter((c) => c.offsetParent !== null);
    let best = { off: -Infinity, el: null };
    els.forEach((c) => { const b = c.getBoundingClientRect(); const off = x - b.left - b.width / 2;
      if (off < 0 && off > best.off) best = { off, el: c }; });
    return best.el;
  };
  let dragEl = null;
  tabs.forEach((b) => {
    b.setAttribute("draggable", "true");
    b.addEventListener("dragstart", (e) => { dragEl = b; b.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move"; try { e.dataTransfer.setData("text/plain", keyOf(b)); } catch (x) {} });
    b.addEventListener("dragend", () => { if (dragEl) dragEl.classList.remove("dragging"); dragEl = null; persist(); });
  });
  nav.addEventListener("dragover", (e) => { if (!dragEl) return; e.preventDefault();
    const before = dropBefore(e.clientX);
    if (before == null) place(dragEl); else nav.insertBefore(dragEl, before); });
  window.resetTabOrder = () => { try { localStorage.removeItem(KEY); } catch (e) {} apply(current); };
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
  if (typeof updateLocator === "function") updateLocator();   // #174: lander moved -> refresh distances
  if (typeof TD3D_ON !== "undefined" && TD3D_ON && window.STEWIE3D && STEWIE3D.setLander3D)
    STEWIE3D.setLander3D(LANDER_P.x, LANDER_P.y);             // #182: keep the 3D lander+AprilTag in sync
}
function recordPose(x, y) {
  LAST_POSE = { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10, ts: Date.now() };
  try { localStorage.setItem("stewie_last_pose", JSON.stringify(LAST_POSE)); } catch (e) {}
  const el = $("lastpose");
  if (el) el.textContent = `rover last known: ${LAST_POSE.x}, ${LAST_POSE.y} m`;
  if ($("roverx")) { $("roverx").value = LAST_POSE.x; $("rovery").value = LAST_POSE.y; }
  if (typeof updateLocator === "function") updateLocator();   // #174: rover moved -> refresh distances
}
// #174: the "where are we" locator -- distance + compass bearing from the rover's known position to the
// lander and every placed landmark (real distance extrapolation from placed points, replacing the fixed
// 100 m ring), plus the actual selenographic coordinates next to the order-frame metres. Answers Aaron's
// "why doesn't where-are-we pick up the lander / why metres not coordinates".
// FS-24: site-frame bearing + lat/lon formatting moved to geofmt.js (STEWIE_GEOFMT); aliased here so the
// #174 locator call sites below are unchanged. Pure -> unit-tested in geofmt.test.js.
const bearingFrom = window.STEWIE_GEOFMT.bearingFrom;       // site frame: +x = East, +y = North
async function siteLatLon(x, y) {                          // order-frame metres -> lat/lon (the #174 reverse route)
  try {
    const r = await fetch(`/dem/site_lonlat?x=${x}&y=${y}&site=${encodeURIComponent(CURRENT_SITE)}`);
    if (!r.ok) return null;
    const d = await r.json();
    return d.ok ? { lat: d.lat, lon: d.lon } : null;
  } catch (e) { return null; }
}
const fmtLL = window.STEWIE_GEOFMT.fmtLL;                   // FS-24: lat/lon formatter -> geofmt.js
async function updateLocator() {
  const box = $("locator"); if (!box) return;
  if (!LAST_POSE) {
    box.innerHTML = '<span style="opacity:.6">place the rover (tool or "place rover") to see distances ' +
      "to the lander and landmarks</span>";
    return;
  }
  const rx = LAST_POSE.x, ry = LAST_POSE.y, hasLander = !!(LANDER_P.x || LANDER_P.y);
  const [roverLL, landerLL] = await Promise.all([
    siteLatLon(rx, ry), hasLander ? siteLatLon(LANDER_P.x, LANDER_P.y) : Promise.resolve(null)]);
  const rows = [`<b style="color:var(--accent)">rover</b> ${rx}, ${ry} m · ` +
                `<span style="opacity:.8">${fmtLL(roverLL)}</span>`];
  if (hasLander) {
    const dE = LANDER_P.x - rx, dN = LANDER_P.y - ry, dist = Math.hypot(dE, dN);
    rows.push(`<b>lander</b> ${LANDER_P.x}, ${LANDER_P.y} m · <b>${dist.toFixed(1)} m</b> ` +
              `${bearingFrom(dE, dN)} · <span style="opacity:.8">${fmtLL(landerLL)}</span>`);
  }
  LANDMARKS.forEach((l) => {
    const dE = l.x - rx, dN = l.y - ry, dist = Math.hypot(dE, dN);
    rows.push(`plot <b>${esc(l.name)}</b> ${l.x}, ${l.y} m · <b>${dist.toFixed(1)} m</b> ${bearingFrom(dE, dN)}`);
  });
  if (rows.length === 1) {
    rows.push('<span style="opacity:.6">no lander or landmarks placed yet — drop a lander or ' +
      "plot landmark to extrapolate distances from the rover</span>");
  }
  box.innerHTML = rows.map((r) => `<div>${r}</div>`).join("");
}
applySettings(SETTINGS);
if ($("set-theme")) $("set-theme").onchange = () => {
  SETTINGS.theme = $("set-theme").value; saveSettings(SETTINGS); applySettings(SETTINGS);
};

// ---- #117: operator access (sign in / request access / set password) + the director admin panel ----
// SEC-01: apikey is an in-memory automation key (never persisted); the operator session is a cookie.
const AUTH = { role: null, identity: null, apikey: "" };
function authMsg(t, ok) { const m = $("auth-msg"); if (m) { m.textContent = t || "";
  m.style.color = ok ? "var(--accent)" : "var(--bad,#ff6b6b)"; } }
// #133: idle auto-logout. A signed-in cockpit left unattended can still command a live rover, so after
// IDLE_MIN minutes with no user activity we sign out and re-raise the blocking sign-in gate. This is a
// client-side control; it composes with the server guarantees that hold regardless (the absolute
// TOKEN_TTL_S cap + jti revocation on /auth/logout). Window configurable via SETTINGS.idle_min.
const IDLE_MIN = window.STEWIE_IDLE ? window.STEWIE_IDLE.clampMinutes(SETTINGS && SETTINGS.idle_min) : 30;
async function idleLogout() {
  try { await fetch("/auth/logout", { method: "POST", headers: apiHeaders() }); } catch (e) {}
  AUTH.role = null; AUTH.identity = null; AUTH.apikey = "";    // SEC-01: drop the in-memory key too
  renderWhoami(null); gateChrome(null);
  applyGate();                                                 // re-raise the gate IN PLACE (no nav away)
  authMsg("Signed out after " + IDLE_MIN + " min of inactivity. Sign in to continue.", false);
}
const _idleMon = window.STEWIE_IDLE ? window.STEWIE_IDLE.IdleMonitor({
  idleMinutes: IDLE_MIN, onIdle: idleLogout,
  now: () => Date.now(), setInterval: (fn, ms) => setInterval(fn, ms), clearInterval: (h) => clearInterval(h),
}) : null;
// Activity resets the window (touch() is a no-op while signed out, so the listeners are harmless then).
if (_idleMon) ["mousemove", "mousedown", "keydown", "touchstart", "scroll", "wheel"].forEach(
  (ev) => document.addEventListener(ev, () => _idleMon.touch(), { passive: true }));
// Settings control: prefill with the active window + persist + apply live.
if (_idleMon && $("set-idle")) {
  $("set-idle").value = IDLE_MIN;
  $("set-idle").onchange = () => {
    const v = window.STEWIE_IDLE.clampMinutes($("set-idle").value);
    $("set-idle").value = v; SETTINGS.idle_min = v; saveSettings(SETTINGS);
    _idleMon.setIdleMinutes(v);
  };
}
function authMode(mode) {
  ["login", "register", "setpw", "redeem"].forEach((k) => { const el = $("auth-" + k);
    if (el) el.style.display = (k === mode) ? "flex" : "none"; });
  const lt = $("auth-tab-login"), rt = $("auth-tab-register"), tabs = $("auth-tabs");
  if (lt && rt) { lt.classList.toggle("active", mode === "login"); rt.classList.toggle("active", mode === "register"); }
  // registration closed -> the register tab is hidden, so a lone "Sign in" tab just duplicates the
  // submit button. Hide the whole tab row in that case; it shows only when registration is open.
  const _regClosed = rt && rt.style.display === "none";
  if (tabs) tabs.style.display = (mode === "setpw" || mode === "redeem" || _regClosed) ? "none" : "flex";
  authMsg("");
}
// GATED APP (Aaron 2026-06-15): the cockpit requires sign-in. _gate=true means a no-session boot ->
// a BLOCKING sign-in (no X, no backdrop/Esc dismiss, opaque backdrop hiding the work area). It lifts
// only once a session exists. applyGate() reconciles it after every refreshAuthState.
let _gate = false;
let INVITE_TOKEN = null;                                   // #179/AG-04: token parsed from an #invite=<token> link
{ const _hm = (location.hash || "").match(/invite=([^&]+)/); if (_hm) INVITE_TOKEN = decodeURIComponent(_hm[1]); }  // parse EARLY so the gate opens redeem, not login
function openAuth(mode) {
  const m = $("authmodal"); if (!m) return;
  let want = mode || "login";
  if (want === "login" && INVITE_TOKEN) want = "redeem";    // #179: a pending invite link redeems, not logs in
  mode = want;
  m.style.display = "flex"; authMode(want);
  // the header X + backdrop dismiss exist only when NOT gated (a signed-in user managing their
  // account); the boot gate is mandatory, so hide the X + make the backdrop fully opaque.
  const x = $("auth-dismiss"); if (x) x.style.display = _gate ? "none" : "";
  m.style.background = _gate ? "var(--bg, #0a0a0c)" : "rgba(0,0,0,.72)";
  // UX-04: focus the ACTIVE form's first field (not the X) so keyboard/SR users land on the input.
  const formId = (mode === "register") ? "auth-register" : (mode === "setpw") ? "auth-setpw"
    : (mode === "redeem") ? "auth-redeem" : "auth-login";
  const first = ($(formId) || m).querySelector("input");
  if (first) first.focus();
}
function closeAuth() {
  if (_gate && !AUTH.identity) return;          // gated + no session -> sign-in is mandatory, no dismiss
  const m = $("authmodal"); if (m) m.style.display = "none";
}
function applyGate() {
  // refreshAuthState (the only caller path) runs on boot + after login/set-password, NOT on a poll, so
  // arming/disarming the idle monitor here tracks real sign-in/out transitions (no spurious resets).
  if (AUTH.identity) { _gate = false; closeAuth(); if (_idleMon) _idleMon.start(); }   // signed in -> lift gate + arm idle logout
  else { _gate = true; openAuth(INVITE_TOKEN ? "redeem" : "login"); if (_idleMon) _idleMon.stop(); }   // no session -> block (redeem if an invite link is present)
}
let _authPromptTs = 0;
let _bootComplete = false;                                // UX-01: set true once the initial load settles
function flashSignInNeeded() {                            // a 401 surfaced -> nudge sign-in (debounced)
  // UX-01/OPT-02: never auto-open the sign-in modal during the initial load. A casual visitor sees a
  // calm signed-out state (the app is fully usable read-only); the modal pops only on an EXPLICIT
  // action that a 401 refused after boot. Without this, any boot-time protected fetch popped a modal.
  if (!_bootComplete) return;
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
let DESKTOP = false;   // STEWIE_DESKTOP: the bundled desktop app -> skip the operator-login gate, run as local-trust director
async function refreshAuthState() {
  const st = $("set-opstate");
  // SEC-01: the session is an HttpOnly cookie -- we cannot read it, but the readable CSRF cookie (set
  // and cleared alongside it) tells us a session likely exists. With neither that nor an in-memory key,
  // skip /auth/me so an unauthenticated load does not pop the sign-in prompt via the 401 observer.
  if (!getCookie("stewie_csrf") && !AUTH.apikey && !DESKTOP) {
    AUTH.role = null; AUTH.identity = null;
    if (st) st.textContent = "not signed in";
    renderWhoami(null);
    gateChrome(null);
    applyGate(); return; }
  try {
    const r = await fetch("/auth/me", { headers: apiHeaders() });
    if (!r.ok) throw 0;
    const j = await r.json(); AUTH.role = j.role; AUTH.identity = j.identity;
    if (st) st.textContent = "signed in: " + j.identity + " (" + j.role + ")";
    renderWhoami(j.identity, j.role);
    gateChrome(j.role);
    // #auth-reload: the gated data loaders 401 if fired pre-login on boot; re-run them now that a session
    // exists so a fresh login populates without a manual refresh. loadSites re-fills the site selector;
    // refetchSun re-applies the on server rasters (hazard/slope/illumination/psr/grid) -- the once-only
    // applyDefaultsOnceReady gate won't re-fetch them, so the main-map hazard overlay needs this re-apply.
    // refreshCatalog/refreshProfiles/refreshEvents are likewise TOP-LEVEL boot calls (lines ~3026/2960/1670)
    // that 401 before login and never re-fire -- without this re-run the mission+structure CATALOG, the
    // saved-PROFILES dropdown, and the EVENT ledger all stay empty after a fresh login (Aaron: "catalog/
    // telemetry empty, fleet doesn't populate"). All are internally try/caught + hoisted, so this is safe.
    try {
      loadSites();
      if (typeof refetchSun === "function") refetchSun();
      if (typeof refreshCatalog === "function") refreshCatalog();
      if (typeof refreshProfiles === "function") refreshProfiles();
      if (typeof refreshEvents === "function") refreshEvents();
      // recovery: if /bodies.json never landed (its retries exhausted during a deploy window), re-fetch it
      // now so the fleet + soil dropdowns self-heal on login (Aaron: "why did fleet and soil break again?").
      if (typeof loadBodies === "function" && (!PHY || !PHY._vehicles)) loadBodies();
      // #246: /dem/georef is now auth-gated, so the boot-time loadSiteFootprint() 401s pre-login and
      // the work-area footprint + georef stay blank. Re-anchor it now that a session exists (the 3D
      // /dem/terrain_grid loader is user-triggered post-login, so it needs no re-fire).
      if (typeof loadSiteFootprint === "function") loadSiteFootprint(true);
    } catch (e) { /* best-effort */ }
  } catch (e) { AUTH.role = null; AUTH.identity = null;
    if (st) st.textContent = "not signed in";
    renderWhoami(null);
    gateChrome(null); }
  applyGate();   // gated app: reconcile the sign-in gate after every auth refresh (boot + session loss)
}
// #workspace (Aaron 2026-06-16 "still cant determine training vs live"): a VISIBLE workspace badge so the
// operator always knows whether they are in the safe TRAINING sandbox or the LIVE mission namespace, plus
// an operator+ toggle. The badge is TRUTHFUL: it drives the ns= on every mission read/write (refreshCatalog
// + save + load + delete), so switching actually changes which namespace the catalog saves to and lists
// from. A trainee is pinned to their sandbox server-side (namespace_for ignores ns for trainees), so their
// badge always reads TRAINING and the toggle is inert.
let WORKSPACE = (localStorage.getItem("stewie_ws") === "live") ? "live" : "sandbox";  // #166: default TRAINING (sandbox); LIVE is an explicit, remembered opt-in
function wsParam() { return "ns=" + WORKSPACE; }
function renderWorkspace(role) {
  const b = $("wsbadge"); if (!b) return;
  if (!role) { b.style.display = "none"; return; }
  const canSwitch = _rrank(role) >= _rrank("operator");
  const live = canSwitch && WORKSPACE === "live";          // trainees can never be on live
  b.textContent = (live ? "● LIVE" : "● TRAINING");        // clickable to switch (title + pointer cue; no emoji)
  b.style.color = live ? "#e8273f" : "#3fa34d";
  b.style.borderColor = live ? "#e8273f" : "#3fa34d";
  b.style.cursor = canSwitch ? "pointer" : "default";
  b.title = (live
    ? "LIVE workspace -- missions save to the shared live namespace that commands the real rover."
    : "TRAINING workspace -- a safe sandbox; missions here never command the real rover.")
    + (canSwitch ? " Click to switch." : " (trainees are pinned to the training sandbox.)");
  b.onclick = canSwitch ? () => {
    WORKSPACE = (WORKSPACE === "live") ? "sandbox" : "live";
    try { localStorage.setItem("stewie_ws", WORKSPACE); } catch (e) { /* private mode */ }
    renderWorkspace(AUTH.role);
    setQ("workspace → " + (WORKSPACE === "live" ? "LIVE" : "TRAINING"));
    if (typeof refreshCatalog === "function") refreshCatalog();   // re-list the now-active namespace
  } : null;
  b.style.display = "inline-flex";
}
// #117: the signed-in identity chip (who's logged in) + sign-out. renderWhoami(null) hides it; a
// director gets the accent avatar, an operator a muted one. Function declarations -> hoisted, so
// refreshAuthState above can call renderWhoami regardless of source order.
function renderWhoami(identity, role) {
  const w = $("whoami"); if (!w) return;
  if (!identity) { w.style.display = "none"; renderWorkspace(null); return; }
  renderWorkspace(role);
  const av = $("whoami-av"), lab = $("whoami-label");
  if (av) { av.textContent = (String(identity).trim()[0] || "?").toUpperCase();
    av.style.background = (role === "director") ? "var(--accent)" : "var(--muted)"; }
  if (lab) lab.textContent = identity + (role ? " (" + role + ")" : "");
  w.style.display = "inline-flex";
}
async function doLogout() {
  try { await fetch("/auth/logout", { method: "POST", headers: apiHeaders() }); } catch (e) {}
  AUTH.role = null; AUTH.identity = null; AUTH.apikey = "";   // SEC-01: drop the in-memory key too
  renderWhoami(null);
  // signing out should LEAVE the work area -> land back on the public page, not sit signed-out in the cockpit
  window.location.assign("/");
}
if ($("whoami-signout")) $("whoami-signout").onclick = doLogout;
async function doLogin() {
  const email = $("auth-email").value.trim(), pass = $("auth-pass").value;
  if (!email) { authMsg("email required"); return; }
  // The deploy key NEVER enters the browser: the founding director is provisioned server-side from
  // STEWIE_BOOTSTRAP_DIRECTOR/_PASSWORD (operators.bootstrap_director_from_env), so login is always
  // password-only here. X-API-Key stays a CI/automation header, not a browser onboarding path.
  if (!pass) { authMsg("enter your password"); return; }
  // SEC-01: the server sets the HttpOnly session + CSRF cookies on success; we DON'T store the token.
  const r = await fetch("/auth/login", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password: pass }) });
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
async function doRedeem() {                                // #179/AG-04: redeem an invite link -> self-create an account
  const email = $("auth-iemail").value.trim(), pass = $("auth-ipass").value;
  if (!INVITE_TOKEN) { authMsg("no invite token in the link"); return; }
  if (!email || !pass) { authMsg("email + password required"); return; }
  const r = await fetch("/auth/invite/redeem", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: INVITE_TOKEN, email, password: pass }) });
  const j = await r.json().catch(() => ({}));
  if (r.ok && j.ok) {
    authMsg("Account created — signing in…", true);
    INVITE_TOKEN = null; try { history.replaceState(null, "", location.pathname + location.search); } catch (e) {}
    $("auth-email").value = email; $("auth-pass").value = pass; authMode("login"); await doLogin();
  } else { authMsg(j.detail || j.error || ("redeem refused (" + r.status + ")")); }
}
(function wireAuth() {
  const bind = (id, fn) => { const e = $(id); if (e) e.onclick = fn; };
  bind("auth-tab-login", () => authMode("login"));
  bind("auth-tab-register", () => authMode("register"));
  bind("auth-do-login", doLogin);
  bind("auth-do-register", doRegister);
  bind("auth-do-setpw", doSetPassword);
  bind("auth-do-redeem", doRedeem);
  if (INVITE_TOKEN) openAuth("redeem");                     // #179/AG-04: an invite link opens the redeem panel
  bind("auth-dismiss", (ev) => { ev.preventDefault(); closeAuth(); });
  // click the dimmed backdrop (outside the card) to dismiss -- no inline handler (CSP forbids it)
  const am = $("authmodal"); if (am) am.addEventListener("click", (e) => { if (e.target === am) closeAuth(); });
  bind("set-account", () => openAuth("login"));
  fetch("/auth/config").then((r) => r.json()).then((c) => {
    if (c.desktop) { DESKTOP = true; refreshAuthState(); }   // desktop app: local-trust director, skip the login gate
    if (!c.operator_login) { const b = $("set-account"); if (b) b.disabled = true; }
    if (!c.registration_open) { const t = $("auth-tab-register"); if (t) t.style.display = "none";
      const tr = $("auth-tabs"); if (tr) tr.style.display = "none"; }   // lone "Sign in" tab is redundant with the submit
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
        actCell.appendChild(mkbtn("logins", "logins"));     // per-user login history (audit)
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
      b.onclick = () => (b.dataset.act === "logins"
        ? showUserLogins(b.dataset.email)
        : adminAction(b.dataset.act, b.dataset.email, b.dataset.role)));
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
// #117 (admin): a per-user login history -- every recorded sign-in for one operator (the audit ledger
// filtered by actor + action=auth.login), shown in the admin audit panel.
async function showUserLogins(email) {
  const box = $("adminaudit"); if (!box) return;
  box.textContent = "loading logins for " + email + " ...";
  try {
    const r = await fetch("/events?action=auth.login&n=200&actor=" + encodeURIComponent(email),
                          { headers: apiHeaders() });
    const evs = (await r.json()).events || [];
    const lines = evs.map((x) => new Date(x.ts * 1000).toLocaleString() + "  via " + (x.target || x.action));
    box.textContent = "logins for " + email + " (" + evs.length + "):\n" + (lines.join("\n") || "— none recorded");
  } catch (e) { box.textContent = "could not load logins for " + email; }
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
// control panel: director creates an account directly (POST /admin/operators/create), no approve dance
if ($("admnew-create")) $("admnew-create").onclick = async () => {
  const email = ($("admnew-email").value || "").trim();
  const password = $("admnew-pass").value || "";
  const role = $("admnew-role").value || "operator";
  if (!email || !password) { alert("email + initial password required"); return; }
  const r = await fetch("/admin/operators/create", { method: "POST", headers: apiHeaders(),
    body: JSON.stringify({ email, password, role }) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false) { alert(j.detail || j.error || ("create failed (" + r.status + ")")); return; }
  $("admnew-email").value = ""; $("admnew-pass").value = "";
  renderAdmin();
};
// #179: surface the AG-03 invite mint (POST /admin/invite) -- a director mints a one-time link the
// invitee redeems (#invite=<token>) to self-create an account. The raw token is returned once.
if ($("invmint")) $("invmint").onclick = async () => {
  const role = $("invrole").value || "operator";
  const ttl_s = Math.max(1, +$("invttl").value || 7) * 86400;
  const max_uses = Math.max(1, +$("invuses").value || 1);
  const r = await fetch("/admin/invite", { method: "POST", headers: apiHeaders(),
    body: JSON.stringify({ role, ttl_s, max_uses }) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false) { alert(j.detail || j.error || ("mint failed (" + r.status + ")")); return; }
  const link = `${location.origin}/#invite=${j.token}`;
  if ($("invout")) $("invout").value = link;
  if ($("invcopy")) { $("invcopy").style.display = "";
    $("invcopy").onclick = () => navigator.clipboard.writeText(link).then(() => setQ("invite link copied")); }
  setQ(`minted ${role} invite (${max_uses} use${max_uses > 1 ? "s" : ""})`);
};
{ const av = $("prof-admin"); if (av) av.addEventListener("click", () => setTimeout(renderAdmin, 0)); }
refreshAuthState();
if ($("set-font")) $("set-font").oninput = () => {
  SETTINGS.fontpx = parseInt($("set-font").value, 10); saveSettings(SETTINGS); applySettings(SETTINGS);
};
// FS-21: reset-to-default is always available -- restore the build order of the sidebar panes
if ($("set-resetlayout")) $("set-resetlayout").onclick = () => {
  if (window.resetPanelLayout) window.resetPanelLayout();      // sidebar pane order
  if (window.resetTabOrder) window.resetTabOrder();            // top-tab order (user customization)
};

// FS-21: NAMED saved workspace layouts. The pure collection logic lives in layouts.js (STEWIE_NAMED_LAYOUTS);
// this glue is the localStorage read/write + the Settings dropdown that drives save / load / rename / delete /
// set-default over the live panes (window.captureLayout / window.applyLayout from wirePanelLayout). A layout
// is a VIEW preference ONLY -- it carries pane order + collapsed booleans, never a role/contract/auth, so it
// cannot change command authority (the FS-21 invariant; enforced by layouts.js dropping non-view fields).
(function wireNamedLayouts() {
  const NL = window.STEWIE_NAMED_LAYOUTS; if (!NL) return;
  const pick = $("set-layout-pick"); if (!pick) return;   // Settings not in this build -> nothing to wire
  const msgEl = $("set-layout-msg"), defBox = $("set-layout-default");
  const readStore = () => { try { return NL.normalize(JSON.parse(localStorage.getItem(NL.KEY) || "null")); } catch (e) { return NL.normalize(null); } };
  const writeStore = (s) => { try { localStorage.setItem(NL.KEY, JSON.stringify(s)); } catch (e) {} };
  const msg = (t) => { if (msgEl) msgEl.textContent = t; };

  function refresh(selected) {
    const store = readStore();
    const names = NL.list(store), def = NL.defaultName(store);
    const want = selected || (names.indexOf(pick.value) !== -1 ? pick.value : def) || names[0] || "";
    pick.textContent = "";
    if (!names.length) {
      const o = document.createElement("option"); o.value = ""; o.textContent = "(no saved layouts)"; pick.appendChild(o);
    }
    names.forEach((n) => {
      const o = document.createElement("option"); o.value = n;
      o.textContent = (n === def ? "★ " : "") + n; pick.appendChild(o);
    });
    pick.value = want;
    if (defBox) defBox.checked = !!want && want === def;
    return store;
  }

  // load on selection change (VIEW restore only)
  pick.onchange = () => {
    const store = readStore(); const name = pick.value; if (!name) return;
    const snap = NL.get(store, name);
    if (snap && window.applyLayout) { window.applyLayout(snap); msg("Loaded layout “" + name + "”."); }
    if (defBox) defBox.checked = name === NL.defaultName(store);
  };

  if ($("set-layout-save")) $("set-layout-save").onclick = () => {
    if (!window.captureLayout) { msg("Pane manager not ready."); return; }
    const suggested = (pick.value || "").trim();
    const name = (prompt("Save the current pane arrangement as:", suggested) || "").trim();
    if (!name) return;
    const r = NL.save(readStore(), name, window.captureLayout());
    if (r.error) { msg(r.error); return; }
    writeStore(r.store); refresh(name); msg("Saved layout “" + name + "”.");
  };

  if ($("set-layout-rename")) $("set-layout-rename").onclick = () => {
    const from = pick.value; if (!from) { msg("Select a layout to rename."); return; }
    const to = (prompt("Rename “" + from + "” to:", from) || "").trim();
    if (!to || to === from) return;
    const r = NL.rename(readStore(), from, to);
    if (r.error) { msg(r.error); return; }
    writeStore(r.store); refresh(to); msg("Renamed to “" + to + "”.");
  };

  if ($("set-layout-delete")) $("set-layout-delete").onclick = () => {
    const name = pick.value; if (!name) { msg("Select a layout to delete."); return; }
    if (!confirm("Delete the saved layout “" + name + "”? (This does not change any pane's contents.)")) return;
    const r = NL.remove(readStore(), name);
    if (r.error) { msg(r.error); return; }
    writeStore(r.store); refresh(); msg("Deleted “" + name + "”.");
  };

  if (defBox) defBox.onchange = () => {
    const name = pick.value; if (!name) { defBox.checked = false; return; }
    const r = NL.setDefault(readStore(), defBox.checked ? name : null);
    if (r.error) { msg(r.error); refresh(); return; }
    writeStore(r.store); refresh(name);
    msg(defBox.checked ? "“" + name + "” is now the default layout." : "Default layout cleared.");
  };

  // apply the default layout on boot (view restore; never blocks if none is set). Deferred a macrotask so it
  // lands AFTER the synchronous boot cascade -- in particular after the #170 plan-stepper's boot focusStep(),
  // which auto-collapses the numbered pipeline sections. The operator's explicitly-saved layout is the
  // authority over that boot default; a LATER step click still re-focuses (a deliberate user action), so this
  // only wins the boot, not the wizard. View preference only -- still just order + open/closed (FS-21).
  const boot = refresh();
  const def = NL.defaultName(boot);
  if (def && window.applyLayout) {
    const snap = NL.get(boot, def);
    if (snap) setTimeout(() => { try { window.applyLayout(snap); } catch (e) {} }, 0);
  }
})();
// #179: clear the auto-saved working draft from THIS browser (the inverse of #177's persistence) -- a clean
// slate without touching display settings or the server-side named-mission catalog. Confirm + reload.
if ($("set-resetws")) $("set-resetws").onclick = () => {
  if (!confirm("Clear the auto-saved draft (orders, keep-outs, landmarks, lander, rover) from this browser? " +
               "Display settings and saved missions are NOT affected.")) return;
  ["stewie_draft", "stewie_lander", "stewie_last_pose"].forEach((k) => { try { localStorage.removeItem(k); } catch (e) {} });
  location.reload();
};

// lazy-load the engineer/dev/intern panes the first time shown (Server refreshes live each open). All read
// real server endpoints; on file:// or a down server they keep their empty state (no fabricated content).
async function loadRelease() {                                            // RELEASE: director sign-off (POST /executive/release-plan)
  const out = $("releaseout"), btn = $("releasebtn");
  if (!out || !btn) return;
  out.innerHTML = ORDERS.length
    ? `<div style="color:var(--muted)">${ORDERS.length} order(s) in the queue. Click <b>Release</b> to drive them through the lifecycle and sign the revision.</div>`
    : '<div class="empty">No build orders yet — author a plan on the Plan tab first.</div>';
  btn.onclick = async () => {
    if (!ORDERS.length) {
      out.innerHTML = '<div class="empty">No build orders to release — author a plan on the Plan tab first.</div>';
      return;
    }
    out.innerHTML = '<div class="empty">Driving the plan through the mission lifecycle…</div>';
    try {
      const r = await fetch("/executive/release-plan", { method: "POST", headers: apiHeaders(),
        body: JSON.stringify({ body: sel.value, orders: ORDERS, mission_id: `${BODIES[sel.value].name} release` }) });
      if (r.status === 401 || r.status === 403) {
        out.innerHTML = '<div class="empty">Release is director-only. Sign in with a director key (RELEASED is a '
          + "director-authority signing transition).</div>";
        return;
      }
      const d = await r.json();
      if (!d.ok) { out.innerHTML = `<div class="empty">Cannot release: ${esc(d.error || "uncompilable plan")}</div>`; return; }
      const rev = d.signed_revision, skipped = d.skipped || [], ev = d.evidence || {};
      const trail = (d.transitions || []).map((t) => `${esc(t.to)} <span style="color:var(--muted)">(${esc(t.role)})</span>`).join(" → ");
      out.innerHTML =
        `<div><b style="color:var(--accent);font-size:13px">${esc(String(d.state).toUpperCase())}</b> — ${d.released_objectives} build objective(s) released <span style="color:var(--muted)">(${esc(d.label)})</span></div>`
        + (rev ? `<div style="margin-top:6px;color:var(--muted)">signed revision <code>${esc(String(rev.content_hash).slice(0, 16))}…</code> by ${esc(rev.signed_by)}</div>` : "")
        + `<div style="margin-top:4px;color:var(--muted)">plan_id <code>${esc(String(ev.plan_id || "—"))}</code></div>`
        + (trail ? `<div style="margin-top:8px">${trail}</div>` : "")
        + (skipped.length ? `<div style="margin-top:12px;color:#e0a000">${skipped.length} non-build order(s) NOT released (path waypoints are not mission objectives): ${skipped.map((s) => esc(String(s.action || s.kind))).join(", ")}</div>` : "");
    } catch (e) { out.innerHTML = `<div class="empty">Release failed: ${esc(String(e))}</div>`; }
  };
}


async function loadPane(name) {
  try {
    if (name === "api") {
      if (!_PANE_LOADED.api) { $("apiframe").src = "/docs"; _PANE_LOADED.api = true; }   // FastAPI Swagger
    } else if (name === "rehearse") {
      await loadRehearse();                                               // REHEARSE: forward-compare candidate cards (/resync/compare)
    } else if (name === "release") {
      await loadRelease();                                                // RELEASE: director sign-off via /executive/release-plan
    } else if (name === "fleet") {
      await loadFleet();                                                  // FS-03: roster (/fleet) + last-plan allocation
    } else if (name === "construction") {
      await loadConstruction();                                          // FS-03: build catalog (/construction) + last-plan as-built
    } else if (name === "models") {
      await loadModels();                                                // FS-03: model + config registries (/models)
    } else if (name === "trainer") {
      await loadTrainer();                                               // TR-02/03/04: program + truth + debrief boards
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
      const yn = (b) => b ? "✓" : "—";
      card("SERVER", [["version", c.server.version], ["data dir", c.server.data_dir],
                      ["backup dir", c.server.backup_dir]]);
      card("AUTH", [["API key", yn(c.auth.api_key_set)], ["operator login", yn(c.auth.operator_login)],
                    ["Tailscale trust", yn(c.auth.trust_tailscale)],
                    ["", '<span style="opacity:.6">flags only — secrets never leave the server</span>']]);
      card("DATA", [["sites", `${c.data.sites_imported}/${c.data.sites_total} imported`],
                    ["SPICE kernels", yn(c.data.spice_available)],
                    ["twin snapshots", c.data.twin_snapshots]]);
      $("cfgout").textContent = JSON.stringify(c.overlay, null, 2);
    } else if (name === "evidence" && !_PANE_LOADED.evidence) {          // #108: dissertation evidence
      _PANE_LOADED.evidence = true;
      const d = await (await fetch("/evidence")).json();
      if (d && d.ok) $("evbox").innerHTML = renderEvidence(d);           // empty state kept if the fetch fails
    }
  } catch (e) { /* server not reachable (file://) -> panes keep their placeholder/empty state */ }
}
// #108: render the three dissertation-evidence sections from /evidence (grounded dart.comparison output).
// FS-24: the evidence/gate HTML builders now live in evidence_html.js (window.STEWIE_EVIDENCE_HTML);
// these thin aliases pass the SEC-04 escaper / write the result into the DOM, preserving behaviour.
function renderEvidence(d) { return window.STEWIE_EVIDENCE_HTML.evidenceHTML(d, (typeof esc === "function") ? esc : null); }
$("srvrefresh").onclick = () => loadPane("server");

// TR-02/03/04 Trainer pane controls: refresh the recorded-session history, pick a session, and scrub its
// debrief legs (seen-vs-estimated-vs-truth). The scrubber re-renders from the cached debrief payload (no
// re-fetch per step) so stepping is instant and the link accounting (server-side) is never touched.
$("trainerrefresh") && ($("trainerrefresh").onclick = () => loadTrainer());
$("trainerdebriefsel") && ($("trainerdebriefsel").onchange = (e) => {
  if (e.target.value) loadTrainerDebrief(e.target.value);
});
$("trainerstep") && ($("trainerstep").oninput = (e) => {
  _TRAINER_STEP = Number(e.target.value) | 0; _renderScrubber();
});
$("trainerstepback") && ($("trainerstepback").onclick = () => {
  if (_TRAINER_STEP > 0) { _TRAINER_STEP -= 1; _renderScrubber(); }
});
$("trainerstepfwd") && ($("trainerstepfwd").onclick = () => {
  const n = (_TRAINER_DEBRIEF && _TRAINER_DEBRIEF.legs) ? _TRAINER_DEBRIEF.legs.length : 0;
  if (_TRAINER_STEP < n - 1) { _TRAINER_STEP += 1; _renderScrubber(); }
});

// ---- Navigation view (P1.4): Navigation estimator surface + articulation-parallax relocalization -----
// FS-24: the four pure nav-pane CANVAS PLOTTERS now live in navplot.js (window.STEWIE_NAVPLOT); these
// thin binding aliases resolve the target <canvas> via $() and forward, preserving behaviour exactly.
function navDrawTrajectory(est, base) { window.STEWIE_NAVPLOT.drawTrajectory($("navplot"), est, base); }
let LAST_LOCALIZATION = null;                              // #nav-mission: localization trace from the last /plan
// the LIVE mission localization: the run_closed_loop real estimate (terrain-relative + AprilTag-beacon
// fixes) vs the true pose per leg, the leg dots colour-coded by which real fix corrected them.
function navDrawMission(loc) {
  const cv = $("navmissionplot"); if (!cv) return;
  const g = cv.getContext("2d"); g.clearRect(0, 0, cv.width, cv.height);
  // FS-15: consume the typed LocalizationFix view model (adapters.js); inline fallback if it didn't load.
  const A = window.STEWIE_ADAPTERS;
  const normLoc = (p) => A ? A.normalizeLocalizationFix({ localization_fix: p })
    : { est: p.est, truePose: p["true"], sigma: p.sigma, fix: p.fix,
        errM: Math.hypot(p.est[0] - p["true"][0], p.est[1] - p["true"][1]) };
  const traj = (((loc && loc.trajectory) || []).map(normLoc).filter(Boolean));
  const stat = $("navmissionstats");
  if (!traj.length) {
    if (stat) stat.textContent =
      "Plan a mission (4·Plan → Plan mission) to see the rover's live estimated path vs truth and the per-leg fixes.";
    g.font = "12px system-ui"; g.fillStyle = "#5a6472"; g.textAlign = "center";   // council #238: in-canvas empty-state
    g.fillText("Plan a mission to see localization vs truth", cv.width / 2, cv.height / 2);
    g.textAlign = "left"; return;
  }
  const est = traj.map((p) => p.est), tru = traj.map((p) => p.truePose);
  const all = est.concat(tru), xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
  const minx = Math.min(...xs), maxx = Math.max(...xs), miny = Math.min(...ys), maxy = Math.max(...ys);
  const pad = 26, s = Math.min((cv.width - 2 * pad) / Math.max(1e-6, maxx - minx),
                               (cv.height - 2 * pad) / Math.max(1e-6, maxy - miny));
  const X = (x) => pad + (x - minx) * s, Y = (y) => cv.height - pad - (y - miny) * s;
  const line = (path, color, w) => { g.strokeStyle = color; g.lineWidth = w; g.beginPath();
    path.forEach((p, i) => (i ? g.lineTo(X(p[0]), Y(p[1])) : g.moveTo(X(p[0]), Y(p[1])))); g.stroke(); };
  line(tru, "#8a8a93", 2);                                 // true path (grey)
  line(est, "#36d1dc", 2);                                 // estimated path (cyan)
  const FIXC = { dem: "#3fa34d", beacon: "#e0b300", none: "#e8273f" };   // green / amber / red per fix kind
  traj.forEach((p) => { g.fillStyle = FIXC[p.fix] || "#888"; g.beginPath();
    g.arc(X(p.est[0]), Y(p.est[1]), 3, 0, 2 * Math.PI); g.fill(); });
  g.font = "10px system-ui";
  g.fillStyle = "#36d1dc"; g.fillText("— estimate", pad, 12); g.fillStyle = "#8a8a93"; g.fillText("— truth", pad + 66, 12);
  g.fillStyle = "#3fa34d"; g.fillText("● DEM", pad + 118, 12); g.fillStyle = "#e0b300"; g.fillText("● beacon", pad + 166, 12);
  g.fillStyle = "#e8273f"; g.fillText("● none", pad + 226, 12);
  const fk = loc.fix_kinds || {}, lastSig = traj[traj.length - 1].sigma;
  const maxErr = Math.max(...traj.map((p) => p.errM));   // FS-15: the view model derives est-vs-truth error
  const summary = `fixes: <b style="color:#3fa34d">${fk.dem || 0} DEM</b> · <b style="color:#e0b300">${fk.beacon || 0} beacon</b> · ` +
    `<b style="color:#e8273f">${fk.none || 0} none</b> · end pose σ <b>${lastSig} m</b> · max est-vs-truth <b>${maxErr.toFixed(2)} m</b>`;
  if (stat) stat.innerHTML = summary;
  const cx = $("ctxnav-loc"); if (cx) cx.innerHTML = summary;   // tab-contextual left: mirror the live summary
}
// FS-05 end-to-end DRIVE PREVIEW: POST /nav/run -> route the global corridor then drive it; draw the
// planned route (amber dashed) vs the executed trajectory (cyan) + start/goal + recovery backups.
let LAST_DRIVE = null;   // council #238: persist the last drive result so re-opening Validate redraws it (else the empty-state)
function navDrawDrive(res) { const cv = $("navdriveplot"); if (cv) window.STEWIE_NAVPLOT.drawDrive(cv, res); }
async function navDriveRun() {
  const btn = $("navdrive"); btn.disabled = true; btn.textContent = "… driving";
  const sx = +$("navdsx").value, sy = +$("navdsy").value, gx = +$("navdgx").value, gy = +$("navdgy").value;
  try {
    const r = await fetch("/nav/run", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ start: [sx, sy], goal: [gx, gy], dt: 2.0, max_ticks: 800 }) });
    const b = await r.json();
    if (!b.ok) { $("navdrivestats").innerHTML = `<span style="color:#e8273f">${esc(b.error || "drive unavailable")}</span>`; return; }  // SEC-04
    LAST_DRIVE = b; navDrawDrive(b);
    const dev = b.deviation || {};
    const arr = b.arrived ? `<b style="color:var(--accent)">arrived</b>` : `<b style="color:#e8273f">${esc(b.reason)}</b>`;
    $("navdrivestats").innerHTML = `${arr} · routed <b>${b.routed_m} m</b> · <b>${b.n_ticks}</b> control ticks · `
      + `<b>${b.n_recoveries}</b> recoveries · cross-track mean <b>${(dev.mean_m || 0).toFixed(2)} m</b> / max <b>${(dev.max_m || 0).toFixed(2)} m</b>`
      + `<br><span style="opacity:.7">Stages: ${esc((b.stages || []).join(" → "))}. Real Haworth DEM; route_leg corridor then plan_local/track_plan/recovery drive.</span>`;
  } catch (e) { $("navdrivestats").innerHTML = `<span style="color:#e8273f">server unreachable</span>`; }
  finally { btn.disabled = false; btn.textContent = "▶ Run drive"; }
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
// #148: REAL terrain-fix est-vs-truth on the real Haworth DEM (register_to_dem fused vs odometry),
// scored against the DEM's own truth -- the real lunar est-vs-truth, distinct from modeled Katwijk.
function navDrawReal(trueXY, fusedXY, odomXY) {
  const cv = $("navrealplot"); if (cv) window.STEWIE_NAVPLOT.drawReal(cv, trueXY, fusedXY, odomXY);
}
async function navRealTraverse() {
  const btn = $("navreal"); if (btn) { btn.disabled = true; btn.textContent = "… running"; }
  try {
    const r = await fetch("/localize/traverse", { headers: apiHeaders() });
    const b = await r.json();
    if (!b.ok) { $("navrealstats").innerHTML = `<span style="color:#e8273f">${esc(b.error || "unavailable")}</span>`; return; }
    navDrawReal(b.true_xy, b.fused_xy, b.odom_xy);
    const red = (b.abs_max_odom_m / Math.max(b.abs_max_fused_m, 1e-9));
    $("navrealstats").innerHTML = `<b>${b.n_dem_fix}</b> real <code>register_to_dem</code> fixes over `
      + `${b.n_keyframes} keyframes · odometry drift <b>${b.abs_max_odom_m.toFixed(1)} m</b> → fused `
      + `<b style="color:var(--accent)">${b.abs_max_fused_m.toFixed(1)} m</b> (<b>${red.toFixed(0)}× tighter</b>) · `
      + `aligned ATE ${b.ate_odom_m.toFixed(2)} → ${b.ate_fused_m.toFixed(2)} m`
      + `<br><span style="opacity:.7">Real Haworth terrain, scored vs the DEM's own truth — no modeled cue.</span>`;
  } catch (e) { $("navrealstats").innerHTML = `<span style="color:#e8273f">server unreachable</span>`; }
  finally { if (btn) { btn.disabled = false; btn.textContent = "▶ Run real traverse"; } }
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
          const cls = k.includes("Navigation") ? "#36d1dc" : k.includes("ShadowNav") ? "#e0a23a" : "#888";
          return `<div style="margin:3px 0"><span style="display:inline-block;width:230px">${k}</span>`
            + `<span style="display:inline-block;height:9px;width:${w}px;background:${cls};vertical-align:middle"></span> `
            + `<b>${v.mean_m} m</b> ±${v.ci95_m}</div>`;
        }).join("")
      + `<div style="color:var(--muted);margin-top:3px">${b.modeled} · n=${b.n_seeds} seeds</div>`;
  } catch (e) { $("navcmpout").innerHTML = `<span style="color:#e8273f">server unreachable</span>`; }
  finally { $("navcmp").disabled = false; $("navcmp").textContent = "Compare approaches"; }
}
function navGate() {                                  // #97 perception gate: should_relocalize(sigma, moving)
  const sig = +$("navsig").value, stand = $("navstand").checked, armed = sig > 2.0 && stand;
  $("navgate").innerHTML = armed
    ? `<span style="color:#36d1dc">● ARMED</span> — σ ${sig.toFixed(1)} m > 2.0 m tolerance, standstill`
    : `<span style="color:var(--muted)">○ not armed</span> — ${stand ? "σ within tolerance (no fix needed)" : "needs a standstill maneuver"}`;
  $("navreloc").disabled = !armed;
  return armed;
}
function navDrawFix(res) { window.STEWIE_NAVPLOT.drawFix($("navcov"), res); }   // top-down DEM-frame plot
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
// #228 L3 / #230: LIVE RC telemetry. The readout is PUSH-DRIVEN over an SSE stream
// (GET /rc/telemetry/stream) so the operator sees continuous live Pose/Leg + SF-01 watchdog state
// instead of poll-on-click; the watchdog ticks on every streamed frame, so the live drain itself keeps
// a stalled operator's SF-01 deadline armed. Auth: EventSource carries the SEC-01 session cookie
// automatically (same-origin) and a GET is CSRF-exempt, so the browser operator session authenticates
// the stream with no header; dev-open works on loopback. (The in-memory automation X-API-Key path can
// only reach the one-shot /rc/telemetry JSON, not this browser stream -- automation polls, it doesn't
// drive the cockpit.) Read-only: the gated command-emit (/rc/command, /rc/plan_ros) stays behind
// AG-08/SF-01, never a button. The button TOGGLES the live stream (start/stop).
let rcStream = null;     // the open EventSource while streaming live; null when stopped

// #230 step 3: the LIVE DRIVE MAP state. The RC backend reports a grid (row, col) pose on a cell_m grid;
// we convert to REP-103 metres EXACTLY as bridge.frames does (x = col*cell_m, y = -row*cell_m) and plot
// the rover + its travelled path + the last commanded GoTo goal on #rcdrivemap. This is the RC backend's
// OWN frame (a teleop sim with origin at its start cell) -- it is deliberately NOT overlaid on the
// planned-mission replay (a different, order-frame coordinate system); conflating them would mis-place
// the rover. So the live map is self-consistent and frame-honest.
let RC_PATH = [];          // travelled path, raw {row, col} cells (converted to metres at draw time)
let RC_GOAL = null;        // last commanded GoTo goal {row, col} cells, or null
let RC_CELL_M = 1;         // latest grid scale from the telemetry payload
let RC_ROS_PATH = [];      // #144: the LIVE ROS2 rover odom path, already REP-103 metres {x, y}
let RC_ROS_STALE = false;  // #144: the live ROS odom is older than the freshness window
let CUR_HF_FRAME = null;    // #144 tier-1: the loaded 3D-DEM frame {dem, cell_m, dem_origin} for the overlay match
const RC_PATH_MAX = 600;   // bound the path buffers (Power-of-10: no unbounded growth)

// #144 tier-1 (frame-match): the live rover is placed on the MAIN 3D view ONLY when its DEM-crop frame
// matches the loaded heightfield's frame (same dem, cell_m, and order origin in DEM metres). Then
// setLiveRover(x,-y) is provably correct; otherwise we suppress it (no mis-placement) -- the sidebar
// RC-frame map is always self-consistent and unaffected.
function _frameMatches(rf, hf) {
  if (!rf || !hf || rf.dem !== hf.dem) return false;
  if (Math.abs((+rf.cell_m) - (+hf.cell_m)) > 1e-6) return false;
  const ao = rf.dem_origin || [], bo = hf.dem_origin || [];
  return Math.abs((+ao[0]) - (+bo[0])) < 0.5 && Math.abs((+ao[1]) - (+bo[1])) < 0.5;
}
const RC_ROS_STALE_S = 3.0;
const _rc_xy = (rc) => ({ x: rc.col * RC_CELL_M, y: -rc.row * RC_CELL_M });   // frames.py: REP-103 metres

function renderRcTelemetry(b) {                          // render ONE pushed telemetry frame
  const out = qel("rctlmout"), hdr = qel("rctlmhdr");
  if (!out) return;
  const wd = b.watchdog || {};
  if (typeof b.cell_m === "number" && b.cell_m > 0) { RC_CELL_M = b.cell_m; rcGotoEcho(); }   // GIS: keep the metres echo accurate to the live grid scale
  if (hdr) hdr.textContent = `live · SF-01 watchdog: ${wd.tripped ? "TRIPPED (auto-SAFE)" : "armed"} · deadline ${wd.deadline_s}s`;
  const tlm = b.telemetry || [];
  // accumulate every POSE sample (it carries row/col); a Leg sample has no row, only final_row
  tlm.forEach((t) => {
    if (t.row !== undefined && t.col !== undefined && t.kind === "pose") {
      RC_PATH.push({ row: +t.row, col: +t.col });
      if (RC_PATH.length > RC_PATH_MAX) RC_PATH.shift();
    }
  });
  // #144: the LIVE ROS2 rover odom (already REP-103 m) -> its own path on the same map
  const ro = b.ros_odom;
  if (ro && typeof ro.x_m === "number") {
    RC_ROS_PATH.push({ x: ro.x_m, y: ro.y_m });
    if (RC_ROS_PATH.length > RC_PATH_MAX) RC_ROS_PATH.shift();
    RC_ROS_STALE = (typeof ro.age_s === "number" && ro.age_s > RC_ROS_STALE_S);
  }
  // #144 tier-1: place the live ROS rover on the MAIN 3D DEM view, in the order frame (y flips: frames.py
  // is y=-row, the 3D view is y=+row), ONLY when the rover's DEM-crop frame matches the loaded heightfield
  // (else the origins differ and it would mis-place -> suppress). Window-gated + harmless when unmounted.
  if (window.STEWIE3D && STEWIE3D.setLiveRover) {
    if (ro && typeof ro.x_m === "number" && !RC_ROS_STALE && _frameMatches(ro.frame, CUR_HF_FRAME))
      STEWIE3D.setLiveRover(ro.x_m, -ro.y_m);
    else STEWIE3D.clearLiveRover();
  }
  if (!RC_PATH.length && !tlm.length && !RC_ROS_PATH.length) {
    out.textContent = "live — no rover pose yet (issue a GoTo, or start the live ROS2 node, to populate).";
  } else {
    const line = [];
    const last = tlm.filter((t) => t.kind === "pose").slice(-1)[0];
    if (last) {
      const p = _rc_xy(last);
      const extra = [];
      if (typeof last.slip === "number") extra.push(`slip ${(+last.slip).toFixed(2)}`);
      if (typeof last.soc === "number") extra.push(`soc ${(last.soc * 100).toFixed(1)}%`);
      if (last.entrapped) extra.push("ENTRAPPED");
      line.push(`sim ${p.x.toFixed(1)}, ${p.y.toFixed(1)} m`
        + (extra.length ? ` · ${extra.join(" · ")}` : ""));
    } else {
      const leg = tlm.filter((t) => t.kind === "leg").slice(-1)[0];
      if (leg) line.push(`sim leg ${leg.leg_id} complete (status ${leg.status})`);
    }
    if (ro && typeof ro.x_m === "number") {
      line.push(`ROS ${ro.x_m.toFixed(1)}, ${ro.y_m.toFixed(1)} m`
        + (ro.mode ? ` · ${ro.mode}` : "")                  // tier-2: idle | cmd_vel (autonomy) | goal | safe
        + (RC_ROS_STALE ? ` · STALE ${ro.age_s.toFixed(1)}s` : " · live"));
    }
    out.textContent = line.join("  ·  ") || "live — streaming.";
  }
  rcDrawMap();
}

function rcDrawMap() {                                   // top-down live map in the RC frame (REP-103 m)
  const cv = qel("rcdrivemap"); if (!cv) return;
  const ctx = cv.getContext("2d"), W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H); ctx.fillStyle = "#05060c"; ctx.fillRect(0, 0, W, H);
  const pts = RC_PATH.map(_rc_xy);
  if (RC_GOAL) pts.push(_rc_xy(RC_GOAL));
  RC_ROS_PATH.forEach((p) => pts.push(p));               // #144: the live ROS rover frames the extent too
  pts.push({ x: 0, y: 0 });                              // always show the RC origin
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const spanx = Math.max(2, x1 - x0), spany = Math.max(2, y1 - y0);
  const padx = spanx * 0.15, pady = spany * 0.15;
  x0 -= padx; x1 += padx; y0 -= pady; y1 += pady;
  const s = Math.min(W / (x1 - x0), H / (y1 - y0));
  const ox = (W - s * (x1 - x0)) / 2, oy = (H - s * (y1 - y0)) / 2;
  const X = (wx) => ox + (wx - x0) * s, Y = (wy) => H - (oy + (wy - y0) * s);   // y up
  // RC origin tick
  ctx.strokeStyle = "rgba(120,130,150,.5)"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(X(0) - 4, Y(0)); ctx.lineTo(X(0) + 4, Y(0));
  ctx.moveTo(X(0), Y(0) - 4); ctx.lineTo(X(0), Y(0) + 4); ctx.stroke();
  // travelled path
  if (pts.length > 1 && RC_PATH.length > 1) {
    ctx.strokeStyle = "#6ee7a8"; ctx.lineWidth = 1.5; ctx.beginPath();
    const pp = RC_PATH.map(_rc_xy);
    ctx.moveTo(X(pp[0].x), Y(pp[0].y));
    for (let i = 1; i < pp.length; i++) ctx.lineTo(X(pp[i].x), Y(pp[i].y));
    ctx.stroke();
  }
  // goal marker (ring)
  if (RC_GOAL) {
    const g = _rc_xy(RC_GOAL);
    ctx.strokeStyle = "#ffd166"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(X(g.x), Y(g.y), 6, 0, 7); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(X(g.x) - 8, Y(g.y)); ctx.lineTo(X(g.x) + 8, Y(g.y));
    ctx.moveTo(X(g.x), Y(g.y) - 8); ctx.lineTo(X(g.x), Y(g.y) + 8); ctx.stroke();
  }
  // rover marker (current = last pose) + a heading tick from the last path delta
  if (RC_PATH.length) {
    const cur = _rc_xy(RC_PATH[RC_PATH.length - 1]);
    if (RC_PATH.length > 1) {
      const prev = _rc_xy(RC_PATH[RC_PATH.length - 2]);
      const dx = cur.x - prev.x, dy = cur.y - prev.y, m = Math.hypot(dx, dy);
      if (m > 1e-6) {
        ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.beginPath();
        ctx.moveTo(X(cur.x), Y(cur.y));
        ctx.lineTo(X(cur.x) + (dx / m) * 10, Y(cur.y) - (dy / m) * 10); ctx.stroke();
      }
    }
    ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(X(cur.x), Y(cur.y), 4, 0, 7); ctx.fill();
    ctx.strokeStyle = "#0b0e17"; ctx.lineWidth = 1.5; ctx.stroke();
  }
  // #144: the LIVE ROS2 rover (cyan when fresh, grey when stale) + its path -- already REP-103 m
  if (RC_ROS_PATH.length) {
    const col = RC_ROS_STALE ? "#7a8290" : "#22d3ee";
    if (RC_ROS_PATH.length > 1) {
      ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.beginPath();
      ctx.moveTo(X(RC_ROS_PATH[0].x), Y(RC_ROS_PATH[0].y));
      for (let i = 1; i < RC_ROS_PATH.length; i++) ctx.lineTo(X(RC_ROS_PATH[i].x), Y(RC_ROS_PATH[i].y));
      ctx.stroke();
    }
    const r = RC_ROS_PATH[RC_ROS_PATH.length - 1];
    ctx.fillStyle = col; ctx.beginPath(); ctx.arc(X(r.x), Y(r.y), 4, 0, 7); ctx.fill();
    ctx.strokeStyle = "#0b0e17"; ctx.lineWidth = 1.5; ctx.stroke();
  }
  // frame label + legend (sim = white, ROS = cyan)
  ctx.fillStyle = "rgba(207,216,227,.65)"; ctx.font = "9px system-ui";
  ctx.fillText(`REP-103 m · cell ${RC_CELL_M} m · ◦sim ◦ROS`, 5, H - 5);
}

function stopRcStream() {
  if (rcStream) { rcStream.close(); rcStream = null; }
  if (window.STEWIE3D && STEWIE3D.clearLiveRover) STEWIE3D.clearLiveRover();   // #144 tier-1: drop the live 3D rover
  const btn = qel("rctlm"), hdr = qel("rctlmhdr");
  if (btn) { btn.textContent = "⇄ Live RC telemetry"; btn.classList.remove("active"); }
  if (hdr) hdr.textContent = "stopped";
}

async function startRcStream() {
  const out = qel("rctlmout"), hdr = qel("rctlmhdr"), btn = qel("rctlm");
  if (!out) return;
  RC_PATH = []; RC_ROS_PATH = [];                        // fresh live session -> clear both travelled paths
  out.textContent = "connecting to the live telemetry stream…"; if (hdr) hdr.textContent = "";
  // Auth probe via the one-shot endpoint (carries any X-API-Key/CSRF) so an unauthenticated tab gets an
  // HONEST message instead of an EventSource retry-loop spinning on a 401 (EventSource exposes no status).
  try {
    const probe = await fetch("/rc/telemetry", { headers: apiHeaders() });
    if (probe.status === 401 || probe.status === 403 || probe.status === 503) {
      if (hdr) hdr.textContent = "auth required";
      out.textContent = "live telemetry needs an authenticated operator session — sign in to stream.";
      return;
    }
  } catch (e) { out.textContent = "live stream unavailable — run server.py (" + e + ")"; return; }
  let es;
  const _rate = (qel("rctlmrate") && qel("rctlmrate").value) || "1.0";  // P4: operator-set push rate (server clamps 0.1-10 s)
  try { es = new EventSource(`/rc/telemetry/stream?interval_s=${encodeURIComponent(_rate)}`); }   // cookie auth, same-origin
  catch (e) { out.textContent = "live stream unavailable — run server.py (" + e + ")"; return; }
  rcStream = es;
  if (btn) { btn.textContent = "■ Stop (live)"; btn.classList.add("active"); }
  es.onmessage = (ev) => {
    try { renderRcTelemetry(JSON.parse(ev.data)); } catch (e) { /* skip a malformed frame; the next re-renders */ }
  };
  es.onerror = () => {                                  // the browser auto-reconnects SSE; surface the drop
    if (rcStream === es && hdr) hdr.textContent = "live · reconnecting…";
  };
}

function rcTelemetryToggle() { if (rcStream) stopRcStream(); else startRcStream(); }

// #229: DT-02 director-only twin audit -- the observed-twin resync history (events + provenance +
// hash-chain validity). Director-gated server-side (require_director); a non-director gets 403 and the
// readout shows the honest director-only state (same pattern as the TR-02/TR-04 trainer boards).
async function twinAudit() {
  const out = qel("twinauditout"), hdr = qel("twinaudithdr");
  if (!out) return;
  out.textContent = "loading…"; if (hdr) hdr.textContent = "";
  try {
    const r = await fetch("/twin/history", { headers: apiHeaders() });
    if (r.status === 401 || r.status === 403) {
      if (hdr) hdr.textContent = "director-only";
      out.textContent = "DT-02 twin audit is director-only — sign in with a director key to view the resync history.";
      return;
    }
    const b = await r.json();
    if (!r.ok) { out.textContent = `twin audit failed: ${b.error || ("HTTP " + r.status)}`; return; }
    if (hdr) hdr.textContent = `v${b.twin_version} · chain ${b.chain_valid ? "VALID" : "BROKEN"}`;
    const ev = b.events || [];
    if (!ev.length) { out.textContent = "no resync events recorded (the observed twin is at its base version)."; return; }
    out.textContent = "";
    ev.slice(-12).forEach((e) => {
      const d = document.createElement("div");
      const ts = e.timestamp || e.ts || e.time || "";
      d.textContent = `#${e.version ?? "?"}  ${e.kind || e.event || "resync"}  ${e.source || e.basis || ""} ${ts}`.replace(/\s+/g, " ").trim();
      out.appendChild(d);
    });
  } catch (e) { out.textContent = "twin audit failed — run server.py (" + e + ")"; }
}

// #229 lane B: FS-17-gated live-rover command console (POST /rc/command). Controls are
// [data-cmd-authority] (auto-disabled by CMD_AUTH in a read-only window); every emit calls guardCommand()
// FIRST; GoTo confirms before sending; the AG-08 published-mission + operator/director role gates are
// enforced server-side and surfaced honestly (403 -> "refused (gated)"). Safe = emergency stop (no mission
// ref, always allowed to the authority holder); SetSim (time-warp) is director-only.
async function rcCommand(kind) {
  const out = qel("rccmdout");
  if (!guardCommand("RC " + kind)) {
    if (out) out.textContent = "this window is READ-ONLY — another cockpit holds command authority (Take over to command).";
    return;
  }
  let body = { kind };
  if (kind === "goto") {
    const gr = parseFloat(qel("rcgr").value), gc = parseFloat(qel("rcgc").value);
    if (!Number.isFinite(gr) || !Number.isFinite(gc)) { out.textContent = "enter a goal row, col first"; return; }
    const m = qel("rccmdmission").value.trim();
    // P5: operator-set drive-speed cap (server takes v_max_mps unbounded -> clamp to a safe IPEx-class range)
    const _vraw = parseFloat(qel("rcvmax") ? qel("rcvmax").value : "");
    const vmax = Number.isFinite(_vraw) ? Math.max(0.05, Math.min(_vraw, 0.5)) : 0.3;
    if (!window.confirm(`Send GoTo (${gr}, ${gc}) at ≤${vmax} m/s${m ? " for mission " + m : ""} to the LIVE rover?`)) return;
    body = { kind, goal_row: gr, goal_col: gc, leg_id: 0, v_max_mps: vmax, ...(m ? { mission: m } : {}) };
  } else if (kind === "setsim") {
    body = { kind, time_factor: parseFloat(qel("rctf").value) || 1.0 };
  }
  out.textContent = "sending…";
  try {
    const r = await fetch("/rc/command", { method: "POST", headers: apiHeaders(), body: JSON.stringify(body) });
    const b = await r.json().catch(() => ({}));
    if (r.status === 403) { out.textContent = `refused (gated): ${b.detail || b.error || "AG-08 / role"}`; return; }
    if (!r.ok) { out.textContent = `command failed: ${b.error || b.detail || ("HTTP " + r.status)}`; return; }
    out.textContent = `accepted: ${b.accepted}${b.watchdog_tripped ? " · watchdog TRIPPED" : ""}`;
    // #230 step 3: a GoTo sets the live-map goal ring; SAFE clears it (the drive was halted).
    if (kind === "goto" && body.goal_row !== undefined) { RC_GOAL = { row: body.goal_row, col: body.goal_col }; rcDrawMap(); }
    else if (kind === "safe") { RC_GOAL = null; rcDrawMap(); }
  } catch (e) { out.textContent = "command failed — run server.py (" + e + ")"; }
}

// GIS: live REP-103 metres echo for the GoTo console. The operator types grid (row, col) on the RC
// backend's cell_m grid; show WHERE that is in metres via the frames.py transform (x = col*cell_m,
// y = -row*cell_m -- the exact transform _rc_xy/the drive map plot), so a GoTo target is never an
// unlabelled cell. Honest: this is the RC backend's OWN REP-103 frame (matching the drive-map label),
// NOT a site lat/lon -- the SimBackend grid is not georeferenced to the DEM, so a geographic coord here
// would be false precision. Refreshes on input + when telemetry updates the grid scale (RC_CELL_M).
function rcGotoEcho() {
  const el = $("rcgotom"); if (!el) return;
  const gr = parseFloat($("rcgr") ? $("rcgr").value : ""), gc = parseFloat($("rcgc") ? $("rcgc").value : "");
  if (Number.isFinite(gr) && Number.isFinite(gc)) {
    const x = gc * RC_CELL_M, y = -gr * RC_CELL_M;            // frames.py REP-103 metres
    el.textContent = `target → ${x.toFixed(1)}, ${y.toFixed(1)} m (REP-103) · cell ${RC_CELL_M} m`;
  } else {
    el.textContent = `target — REP-103 m (enter row, col) · cell ${RC_CELL_M} m`;
  }
}

// FS-05 nav contract readout: GET /nav/contract -> render each nav stage's on-host wired status (the
// auditable navigation contract). Read-only diagnostic; the missing on-host stages render flagged.
async function navContract() {
  const out = qel("navcontractout"), hdr = qel("navcontracthdr");
  out.textContent = "loading…"; hdr.textContent = "";
  try {
    const r = await fetch("/nav/contract", { headers: apiHeaders() });
    const b = await r.json();
    if (!r.ok) { out.textContent = `nav contract failed: ${b.error || ("HTTP " + r.status)}`; return; }
    hdr.textContent = `v${b.version} · on-host ${b.on_host_complete ? "COMPLETE" : "partial"}`;
    out.textContent = "";
    (b.stages || []).forEach((s) => {
      const d = document.createElement("div");
      d.textContent = `${s.present ? "✓" : "✗"} ${s.stage}  —  ${s.seam}${s.note ? "  (" + s.note + ")" : ""}`;
      if (!s.present && !s.note) d.style.color = "var(--accent)";  // a missing on-host stage is flagged
      out.appendChild(d);
    });
  } catch (e) { out.textContent = "nav contract failed — run server.py (" + e + ")"; }
}
if ($("navrun")) {
  $("navrun").onclick = navRun;
  $("navcmp").onclick = navCompare;
  if ($("navcontract")) $("navcontract").onclick = navContract;  // #228 L2: FS-05 nav-stage contract readout
  if ($("rctlm")) $("rctlm").onclick = rcTelemetryToggle;       // #228 L3 / #230: push-driven live RC telemetry + SF-01 watchdog stream
  if ($("rctlmrate")) $("rctlmrate").addEventListener("change", () => { if (rcStream) { stopRcStream(); startRcStream(); } });  // P4: re-open at the new push rate without losing the session
  if ($("twinaudit")) $("twinaudit").onclick = twinAudit;       // #229: DT-02 director-only twin audit readout
  if ($("rcsafe")) $("rcsafe").onclick = () => rcCommand("safe");     // #229 L B: FS-17/AG-08 command console
  if ($("rcgoto")) $("rcgoto").onclick = () => rcCommand("goto");
  if ($("rcsetsim")) $("rcsetsim").onclick = () => rcCommand("setsim");
  ["rcgr", "rcgc"].forEach((id) => { if ($(id)) $(id).addEventListener("input", rcGotoEcho); });  // GIS: live REP-103 metres echo of the GoTo target
  rcGotoEcho();
  if ($("navdrive")) $("navdrive").onclick = navDriveRun;     // FS-05 end-to-end route-then-drive preview
  if ($("navreal")) $("navreal").onclick = navRealTraverse;   // #148 real Haworth terrain-fix est-vs-truth
  $("navreloc").onclick = navReloc;
  if ($("ctxnav-run")) $("ctxnav-run").onclick = navRun;   // tab-contextual left: same estimator run
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
  // #172 (Aaron "is this appropriate for the Body?"): BODY info is terramechanics ONLY (g/ρ/c/φ/Bekker).
  // The IPEx POWER block is the vehicle's draw on this body, not a body property -> moved to the VEHICLE
  // info popover (syncKinds). This also drops the long power tail that abutted the Layer control.
  $("terra").textContent =
    `terramechanics  g ${p.g} m/s² · ρ ${p.density} kg/m³`
    + (p.cohesion_pa != null ? ` · c ${p.cohesion_pa} Pa` : "")
    + (p.friction_deg != null ? ` · φ ${p.friction_deg}°` : "")
    + ` · ${bk}` + (p.regime ? ` · ${p.regime}` : "")
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
  summary.textContent = `dig-only est · ${(cutMass / 1000).toFixed(1)} t · ${charges.toFixed(1)} charges · ~${Math.round(hrs + rechargeH).toLocaleString()} h (dig + recharge) `;
  // #7 (conservative feasibility, Aaron): a single battery charge is the conservative baseline. >1 charge
  // = a multi-sortie mission -> FLAG it amber ("review"), never present it as feasible-green. Planning
  // still allows >1 charge (not capped); the readout just stops calling it green.
  const overCharge = charges > 1.0 + 1e-9;
  if (overCharge) {
    summary.style.color = "#e0b300";                         // amber = review-needed, not the green feasible state
    const flag = document.createElement("b");
    flag.textContent = `⚠ ${Math.ceil(charges - 1e-9)} sorties (>1 charge) — review  `;
    flag.style.cssText = "color:#e0b300";
    flag.title = "exceeds a single battery charge -> multi-sortie; the conservative default flags this for review rather than feasible-green";
    $("est").append(flag);
  }
  const info = document.createElement("button");
  info.textContent = "ⓘ details";
  info.style.cssText = "background:none;border:1px solid var(--line);border-radius:4px;color:var(--accent);cursor:pointer;font-size:10px;padding:1px 6px";
  // Planner P4: the estimate is a DIG-ONLY lower bound -- say so on the summary itself, not just the ⓘ
  // popover, so a planner never reads it as the real feasibility verdict (the 4·Plan solver supersedes it).
  const sub = document.createElement("div");
  sub.style.cssText = "font-size:9px;color:var(--muted);margin-top:1px";
  sub.textContent = "lower bound — the 4·Plan solver adds travel + slip + recharge routing (it supersedes this)";
  $("est").append(summary, info, sub);
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
      design; the solver in 4·Plan adds travel + slip + recharge routing per leg. Updates live.</div>`;
  });
  refreshPopovers();
  return { body: sel.value, padW, padL, cut_m: cut, bermH_m: bermH, cutVol_m3: cutVol, cutMass_kg: cutMass,
           weight_N: weightN, bermArea_m2: bermArea, drumLoads, energy_MJ: energyJ / 1e6,
           batteryCharges: charges, digHours: hrs, terramechanics: p };
}

function showSiteDem() {                                   // auto-show the real Haworth 5 m work-area DEM on Moon
  const wa = document.getElementById("workarea");
  if (VIEW !== "plan" || sel.value !== "moon") { wa.classList.remove("show"); return; }  // inset is Plan/Moon only
  // #162 fix: REVEAL the locator only once its hillshade has actually decoded. #workarea is display:none
  // until .show, but it carries a dark-panel min-box (180x120) -- adding .show BEFORE the image loads (or
  // when it silently fails / a stale cache resolves empty) renders that dark box: the "black square" the
  // operator reported. Gate .show on img.onload, and cache-bust per session so a bad cached image can't stick.
  const i = document.getElementById("workareaimg");
  if (!i.dataset.locv) i.dataset.locv = String(Date.now());
  // REG-01: the work-area + plan-view preview follows the SELECTED site (not always Haworth). The site is
  // in the URL, so switching sites changes `want` -> the image reloads for the new tile.
  // GIS-WA1: the CLEAN, axis-free, native-res work-area hillshade of [0,WORK_AREA_M]^2 (was /dem/hillshade.png
  // = preview_hillshade.png, a matplotlib FIGURE whose axis margins inset the terrain and misregistered the
  // plan-canvas drape). This raster fills the [0,WORK_AREA_M] world box exactly, so authoring clicks land true.
  const want = "/dem/workarea.png?site=" + encodeURIComponent(CURRENT_SITE) + "&window_m=" + WORK_AREA_M + "&v=" + i.dataset.locv;
  // #167 (Aaron "body still doesn't show in work area" on Moon/Plan): reveal ROBUSTLY. The old gate only
  // revealed-when-already-decoded if src===want, so a cached/fast image that fired its load before this
  // handler (re)attached stayed hidden -> the panel never showed. Now: reveal on load, reveal NOW if the
  // image is already usable (no src-match requirement), and a short fallback in case the load was missed.
  const reveal = () => { if (VIEW === "plan" && sel.value === "moon" && i.complete && i.naturalWidth > 0) wa.classList.add("show"); };
  i.onload = reveal;
  if (i.getAttribute("src") !== want) i.src = want;       // (re)load -> onload reveals it; error handler hides on real failure
  reveal();                                               // already-decoded path
  setTimeout(reveal, 500);                                // fallback: a missed load event still reveals
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
// GIS-WA1: rendering a Godot sensor frame is a ~40 s heavy action, so it is EXPLICIT (double-click the
// locator) -- a plain single click on the work-area inset no longer fires it (it used to, which fired a
// surprise 40 s render on the lightest gesture). Single-drag = locator pan (the canvas above captures it).
$("piploc") && ($("piploc").ondblclick = (e) => {
  const r = e.target.getBoundingClientRect();
  const u = (e.clientX - r.left) / r.width, v = (e.clientY - r.top) / r.height;
  renderArea(u, v, {});
});
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
      $("rpstatus").innerHTML = "⚠ API key required for rendering — paste it in <b>Settings</b> (the server key lives in deploy/.env)";
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
  const el = $("gateevidence"); if (!el) return;
  el.innerHTML = window.STEWIE_EVIDENCE_HTML.gateEvidenceHTML(j);
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
      $("admout").textContent = r.status === 401 ? "⚠ sign in (Settings)" : (j.ok ? fmt(j) : (j.error || r.status));
    } catch (e) { $("admout").textContent = "failed: " + e; }
    b.disabled = false;
  };
});
// #25: the CG / stability side-profile (server physics: /twin/cg). WHAT-IF, not live: the posture
// (front/back arm deg, drum kg, pitch) is read from the sliders below, NOT from live rover pose. The
// SSA tip-margin math is real; its inputs are operator-set. Bind to live pose when a live mission connects.
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
  // council #238: lead with WHAT-IF so the green "risk OK" verdict + precise margin are not read as a LIVE
  // safety call -- this is a posture computed from the sliders, not a live-pose telemetry verdict.
  $("cgout").innerHTML = `<span style="color:var(--muted)">what-if · sliders, not live</span> · ` +
    `CG <b>${(d.cg_dx_m * 100).toFixed(1)} cm</b> fwd · height <b>${(d.cg_height_m * 100).toFixed(1)} cm</b> · ` +
    `tip margin <b style="color:${riskCol}">${d.margin_deg.toFixed(2)}°</b> (${d.binding_axis}) · risk <b style="color:${riskCol}">${d.risk.toUpperCase()}</b>`;
  if (typeof drawRoverHUD === "function") drawRoverHUD(roverHUDState());   // #184: drum-load change -> refresh the rover HUD
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
async function loadSites() {     // #auth-reload: named (not an IIFE) so refreshAuthState re-runs it after login
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
      if (typeof showSiteDem === "function") showSiteDem();   // REG-01: reload the work-area DEM for the chosen site
      if (typeof drawPlan === "function") drawPlan();         // refresh the plan-view background to the new tile
      if (typeof loadSiteFootprint === "function") loadSiteFootprint(true);   // REG-01: re-anchor the globe footprint + drape
      setTimeout(() => { if (viewer) viewer.camera.setView({ destination:
        Cesium.Cartesian3.fromDegrees(lo, la, 90000, viewer.scene.globe.ellipsoid) }); }, 800);
      setQ(sl.options[sl.selectedIndex].text.includes("✓DEM")
        ? "site has an imported DEM bundle -- full planning available"
        : "no DEM bundle imported for this site yet (registry: stewie/specs/sites.py; import via the dem_import pipeline)");
    };
  } catch (e) { /* offline */ }
}
// #150: surface the DEM base-layer catalog (GET /dem/sources) in the Contents section -- provenance +
// readiness (which tiles ship bundled vs need a real download; display-only products flagged).
(async function loadDemSources() {
  const box = document.getElementById("demsources"); if (!box) return;
  try {
    const j = await (await fetch("/dem/sources")).json();
    if (!j.ok || !Array.isArray(j.sources)) return;
    const rows = j.sources.map((s) => {
      const tag = s.bundled ? '<span style="color:var(--accent)">&#10003; bundled</span>'
                            : '<span style="opacity:.6">download</span>';
      const grade = s.planning_grade ? "" : ' &middot; <span style="opacity:.6" title="display only, not metric-controlled">view-only</span>';
      return '<div style="padding:2px 0">' +
        '<a href="' + esc(s.access_url) + '" target="_blank" rel="noopener" style="color:var(--txt,#dfe7ef)">' + esc(s.name) + '</a> ' +
        '<span style="opacity:.6">' + esc(String(s.resolution_m)) + ' m</span> &mdash; ' + tag + grade + '</div>';
    }).join("");
    const bundled = j.sources.filter((s) => s.bundled).length;
    box.innerHTML = '<details><summary style="cursor:pointer;color:var(--muted)">DEM base layers (' +
      bundled + ' bundled / ' + j.sources.length + ' total)</summary>' +
      '<div style="margin-top:4px">' + rows + '</div></details>';
  } catch (e) { /* offline */ }
})();
$("landset").onclick = () => { setLander(+$("landx").value || 0, +$("landy").value || 0);
  setQ(`lander @ site-frame ${LANDER_P.x} m E, ${LANDER_P.y} m N`); };
if ($("landx")) { $("landx").value = LANDER_P.x; $("landy").value = LANDER_P.y; }
// #174: type the rover's known position (mirrors the lander control); the rover edit tool is the map-click path.
if ($("roverset")) $("roverset").onclick = () => { recordPose(+$("roverx").value || 0, +$("rovery").value || 0);
  setQ(`rover @ site-frame ${LAST_POSE.x} m E, ${LAST_POSE.y} m N`); };
if ($("roverx") && LAST_POSE) { $("roverx").value = LAST_POSE.x; $("rovery").value = LAST_POSE.y; }
// #audit-5: 4b (Traverse) seeds the first waypoint from the rover's last known pose so the path starts where
// the rover actually is; with no pose set it stays at the site origin (0,0) -- a valid, explicit start.
if (LAST_POSE && $("wpx")) { $("wpx").value = LAST_POSE.x; $("wpy").value = LAST_POSE.y; }
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
  PLACED_STRUCTURES.length = 0; if (typeof renderSitePlan === "function") renderSitePlan(null);
  SELECTED_ORDER = -1; LAST_ROUTES.length = 0;
  EDIT_PINS.forEach((e) => viewer && viewer.entities.remove(e)); EDIT_PINS.length = 0;
  LANDER_PIN = null;                                        // #lander-pin: the marker was just removed above
  renderQueue(); setQ("plan reset");
};
if ($("drawerbtn")) {
  $("drawerbtn").onclick = () => {
    const panel = document.getElementById("panel");
    if (innerWidth <= 860) { panel.classList.toggle("open"); return; }   // mobile: slide-over drawer
    // UX-05 desktop: toggle the collapse AND pin the explicit choice so it survives view switches + reloads
    const nowCollapsed = !panel.classList.contains("collapsed");
    panel.classList.toggle("collapsed", nowCollapsed);
    SIDEBAR_PIN = nowCollapsed ? "collapsed" : "open";
    try { localStorage.setItem("stewie_sidebar_pin", SIDEBAR_PIN); } catch (e) {}
  };
  // tapping the map closes the drawer (mobile pattern)
  document.getElementById("cesium").addEventListener("pointerdown", () => {
    const p2 = document.getElementById("panel");
    if (innerWidth <= 860 && p2.classList.contains("open")) p2.classList.remove("open");
  });
  // crossing the mobile/desktop breakpoint: re-apply so a desktop collapse never lingers on a phone
  addEventListener("resize", () => applySidebar(VIEW));
}
$("editmode").onclick = () => setEdit(true);
$("editdone").onclick = () => setEdit(false);
document.querySelectorAll(".etool").forEach((b) => {
  b.onclick = () => { EDIT.tool = b.dataset.tool; MEASURE_A = null; BOX_A = null;
    if (typeof clearPolyDraft === "function") clearPolyDraft();           // #178: drop any half-drawn polygon
    $("editstate").textContent = `LOCKED · ${b.dataset.tool} armed — click the map`; };
});
// #mobile-delete (Aaron: "there is no delete on mobile"): the touch equivalent of the Delete key. Tap a
// pin to select it (SELECTED_PIN, highlighted green), then tap this to remove the feature + its pin.
if ($("editdel")) $("editdel").onclick = () => {
  if (SELECTED_PIN) deleteSelectedPin();
  else setQ("tap a pin on the map first (it turns green), then tap delete");
};
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
// structure-first base planning: the placed structures the operator dropped (name + site coords), kept
// as a first-class list so the Site-plan analyzer can reason ACROSS them (base-wide mass routing,
// clearances, build order). Distinct from ORDERS, which is the lowered cut/fill queue they expand into.
const PLACED_STRUCTURES = [];
const KEEPOUTS = [];                                          // discrete obstacles (local m): {x,y,r} circle OR {x0,y0,x1,y1} rect (#178); hauls route around
// FS-24: keep-out shape predicates + bounds + label now live in keepout_geom.js
// (window.STEWIE_KEEPOUT_GEOM); thin binding aliases preserve behaviour. fillKeepout (below) draws on
// the canvas using these.
const koIsPoly = window.STEWIE_KEEPOUT_GEOM.koIsPoly;   // #178: polygon keep-out (matches keepout_is_poly)
const koIsRect = window.STEWIE_KEEPOUT_GEOM.koIsRect;   // #178: rect keep-out (matches keepout_is_rect)
const koBounds = window.STEWIE_KEEPOUT_GEOM.koBounds;   // #178: a keep-out's local-frame AABB, any shape
const koLabel = window.STEWIE_KEEPOUT_GEOM.koLabel;     // #178: a human-readable keep-out summary
// #178: draw a keep-out on the 2D plan (poly/rect/disc). The drawing lives in plan_geom.js; this thin
// alias supplies the keepout_geom shape helpers (FS-24). Callers unchanged.
function fillKeepout(ctx, k, X, Y, s) { window.STEWIE_PLAN_GEOM.fillKeepout(ctx, k, X, Y, s, koIsPoly, koIsRect, koBounds); }
// #170: mission-pipeline WIZARD state -- STEP_DONE holds the steps the operator has CONFIRMED via "Done"
// (the real red->green gate, replacing the old hardcoded site/fleet="done"); WIZ_STEP is the step in focus.
const STEP_ORDER = ["site", "fleet", "orders", "solve", "review", "execute"];
let WIZ_STEP = "site";
const STEP_DONE = {};
// #177: AUTO-SAVE the working draft. Orders + keep-outs lived only in memory (the lander already
// persisted via stewie_lander), so anything placed on the map vanished on reload unless explicitly
// saved as a NAMED mission -- "adding something doesn't save it". Persist the working set to
// localStorage on every change and restore it on boot, so work survives a reload (the named-save
// catalog is unchanged). Guarded by DRAFT_READY so an early render cannot clobber the saved draft.
let DRAFT_READY = false;
let _draftSaveT = 0;                                          // #241: debounce the per-owner SERVER autosave
function _draftPayload() {
  return { body: (typeof sel !== "undefined" ? sel.value : "moon"), orders: ORDERS, keepouts: KEEPOUTS,
           landmarks: LANDMARKS, step_done: STEP_DONE, wiz_step: WIZ_STEP };
}
function persistDraft() {
  if (!DRAFT_READY) return;
  try { localStorage.setItem("stewie_draft", JSON.stringify(_draftPayload())); } catch (e) { /* storage disabled / full */ }
  // #241: ALSO autosave to the per-owner SERVER draft (durable + cross-device), DEBOUNCED ~1.5s so per-drag/
  // per-keystroke edits coalesce. Only when signed in (csrf cookie or in-memory key) -- an anonymous cockpit
  // stays localStorage-only (the server has no anonymous draft owner). owner is the server identity, not sent.
  if (!getCookie("stewie_csrf") && !AUTH.apikey) return;
  clearTimeout(_draftSaveT);
  _draftSaveT = setTimeout(() => {
    fetch("/draft", { method: "PUT", headers: apiHeaders(), body: JSON.stringify(_draftPayload()) }).catch(() => {});
  }, 1500);
}
function _hydrateDraft(d) {                                   // apply a draft doc (localStorage OR server) into the live state
  if (d && Array.isArray(d.orders)) { ORDERS.length = 0; d.orders.forEach((o) => ORDERS.push(o)); }
  if (d && Array.isArray(d.keepouts)) { KEEPOUTS.length = 0; d.keepouts.forEach((k) => KEEPOUTS.push(k)); }
  if (d && Array.isArray(d.landmarks)) {
    LANDMARKS.length = 0;
    d.landmarks.forEach((l) => {
      LANDMARKS.push(l);
      // #178: re-drop the globe marker for a restored landmark (we stored its lat/lon), so a persistent
      // reference point survives reload ON the map -- not just in the data model.
      if (typeof viewer !== "undefined" && viewer && typeof l.lat === "number" && typeof l.lon === "number") {
        dropPin(l.lat, l.lon, `plot ${l.name}`, "#3fb6ff", { kind: "landmark", obj: l });
      }
    });
  }
  if (d && d.step_done && typeof d.step_done === "object") Object.assign(STEP_DONE, d.step_done);
  if (d && typeof d.wiz_step === "string") WIZ_STEP = d.wiz_step;
}
function _redrawAfterDraft() {                                // #241: re-render after a LATE server-draft hydrate
  try {
    if (typeof renderQueue === "function") renderQueue();
    if (typeof renderKeepouts === "function") renderKeepouts();
    if (typeof drawPlan === "function") drawPlan();
    if (typeof estimate === "function") estimate();
    if (typeof renderStepper === "function") renderStepper();
  } catch (e) { /* best-effort */ }
}
function restoreDraft() {
  try { _hydrateDraft(JSON.parse(localStorage.getItem("stewie_draft") || "null")); } catch (e) { /* corrupt local draft */ }
  // #241: the per-owner SERVER draft WINS when present (cross-device source of truth). Async: arm autosave
  // only AFTER it is fetched + applied (the .finally), so an empty/stale local draft can't PUT-clobber a good
  // server draft on boot. Anonymous (no creds) stays localStorage-only and arms immediately.
  if (!getCookie("stewie_csrf") && !AUTH.apikey) { DRAFT_READY = true; return; }
  fetch("/draft", { headers: apiHeaders() })
    .then((r) => r.ok ? r.json() : null)
    .then((j) => { if (j && j.doc) { _hydrateDraft(j.doc); _redrawAfterDraft(); } })
    .catch(() => {})
    .finally(() => { DRAFT_READY = true; });                 // from here on, every change auto-persists (local + server)
}
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
  persistDraft();                                             // #177: keep-out change -> auto-save the draft
  const ol = qel("kolist"); ol.innerHTML = "";
  KEEPOUTS.forEach((k, i) => {
    const li = document.createElement("li");
    const g = document.createElement("span"); g.className = "g";
    g.textContent = `obstacle: ${koLabel(k)}`;                 // #178: circle or box
    li.appendChild(g);
    li.appendChild(mkbtn("✕", () => { KEEPOUTS.splice(i, 1); renderKeepouts(); }));
    ol.appendChild(li);
  });
  drawPlan();
  if (typeof renderContentsTree === "function") renderContentsTree();   // GIS S-2: keep-out feature rows in the tree
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
  persistDraft();                                             // #177: order change -> auto-save the draft
  const tb = qel("qtable"); tb.innerHTML = "";
  // #4: x/y are site-local metres (East/North from the site origin) -- label the units so a queued
  // "wp1  2310  8165" reads as 2310 m E, 8165 m N, not bare unexplained numbers.
  const cols = [["#", null], ["kind", "kind"], ["action", "action"], ["x m·E", "x"], ["y m·N", "y"],
                ["m²", "footprint_m2"], ["shape", null], ["depth", "depth_m"], ["", null]];
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
    // GIS S-3: the queue shows the typed footprint shape (e.g. "rect 15×2 @30°") or "square" (legacy).
    const shapeLabel = o.kind === "goto" ? "—" : (function () {
      const sh = o.shape;
      if (!sh) return "square";
      const t = sh.theta_deg ? ` @${Number(sh.theta_deg).toFixed(0)}°` : "";
      if (sh.kind === "rectangle") return `rect ${fx(sh.w)}×${fx(sh.h)}${t}`;
      if (sh.kind === "corridor") return `corridor ${fx(sh.length)}×${fx(sh.width)}${t}`;
      if (sh.kind === "circle") return `circle r${fx(sh.r)}`;
      if (sh.kind === "polygon") return `poly (${(sh.vertices || []).length}v)`;
      return "square";
    })();
    const cells = [String(i + 1), o.kind, o.action || "", fx(o.x), fx(o.y),
                   o.kind === "goto" ? "—" : fx(o.footprint_m2), shapeLabel,
                   o.kind === "goto" ? "—" : fx(o.depth_m)];
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
  if (typeof renderStepper === "function") renderStepper();  // pipeline spine: Orders done when queue non-empty
  if (typeof renderContentsTree === "function") renderContentsTree();   // GIS S-2: orders feature layer in the tree
}
function addOrder(o) { snapshotAuthoring(); ORDERS.push(o); renderQueue(); }

// GIS S-2: the Contents tree -- a sidebar PRESENTATION layer over the existing plan/layer state. It owns NO
// state: it snapshots LAYER_ON / ORDERS / KEEPOUTS / markers, asks the pure module to build the tree, and
// wires each row's checkbox/zoom/remove/select back to the SAME functions the flat widgets already call
// (applyLayerToggle, flyToWorkArea, the ORDERS/KEEPOUTS splices + renderQueue/renderKeepouts). So the queue,
// keep-out list, layer strip and tree all stay in sync off one source of truth.
function syncLayerStripCheckbox(lid, on) {                  // keep the flat LAYERS strip in lockstep
  const lp = qel("layerpanel"); if (!lp) return;
  if (lid === "terrain3d") { const c = qel("lyr_terrain3d"); if (c) c.checked = on; return; }
  if (lid === "recon_twin") { const c = qel("lyr_recon_twin"); if (c) c.checked = on; return; }
  // the /layers rows have no stable id; match by the layer's display name in the label text.
  const NAME = { imagery: "imagery", dem: "DEM", slope: "Slope", topology: "Topology", grid: "grid",
                 hazard: "no-go", illumination: "Shadow", incidence: "incidence", psr: "PSR", excavation: "excavation",
                 lander: "lander" };
  const needle = NAME[lid]; if (!needle) return;
  lp.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    const t = (cb.parentElement && cb.parentElement.textContent) || "";
    if (t.toLowerCase().includes(needle.toLowerCase())) cb.checked = on;
  });
}
function renderContentsTree() {
  const CT = window.STEWIE_CONTENTS_TREE; if (!CT) return;
  const tgt = qel("contents-tree"); if (!tgt) return;
  const tree = CT.buildTree({
    layerOn: LAYER_ON,
    orders: ORDERS,
    keepouts: KEEPOUTS,
    selectedOrder: SELECTED_ORDER,
    koLabel,
    markers: {
      lander: { present: true, x: (typeof LANDER_P !== "undefined" ? LANDER_P.x : 0),
                y: (typeof LANDER_P !== "undefined" ? LANDER_P.y : 0) },
      charger: { present: true, x: 0, y: 0 },               // the planner charger is fixed at the site origin (0,0)
    },
  });
  CT.renderTree(tgt, tree, document, {
    onToggle: (row, checked) => {
      if (row.kind === "layer" || row.kind === "marker" || row.kind === "keepout") {
        const lid = row.kind === "marker" ? "lander" : (row.kind === "keepout" ? "hazard" : row.ref);
        LAYER_ON[lid] = checked;
        applyLayerToggle(lid, checked);
        syncLayerStripCheckbox(lid, checked);
        if (typeof drawPlan === "function") drawPlan();
      } else if (row.kind === "order") {                    // orders ride the excavation feature layer
        LAYER_ON.excavation = checked;
        applyLayerToggle("excavation", checked);
        syncLayerStripCheckbox("excavation", checked);
        if (typeof drawPlan === "function") drawPlan();
      }
      renderContentsTree();
    },
    onZoom: (row) => {
      if (row.kind === "order") { SELECTED_ORDER = row.ref; if (typeof drawPlan === "function") drawPlan(); }
      if (typeof flyToWorkArea === "function") flyToWorkArea();
      renderContentsTree();
    },
    onRemove: (row) => {
      if (row.kind === "order") {
        snapshotAuthoring(); ORDERS.splice(row.ref, 1);
        if (SELECTED_ORDER === row.ref) SELECTED_ORDER = -1;
        else if (SELECTED_ORDER > row.ref) SELECTED_ORDER -= 1;
        renderQueue();
      } else if (row.kind === "keepout") {
        KEEPOUTS.splice(row.ref, 1); renderKeepouts();
      }
    },
    onSelect: (row) => {
      if (row.kind === "order") {
        SELECTED_ORDER = row.ref;
        if (typeof drawPlan === "function") drawPlan();
        renderQueue();
      }
    },
  });
}
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
const SLOPE_SYM = { vmax: 30, classes: 0 };   // G5 (#251): slope graduated-renderer (ramp domain deg / N bands, 0=continuous)
function slopeRampText() {                     // G5: the legend tracks the operator's live symbology (not a stale "0-30")
  return `green 0° → red ${SLOPE_SYM.vmax}°` + (SLOPE_SYM.classes >= 2 ? ` · ${SLOPE_SYM.classes} classes` : " · continuous");
}

// G6 (#252): map capture / print composer -- the current globe view + a captioned legend strip, exported
// as a downloadable PNG (the ArcGIS layout-view analog). Composited via Canvas 2D so the caption + legend
// travel with the map image. Returns the data URL (also exposed for the Playwright check).
function captureMapDataURL() {
  if (!viewer || !viewer.scene) return null;
  viewer.render();                                       // force a fresh synchronous frame before reading the buffer
  const globe = viewer.scene.canvas;
  const gw = globe.width, gh = globe.height;
  if (!gw || !gh) return null;
  const capH = 26, pad = 10;
  // active GIS layers + the live slope symbology -> a one-line legend
  const active = (typeof LAYER_ON === "object")
    ? Object.keys(LAYER_ON).filter((k) => LAYER_ON[k] && ["dem", "slope", "hazard", "illumination", "incidence", "psr", "grid"].includes(k)) : [];
  const legend = active.map((k) => (k === "slope" ? `slope (${slopeRampText()})` : k)).join("  ·  ") || "base map";
  const legH = 22;
  const cv = document.createElement("canvas");
  cv.width = gw; cv.height = gh + capH + legH;
  const ctx = cv.getContext("2d");
  ctx.fillStyle = "#0a0a0c"; ctx.fillRect(0, 0, cv.width, cv.height);
  const site = (typeof CURRENT_SITE === "string" ? CURRENT_SITE : "site");
  const stamp = new Date().toISOString().slice(0, 19).replace("T", " ") + " UTC";
  ctx.fillStyle = "#e6f0ff"; ctx.font = "15px sans-serif"; ctx.textBaseline = "middle";
  ctx.fillText(`STEWIE lunar map — ${site}`, pad, capH / 2);
  ctx.fillStyle = "#9ab"; ctx.font = "12px sans-serif"; ctx.textAlign = "right";
  ctx.fillText(stamp, gw - pad, capH / 2); ctx.textAlign = "left";
  ctx.drawImage(globe, 0, capH);                         // the captured globe view
  ctx.fillStyle = "#0a0a0c"; ctx.fillRect(0, capH + gh, gw, legH);
  ctx.fillStyle = "#cdd"; ctx.font = "12px sans-serif";
  ctx.fillText("layers: " + legend, pad, capH + gh + legH / 2);
  return cv.toDataURL("image/png");
}
async function captureMap() {
  if (!viewer) { if (typeof alertMsg === "function") alertMsg("error", "map capture needs the 3-D globe (no WebGL here)"); return; }
  try {
    const data = captureMapDataURL();                    // a non-empty check (not a blank-frame detector)
    if (!data || data.length < 200) { if (typeof alertMsg === "function") alertMsg("error", "map capture produced no image"); return; }
    const a = document.createElement("a");
    a.href = data; a.download = `stewie_${(typeof CURRENT_SITE === "string" ? CURRENT_SITE : "map")}_${new Date().toISOString().slice(0, 10)}.png`;
    document.body.appendChild(a); a.click(); a.remove();
    // honesty: a capture taken mid-stream shows whatever tiles have loaded -- say so rather than imply complete
    const loading = viewer.scene && viewer.scene.globe && viewer.scene.globe.tilesLoaded === false;
    if (typeof setQ === "function") setQ("map captured → PNG downloaded" + (loading ? " (some tiles were still loading)" : ""));
  } catch (e) {
    // a cross-origin layer WITHOUT CORS taints the WebGL canvas -> toDataURL throws SecurityError. Shipped
    // layers (Trek/Esri/GIBS) are CORS-clean; this guards a future user-added non-CORS layer (#241).
    const taint = /SecurityError|tainted/i.test(String(e));
    if (typeof alertMsg === "function") alertMsg("error", taint
      ? "map capture blocked: a layer's tiles are cross-origin without CORS, so the map cannot be exported"
      : "map capture failed: " + e);
  }
}
if (qel("mapcapture")) qel("mapcapture").onclick = captureMap;
let LANDER = { name: "Nova-C", x: LANDER_P.x, y: LANDER_P.y, footprint_m: 4.6, n_legs: 6 };   // delivery lander (persisted position, #65)
// #161: a toggleable 100 m reference ring around the lander (the safe-operating-radius cue; pairs with
// the planner's return-to-lander feasibility). Persisted per-browser; default on.
const LANDER_RING_M = 100;
let LANDER_RING_ON = (localStorage.getItem("stewie_landring") !== "0");
if ($("landring")) {
  $("landring").checked = LANDER_RING_ON;
  $("landring").onchange = () => {
    LANDER_RING_ON = $("landring").checked;
    try { localStorage.setItem("stewie_landring", LANDER_RING_ON ? "1" : "0"); } catch (e) {}
    if (typeof drawPlan === "function") drawPlan();       // redraw the plan view with/without the ring
  };
}
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
      cb.onchange = () => { LAYER_ON[lid] = cb.checked; applyLayerToggle(lid, cb.checked); drawPlan();
        if (typeof renderContentsTree === "function") renderContentsTree(); };   // GIS S-2: mirror the flat strip into the tree
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
    // 3D Terrain: a client-side toggle (not a /layers raster) that drapes the chosen site's real DEM as a
    // 3D mesh on the globe (GET /dem/terrain_grid). Off by default; additive, so it can't disturb the rasters.
    const t3 = document.createElement("label");
    t3.style.cssText = "display:inline-flex;gap:3px;align-items:center;cursor:pointer";
    t3.title = "drape the work-area DEM as a 3D relief mesh on the globe";
    const cb3 = document.createElement("input"); cb3.type = "checkbox"; cb3.id = "lyr_terrain3d"; cb3.checked = !!LAYER_ON.terrain3d;
    cb3.onchange = () => { LAYER_ON.terrain3d = cb3.checked; applyLayerToggle("terrain3d", cb3.checked);
      if (typeof renderContentsTree === "function") renderContentsTree(); };
    t3.appendChild(cb3); t3.appendChild(document.createTextNode("3D Terrain"));
    panel.appendChild(t3);
    // Reconstruction twin: the COLMAP dense-cloud 3D Tiles overlay (off by default; additive).
    const rt = document.createElement("label");
    rt.style.cssText = "display:inline-flex;gap:3px;align-items:center;cursor:pointer";
    rt.title = "load the photogrammetric reconstruction (COLMAP dense cloud) as a 3D Tiles twin at the site";
    const cbr = document.createElement("input"); cbr.type = "checkbox"; cbr.id = "lyr_recon_twin"; cbr.checked = !!LAYER_ON.recon_twin;
    cbr.onchange = () => { LAYER_ON.recon_twin = cbr.checked; applyLayerToggle("recon_twin", cbr.checked);
      if (typeof renderContentsTree === "function") renderContentsTree(); };
    rt.appendChild(cbr); rt.appendChild(document.createTextNode("Reconstruction"));
    panel.appendChild(rt);
  } catch (e) { /* serverless preview keeps the defaults */ }
  applyDefaultsOnceReady();                                // #63: the other ready side
  if (typeof renderContentsTree === "function") renderContentsTree();   // GIS S-2: build the tree once layers are known
}
const GIS_RASTERS = ["slope", "hazard", "illumination", "incidence", "psr", "grid"];
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
  // G5: the slope layer carries the operator's graduated-renderer choice (ramp max + class count)
  const symQS = (key === "slope") ? `&vmax=${SLOPE_SYM.vmax}&classes=${SLOPE_SYM.classes}` : "";
  // loading feedback: the server-rendered drapes take real time (PSR's horizon sweep ~40s cold), so
  // a toggle isn't instant -- tell the operator it's rendering instead of looking dead.
  const _busy = (typeof setQ === "function");
  if (_busy) setQ("rendering " + key.toUpperCase() + " layer…" + (key === "psr" ? " (PSR cold render up to ~40s)" : ""));
  try {
    const bb = await (await fetch(`/layers/globe/${key}/bbox?` + qs)).json();
    if (!bb.ok) { console.error("layer bbox failed:", key, bb); if (_busy) setQ(key.toUpperCase() + " layer unavailable"); return; }
    // fromUrl = the supported modern-Cesium path (the constructor-with-url form is deprecated);
    // errors surface to the console instead of a silent swallow (the old catch hid failures).
    const prov = await Cesium.SingleTileImageryProvider.fromUrl(
      `/layers/globe/${key}.png?` + qs + symQS,
      { rectangle: Cesium.Rectangle.fromDegrees(bb.west, bb.south, bb.east, bb.north) });
    GLOBE_LAYERS[key] = viewer.imageryLayers.addImageryProvider(prov);
    if (LAYER_OPACITY[key]) GLOBE_LAYERS[key].alpha = LAYER_OPACITY[key] / 100;   // slider persists
    // Aaron: the reference grid must sit ON TOP of every DEM/analysis drape
    if (GLOBE_LAYERS.grid) viewer.imageryLayers.raiseToTop(GLOBE_LAYERS.grid);
    if (_busy) setQ(key.toUpperCase() + " layer ready");
  } catch (e) { console.error("globe layer failed:", key, e); alertMsg("error", `layer ${key} failed: ${e}`);
    if (_busy) setQ(key.toUpperCase() + " layer failed"); }
}
const BOOT_V = Date.now();                                 // per-pageload cache-bust for layer images
function sunQS() {
  const gc = "&color=" + encodeURIComponent((SETTINGS.gridcolor || "#39ff14").replace("#", ""));
  const st = "&site=" + encodeURIComponent(CURRENT_SITE);  // REG-01: globe drape + raster overlays follow the chosen site
  if (qel("sunauto") && qel("sunauto").checked)            // AUTO: mission time -> real solar geometry server-side
    return `mission_t_s=${Math.round(parseFloat(qel("suntime").value) * 86400)}&b=${BOOT_V}` + gc + st;
  return `sun_el=${qel("sunel").value}&sun_az=${qel("sunaz").value}&b=${BOOT_V}` + gc + st;
}
// REG-01: (re)draw the SELECTED site's globe footprint + re-anchor HAWORTH_RECT (the cursor-meters gate +
// inset georef). Re-runnable: selecting a new site removes the old footprint, fetches that site's georef,
// and (on reload) re-places the globe drape via refetchSun. The HAWORTH_* names are kept (internal) but
// now hold whatever site CURRENT_SITE points at.
function loadSiteFootprint(reload) {
  if (!viewer) return;
  HAWORTH_ENTITIES.forEach((e) => viewer.entities.remove(e)); HAWORTH_ENTITIES.length = 0;
  // GIS-WA1: this outline is the WHOLE DEM TILE (e.g. Haworth ~10 km), not the work area. The true
  // operational work area is the small [0, WORK_AREA_M]^2 patch drawn by drawWorkAreaRect() below.
  const label = (CURRENT_SITE || "site").toUpperCase().replace(/_/g, " ") + " DEM TILE";
  fetch("/dem/georef?site=" + encodeURIComponent(CURRENT_SITE)).then((r) => r.json()).then((g) => {
    if (!g.ok || !viewer) return;
    const ll = []; g.corners.forEach((p) => { ll.push(p.lon, p.lat); });
    HAWORTH_CENTER = g.center;
    WORK_AREA_ANCHOR = (g.anchor_xy && g.anchor_xy.length === 2) ? g.anchor_xy : [0, 0];   // #audit-2b: the true work-area origin
    const lats = g.corners.map((p) => p.lat), lons = g.corners.map((p) => p.lon);
    HAWORTH_RECT = Cesium.Rectangle.fromDegrees(Math.min(...lons), Math.min(...lats),
                                                Math.max(...lons), Math.max(...lats));
    applyDefaultsOnceReady();                              // #63: fires once BOTH sides are ready
    HAWORTH_ENTITIES.push(viewer.entities.add({
      name: label,
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArray(ll, ellipsoid),
        material: Cesium.Color.fromCssColorString("#e8273f").withAlpha(0.04),
        outline: true, outlineColor: Cesium.Color.fromCssColorString("#e8273f"),
      },
    }));
    HAWORTH_ENTITIES.push(viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(g.center.lon, g.center.lat, 0, ellipsoid),
      label: { text: label, font: "11px Orbitron, sans-serif",
               fillColor: Cesium.Color.fromCssColorString("#e8273f"),
               pixelOffset: new Cesium.Cartesian2(0, -18), showBackground: true,
               backgroundColor: Cesium.Color.fromCssColorString("#0a0a0cdd") },
    }));
    drawWorkAreaRect();                                    // GIS-WA1: the TRUE operational patch, inside the tile
    setMoonOverlaysVisible(sel.value === "moon");
    if (reload && typeof refetchSun === "function") refetchSun();   // re-place the globe drape at the new footprint
    if (LAYER_ON.terrain3d) loadTerrain3D(true);          // re-drape the 3D terrain mesh at the new site
  }).catch(() => {});
}
// GIS-WA1: draw the TRUE operational work area = the [0, WORK_AREA_M]^2 order frame, as a small bright-cyan
// rectangle ON the globe so "work area" means the patch IPEx actually works (the big red outline is the
// whole DEM tile). The 4 order-frame corners -> selenographic lat/lon via /dem/site_lonlat (the exact
// inverse the cursor readout uses), so the rectangle is georeferenced, not an approximation.
function drawWorkAreaRect() {
  if (!viewer) return;
  const site = encodeURIComponent(CURRENT_SITE), W = WORK_AREA_M;
  // #audit-2b: draw the rect at the work area's TRUE anchor origin (tile-metres, from /dem/georef), where
  // the inset + planner actually work -- NOT the tile's (0,0) corner (which sat ~8 km away, "top-left").
  const [ox, oy] = (WORK_AREA_ANCHOR && WORK_AREA_ANCHOR.length === 2) ? WORK_AREA_ANCHOR : [0, 0];
  const corners = [[ox, oy], [ox + W, oy], [ox + W, oy + W], [ox, oy + W]];
  Promise.all(corners.map(([x, y]) =>
    fetch(`/dem/site_lonlat?x=${x}&y=${y}&site=${site}`).then((r) => r.json()).catch(() => null)))
    .then((cs) => {
      if (!viewer || !cs.every((c) => c && c.ok)) return;
      const ll = []; cs.forEach((c) => ll.push(c.lon, c.lat));
      const wlons = cs.map((c) => c.lon), wlats = cs.map((c) => c.lat);
      // the inset image IS this work area, so the overview-locator maps the camera view over THIS rect
      // (not the full tile). bbox of the 4 corners -- the polar-stereo rotation over 640 m is negligible.
      WORK_AREA_RECT = Cesium.Rectangle.fromDegrees(Math.min(...wlons), Math.min(...wlats),
                                                    Math.max(...wlons), Math.max(...wlats));
      HAWORTH_ENTITIES.push(viewer.entities.add({
        name: "WORK AREA",
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArray(ll, ellipsoid),
          material: Cesium.Color.fromCssColorString("#38bdf8").withAlpha(0.12),
          outline: true, outlineColor: Cesium.Color.fromCssColorString("#38bdf8"),
        },
      }));
      const clon = cs.reduce((s, c) => s + c.lon, 0) / cs.length;
      const clat = cs.reduce((s, c) => s + c.lat, 0) / cs.length;
      HAWORTH_ENTITIES.push(viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(clon, clat, 0, ellipsoid),
        label: { text: `WORK AREA (${W} m)`, font: "10px Orbitron, sans-serif",
                 fillColor: Cesium.Color.fromCssColorString("#38bdf8"),
                 pixelOffset: new Cesium.Cartesian2(0, 10), showBackground: true,
                 backgroundColor: Cesium.Color.fromCssColorString("#0a0a0cdd") },
      }));
      try { viewer.scene.requestRender(); } catch (e) {}
    }).catch(() => {});
}
// 3D TERRAIN LAYER: drape the chosen site's REAL DEM (GET /dem/terrain_grid -> georeferenced n*n height
// grid) as a triangulated mesh primitive on the globe, so the work-area relief is a layer ON the Cesium
// map (not just a separate Three.js view). Heights are the real DEM elevations [m] above the lunar datum;
// nodes are placed by their selenographic lon/lat on the shared `ellipsoid`, so the mesh co-locates with
// the WORK AREA footprint. Per-vertex graphite->light elevation ramp. Toggleable + re-draped on site change.
let TERRAIN3D = null;
function loadTerrain3D(on) {
  if (!viewer) return;
  if (TERRAIN3D) { try { viewer.scene.primitives.remove(TERRAIN3D); } catch (e) {} TERRAIN3D = null; }
  if (!on) { try { viewer.scene.requestRender(); } catch (e) {} return; }
  const site = CURRENT_SITE || "haworth";
  fetch("/dem/terrain_grid?site=" + encodeURIComponent(site) + "&n=64").then((r) => r.json()).then((g) => {
    if (!g || !g.ok || !viewer || !g.z || !g.z.length) return;
    const n = g.n, lat = g.lat, lon = g.lon, z = g.z, N = n * n;
    const zmin = g.z_min, zspan = Math.max(1e-6, g.z_max - g.z_min);
    const coords = new Array(N * 3);
    // anchor the base to the globe surface: g.z are ABSOLUTE datum elevations (mean ~+1 km), so plotting
    // them as height-above-ellipsoid floated the whole sheet ~1 km above the drape. Subtract z_min so the
    // lowest point sits on the draped surface and the real relief (z - z_min) rises from there.
    for (let k = 0; k < N; k++) { coords[k * 3] = lon[k]; coords[k * 3 + 1] = lat[k]; coords[k * 3 + 2] = z[k] - zmin; }
    const carts = Cesium.Cartesian3.fromDegreesArrayHeights(coords, ellipsoid);
    const pos = new Float64Array(N * 3), col = new Uint8Array(N * 4);
    for (let k = 0; k < N; k++) {
      pos[k * 3] = carts[k].x; pos[k * 3 + 1] = carts[k].y; pos[k * 3 + 2] = carts[k].z;
      const t = (z[k] - zmin) / zspan, v = Math.round(45 + 175 * t);   // graphite -> light grey ramp
      col[k * 4] = v; col[k * 4 + 1] = v; col[k * 4 + 2] = Math.round(v * 0.95); col[k * 4 + 3] = 230;
    }
    const idx = [];                                       // triangulate the grid (k = j*n + i; i=East col, j=North row)
    for (let j = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++) {
      const a = j * n + i, b = a + 1, c = a + n, d = c + 1;
      idx.push(a, b, c, b, d, c);
    }
    const geom = new Cesium.Geometry({
      attributes: {
        position: new Cesium.GeometryAttribute({ componentDatatype: Cesium.ComponentDatatype.DOUBLE, componentsPerAttribute: 3, values: pos }),
        color: new Cesium.GeometryAttribute({ componentDatatype: Cesium.ComponentDatatype.UNSIGNED_BYTE, componentsPerAttribute: 4, normalize: true, values: col }),
      },
      indices: new Uint32Array(idx),
      primitiveType: Cesium.PrimitiveType.TRIANGLES,
      boundingSphere: Cesium.BoundingSphere.fromVertices(Array.from(pos)),
    });
    const prim = new Cesium.Primitive({
      geometryInstances: new Cesium.GeometryInstance({ geometry: geom }),
      appearance: new Cesium.PerInstanceColorAppearance({ flat: true, translucent: true }),
      asynchronous: false,
    });
    TERRAIN3D = viewer.scene.primitives.add(prim);
    try { viewer.scene.requestRender(); } catch (e) {}
    if (typeof flyToWorkArea === "function") flyToWorkArea();   // toggles give feedback: frame the relief
  }).catch(() => {});
}
// RECONSTRUCTION TWIN: load the COLMAP dense cloud as a Cesium 3D Tiles point cloud (GET
// /tiles/twin/tileset.json, packed + georeferenced by scripts/colmap/ply_to_3dtiles.py). It is placed at
// the work-area site, so toggling on frames it up close (a ~5 m patch -- the work-area fly-to is too far).
// Additive + off by default; a no-op if no tileset is published on this deployment.
let RECON_TWIN = null;
function loadReconTwin(on) {
  if (!viewer || !Cesium.Cesium3DTileset) return;
  if (RECON_TWIN) { try { viewer.scene.primitives.remove(RECON_TWIN); } catch (e) {} RECON_TWIN = null; }
  if (!on) { try { viewer.scene.requestRender(); } catch (e) {} return; }
  Cesium.Cesium3DTileset.fromUrl("/tiles/twin/tileset.json").then((ts) => {
    if (!viewer) return;
    RECON_TWIN = viewer.scene.primitives.add(ts);
    try { ts.pointCloudShading.attenuation = true; ts.pointCloudShading.maximumAttenuation = 5; } catch (e) {}
    try {                                                  // frame the patch (setView: flyTo tweens don't progress here)
      const bs = ts.boundingSphere;
      viewer.camera.lookAt(bs.center, new Cesium.HeadingPitchRange(0.0, Cesium.Math.toRadians(-35),
                                                                   Math.max(bs.radius * 4.0, 15.0)));
    } catch (e) {}
    try { viewer.scene.requestRender(); } catch (e) {}
  }).catch(() => { /* no tileset published on this deployment -> no-op */ });
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
  if (id === "terrain3d") { loadTerrain3D(on); return; }   // the 3D DEM mesh on the globe (additive layer)
  if (id === "recon_twin") { loadReconTwin(on); return; }  // the COLMAP dense-cloud 3D Tiles twin
  if (id === "dem") {
    const wa = qel("workarea"); if (wa) wa.style.display = on ? "" : "none";
    globeLayer("dem", "", on);                               // the GLOBE drape obeys the checkbox too
    if (on) flyToWorkArea();
  }
  if (id === "imagery" && viewer && viewer.imageryLayers && viewer.imageryLayers.length) viewer.imageryLayers.get(0).show = on;
  if (id === "grid") drawGraticule();                      // the global graticule follows the toggle
  if (GIS_RASTERS.includes(id)) {
    renderLegend();
    // G5 (#251): the slope graduated-renderer choice flows to BOTH the PIP overlay and the globe drape,
    // so the two views never disagree on the color->value mapping.
    const symQS = (id === "slope") ? `&vmax=${SLOPE_SYM.vmax}&classes=${SLOPE_SYM.classes}` : "";
    const im = qel("ovl_" + id);
    if (im) {
      if (on) { im.src = `/layers/raster/${id}.png?` + sunQS() + symQS; im.style.display = "block"; }
      else { im.style.display = "none"; }
    }
    globeLayer(id, `/layers/raster/${id}.png?` + sunQS(), on);   // AND on the big map (adds its own symQS)
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
    slope: { name: "Slope", text: slopeRampText(), sw: "#7bd07b→#ff5544" },   // G5: live symbology, not stale "0-30"
    hazard: { name: "Hazard / no-go", text: LEGEND.hazard.text, sw: "#e8273f" },
    illumination: { name: "Shadow (mission-time sun)", text: LEGEND.illumination.text, sw: "#5577dd" },
    incidence: { name: "Sun incidence (grazing)", text: (LEGEND.incidence || {}).text || "grazing-angle solar incidence from the DEM", sw: "#ffc828" },
    psr: { name: "Permanently shadowed regions", text: LEGEND.psr.text, sw: "#9966dd" },
    grid: { name: "Site grid", text: "site-frame meters: 100 m minor / 500 m major (labels: inset axes + cursor readout)", sw: "#39ff14", colorpick: true },
  };
  BASEMAP_STACK.forEach((bm, bi) => {                      // #51: basemap cards (stack + opacity)
    const L = BODIES[sel.value].layers[bm.idx]; if (!L) return;
    const card = document.createElement("div");
    card.style.cssText = "border:1px solid var(--line);border-radius:6px;padding:6px 8px;margin:4px 0;font-size:10px;line-height:1.45";
    const head = document.createElement("div"); head.style.cssText = "display:flex;align-items:center;gap:6px";
    const ttl = document.createElement("b"); ttl.textContent = "" + L.name; head.appendChild(ttl);
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
    if (k === "slope") {                                   // G5 (#251): graduated-renderer controls
      const sym = document.createElement("div");
      sym.style.cssText = "display:flex;align-items:center;gap:4px;margin-top:4px;flex-wrap:wrap";
      const vlab = document.createElement("label"); vlab.textContent = "max°"; vlab.style.opacity = ".75";
      const v = document.createElement("input");
      v.type = "number"; v.min = "1"; v.max = "90"; v.step = "1"; v.value = String(SLOPE_SYM.vmax);
      v.title = "slope ramp domain: the angle that maps to the steepest (red) end";
      v.style.cssText = "width:48px;background:var(--panel);color:var(--txt);border:1px solid var(--line);border-radius:4px;font-size:10px";
      const clab = document.createElement("label"); clab.textContent = "classes"; clab.style.opacity = ".75";
      const cls = document.createElement("select");
      cls.style.cssText = "background:var(--panel);color:var(--txt);border:1px solid var(--line);border-radius:4px;font-size:10px";
      [["0", "continuous"], ["3", "3"], ["5", "5"], ["7", "7"], ["10", "10"]].forEach(([val, txt]) => {
        const o = document.createElement("option"); o.value = val; o.textContent = txt;
        if (+val === SLOPE_SYM.classes) o.selected = true; cls.appendChild(o);
      });
      const apply = () => {
        SLOPE_SYM.vmax = Math.max(1, Math.min(90, Math.round(+v.value || 30)));
        SLOPE_SYM.classes = +cls.value;
        applyLayerToggle("slope", true);                   // re-render BOTH the drape + the PIP overlay
        renderLegend();                                    // G5 (#251): the legend tracks the new symbology
        renderWorkbench();                                 // refresh the card's legend text
      };
      v.onchange = apply; cls.onchange = apply;
      sym.append(vlab, v, clab, cls); card.appendChild(sym);
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
  if (LAYER_ON.slope) rows.push(`<span style="color:#7bd07b">■</span>→<span style="color:#ff5544">■</span> slope: ${slopeRampText()}`);
  if (LAYER_ON.hazard) rows.push(`<span style="color:#e8273f">■</span> hazard: no-go &gt;${LEGEND.hazard.nogo_deg}° (tested) · <span style="color:#e0b300">■</span> penalty &gt;${LEGEND.hazard.penalty_deg}° · rocks &gt;${(LEGEND.hazard.obstacle_m*100).toFixed(1)} cm`);
  if (LAYER_ON.illumination) rows.push(`<span style="color:#5577dd">■</span> ${LEGEND.illumination.text}`);
  if (LAYER_ON.psr) rows.push(`<span style="color:#9966dd">■</span> ${LEGEND.psr.text}`);
  box.innerHTML = rows.join("<br>");
  renderWorkbench();                                       // the cards carry the legends now
}
function refetchSun() { GIS_RASTERS.forEach((k) => { if (LAYER_ON[k]) applyLayerToggle(k, true); }); renderLegend();
  if (typeof TD3D_ON !== "undefined" && TD3D_ON && typeof apply3DSun === "function") apply3DSun(); }  // #181: track the sun in the 3D view too
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
// FS-24: the plan-canvas extent/transform/glyph math lives in plan_geom.js (pure). These thin aliases
// resolve the cockpit's globals (ORDERS/KEEPOUTS/_placeXY/koBounds) and pass them in; callers unchanged.
// GIS-WA1: the canonical WORK-AREA operational extent [0, WORK_AREA_M]^2 (site metres). ONE constant so
// the authoring backdrop image (/dem/workarea.png?window_m=), the plan-canvas drape box, and the globe
// work-area rectangle all agree -- the precision fix for "what should the work area be".
const WORK_AREA_M = 640;
function _planExtent() { return window.STEWIE_PLAN_GEOM.planExtent(ORDERS, KEEPOUTS, _placeXY, koBounds, window.STEWIE_FOOTPRINT_GEOM.footprintBounds, WORK_AREA_M); }
const _planXform = window.STEWIE_PLAN_GEOM.planXform;
let LAST_ROUTES = [];                                      // item 3: routes from the last /plan response, drawn on the 2D canvas
// #29: the branded feature glyphs -- ONE drawing function so map, queue, and legend agree (plan_geom.js).
const drawGlyph = window.STEWIE_PLAN_GEOM.drawGlyph;

function drawPlan() {
  const cv = qel("plancanvas"); if (!cv) return;
  const ctx = cv.getContext("2d"), W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H); ctx.fillStyle = "#05060c"; ctx.fillRect(0, 0, W, H);
  const ext = _planExtent(), tf = _planXform(cv, ext), X = tf.X, Y = tf.Y, s = tf.s;
  // #48 (Aaron): TERRAIN UNDER THE FEATURES -- the clean work-area hillshade (site frame [0, WORK_AREA_M] m)
  // drawn beneath the vectors so authoring has real, correctly-registered context (GIS-WA1).
  const wai = qel("workareaimg");
  if (LAYER_ON.dem !== false && wai && wai.complete && wai.naturalWidth) {
    const x0 = X(0), y0 = Y(WORK_AREA_M), x1 = X(WORK_AREA_M), y1 = Y(0);  // site Y up; canvas Y down
    ctx.save(); ctx.globalAlpha = 0.55;
    ctx.drawImage(wai, x0, y0, x1 - x0, y1 - y0);
    ctx.restore();
  }
  if (LAYER_ON.hazard) KEEPOUTS.forEach((k) => {           // hazard layer: keep-outs = red discs / boxes (#178)
    ctx.fillStyle = "rgba(224,86,75,.22)"; ctx.strokeStyle = "#e0564b"; ctx.lineWidth = 1;
    fillKeepout(ctx, k, X, Y, s);
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
  if (LAYER_ON.excavation) ORDERS.forEach((o, i) => {      // excavation layer: cut (blue) / fill (orange)
    if (o.kind === "goto") return;                         // S-3 waypoints are drawn as the path, not a footprint
    const half = Math.max(2, Math.sqrt(o.footprint_m2) / 2 * s);
    ctx.fillStyle = o.kind === "cut" ? "rgba(79,156,255,.30)" : "rgba(224,123,57,.30)";
    ctx.strokeStyle = o.kind === "cut" ? "#4f9cff" : "#e07b39"; ctx.lineWidth = 1;
    // GIS S-3: draw the REAL typed footprint (oriented rect / corridor / circle / polygon); an order
    // with no shape falls back to its legacy axis-aligned square inside footprint_geom.drawFootprint.
    window.STEWIE_FOOTPRINT_GEOM.drawFootprint(ctx, o, X, Y);
    if (i === SELECTED_ORDER) {                            // S-2: selection highlight (brand red AABB)
      const b = window.STEWIE_FOOTPRINT_GEOM.footprintBounds(o);
      const bx0 = X(b.x0), by1 = Y(b.y0), bx1 = X(b.x1), by0 = Y(b.y1);   // site Y up, canvas Y down
      ctx.strokeStyle = "#e8273f"; ctx.lineWidth = 2;
      ctx.strokeRect(Math.min(bx0, bx1) - 3, Math.min(by0, by1) - 3,
                     Math.abs(bx1 - bx0) + 6, Math.abs(by1 - by0) + 6);
    }
    drawGlyph(ctx, o.kind, X(o.x), Y(o.y) - half - 6, 5);  // the kind glyph above the footprint
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
  if (LANDER_RING_ON) {                                    // #161: toggleable 100 m ring around the lander
    const lx = X(LANDER.x), ly = Y(LANDER.y), rr = LANDER_RING_M * s;
    ctx.save();
    ctx.strokeStyle = "rgba(255,209,102,.7)"; ctx.lineWidth = 1; ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.arc(lx, ly, rr, 0, 2 * Math.PI); ctx.stroke();
    ctx.setLineDash([]); ctx.fillStyle = "rgba(255,209,102,.85)"; ctx.font = "8px system-ui"; ctx.textAlign = "left";
    ctx.fillText(LANDER_RING_M + " m", lx + rr * 0.7071 + 2, ly - rr * 0.7071);   // label on the NE arc
    ctx.restore();
  }
  if (_placeXY) {                                          // the click-to-place crosshair
    ctx.strokeStyle = "#4f9cff"; ctx.lineWidth = 1; const cx = X(_placeXY.x), cy = Y(_placeXY.y);
    ctx.beginPath(); ctx.arc(cx, cy, 5, 0, 7); ctx.moveTo(cx - 8, cy); ctx.lineTo(cx + 8, cy);
    ctx.moveTo(cx, cy - 8); ctx.lineTo(cx, cy + 8); ctx.stroke();
  }
  syncPlanToGlobe();                                        // #audit-7: mirror the placed plan onto the 3D globe
}

// #audit-7 (#257): the placed plan (orders/keep-outs/routes) drew ONLY on the 2D plan canvas, so the main
// globe looked empty -- Aaron: "I plotted waypoints... doesn't show on the actual main view." This mirrors
// them onto the Cesium globe: each order-frame (x,y) -> tile-metres (WORK_AREA_ANCHOR + (x,y)) -> selenographic
// lon/lat via /dem/site_lonlat (the SAME anchor offset the work-area rect uses, so markers land in the rect).
// Debounced so a drag / queue edit coalesces into one batched conversion; entities live in their OWN layer
// (PLAN_GLOBE_ENTS), separate from the edit-mode EDIT_PINS.
let PLAN_GLOBE_ENTS = [];
let _syncPlanTimer = 0;
function syncPlanToGlobe() {
  if (_syncPlanTimer) clearTimeout(_syncPlanTimer);
  _syncPlanTimer = setTimeout(_syncPlanToGlobeNow, 250);
}
async function _syncPlanToGlobeNow() {
  _syncPlanTimer = 0;
  if (!viewer) return;
  PLAN_GLOBE_ENTS.forEach((e) => { try { viewer.entities.remove(e); } catch (_e) {} });
  PLAN_GLOBE_ENTS = [];
  const [ox, oy] = (WORK_AREA_ANCHOR && WORK_AREA_ANCHOR.length === 2) ? WORK_AREA_ANCHOR : [0, 0];
  const site = encodeURIComponent(CURRENT_SITE);
  const showOrders = LAYER_ON.excavation !== false;        // respects the Contents-tree Operations toggle
  const pts = [];                                          // every (x,y) tile-metre needing a lon/lat
  if (showOrders) ORDERS.forEach((o, i) => pts.push({ t: "order", i, x: ox + (+o.x || 0), y: oy + (+o.y || 0) }));
  KEEPOUTS.forEach((k, i) => {
    if (typeof k.x === "number") pts.push({ t: "koc", i, x: ox + k.x, y: oy + k.y, r: +k.r || 5 });
    else if (Array.isArray(k.points)) k.points.forEach((p, j) => pts.push({ t: "kop", i, j, x: ox + (+p[0]), y: oy + (+p[1]) }));
  });
  if (showOrders) LAST_ROUTES.forEach((rt, i) => (rt.waypoints || rt.points || []).forEach((w, j) =>
    pts.push({ t: "route", i, j, x: ox + (+w[0]), y: oy + (+w[1]) })));
  if (!pts.length) { try { viewer.scene.requestRender(); } catch (_e) {} return; }
  const res = await Promise.all(pts.map((p) =>
    fetch(`/dem/site_lonlat?x=${p.x}&y=${p.y}&site=${site}`).then((r) => r.json())
      .then((d) => ({ p, d })).catch(() => null)));
  if (!viewer) return;
  const polys = {}, routes = {};
  res.forEach((rr) => {
    if (!rr || !rr.d || !rr.d.ok) return;
    const { p, d } = rr, red = Cesium.Color.fromCssColorString("#e0564b");
    if (p.t === "order") {
      const o = ORDERS[p.i] || {};
      const col = o.kind === "goto" ? "#38bdf8" : (o.kind === "fill" ? "#fbbf24" : "#22d3ee");
      PLAN_GLOBE_ENTS.push(viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(d.lon, d.lat, 0, ellipsoid),
        point: { pixelSize: 6, color: Cesium.Color.fromCssColorString(col), outlineColor: Cesium.Color.BLACK, outlineWidth: 1 },
        label: { text: `${o.kind || "order"} ${o.action || ""}`.trim(), font: "10px Orbitron, sans-serif",
                 fillColor: Cesium.Color.fromCssColorString("#c7d2e3"), pixelOffset: new Cesium.Cartesian2(0, -13),
                 showBackground: true, backgroundColor: Cesium.Color.fromCssColorString("#0a0a0cbb") },
      }));
    } else if (p.t === "koc") {
      PLAN_GLOBE_ENTS.push(viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(d.lon, d.lat, 0, ellipsoid),
        ellipse: { semiMajorAxis: p.r, semiMinorAxis: p.r, height: 0, material: red.withAlpha(0.18),
                   outline: true, outlineColor: red.withAlpha(0.9) },
      }));
    } else if (p.t === "kop") {
      (polys[p.i] = polys[p.i] || []).push([d.lon, d.lat]);
    } else if (p.t === "route") {
      (routes[p.i] = routes[p.i] || []).push([d.lon, d.lat]);
    }
  });
  Object.values(polys).forEach((ll) => {
    if (ll.length < 3) return;
    const red = Cesium.Color.fromCssColorString("#e0564b"), flat = [];
    ll.forEach(([lo, la]) => flat.push(lo, la));
    PLAN_GLOBE_ENTS.push(viewer.entities.add({
      polygon: { hierarchy: Cesium.Cartesian3.fromDegreesArray(flat, ellipsoid),
                 material: red.withAlpha(0.18), outline: true, outlineColor: red.withAlpha(0.9) } }));
  });
  Object.values(routes).forEach((ll) => {
    if (ll.length < 2) return;
    const flat = [];
    ll.forEach(([lo, la]) => flat.push(lo, la));
    PLAN_GLOBE_ENTS.push(viewer.entities.add({
      polyline: { positions: Cesium.Cartesian3.fromDegreesArray(flat, ellipsoid), width: 2,
                  material: Cesium.Color.fromCssColorString("#38bdf8").withAlpha(0.85) } }));
  });
  try { viewer.scene.requestRender(); } catch (_e) {}
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
  // G4 (#250): circle keep-outs ({x,y,r}) are repositionable too (orders already were). Grab by centroid
  // proximity; the closest grabbable feature wins. (Polygon keep-outs + vertex-edit are a later slice.)
  let bestKo = -1, bdk = tol;
  KEEPOUTS.forEach((k, i) => {
    if (typeof k.x === "number" && typeof k.y === "number") {
      const d = Math.hypot(k.x - wx, k.y - wy);
      if (d < bdk) { bdk = d; bestKo = i; }
    }
  });
  if (bestKo >= 0 && bdk <= bd) {                          // a keep-out is the nearest grabbable feature
    DRAG = { ko: bestKo, moved: false };
    qel("plancanvas").setPointerCapture(e.pointerId);
    return;
  }
  if (best >= 0) {
    DRAG = { i: best, moved: false };
    SELECTED_ORDER = best;
    qel("plancanvas").setPointerCapture(e.pointerId);
  }
});
qel("plancanvas").addEventListener("pointermove", (e) => {
  if (!DRAG) return;
  const { wx, wy } = _canvasToWorld(e);
  if (DRAG.ko != null) {                                   // G4: move a circle keep-out's center
    const k = KEEPOUTS[DRAG.ko];
    k.x = Math.round(wx * 10) / 10; k.y = Math.round(wy * 10) / 10;
    DRAG.moved = true;
    drawPlan();
    return;
  }
  const o = ORDERS[DRAG.i];
  o.x = Math.round(wx * 10) / 10; o.y = Math.round(wy * 10) / 10;
  DRAG.moved = true;
  drawPlan();
});
qel("plancanvas").addEventListener("pointerup", (e) => {
  if (DRAG && DRAG.moved) {
    if (DRAG.ko != null) {                                 // G4: commit the keep-out move (persists + redraws)
      const k = KEEPOUTS[DRAG.ko];
      setQ(`moved keep-out to (${k.x}, ${k.y})`);
      renderKeepouts();
    } else {
      const o = ORDERS[DRAG.i];
      setQ(`moved ${o.kind} "${o.action}" to (${o.x}, ${o.y})`);
      renderQueue();
    }
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
// GIS S-3: read the authoring form's footprint-shape control into a CP-05 shape dict (or null for the
// legacy "square (area)" default). Pure builder lives in footprint_geom.js; this thin reader pulls the
// DOM values, mirroring the FS-24 pattern. Returns {shape, area} -- area is the shape's planar area so
// the order's footprint_m2 stays consistent with the typed geometry the planner rasterizes.
const _FPG = window.STEWIE_FOOTPRINT_GEOM;
function _authoredFootprint() {
  const kind = qel("qshape") ? qel("qshape").value : "square";
  let vals;
  if (kind === "rectangle" || kind === "corridor") {
    const w = +qel("qsw").value, l = +qel("qsh").value, theta = +qel("qstheta").value;
    vals = (kind === "rectangle") ? { w, h: l, theta_deg: theta }
                                  : { length: w, width: l, theta_deg: theta };
  } else if (kind === "polygon") {
    vals = { vertices: _FPG.parsePolyVerts(qel("qspoly") ? qel("qspoly").value : "") };
  }
  const shape = _FPG.shapeFromForm(kind, vals);
  return { shape, area: shape ? _FPG.shapeArea(shape) : NaN };
}
qel("qadd").onclick = () => {
  const fp = _authoredFootprint();
  const order = {
    action: qel("qlabel").value || (qel("qkind").value === "cut" ? "Cut" : "Fill"),
    kind: qel("qkind").value, x: +qel("qx").value, y: +qel("qy").value,
    // a typed shape supplies the area (CP-05) and carries orientation; otherwise the legacy scalar.
    footprint_m2: fp.shape ? +fp.area.toFixed(3) : +qel("qfoot").value,
    depth_m: +qel("qdepth").value,
  };
  if (fp.shape) order.shape = fp.shape;                    // round-trips to mission_from_dict -> planner
  addOrder(order);
};
// toggle the shape sub-rows so only the chosen shape's inputs show (square = legacy area path)
if (qel("qshape")) {
  const _syncShapeRows = () => {
    const k = qel("qshape").value;
    const rect = qel("qshape-rect"), poly = qel("qshape-poly"), area = qel("qfoot");
    if (rect) rect.style.display = (k === "rectangle" || k === "corridor") ? "" : "none";
    if (poly) poly.style.display = (k === "polygon") ? "" : "none";
    if (area && area.parentElement) area.parentElement.style.opacity = (k === "square") ? "1" : ".45";
  };
  qel("qshape").addEventListener("change", _syncShapeRows);
  _syncShapeRows();
}
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
    // structure-first: remember the structure itself (name + site coords), not just its lowered orders,
    // so the Site-plan analyzer can reason across the whole base. Same name+x,y the server expanded.
    PLACED_STRUCTURES.push({ name: qel("struct").value, x: +qel("qx").value, y: +qel("qy").value });
    if (typeof renderSitePlan === "function") renderSitePlan(null);
    setQ(`added ${j.orders.length} order(s) from ${qel("struct").value}`);
  } catch (e) { setQ("structure failed — run server.py (" + e + ")"); }
};
// structure-first VALIDATE-AND-ADVISE: analyze the placed structures AS A BASE -- base-wide mass economy,
// inter-structure clearances, build order, and advisories (POST /siteplan/analyze -> leap.siteplan). The
// operator keeps placement authority; this only checks + advises. ``rpt`` null = just refresh the count.
function renderSitePlan(rpt) {
  const cnt = qel("qsitecount");
  if (cnt) cnt.textContent = PLACED_STRUCTURES.length ? `${PLACED_STRUCTURES.length} structure(s) placed` : "";
  const out = qel("qsiteout"); if (!out || rpt === null) return;
  if (rpt.error) { out.textContent = "site-plan error: " + rpt.error; return; }
  const fmt = (n) => Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
  const net = rpt.net_mass_kg;
  const netTxt = Math.abs(net) < 1 ? "mass balanced"
    : net > 0 ? `+${fmt(net)} kg surplus` : `${fmt(-net)} kg deficit`;
  const overlaps = (rpt.clearances || []).filter((c) => c.overlap).length;
  let html = `<div style="color:var(--muted)">cut ${fmt(rpt.total_cut_mass_kg)} kg · fill ${fmt(rpt.total_fill_mass_kg)} kg · <b style="color:${Math.abs(net) < 1 ? "var(--txt)" : "var(--accent)"}">${netTxt}</b></div>`;
  html += `<div style="color:var(--muted)">haul work ${fmt(rpt.total_haul_work_kg_m)} kg·m · ${overlaps ? `<b style="color:var(--accent)">${overlaps} overlap(s)</b>` : "footprints clear"}</div>`;
  if (rpt.advisories && rpt.advisories.length) {
    html += "<ul style='margin:4px 0 0;padding-left:16px;color:var(--txt)'>"
      + rpt.advisories.map((a) => `<li>${a}</li>`).join("") + "</ul>";
  }
  out.innerHTML = html;
}
async function analyzeSitePlan() {
  const out = qel("qsiteout"); if (!out) return;
  if (!PLACED_STRUCTURES.length) { out.textContent = "place one or more structures first (+ Structure @ x,y)"; return; }
  out.textContent = "analyzing the site plan…";
  try {
    const res = await fetch("/siteplan/analyze", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ placements: PLACED_STRUCTURES, min_gap_m: 2 }) });
    const j = await res.json();
    renderSitePlan(j.ok ? j : { error: j.error || ("HTTP " + res.status) });
  } catch (e) { out.textContent = "site-plan failed — run server.py (" + e + ")"; }
}
{ const b = qel("qsiteplan"); if (b) b.onclick = analyzeSitePlan; }

// GI-03 GIS interchange: export the current plan to GeoJSON / an offline mission package, import a
// FeatureCollection back to local order-frame features, and query a loaded FeatureCollection by layer.
// Routes: GET /export/geojson, GET /gis/mission-package, POST /gis/import, POST /gis/query.
let LAST_FC = null;
function _gisMission() {
  return { name: "gis export", body: sel.value, charger: [0, 0], orders: ORDERS, keepouts: KEEPOUTS };
}
function _gisDownload(name, text, type) {
  const blob = new Blob([text], { type: type || "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}
async function gisExportGeojson() {
  const out = qel("gisout"); out.textContent = "exporting…";
  const q = `mission=${encodeURIComponent(JSON.stringify(_gisMission()))}&site=${encodeURIComponent(CURRENT_SITE)}`;
  try {
    const r = await fetch(`/export/geojson?${q}`, { headers: apiHeaders() });
    const b = await r.json();
    if (!r.ok) { out.textContent = `export failed: ${b.error || ("HTTP " + r.status)}`; return; }
    LAST_FC = b; _gisDownload("plan.geojson", JSON.stringify(b, null, 1), "application/geo+json");
    out.textContent = `exported ${b.features.length} feature(s) → plan.geojson`;
  } catch (e) { out.textContent = "export failed — run server.py (" + e + ")"; }
}
async function gisExportPackage() {
  const out = qel("gisout"); out.textContent = "packaging…";
  const q = `mission=${encodeURIComponent(JSON.stringify(_gisMission()))}&site=${encodeURIComponent(CURRENT_SITE)}`;
  try {
    const r = await fetch(`/gis/mission-package?${q}`, { headers: apiHeaders() });
    const b = await r.json();
    if (!r.ok) { out.textContent = `package failed: ${b.error || ("HTTP " + r.status)}`; return; }
    _gisDownload("mission_package.json", JSON.stringify(b, null, 1));
    out.textContent = `package: ${b.manifest.feature_count} feature(s), body ${b.manifest.body} → mission_package.json`;
  } catch (e) { out.textContent = "package failed — run server.py (" + e + ")"; }
}
async function gisImport() {
  const out = qel("gisout"); let fc;
  try { fc = JSON.parse(qel("gisin").value); } catch (e) { out.textContent = "paste a valid GeoJSON FeatureCollection first"; return; }
  try {
    const r = await fetch("/gis/import", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ featurecollection: fc, site: CURRENT_SITE }) });
    const b = await r.json();
    if (!r.ok) { out.textContent = `import failed: ${b.error || ("HTTP " + r.status)}`; return; }
    LAST_FC = fc;
    // #audit-9: actually LOAD the imported geometry into the live plan (previously it only printed a count).
    if ((Array.isArray(b.orders) && b.orders.length) || (Array.isArray(b.keepouts) && b.keepouts.length)) {
      snapshotAuthoring();
      (b.orders || []).forEach((o) => ORDERS.push(o));
      (b.keepouts || []).forEach((k) => KEEPOUTS.push(k));
      renderQueue();
      if (typeof renderKeepouts === "function") renderKeepouts();
      drawPlan();
    }
    out.textContent = `imported + LOADED: ${b.orders.length} order(s), ${b.keepouts.length} keep-out(s), charger ${b.charger ? "yes" : "no"}, ${b.route.length} route leg(s)`;
  } catch (e) { out.textContent = "import failed — run server.py (" + e + ")"; }
}
async function gisQuery() {
  const out = qel("gisout");
  if (!LAST_FC) { out.textContent = "export or import a FeatureCollection first"; return; }
  const layer = qel("gisq").value.trim();
  try {
    const r = await fetch("/gis/query", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ featurecollection: LAST_FC, feature: layer || null }) });
    const b = await r.json();
    out.textContent = r.ok ? `query "${layer || "*"}": ${b.count} feature(s)` : `query failed: ${b.error || ("HTTP " + r.status)}`;
  } catch (e) { out.textContent = "query failed — run server.py (" + e + ")"; }
}
{ const e = qel("gisexport"); if (e) e.onclick = gisExportGeojson; }
{ const e = qel("gispkg"); if (e) e.onclick = gisExportPackage; }
{ const e = qel("gisimport"); if (e) e.onclick = gisImport; }
{ const e = qel("gisquery"); if (e) e.onclick = gisQuery; }
// precedence text "Grade road > Build berm, Dig pit > Fill" -> [[before, after], ...] (I9). The pure
// parser lives in plan_geom.js; this thin alias reads the #qprec field and passes it in (FS-24).
function parsePrec() { return window.STEWIE_PLAN_GEOM.parsePrec(qel("qprec").value); }
// TR-01: render the persisted trainer A-board into the Metrics pane (#scorecard-board). The board is
// the autonomy-run KPIs the server persisted to data_dir/sessions/; makespan-vs-optimal scores the run
// against the best alternative forward_compare found. Truth divergence only shows when the director key
// is present (the server gates it). LAST_SCORECARD lets a Metrics-tab switch re-show the last run.
let LAST_SCORECARD = null;
function renderScorecardBoard(sid, b) {
  LAST_SCORECARD = b ? { sid, b } : LAST_SCORECARD;
  const host = document.getElementById("scorecard-board");
  if (!host || !LAST_SCORECARD) return;
  const cur = LAST_SCORECARD;
  document.getElementById("sc-sid").textContent = cur.sid.slice(0, 8);
  const m = cur.b;
  const chip = (k, v, warn) => `<span style="border:1px solid ${warn ? "#c0392b" : "var(--line)"};border-radius:6px;padding:3px 8px;margin:2px;display:inline-block;font-size:11px"><span style="color:var(--muted)">${k}</span> <b style="font-variant-numeric:tabular-nums">${v}</b></span>`;
  const html =
    chip("objectives", `${m.completed ? "✓" : "✗"} ${m.objectives_total}`) +
    chip("legs delivered", `${m.legs_delivered}/${m.legs_total}`) +
    chip("comm delivered", `${(m.comm_delivered_frac * 100).toFixed(0)}%`) +
    chip("makespan", `${m.makespan_s} s`) +
    chip("optimal", `${m.optimal_s} s`) +
    chip("makespan/opt", `${(m.makespan_ratio || 1).toFixed(2)}×`, (m.makespan_ratio || 1) > 1.15) +
    chip("recharges", m.recharges) + chip("replans", m.replans) +
    chip("stranded pkts", m.stranded_packets) + chip("dropped pkts", m.dropped_packets) +
    chip("energy", `${m.energy_MJ} MJ`) +
    (m.energy_divergence_J !== undefined ? chip("⚠ believed↔actual (truth)", `${m.energy_divergence_J} J`, true) : "");
  document.getElementById("sc-chips").innerHTML = html;
  host.style.display = "block";
}
qel("sesstart").onclick = async () => {                  // B3: operator/director training session
  if (!ORDERS.length) { setQ("add at least one order first"); return; }
  const b = qel("sesstart"); b.disabled = true; b.textContent = "running session…";
  try {
    const res = await fetch("/session/start", { method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({ name: `${BODIES[sel.value].name} session`, body: sel.value,
        charger: [0, 0], orders: ORDERS, keepouts: KEEPOUTS,
        profile: qel("seslink").value }) });
    const j = await res.json();
    if (!j.ok) { setQ("session error: " + (j.error || res.status)); return; }
    const o = qel("sesout"); o.style.display = "block";
    o.innerHTML = `session <code>${esc(String(j.session_id).slice(0, 8))}</code> · ${j.n_legs} legs · ` +
      `<a href="${esc(j.operator_url)}" target="_blank">operator view</a> · ` +
      `<a href="${esc(j.debrief_url)}" target="_blank">debrief</a> · ` +
      `<a href="/session/${esc(j.session_id)}/summary" target="_blank">summary</a>` +
      ` <span style="opacity:.7">(debrief + summary need the director key when auth is on)</span>`;
    // #80 / TR-01: the trainer SCORECARD (A-board KPIs, persisted server-side) rendered inline AND in
    // the Metrics pane -- director also sees the truth divergence; the inline block is the quick chip strip.
    try {
      const sb = await (await fetch(`/session/${j.session_id}/scorecard`, { headers: apiHeaders() })).json();
      if (sb.ok) {
        const b = sb.scorecard;
        const chip = (k, v) => `<span style="border:1px solid var(--line);border-radius:6px;padding:3px 8px;margin:2px;display:inline-block;font-size:11px"><span style="color:var(--muted)">${k}</span> <b style="font-variant-numeric:tabular-nums">${v}</b></span>`;
        o.innerHTML += `<div style="margin-top:8px"><b style="font-family:Orbitron,system-ui;font-size:10px;letter-spacing:.08em">TRAINER SCORECARD</b><br>` +
          chip("objectives", `${b.completed ? "✓" : "✗"} ${b.objectives_total}`) +
          chip("legs delivered", `${b.legs_delivered}/${b.legs_total}`) +
          chip("comm delivered", `${(b.comm_delivered_frac * 100).toFixed(0)}%`) +
          chip("makespan/opt", `${(b.makespan_ratio || 1).toFixed(2)}×`) +
          chip("recharges", b.recharges) + chip("replans", b.replans) +
          chip("stranded", b.stranded_packets) + chip("energy", `${b.energy_MJ} MJ`) +
          (b.energy_divergence_J !== undefined ? chip("⚠ divergence (truth)", `${b.energy_divergence_J} J`) : "") +
          `</div>`;
        renderScorecardBoard(j.session_id, b);             // TR-01: the Metrics-pane A-board surface
      }
    } catch (e) { /* scorecard optional */ }
    setQ("session ready — operator link is the trainee view; scorecard in the Metrics tab");
  } catch (e) { setQ("session error: " + e); }
  finally { b.disabled = false; b.textContent = "Start session"; }
};

// REHEARSE: the "Re-run forward-compare" button re-fetches the candidate cards from the current queue.
if (qel("rehearserun")) qel("rehearserun").onclick = async () => {
  const b = qel("rehearserun"); b.disabled = true; const t = b.textContent; b.textContent = "rehearsing…";
  try { await loadRehearse(); } finally { b.disabled = false; b.textContent = t; }
};

qel("qplan").onclick = async () => {
  if (!ORDERS.length) { setQ("add at least one order first"); return; }
  const pb = qel("qplan"); pb.disabled = true; pb.textContent = "planning + rendering report…";   // B0.4
  setQ("planning…");
  try {
    const res = await fetch("/plan", { method: "POST", headers: apiHeaders(),
      body: JSON.stringify({ name: `${BODIES[sel.value].name} build`, body: sel.value, charger: [0, 0],
        orders: ORDERS, algorithm: qel("qalgo").value, objective: qel("qobj").value, precedence: parsePrec(),
        keepouts: KEEPOUTS, max_traverse_slope_deg: +(qel("qslope") ? qel("qslope").value : 25),
        charger_capacity: +(qel("qchargers") ? qel("qchargers").value : 1),
        ...fleet(), ...site() }) });
    const j = await res.json();
    if (res.status === 401) { setQ("⚠ API key required: paste it in Settings (server key lives in deploy/.env)"); setView("settings"); return; }
    if (!j.ok) { setQ("error: " + j.error); return; }
    const t = j.totals;
    // FS-15: the Report-pane dashboard + CONOPS consume the TYPED PlanResult view model (adapters.js),
    // not ad-hoc legacy `totals` keys. Falls back to the raw dict if the adapter layer didn't load (never
    // worse than before). This also corrects the `recharges` chip, which read a non-existent `totals` key.
    const PR = (window.STEWIE_ADAPTERS && j.plan_result)
      ? window.STEWIE_ADAPTERS.normalizePlanResult({ plan_result: j.plan_result }) : null;
    const drumCycles = PR ? PR.drumCycles : (t.drum_cycles ?? 0);
    const cutPasses = PR ? PR.cutPasses : (t.cut_passes ?? 1);
    if ($("conops")) $("conops").textContent =
      `CONOPS PLANNED · ${t.trips ?? "—"} trips · ${drumCycles} drum cycles · ` +
      `${cutPasses} cut pass${cutPasses > 1 ? "es" : ""}`;
    LAST_ROUTES = t.routes || []; drawPlan();              // item 3: overlay the planned routes on the 2D canvas
    // #56: the dashboard strip -- the last plan's headline numbers, chips on the Report pane
    const ds = $("dashstrip");
    if (ds) {
      const chip = (k, v) => `<span style="border:1px solid var(--line);border-radius:6px;padding:5px 10px;font-size:11px"><span style="color:var(--muted)">${k}</span> <b style="font-variant-numeric:tabular-nums">${v}</b></span>`;
      const hz = (t.hazard_violations || []).length;
      if (hz) alertMsg("warn", `plan has ${hz} hazard flag(s): legs crossing freshly built terrain (repose-angle edges)`);
      alertMsg("info", `plan solved: ${(t.energy_J / 1e6).toFixed(1)} MJ · ${(t.time_s / 3600).toFixed(1)} h · ${t.resolved_algorithm || t.algorithm}`);
      ds.innerHTML =
        chip("moved", `${(PR ? PR.massMovedT : (t.cut_kg + (t.fill_kg || 0)) / 1000).toFixed(1)} t`) +
        chip("energy", `${(PR ? PR.energyMJ : t.energy_J / 1e6).toFixed(1)} MJ`) +
        chip("recharges", PR ? PR.recharges : (t.recharges ?? "—")) +     // FS-15: now the real count, not "—"
        chip("duration", `${(PR ? PR.durationH : t.time_s / 3600).toFixed(1)} h`) +
        chip("hazard flags", hz ? `⚠ ${hz}` : "0") +
        chip("solver", (PR ? PR.solver : (t.resolved_algorithm || t.algorithm)) || "—");
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
    LAST_LOCALIZATION = pc.localization || null;            // #nav-mission: the live est-vs-truth trace
    if (typeof navDrawMission === "function" && VIEW === "nav") navDrawMission(LAST_LOCALIZATION);
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
    if (typeof renderStepper === "function") renderStepper();  // pipeline spine: Solve done -> unlock Review/Execute
    LAST_TOTALS = t; LAST_PDF = j.pdf;                     // mirror the last plan into the tab-contextual left blocks
    LAST_VALIDATION = j.validation || null;                // FS-03: the as-built acceptance verdict for the Construction pane
    if (typeof renderCtxSummaries === "function") renderCtxSummaries();
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
  if (!guardCommand("commands")) return;                  // FS-17: only the command-authority window may emit commands
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
// FS-24: the execution-telemetry renderers (sparkline, ring push, chips, rover HUD, activity Gantt) now
// live in rover_hud.js (window.STEWIE_ROVER_HUD); these thin aliases resolve the DOM target / module
// state (TELE_BUF, DRUM_CAP_KG, markFresh) and forward, preserving behaviour exactly.
function teleChip(ch, text, ok) {
  window.STEWIE_ROVER_HUD.teleChip(qel("telerail"), ch, text, ok,
    (typeof markFresh === "function") ? markFresh : null);
}
function teleSpark() { window.STEWIE_ROVER_HUD.teleSpark(qel("telespark"), TELE_BUF); }
function telePush(batt, mass, slip) {
  window.STEWIE_ROVER_HUD.telePush(TELE_BUF, batt, mass, slip, teleSpark);
}
// #184: the rover HUD -- azimuth compass, battery, front/rear drum weight, live pose -- on #hudcanvas.
// Updated each execution frame (heading from the path delta, SoC from the battery channel, pose) and when
// the operator sets the drum loads. All real: pose/SoC from the planned timeline; drum kg from the
// stability inputs (cgFk/cgBk) -- the same masses that feed the CG/tip-margin physics.
const DRUM_CAP_KG = (typeof IPEX_FALLBACK !== "undefined" ? IPEX_FALLBACK.drum_kg : 30);
function roverHUDState(extra) {
  return Object.assign({ frontKg: +(qel("cgFk") ? qel("cgFk").value : 0) || 0,
                         rearKg: +(qel("cgBk") ? qel("cgBk").value : 0) || 0 }, extra || {});
}
function drawRoverHUD(s) { window.STEWIE_ROVER_HUD.drawRoverHUD(qel("hudcanvas"), s, DRUM_CAP_KG); }
// UI-17: the activity Gantt -- one lane per phase kind, bars at [t0, t1], battery curve under.
// FS-24: the painter lives in rover_hud.js; this thin alias resolves $("gantt") and forwards.
function drawGantt(rawFrames) { window.STEWIE_ROVER_HUD.drawGantt($("gantt"), rawFrames); }
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
  // NOT markFresh(cv): this canvas REPLAYS the precomputed planned timeline (a dry-run forecast), it does
  // not receive live telemetry. Stamping it data-fresh="ok" painted a "FRESH" badge that read as a live
  // feed -- the forecast must not claim freshness. (Live data-freshness badges belong on the genuine SSE
  // RC stream + camera tile only.) The pane caption labels this explicitly as a forecast replay.
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
    fillKeepout(ctx, k, X, Y, s);                          // #178: rect or disc
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
// council #238: an honest in-canvas placeholder when the Execute view is opened with no mission (the empty
// dark grid read as "broken"). clearRect leaves the canvas transparent so the faint CSS grid still shows
// THROUGH, with a centered "No mission loaded" cue; a real run (execDraw) overwrites it.
function paintExecIdle() {
  const cv = qel("execcanvas"); if (!cv) return;
  if (LAST_TIMELINE && LAST_TIMELINE.frames && LAST_TIMELINE.frames.length) return;   // a run exists -> leave it
  const g = cv.getContext("2d"); g.clearRect(0, 0, cv.width, cv.height);
  g.textAlign = "center";
  g.font = "12px system-ui"; g.fillStyle = "#7a8696"; g.fillText("No mission loaded", cv.width / 2, cv.height / 2 - 6);
  g.font = "10px system-ui"; g.fillStyle = "#5a6472"; g.fillText("plan a mission, then ▶ Execute + watch", cv.width / 2, cv.height / 2 + 11);
  g.textAlign = "left";
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
    // visual-appeal council (#234 dim-1): state triad -- green healthy / amber caution / red ONLY at a
    // genuine low charge, so a full battery no longer renders as a brand-red "alarm" bar.
    qel("excbattfill").style.background = bf < 0.15 ? "#e0564b" : bf < 0.40 ? "#e0b300" : "#19c37d";
    qel("excbattlbl").textContent = `${(bf * 100).toFixed(1)}%`;   // 1 decimal: the bar flips red at <20% on the raw value, so a rounded "20%" beside a red bar was a mismatch
    // #184: rover HUD -- heading from the path delta (from-north-eastward), live SoC + pose, drum from the stability inputs
    const _dE = fr.x1 - fr.x0, _dN = fr.y1 - fr.y0;
    const _hd = (Math.abs(_dE) + Math.abs(_dN) > 1e-6) ? (Math.atan2(_dE, _dN) * 180 / Math.PI + 360) % 360 : undefined;
    drawRoverHUD(roverHUDState({ headingDeg: _hd, soc: bf,
      x: fr.x0 + (fr.x1 - fr.x0) * u, y: fr.y0 + (fr.y1 - fr.y0) * u }));
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

// #245: run the current build queue as a real SIM EXECUTION via POST /executive/run -- the MO-02 executive
// drives ARMED -> EXECUTING -> (COMPLETED | SAFED) on the conserved sim authority. Distinct from the forecast
// replay above (qexec/LAST_TIMELINE): this is the executive actually running the released plan, SIM-labeled.
// The real-rover command path stays gated; this only exercises the in-process plant.
async function runExecutiveSim() {
  if (!ORDERS.length) { setQ("⚠ add build orders first — nothing to run"); return; }
  const out = qel("execrunout"); const btn = qel("execrun");
  if (out) { out.style.display = ""; out.textContent = "running SIM execution…"; }
  if (btn) btn.disabled = true;
  try {
    const r = await fetch("/executive/run", {
      method: "POST", headers: apiHeaders(),   // already sets Content-Type+CSRF; a 2nd content-type key collides -> 400
      body: JSON.stringify({ orders: ORDERS, site: CURRENT_SITE }) });
    const j = await r.json();
    if (!r.ok || !j.ok) { if (out) out.textContent = "run rejected: " + esc(String(j.error || r.status)); return; }
    const chain = (j.transitions || []).join(" → ");
    const fs = String(j.final_state || "").toUpperCase();
    const safe = j.safed ? ' <b style="color:#e8273f">⚠ SAFED</b>' : "";
    if (out) {
      out.innerHTML = '<b>SIM RUN</b> <span style="color:var(--muted)">[' + esc(String(j.label)) + ']</span> — '
        + esc(chain) + " · <b>" + esc(fs) + "</b>" + safe
        + " · " + (j.n_legs_total | 0) + " legs"
        + (j.nonnominal_legs ? ", " + (j.nonnominal_legs | 0) + " non-nominal" : "")
        + (j.run_id ? ' <span style="color:var(--muted)">· run ' + esc(String(j.run_id)) + "</span>" : "");
    }
  } catch (e) { if (out) out.textContent = "run error: " + esc(String(e)); }
  finally { if (btn) btn.disabled = false; }
}
if (qel("execrun")) qel("execrun").onclick = runExecutiveSim;
qel("execpause").onclick = () => { EXEC_PAUSED = !EXEC_PAUSED;
  qel("execpause").innerHTML = window.STEWIE_ICONS ? window.STEWIE_ICONS.icon(EXEC_PAUSED ? "play" : "pause") : (EXEC_PAUSED ? "resume" : "pause"); };
qel("execspd").onclick = () => { EXEC_SPEEDUP = EXEC_SPEEDUP === 10 ? 60 : EXEC_SPEEDUP === 60 ? 600 : 10;
  qel("execspeed").textContent = ` ${EXEC_SPEEDUP}×`; };
qel("execclose").onclick = () => { cancelAnimationFrame(EXEC_RAF); setView("plan"); };

// #165: the in-cockpit 3D terrain dry-run. Toggle hides the 2D top-down and shows the WebGL view
// (window.STEWIE3D, three3d.js): the real work-area DEM in the order frame, plus -- once a mission is
// planned -- the physics-truth path (amber) vs estimator belief (cyan) from LAST_LOCALIZATION and the
// rover on the surface. Simulation, never a live rover.
let TD3D_ON = false;
// #181: drive the 3D-view sun from the SAME solar authority the shadow layer uses -- /ephemeris in AUTO
// mode (real az/el at the Haworth latitude from mission time), or the manual az/el sliders. One source
// of solar truth; the 3D wireframe/terrain then self-shadows under the real sun.
// #147 tier-3: fetch the REAL Chrono-settled boulder scene (GET /clasts/scene -- written by
// scripts/chrono_clast_scene.py, a ChSystemSMC rigid-body solve) and render it on the DEM. Self-gates
// (empty scene -> clears); harmless when the 3D view isn't mounted. Not the force-accurate excavation tier.
async function loadClasts() {
  if (!window.STEWIE3D || !STEWIE3D.setClasts) return;
  try {
    const r = await fetch("/clasts/scene", { headers: apiHeaders() });
    const d = await r.json();
    if (d && d.present && Array.isArray(d.clasts) && d.clasts.length) STEWIE3D.setClasts(d.clasts);
    else STEWIE3D.clearClasts();
  } catch (e) { /* no scene produced yet -- leave the terrain bare */ }
}

function apply3DSun() {
  if (!window.STEWIE3D || !STEWIE3D.setSun) return;
  const auto = $("sunauto") && $("sunauto").checked;
  if (auto && $("suntime")) {
    const mt = Math.round(parseFloat($("suntime").value) * 86400);
    fetch(`/ephemeris?mission_t_s=${mt}&lat_deg=-87.45&lon_deg=0`, { headers: apiHeaders() })
      .then((r) => r.json()).then((d) => {
        if (d && d.ok && d.ephemeris) STEWIE3D.setSun(d.ephemeris.sun_az_deg, d.ephemeris.sun_el_deg);
      }).catch(() => {});
  } else if ($("sunaz") && $("sunel")) {
    STEWIE3D.setSun(+$("sunaz").value || 90, +$("sunel").value || 6);
  }
}
function open3D() {
  const host = $("td3d"); if (!host || !window.STEWIE3D) { setQ("3D view unavailable (three.js not loaded)"); return; }
  STEWIE3D.mount(host);
  const site = (typeof CURRENT_SITE !== "undefined" && CURRENT_SITE) || "haworth";
  const loc = LAST_LOCALIZATION;
  // fit the window to the mission extent (the order frame is anchored at 0): cover orders + trajectory
  let maxc = 120;
  (typeof ORDERS !== "undefined" ? ORDERS : []).forEach((o) => { maxc = Math.max(maxc, o.x || 0, o.y || 0); });
  if (loc && loc.trajectory) loc.trajectory.forEach((p) => {
    maxc = Math.max(maxc, p["true"][0], p["true"][1], p.est[0], p.est[1]); });
  const win = Math.min(2000, Math.max(120, Math.round(maxc * 1.2)));
  fetch("/dem/heightfield?site=" + encodeURIComponent(site) + "&n=129&window_m=" + win, { headers: apiHeaders() })
    .then((r) => r.json()).then((hf) => {
      if (!hf || !hf.ok) { setQ("3D: heightfield unavailable for " + site); return; }
      STEWIE3D.render(hf);
      CUR_HF_FRAME = { dem: hf.site, cell_m: hf.cell_m, dem_origin: hf.dem_origin };   // #144 tier-1: overlay frame-match
      loadClasts();                                                       // #147: REAL Chrono boulder scene on the DEM
      apply3DSun();                                                       // #181: ephemeris-driven sun + shadows
      if (typeof LANDER_P !== "undefined" && (LANDER_P.x || LANDER_P.y) && STEWIE3D.setLander3D)
        STEWIE3D.setLander3D(LANDER_P.x, LANDER_P.y);                     // #182: lander + AprilTag beacon
      STEWIE3D.clearTracks(); STEWIE3D.stopRoverAnim();
      if (loc && loc.trajectory && loc.trajectory.length) {
        const truth = loc.trajectory.map((p) => p["true"]);
        STEWIE3D.setPath(truth, 0xf3b13a);                                  // physics truth
        STEWIE3D.setPath(loc.trajectory.map((p) => p.est), 0x35e0d0);       // estimator belief
        STEWIE3D.animateRover(truth);                                       // watch the rover drive the plan
        setQ("3D dry-run: " + truth.length + " poses on the real DEM (truth vs estimate)");
      } else {
        setQ("3D terrain loaded — plan a mission to see the rover drive it");
      }
    }).catch(() => setQ("3D: heightfield fetch failed"));
}
if ($("exec3d")) $("exec3d").onclick = () => {
  TD3D_ON = !TD3D_ON;
  $("td3d").style.display = TD3D_ON ? "block" : "none";
  $("td3d-hint").style.display = TD3D_ON ? "block" : "none";
  $("execcanvas").style.display = TD3D_ON ? "none" : "";
  $("exec3d").style.borderColor = TD3D_ON ? "var(--accent)" : "";
  if ($("exec-mode-lbl")) $("exec-mode-lbl").textContent = TD3D_ON ? "3D terrain dry-run" : "execution top-down";
  if ($("td3dlegend")) $("td3dlegend").style.display = TD3D_ON ? "" : "none";
  if (TD3D_ON) { open3D(); update3DLegend(); }
  else if (window.STEWIE3D) STEWIE3D.stopRoverAnim();
};
// #180: toggle the depth/heightfield WIRE overlay (the convergence-viz structural backdrop); default on
let TD3D_WIRE = true;
if ($("exec3dwire")) {
  $("exec3dwire").style.borderColor = "var(--accent)";          // reflect the default-on state
  $("exec3dwire").onclick = () => {
    TD3D_WIRE = !TD3D_WIRE;
    if (window.STEWIE3D && STEWIE3D.setWireframe) STEWIE3D.setWireframe(TD3D_WIRE);
    $("exec3dwire").style.borderColor = TD3D_WIRE ? "var(--accent)" : "";
    setQ(`3D wire overlay ${TD3D_WIRE ? "on" : "off"}`);
  };
}
// GIS-WA2 (+ council fix): drape the selected GIS layer onto the 3D relief + vertical exaggeration, with a
// LEGEND (the ramp -> values) and an explicit exaggeration disclosure so the relief is never silently
// scaled (precision-honesty) and the layer is readable (not just coloured). The layer raster is rendered in
// the loaded heightfield's exact order-frame window.
function _layer3DLegendHTML(kind) {
  const sw = (g) => `<span style="display:inline-block;width:34px;height:9px;border:1px solid #2a3340;vertical-align:middle;background:${g}"></span>`;
  if (kind === "slope") return sw("linear-gradient(90deg,#3cc828,#ffd200,#ff3c28)") + ` slope 0°–${SLOPE_SYM.vmax}°` + (SLOPE_SYM.classes >= 2 ? ` (${SLOPE_SYM.classes})` : "+");
  if (kind === "hazard") return sw("linear-gradient(90deg,#ff8c00,#ff2000)") + " hazard nominal–no-go &gt;20°";
  if (kind === "illumination") return sw("#1a73e8") + " blue = shadowed now";
  if (kind === "incidence") return sw("linear-gradient(90deg,#ffc828,#ff2840)") + " sun incidence 0°–90° (grazing)";
  if (kind === "psr") return sw("#1a73e8") + " blue = ever-shadowed (PSR)";
  if (kind === "dem") return sw("linear-gradient(90deg,#2a2a2a,#f0f0f0)") + " hillshade 315°/45°";
  return "relief — height shading";
}
function update3DLegend() {
  const el = $("td3dlegend"); if (!el || !window.STEWIE3D) return;
  const vex = +STEWIE3D.vertExag || 1;
  const exag = vex > 1 ? ` · ↕×${vex.toFixed(1)} vert. exag` : " · ↕ true scale";
  el.innerHTML = _layer3DLegendHTML(STEWIE3D.layerKind) + `<span style="opacity:.8">${exag}</span>`;
}
if (window.STEWIE3D && STEWIE3D.onLayerError) STEWIE3D.onLayerError((kind) => {   // raster failed -> revert UI + warn
  if ($("exec3dlayer")) $("exec3dlayer").value = "height";
  update3DLegend(); setQ(`3D: ${kind} layer unavailable — reverted to relief`);
});
if ($("exec3dlayer")) $("exec3dlayer").onchange = (e) => {
  if (window.STEWIE3D && STEWIE3D.setLayer) STEWIE3D.setLayer(e.target.value);
  update3DLegend();
  setQ(e.target.value === "height" ? "3D: height-ramp relief" : `3D: ${e.target.value} layer on the relief`);
};
if ($("exec3dvex")) $("exec3dvex").oninput = (e) => {
  const k = parseFloat(e.target.value) || 1;
  if ($("exec3dvexv")) $("exec3dvexv").textContent = k.toFixed(1);
  if (window.STEWIE3D && STEWIE3D.setVertExag) STEWIE3D.setVertExag(k);
  update3DLegend();
};

// 3D path definition in the PLAN flow (Aaron 2026-06-17, option 1): a relief-accurate alternative to the
// 2D globe. "▦ 3D path" swaps the Plan map for a Three.js wireframe of the CHOSEN SITE's DEM; clicking the
// terrain drops goto-waypoint ORDERS on the real surface (the same `goto` kind the 2D path uses), so Solve
// routes them. Live per-leg length + slope; slopes > 25 deg flagged. The Metrics 3D view stays read-only.
let PLAN3D_ON = false;
function planSyncPathOrders() {
  if (!window.STEWIE3D || !STEWIE3D.getWaypoints) return;
  const wps = STEWIE3D.getWaypoints();
  snapshotAuthoring();
  for (let i = ORDERS.length - 1; i >= 0; i--)                 // drop the previous 3D-path gotos (keep other orders)
    if (ORDERS[i].kind === "goto" && String(ORDERS[i].action || "").startsWith("p3d_")) ORDERS.splice(i, 1);
  wps.forEach((p, i) => ORDERS.push({ action: "p3d_wp" + (i + 1), kind: "goto", x: Math.round(p[0]), y: Math.round(p[1]) }));
  renderQueue();
  const el = $("plan3dstats"); if (el && STEWIE3D.pathStats) {
    const s = STEWIE3D.pathStats(), col = (d) => (d > 25 ? "#e8273f" : "var(--accent)");
    el.innerHTML = s.n
      ? `<b>${s.n}</b> waypoints → <b>${s.n}</b> goto orders · path <b>${s.total_len_m.toFixed(1)} m</b> · `
        + `max slope <b style="color:${col(s.max_slope_deg)}">${s.max_slope_deg.toFixed(1)}°</b>`
        + (s.legs.length ? "<br>" + s.legs.map((l, i) => `L${i + 1} ${l.len_m.toFixed(1)}m@${l.slope_deg.toFixed(0)}°`).join(" · ") : "")
      : '<span style="opacity:.6">Click the 3D terrain to drop traverse waypoints on the surface — they become goto orders Solve routes.</span>';
  }
}
function planLoad3D() {
  const host = $("plan3d"); if (!host || !window.STEWIE3D) { setQ("3D view unavailable (three.js not loaded)"); return; }
  STEWIE3D.mount(host);
  const site = (typeof CURRENT_SITE !== "undefined" && CURRENT_SITE) || "haworth";
  fetch("/dem/heightfield?site=" + encodeURIComponent(site) + "&n=129&window_m=300", { headers: apiHeaders() })
    .then((r) => r.json()).then((hf) => {
      if (!hf || !hf.ok) { setQ("3D: heightfield unavailable for " + site); return; }
      STEWIE3D.render(hf); if (STEWIE3D.setSun) STEWIE3D.setSun(135, 18);
      CUR_HF_FRAME = { dem: hf.site, cell_m: hf.cell_m, dem_origin: hf.dem_origin };   // #144 tier-1: overlay frame-match
      loadClasts();                                                       // #147: REAL Chrono boulder scene on the DEM
      if (typeof LANDER_P !== "undefined" && (LANDER_P.x || LANDER_P.y) && STEWIE3D.setLander3D) STEWIE3D.setLander3D(LANDER_P.x, LANDER_P.y);
      STEWIE3D.setPathEdit(true); STEWIE3D.onPathChange(planSyncPathOrders); planSyncPathOrders();
      // 3D plotting toolbox: live cursor coord readout + plotted coordinate markers + 3D distance measures
      if (STEWIE3D.onHover) STEWIE3D.onHover((c) => {
        P3D_HOVER = c ? `▸ E ${c.e.toFixed(1)}  N ${c.n.toFixed(1)}  ↕ ${c.elev.toFixed(1)} m` : "▸ (cursor off surface)";
        p3dHud();
      });
      if (STEWIE3D.onMarkers) STEWIE3D.onMarkers((ms) => {
        P3D_MARKERS = ms.length ? `plot ${ms.length} plotted:\n` + ms.map((m, i) => `  #${i + 1} E${m.e.toFixed(1)} N${m.n.toFixed(1)} ${m.elev.toFixed(1)}m`).join("\n") : "";
        p3dHud();
      });
      if (STEWIE3D.onMeasure) STEWIE3D.onMeasure((d) => {
        P3D_MEAS = `measure ${d.slant_m.toFixed(1)} m slant · H ${d.horiz_m.toFixed(1)} · V ${d.vert_m >= 0 ? "+" : ""}${d.vert_m.toFixed(1)} · ${d.slope_deg.toFixed(0)}°`;
        p3dHud();
      });
      P3D_TOOL = "path"; P3D_COORDS = true; P3D_HOVER = ""; P3D_MARKERS = ""; P3D_MEAS = "";
      if (STEWIE3D.setCoordReadout) STEWIE3D.setCoordReadout(true);
      if ($("plan3dcoords")) $("plan3dcoords").style.borderColor = "var(--accent)";
      if ($("plan3dplot")) $("plan3dplot").style.borderColor = "";
      if ($("plan3dmeasure")) $("plan3dmeasure").style.borderColor = "";
      p3dHud();
      setQ("3D path mode — click the " + site + " terrain to drop traverse waypoints (→ goto orders)");
    }).catch(() => setQ("3D: heightfield fetch failed"));
}
let FLY3D_ON = false, P3D_TOOL = "path", P3D_COORDS = true, P3D_HOVER = "", P3D_MARKERS = "", P3D_MEAS = "";
function p3dHud() {                                         // compose the live-coord / plotted-points / measure HUD
  const el = $("plan3dcoord"); if (!el) return;
  const parts = [];
  if (P3D_COORDS) parts.push(P3D_HOVER || "▸ move over the terrain for live E / N / elevation");
  if (P3D_MEAS) parts.push(P3D_MEAS);
  if (P3D_MARKERS) parts.push(P3D_MARKERS);
  el.textContent = parts.join("\n");
}
function p3dSetTool(tool) {                                 // one click-tool at a time in orbit: path | plot | measure
  P3D_TOOL = tool;
  if (window.STEWIE3D) {
    if (STEWIE3D.setPlotMode) STEWIE3D.setPlotMode(tool === "plot");
    if (STEWIE3D.setMeasureMode) STEWIE3D.setMeasureMode(tool === "measure");
    if (STEWIE3D.setPathEdit) STEWIE3D.setPathEdit(tool === "path" && !FLY3D_ON);
  }
  if ($("plan3dplot")) $("plan3dplot").style.borderColor = tool === "plot" ? "var(--accent)" : "";
  if ($("plan3dmeasure")) $("plan3dmeasure").style.borderColor = tool === "measure" ? "var(--accent)" : "";
  if ($("plan3dctl")) $("plan3dctl").style.display = (tool === "path" && !FLY3D_ON) ? "inline" : "none";
}
if ($("plan3dtoggle")) $("plan3dtoggle").onclick = () => {
  PLAN3D_ON = !PLAN3D_ON;
  if ($("cesium")) $("cesium").style.display = PLAN3D_ON ? "none" : "";
  if ($("plan3d")) $("plan3d").style.display = PLAN3D_ON ? "block" : "none";
  if ($("plan3dfly")) $("plan3dfly").style.display = PLAN3D_ON ? "inline-block" : "none";
  if ($("plan3dtools")) $("plan3dtools").style.display = PLAN3D_ON ? "inline" : "none";
  if ($("plan3dcoord")) $("plan3dcoord").style.display = PLAN3D_ON ? "block" : "none";
  if ($("plan3dstats")) $("plan3dstats").style.display = PLAN3D_ON ? "block" : "none";
  $("plan3dtoggle").style.borderColor = PLAN3D_ON ? "var(--accent)" : "";
  $("plan3dtoggle").textContent = PLAN3D_ON ? "▦ 2D map" : "▦ 3D path";
  if (PLAN3D_ON) { planLoad3D(); }                         // enters orbit + path-def on the chosen-site DEM
  else {                                                   // leaving 3D: reset fly + every click-tool
    FLY3D_ON = false; if ($("plan3dfly")) $("plan3dfly").style.borderColor = "";
    if (window.STEWIE3D) {
      if (STEWIE3D.setFlyMode) STEWIE3D.setFlyMode(false);
      if (STEWIE3D.setPlotMode) STEWIE3D.setPlotMode(false);
      if (STEWIE3D.setMeasureMode) STEWIE3D.setMeasureMode(false);
      if (STEWIE3D.setPathEdit) STEWIE3D.setPathEdit(false);
    }
    P3D_TOOL = "path";
    if ($("plan3dplot")) $("plan3dplot").style.borderColor = "";
    if ($("plan3dmeasure")) $("plan3dmeasure").style.borderColor = "";
  }
  if ($("plan3dctl")) $("plan3dctl").style.display = (PLAN3D_ON && !FLY3D_ON && P3D_TOOL === "path") ? "inline" : "none";
};
if ($("plan3dfly")) $("plan3dfly").onclick = () => {       // fly/move-through; overrides every click-tool
  FLY3D_ON = !FLY3D_ON;
  if (window.STEWIE3D && STEWIE3D.setFlyMode) STEWIE3D.setFlyMode(FLY3D_ON, false);
  $("plan3dfly").style.borderColor = FLY3D_ON ? "var(--accent)" : "";
  if (FLY3D_ON) {
    if (window.STEWIE3D) {
      if (STEWIE3D.setPlotMode) STEWIE3D.setPlotMode(false);
      if (STEWIE3D.setMeasureMode) STEWIE3D.setMeasureMode(false);
      if (STEWIE3D.setPathEdit) STEWIE3D.setPathEdit(false);
    }
    if ($("plan3dplot")) $("plan3dplot").style.borderColor = "";
    if ($("plan3dmeasure")) $("plan3dmeasure").style.borderColor = "";
    if ($("plan3dctl")) $("plan3dctl").style.display = "none";
    setQ("fly Fly — drag to look · W/A/S/D move · R/F up·down");
  } else {
    p3dSetTool(P3D_TOOL);                                  // restore the previously-selected click-tool
    setQ("Orbit view + " + (P3D_TOOL === "path" ? "path-def (click to drop waypoints)" : P3D_TOOL + " tool"));
  }
};
if ($("plan3dcoords")) $("plan3dcoords").onclick = () => { // live cursor coordinate readout on/off
  P3D_COORDS = !P3D_COORDS;
  if (window.STEWIE3D && STEWIE3D.setCoordReadout) STEWIE3D.setCoordReadout(P3D_COORDS);
  $("plan3dcoords").style.borderColor = P3D_COORDS ? "var(--accent)" : "";
  if (!P3D_COORDS) P3D_HOVER = "";
  p3dHud();
};
if ($("plan3dplot")) $("plan3dplot").onclick = () => {     // plot labeled coordinate markers
  if (FLY3D_ON) return;
  const t = P3D_TOOL === "plot" ? "path" : "plot"; p3dSetTool(t);
  setQ(t === "plot" ? "plot Plot — click the terrain to drop a coordinate marker (exact E / N / elevation)" : "Path-def — click to drop waypoints");
};
if ($("plan3dmeasure")) $("plan3dmeasure").onclick = () => { // 3D distance between two surface points
  if (FLY3D_ON) return;
  const t = P3D_TOOL === "measure" ? "path" : "measure"; p3dSetTool(t);
  setQ(t === "measure" ? "measure Measure — click two surface points for slant / horizontal / vertical distance" : "Path-def — click to drop waypoints");
};
if ($("plan3dplotclear")) $("plan3dplotclear").onclick = () => { // clear plotted markers + measures
  if (window.STEWIE3D && STEWIE3D.clearPlots) STEWIE3D.clearPlots();
  P3D_MARKERS = ""; P3D_MEAS = ""; p3dHud();
};
if ($("plan3dundo")) $("plan3dundo").onclick = () => { if (window.STEWIE3D && STEWIE3D.undoWaypoint) STEWIE3D.undoWaypoint(); };
if ($("plan3dclear")) $("plan3dclear").onclick = () => { if (window.STEWIE3D && STEWIE3D.clearWaypoints) STEWIE3D.clearWaypoints(); };

// ---- compare algorithms: POST /compare -> a table sorted by the chosen objective --------------
qel("qcompare").onclick = async () => {
  if (!ORDERS.length) { setQ("add at least one order first"); return; }
  const obj = qel("qobj").value;
  setQ(`comparing algorithms by ${obj}…`);
  try {
    const res = await fetch("/compare", { method: "POST", headers: apiHeaders(),
      // usefulness council #234 dim-2 (GAP 3): rank algorithms on the REAL world -- carry keep-outs, the
      // traverse-slope cap, and the site, exactly as /plan does, so the Pareto "best" can't be wrong
      // because the comparison saw a flatter, obstacle-free, wrong-site terrain.
      body: JSON.stringify({ name: "compare", body: sel.value, charger: [0, 0], orders: ORDERS,
        keepouts: KEEPOUTS, objective: obj, precedence: parsePrec(),
        max_traverse_slope_deg: +(qel("qslope") ? qel("qslope").value : 25), ...fleet(), ...site() }) });
    const j = await res.json();
    if (!j.ok) { setQ("compare error: " + j.error); return; }
    const fmt = { time_s: v => (v / 3600).toFixed(1) + " h", energy_J: v => (v / 1e6).toFixed(1) + " MJ",
      avg_power_w: v => v.toFixed(0) + " W", distance_m: v => (v / 1000).toFixed(2) + " km",
      charges: v => v.toFixed(0), mass_kg: v => (v / 1000).toFixed(1) + " t" };
    const cols = ["algorithm", "time_s", "energy_J", "avg_power_w", "distance_m", "charges", "mass_kg"];
    const head = "<tr>" + cols.map(c => `<th style="text-align:left;color:var(--muted)">${c.replace('_s','').replace('_J','').replace('_w','').replace('_m','').replace('_kg','')}</th>`).join("") + "</tr>";
    const rows = j.rows.map((r, i) => `<tr${r.error ? "" : ` data-algo="${esc(r.algorithm)}" style="cursor:pointer"`}>` + cols.map(c => {
      if (c === "algorithm") return `<td><b>${esc(r.algorithm)}${i === 0 ? " ★" : ""}${r.pareto ? " •" : ""}</b></td>`;  // SEC-04 (#234 dim-3): escape server data into the DOM
      return `<td>${r.error ? "—" : fmt[c](r[c])}</td>`;
    }).join("") + "</tr>").join("");
    const t = qel("cmptable"); t.innerHTML = head + rows; t.style.display = "table";
    // GAP 2 (usefulness council #234 dim-2): the Pareto frontier IS the solver picker -- click a row to set
    // the algorithm + re-plan, instead of hand-copying the winner into the dropdown.
    t.querySelectorAll("tr[data-algo]").forEach((tr) => {
      tr.title = `click to plan with ${tr.dataset.algo}`;
      tr.onclick = () => {
        if (qel("qalgo")) qel("qalgo").value = tr.dataset.algo;
        setQ(`algorithm → ${tr.dataset.algo}; planning…`);
        if (qel("qplan")) qel("qplan").click();
      };
    });
    setQ(`compared ${j.rows.length} algorithms by ${obj} (★ best, • Pareto-optimal); click a row to plan with it`);
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
    const pw = (PHY && PHY[sel.value]) ? PHY[sel.value].ipex_power : null;   // #172: per-body (g-scaled) power lives WITH the vehicle
    return `<b>${v.label}</b><table style="width:100%;border-collapse:collapse;margin-top:4px">` +
      row("capabilities", [...caps].sort().join(", ")) +
      row("dry mass", `${v.dry_mass_kg} kg`) + row("wheels", v.n_wheels) +
      row("drum capacity", `${v.drum_capacity_kg} kg`) +
      row("drive power", `${v.drive_power_w} W`) +
      row("dig energy", `${v.dig_energy_j_per_kg} J/kg`) +
      (pw ? row(`power on ${sel.value} (g-scaled)`, `drive ${pw.drive_power_w} W (15° ${pw.drive_power_15deg_w} W) · system ${pw.system_power_w} W`)
          + row("heater / env", pw.thermal_by_env_w ? Object.entries(pw.thermal_by_env_w).map(([e, w]) => `${e.replace(/^(lunar|mars)_/, "")} ${w}W`).join(", ") : "—") : "") +
      `</table><div style="opacity:.6;margin-top:4px">registry values (provenance-tagged in stewie/specs/vehicles.py)</div>`;
  });
  refreshPopovers();
  renderFleet();                                            // Fleet: keep the add/delete roster in sync with the type
}
// Fleet roster (Aaron: "more vehicles / add like waypoints / delete"). Add/remove rovers; the roster
// length IS the vehicle count plan_multi honors. HONEST: the fleet is HOMOGENEOUS (all the selected type)
// -- per-vehicle DIFFERENT types + map-placed start positions need a plan_multi extension (it builds trips
// once from one drum capacity, so heterogeneous specs are a backend rearchitecture, tracked separately).
function setFleetCount(n) {
  const c = qel("vehcount"); if (!c) return;
  c.value = String(Math.max(1, Math.min(16, n)));
  c.dispatchEvent(new Event("change"));
  renderFleet();
  if (typeof drawPlan === "function") drawPlan();
}
function renderFleet() {
  const list = qel("fleetlist"); if (!list) return;
  const n = Math.max(1, Math.min(16, parseInt((qel("vehcount") || {}).value, 10) || 1));
  const v = (PHY && PHY._vehicles) ? PHY._vehicles[(qel("vehicle") || {}).value] : null;
  const label = v ? v.label : ((qel("vehicle") || {}).value || "rover");
  list.innerHTML = "";
  for (let i = 0; i < n; i++) {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:6px;padding:2px 0;font-size:11px";
    const txt = document.createElement("span");
    txt.innerHTML = `<b>Rover ${i + 1}</b> <span style="color:var(--muted)">&middot; ${esc(label)}</span>`;
    row.appendChild(txt);
    if (n > 1) {
      const del = document.createElement("button");
      del.textContent = "delete"; del.title = "remove a rover";
      del.style.cssText = "margin-left:auto;background:none;border:1px solid var(--line);border-radius:4px;color:var(--muted);cursor:pointer;font-size:10px;padding:1px 6px";
      del.onclick = () => setFleetCount(n - 1);
      row.appendChild(del);
    }
    list.appendChild(row);
  }
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
  if (qel("fleetadd")) qel("fleetadd").onclick = () => setFleetCount((parseInt(qel("vehcount").value, 10) || 1) + 1);
  if (qel("vehcount")) qel("vehcount").addEventListener("input", renderFleet);
  // #172/#173: soil + charger info popovers, sourced from the loaded registries (PHY[soil], PHY._chargers)
  if ($("soilinfo")) popover("soil", $("soilinfo"), () => {
    const key = (qel("soil").value) || sel.value;            // "" -> the body's own regolith
    const ph = (PHY && PHY[key]) || null; if (!ph) return "<i>soil model unavailable</i>";
    const bk = ph.bekker ? `kφ ${(ph.bekker.k_phi / 1000).toFixed(0)}k · kc ${ph.bekker.k_c} · n ${ph.bekker.n}` : "—";
    const r = (k, v) => `<tr><td style="color:var(--muted);padding-right:10px">${k}</td><td style="text-align:right">${v}</td></tr>`;
    return `<b>${esc(ph.label || key)} regolith</b><table style="width:100%;border-collapse:collapse;margin-top:4px">`
      + r("bulk density", `${ph.bulk_density} kg/m³`)
      + (ph.cohesion_pa != null ? r("cohesion", `${ph.cohesion_pa} Pa`) : "")
      + (ph.friction_deg != null ? r("friction", `${ph.friction_deg}°`) : "")
      + r("Bekker", bk) + (ph.bekker_regime ? r("regime", esc(ph.bekker_regime)) : "")
      + `</table><div style="opacity:.6;margin-top:4px">the regolith model the planner uses; override the body default to test a cross-soil run</div>`;
  });
  if ($("chargerinfo")) popover("charger", $("chargerinfo"), () => {
    const ch = (PHY && PHY._chargers) || null; if (!ch) return "<i>charger registry unavailable</i>";
    const rows = Object.values(ch).map((c) =>
      `<tr><td><b>${esc(c.label)}</b></td><td style="text-align:right">${c.recharge_power_w} W</td>`
      + `<td style="text-align:right;color:var(--muted)">×${c.concurrent}</td></tr>`).join("");
    return `<b>Charger registry</b><table style="width:100%;border-collapse:collapse;margin-top:4px">`
      + `<tr><td style="color:var(--muted)">station</td><td style="text-align:right;color:var(--muted)">recharge</td><td style="text-align:right;color:var(--muted)">at&nbsp;once</td></tr>`
      + rows + `</table><div style="opacity:.6;margin-top:4px">the “Chargers” count = concurrent slots; recharge power [CALIB] (stewie/specs/vehicles.py)</div>`;
  });
  refreshPopovers();
  syncKinds();
}

// load the py-generated terramechanics + IPEx constants (single source); graceful on file://.
// Aaron 2026-06-16 ("why did fleet and soil break again?"): the fleet + soil dropdowns populate ONLY from
// this /bodies.json fetch. A SINGLE miss -- a flaky connection, or loading the page during a container
// rebuild's brief restart window -- used to leave PHY null with NO retry, so the dropdowns stayed empty
// until a manual reload. Make it self-healing: retry with backoff (and re-run on login, see refreshAuthState).
function loadBodies(attempt) {
  attempt = attempt || 0;
  const retry = () => {
    if (attempt < 5) { setTimeout(() => loadBodies(attempt + 1), 700 * (attempt + 1)); }
    // don't fail SILENTLY (Codex review): exhausted retries with no valid payload -> surface it so an empty
    // fleet/soil reads as a diagnosable error (e.g. /bodies.json 403/blocked), not a mystery blank dropdown.
    else if (typeof setQ === "function") setQ("⚠ could not load vehicle/soil data (/bodies.json) — reload to retry");
  };
  fetch("/bodies.json").then((r) => (r.ok ? r.json() : null)).then((d) => {
    if (d && d._vehicles) { PHY = d; showTerra(); estimate(); populateFleet(); }   // accept only a VALID payload
    else retry();                                                                   // 403 / empty / partial -> retry
  }).catch(() => retry());
}
loadBodies();
refreshProfiles();                                            // populate the saved-profiles dropdown
// ---- S-4: the Catalog (saved missions + custom structure templates) ---------------------------
async function refreshCatalog() {
  try {
    const ms = await (await fetch("/missions?" + wsParam())).json();   // #workspace: list the active namespace
    const ol = $("mslist"); ol.innerHTML = "";
    (ms.missions || []).forEach((m) => {
      const li = document.createElement("li");
      li.append(`${m.title || m.name} · ${m.body} · ${m.n_orders} orders `,
        mkbtn("⤓ load", async () => {
          const d = (await (await fetch(`/missions/${m.name}?` + wsParam())).json()).doc;
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
          await fetch(`/missions/${m.name}?` + wsParam(), { method: "DELETE", headers: apiHeaders() });
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
  const r = await fetch(`/missions/${encodeURIComponent(name)}?` + wsParam(), { method: "POST",
    headers: apiHeaders(), body: JSON.stringify({ body: sel.value, orders: ORDERS,
      keepouts: KEEPOUTS, precedence: parsePrec(), note: $("msnotes") ? $("msnotes").value : "",
      lander: { x: LANDER_P.x, y: LANDER_P.y } }) });
  if (r.status === 401) { setQ("⚠ API key required: Settings"); setView("settings"); return; }
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
  if (r.status === 401) { setQ("⚠ API key required: Settings"); setView("settings"); return; }
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

// Mission pipeline spine (#131/#132): the always-visible Site->...->Execute stepper above the app.
const STEP_TITLES = {
  site: "Site - choose the landing / work site (Plan, 1·Site)",
  fleet: "Fleet - set the rover count (Plan, 3·Fleet)",
  orders: "Orders - author build orders + keep-outs (Plan, 4·Plan)",
  solve: "Solve - plan the mission (Plan mission -> report)",
  review: "Review - the mission-control report",
  execute: "Execute - execution forecast, before uplink",
};
// council #4: the single primary button's label per step -- it NAMES the real next action + jumps to it.
const STEP_ACTION = {
  site: "Set a site", fleet: "Set the fleet", orders: "Add a build order",
  solve: "Plan the mission", review: "Open the report", execute: "Execute + watch",
};
// the first step whose REAL prerequisite is not yet satisfied -- data-driven (validateStep is the truth),
// no manual Done flag. This is the "current" step the primary button + the NEXT label point at.
function _currentStep() { return STEP_ORDER.find((s) => !validateStep(s).ok) || "execute"; }
function stepScrollTo(prefix) {                            // scroll the sidebar to a numbered section, opening it
  for (const h of document.querySelectorAll("#panel h3, #panel summary")) {
    if (h.textContent.trim().startsWith(prefix)) {
      const det = h.closest("details"); if (det) det.open = true;
      h.scrollIntoView({ behavior: "smooth", block: "start" }); return true;
    }
  }
  return false;
}
function _pulseQplan() {
  const b = $("qplan"); if (!b) return;
  b.classList.add("pulse"); setTimeout(() => b.classList.remove("pulse"), 1700);
}
// #170: the wizard step actions. Done VALIDATES + confirms the current step (red->green) and advances;
// Next just moves on; Reset un-confirms it (without wiping data). validateStep gates each on its real input.
function validateStep(step) {
  if (step === "site")    return (typeof CURRENT_SITE !== "undefined" && CURRENT_SITE) ? { ok: true } : { ok: false, msg: "choose a site first (1·Site)" };
  if (step === "fleet")   return ((+(($("vehcount") || {}).value) || 0) >= 1) ? { ok: true } : { ok: false, msg: "set at least one rover (3·Fleet)" };
  if (step === "orders")  return (ORDERS.length > 0 || KEEPOUTS.length > 0) ? { ok: true } : { ok: false, msg: "add at least one build order or keep-out" };
  if (step === "solve")   return (!!LAST_TIMELINE) ? { ok: true } : { ok: false, msg: "press “Plan mission → open report” to solve" };
  if (step === "review")  return (!!LAST_TIMELINE) ? { ok: true } : { ok: false, msg: "solve a plan before reviewing" };
  if (step === "execute") return (!!LAST_TIMELINE) ? { ok: true } : { ok: false, msg: "solve + review before execute" };
  return { ok: true };
}
function setWizStep(step) { WIZ_STEP = step; renderStepper(); }
// council #4: the manual Done/Next/Reset confirm flow is gone -- steps are data-driven (validateStep), and
// the single #wizgo primary jumps to _currentStep()'s real action. wizGo is its handler.
function wizGo() { goStep(_currentStep()); }
// #170: step -> sidebar sections. Clicking a step shows ONLY its sections (Aaron: "Site should pull up
// 1/2"); the rest collapse. The numbered sections (1·Site · 2·Contents · 3·Rovers · 4·Plan) are the
// collapsible <details> (sidebar 7->4 reorg: orders/solve/review/execute all live inside 4·Plan now).
// The step->section map is the pure window.STEWIE_PLAN_STEPPER module (single source of truth, unit-
// tested); ALL six steps map now (review/execute used to be no-ops, leaving the previous step's
// sections showing). The inline fallback keeps focusStep working if the module fails to load.
const STEP_SECTIONS = (typeof window !== "undefined" && window.STEWIE_PLAN_STEPPER)
  ? window.STEWIE_PLAN_STEPPER.STEP_SECTIONS
  : { site: ["1", "2"], fleet: ["3"], orders: ["4"], solve: ["4"], review: ["4"], execute: ["4"] };
function focusStep(step) {
  const want = (typeof window !== "undefined" && window.STEWIE_PLAN_STEPPER)
    ? window.STEWIE_PLAN_STEPPER.sectionsForStep(step)
    : (STEP_SECTIONS[step] || []);
  if (!want.length) return;                                  // unknown step: leave the sidebar untouched
  for (const det of document.querySelectorAll("#panel details")) {
    const sum = det.querySelector("summary"); if (!sum) continue;
    const m = sum.textContent.replace(/^\W+/, "").match(/^(\d)/);   // numbered pipeline section (the FS-21 drag-grip ⠿ precedes the number)
    if (m) det.open = want.includes(m[1]);                          // open this step's sections, collapse the rest
  }
}
function goStep(step) {
  setWizStep(step);                                         // #170: focus this step in the wizard
  const planned = !!LAST_TIMELINE;
  if ((step === "review" || step === "execute") && !planned) {   // can't review/execute before a plan exists
    setView("plan"); if (innerWidth <= 860) $("panel").classList.add("open");
    focusStep(step);                                        // reflect THIS step's sections, not the prior step's
    stepScrollTo("4 ·"); _pulseQplan();
    setQ("plan a mission first - press “Plan mission → open report”"); return;
  }
  if (step === "review") { setView("report"); return; }
  if (step === "execute") { setView("metrics"); return; }
  setView("plan");                                          // site / fleet / orders / solve all live in the Plan sidebar
  if (innerWidth <= 860) $("panel").classList.add("open");
  focusStep(step);                                          // #170: show ONLY this step's sidebar sections
  stepScrollTo(step === "site" ? "1 ·" : step === "fleet" ? "3 ·" : "4 ·");
  if (step === "solve") _pulseQplan();
}
function renderStepper() {
  const wrap = $("stepper"); if (!wrap) return;
  // council #4: DATA-DRIVEN -- a step lights green the moment its REAL prerequisite is satisfied
  // (validateStep), sequentially; the first unsatisfied step is "current", the rest are "locked". No
  // manual Done/Reset flag. The single #wizgo primary always names + jumps to current's real next action.
  const state = {}; let current = null;
  for (const s of STEP_ORDER) {
    if (!current && validateStep(s).ok) state[s] = "done";
    else if (!current) { state[s] = "current"; current = s; }
    else state[s] = "locked";
  }
  const allDone = !current;
  if (!current) current = "execute";
  const wl = $("wizstep"); if (wl) wl.textContent = allDone ? "READY" : current.toUpperCase();
  const viewStep = { plan: "orders", rehearse: "solve", report: "review", metrics: "execute",
                     nav: "review", perception: "review", release: "review" }[VIEW];
  wrap.querySelectorAll(".step").forEach((b) => {
    const s = b.dataset.step;
    b.className = "step " + (state[s] || "todo");
    if (s === current && !allDone) b.classList.add("current");
    if (s === viewStep) b.classList.add("viewactive");
    b.title = STEP_TITLES[s] || s;
  });
  const go = $("wizgo");
  if (go) go.textContent = allDone ? "Mission ready ✓" : ((STEP_ACTION[current] || "Continue") + " →");
  const co = $("conops"); if (co) co.textContent = "CONOPS — " + current.toUpperCase();
}
(function initStepper() {
  const wrap = $("stepper"); if (!wrap) return;
  wrap.querySelectorAll(".step").forEach((b) => { b.onclick = () => goStep(b.dataset.step); });
  if ($("wizgo")) $("wizgo").onclick = wizGo;                // council #4: ONE primary -> jump to the next real action
})();

// #126: the guided walkthrough -- discoverable via the stepper's Guide button (no auto-popup, so it
// never stacks over the sign-in screen); the sample CTA reuses the existing mission loader.
function openGuide() { if ($("guidemodal")) $("guidemodal").hidden = false; }
function closeGuide() { if ($("guidemodal")) $("guidemodal").hidden = true; }
if ($("guidebtn")) $("guidebtn").onclick = openGuide;
if ($("guide-close")) $("guide-close").onclick = closeGuide;
if ($("guidemodal")) $("guidemodal").addEventListener("click", (e) => { if (e.target.id === "guidemodal") closeGuide(); });
if ($("guide-sample")) $("guide-sample").onclick = () => {
  closeGuide(); setView("plan");
  const ss = $("qsample");
  if (ss && ss.options.length && $("qloadsample")) { if (!ss.value) ss.value = ss.options[0].value; $("qloadsample").click(); }
};

// tab-contextual left blocks (#131/#132 follow-up): mirror the last plan into the per-tab left content
// so #ctx-metrics/report/perception carry live status, not just "look in the pane ->" blurbs.
let LAST_TOTALS = null, LAST_PDF = null;
let LAST_VALIDATION = null;                               // FS-03: the last plan's validate_plan as-built verdict (Construction pane)
function renderCtxSummaries() {
  const t = LAST_TOTALS, m = $("ctxmet-sum"), r = $("ctxrep-sum"), pp = $("ctxperc-sum");
  if (m) m.innerHTML = t
    ? `<b>Last plan</b><br>cut ${(t.cut_kg / 1000).toFixed(1)} t &rarr; fill ${(t.fill_kg / 1000).toFixed(1)} t`
      + `<br>${(t.energy_J / 1e6).toFixed(1)} MJ &middot; ${t.charges || 0} recharge(s)`
      + `<br><span style="color:${t.feasible === false ? "#e8273f" : "#39ff14"}">${t.feasible === false ? "INFEASIBLE" : "feasible"}</span>`
      + (t.traverse_cap_deg != null ? ` &middot; &le;${t.traverse_cap_deg}&deg; slope` : "")
    : "Plan a mission to see its totals here.";
  if (r) r.innerHTML = LAST_PDF
    ? `Report ready &mdash; <a href="${LAST_PDF}" target="_blank" rel="noopener" style="color:var(--accent)">open PDF &#8599;</a>`
    : "No report yet.";
  if (pp) {
    const fk = (typeof LAST_LOCALIZATION !== "undefined" && LAST_LOCALIZATION) ? LAST_LOCALIZATION.fix_kinds : null;
    pp.innerHTML = fk
      ? `<b>Last localization fixes</b><br>DEM ${fk.dem || 0} &middot; beacon ${fk.beacon || 0} &middot; none ${fk.none || 0}`
      : "Plan a mission to see the perception fix mix.";
  }
}

loadBody("moon"); restoreDraft(); estimate(); renderQueue(); renderKeepouts(); drawPlan(); updateLocator(); setView("plan");  // #177: restore the auto-saved working draft before the first render
focusStep(WIZ_STEP);                                         // #170: open the current wizard step's sidebar sections on boot
_bootComplete = true;                                     // UX-01: boot done -> 401s may now nudge sign-in
CMD_AUTH.start();                                         // FS-17: claim/observe single command authority across tabs
