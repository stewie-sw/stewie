/* viz3d/scalebar.js -- dynamic scale bar + north arrow + sun arrow + cursor readout HUD for the
 * standalone lunar 3D viewer (viz3d.js). PURE perspective/scale math (node-tested) + a thin DOM HUD
 * writer. UMD (browser <script> global + `node --test`), mirroring gis/qwc2/js/mission/reqGuard.js and
 * stewie/server/web/assets/geofmt.js -- no framework coupling, no ES import so it loads as a classic
 * <script> alongside the viz3d ES module.
 *
 * ---------------------------------------------------------------------------------------------------
 * WHY the metric scale is TRUE-AT-TILE (design STEWIE_viz3d_geospatial_upgrade_2026-07-09.md sec.2/sec.8)
 * ---------------------------------------------------------------------------------------------------
 * STEWIE renders the DEM in IAU_2015:30135 south-polar-stereographic PROJECTED METRES (x0+lx, y0+ly),
 * reprojected SERVER-SIDE (dart/dem_reproject.py). It is NOT Web Mercator: there is no per-latitude
 * sec(phi) pixel stretch to undo. So one screen pixel maps to a genuine ground-metre count set purely by
 * the perspective camera at the look-at point -- the scale bar is true at the tile with latitudeFactor
 * === 1. The latitudeFactor() hook is exposed (a) to keep the projection assumption HONEST and legible,
 * and (b) so a future genuinely-Mercator raster or a globe path can plug a real correction; STEWIE's
 * default path never calls it with mode 'mercator'.
 *
 * ---------------------------------------------------------------------------------------------------
 * viz3d.js INTEGRATION NOTE (main thread wires this; DO NOT edit viz3d.js from here)
 * ---------------------------------------------------------------------------------------------------
 * 1. LOAD ORDER: add `<script src="/assets/viz3d/scalebar.js"></script>` in the page <head> BEFORE the
 *    `<script type="module" src="/assets/viz3d.js">`. Classic scripts run before deferred ES modules, so
 *    `window.STEWIE_SCALEBAR` is present when viz3d.js first renders. viz3d.js reads the global; it is
 *    never `import`ed (UMD, no ES export). Provide 1..4 HUD container <div>s positioned over the canvas
 *    (CSS: absolute, pointer-events:none) -- one may host all four widgets, or one each.
 *
 * 2. EACH FRAME (inside _loop, after camera.lookAt): the orbit camera's look-at distance is `S.dist`, its
 *    vertical FOV is `S.camera.fov` (DEGREES in three.js -> convert), the drawing-buffer height is
 *    `S.renderer.domElement.height` (or container.clientHeight). Compute + render the scale bar:
 *        const SB = window.STEWIE_SCALEBAR;
 *        const mpp = SB.metresPerPixel({ cameraDistance_m: S.dist,
 *                                        fovYRad: S.camera.fov * Math.PI / 180,
 *                                        viewportHeightPx: S.container.clientHeight });
 *        SB.renderScaleBar(scaleBarDom, SB.niceScaleBar(mpp, 120));
 *    (S.dist is the exact distance from camera to S.target -- see _loop's cx/cy/cz -- so it IS the
 *     look-at cameraDistance the perspective math wants. Throttle to ~4 Hz if you like; the math is cheap.)
 *
 * 3. NORTH ARROW: the camera forward, ground-projected, is proportional to (-cos(S.az), -sin(S.az)) in
 *    (E=+x, N=+z). Its compass bearing (clockwise from North) is:
 *        const headingRad = Math.atan2(-Math.cos(S.az), -Math.sin(S.az));   // atan2(forwardE, forwardN)
 *        SB.renderNorthArrow(northDom, headingRad);
 *    The needle then points to true North on a screen whose "up" is the camera forward, spinning as you
 *    orbit. (VERIFY THIS SIGN IN A LIVE BROWSER -- see the report; it is the one claim most worth a check.)
 *
 * 4. SUN ARROW: viz3d already tracks the sun as `S._sunAz` / `S._sunEl` DEGREES (setSun). Render absolute
 *    (North-up) azimuth + elevation-driven length:
 *        SB.renderSunArrow(sunDom, S._sunAz * Math.PI/180, S._sunEl * Math.PI/180);
 *    To make the sun arrow CAMERA-RELATIVE (same rose as the north arrow), pass the camera heading to the
 *    pure helper yourself: SB.sunArrowRotationRad(sunAz, headingRad) and drive the DOM from that.
 *
 * 5. READOUT: reuse the EXISTING hover pick. viz3d.js already calls onHover(cb) with
 *    {e_m, n_m, elev_m, lat, lon} (see _hoverPick). In that callback, add slope if you have it (or omit),
 *    and write the HUD:
 *        STEWIE_VIZ.onHover((h) => { existingHudUpdate(h);
 *            SB.renderReadout(readoutDom, { lon: h && h.lon, lat: h && h.lat,
 *                elev_m: h && h.elev_m, slope_deg: h && h.slope_deg, e_m: h && h.e_m, n_m: h && h.n_m }); });
 *    A null/absent field renders as an em-dash placeholder, so a hover-off (cb(null)) clears cleanly.
 *
 * All four renderers are IDEMPOTENT: first call builds the nodes (createElement/textContent, never an
 * HTML-string sink), later calls update text/transform in place. Safe to call every frame. They no-op when
 * the dom arg is missing OR when there is no `document` (node) -- importing the module in node never crashes.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { root.STEWIE_SCALEBAR = factory(); }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var TWO_PI = Math.PI * 2;

  // Wrap an angle (rad) into (-PI, PI]. Keeps CSS rotations continuous across the +/-180 seam.
  function normalizeAngleRad(a) {
    if (!isFinite(a)) return 0;
    a = a % TWO_PI;
    if (a <= -Math.PI) a += TWO_PI;
    else if (a > Math.PI) a -= TWO_PI;
    return a === 0 ? 0 : a;   // collapse -0 to +0 (clean CSS + strict-equal friendly)
  }

  // ---- CORE perspective scale math -----------------------------------------------------------------
  // Ground metres spanned by ONE screen pixel at the look-at point of a perspective camera. The vertical
  // world extent visible on the plane a perpendicular distance `cameraDistance_m` down the view axis is
  // 2*d*tan(fovY/2); dividing by the viewport pixel height gives metres-per-pixel. This is exact for a
  // surface facing the camera at the look-at depth; the terrain is treated as locally planar there (an
  // honest first-order HUD approximation, standard for a scale bar). Returns 0 on degenerate input so the
  // caller (niceScaleBar) can render an empty bar rather than propagate NaN.
  function metresPerPixel(opts) {
    opts = opts || {};
    var d = +opts.cameraDistance_m, fov = +opts.fovYRad, vh = +opts.viewportHeightPx;
    if (!isFinite(d) || !isFinite(fov) || !isFinite(vh) || d <= 0 || fov <= 0 || fov >= Math.PI || vh <= 0) {
      return 0;
    }
    return (2 * d * Math.tan(fov / 2)) / vh;
  }

  // Round a target on-screen length to a 1/2/5 * 10^n "nice" ground distance whose pixel width sits
  // nearest `targetPx`. Returns { label, lengthPx, metres }. label auto-switches m <-> km at 1000 m.
  function niceScaleBar(mPerPx, targetPx) {
    if (targetPx == null) targetPx = 120;
    if (!isFinite(mPerPx) || mPerPx <= 0 || !isFinite(targetPx) || targetPx <= 0) {
      return { label: "", lengthPx: 0, metres: 0 };
    }
    var targetM = targetPx * mPerPx;
    var exp = Math.floor(Math.log10(targetM));
    var mults = [1, 2, 5], cand = [];
    for (var e = exp - 1; e <= exp + 1; e++) {
      var base = Math.pow(10, e);
      for (var i = 0; i < mults.length; i++) cand.push(mults[i] * base);
    }
    cand.sort(function (a, b) { return a - b; });   // ascending -> smaller distance wins an exact tie
    var best = cand[0], bestErr = Infinity;
    for (var k = 0; k < cand.length; k++) {
      var px = cand[k] / mPerPx, err = Math.abs(px - targetPx);
      if (err < bestErr) { bestErr = err; best = cand[k]; }
    }
    return { label: formatDistance(best), lengthPx: best / mPerPx, metres: best };
  }

  // A 1/2/5*10^n metre distance -> a clean "<n> m" / "<n> km" label (>= 1000 m switches to km).
  function formatDistance(metres) {
    if (!isFinite(metres) || metres <= 0) return "";
    if (metres >= 1000) return trimNum(metres / 1000) + " km";
    return trimNum(metres) + " m";
  }
  function trimNum(n) {
    if (Number.isInteger(n)) return String(n);
    return String(Number(n.toFixed(6)));   // strip fp noise; keeps 0.5 / 0.2 / 0.1 exact
  }

  // Projection scale hook. STEWIE renders in polar-stereographic PROJECTED metres (true-at-tile), so the
  // default is 1 -- NOT a Web-Mercator sec(phi) stretch. mode 'mercator' returns the genuine Mercator
  // correction 1/cos(phi) ONLY for a hypothetical Mercator raster (STEWIE never calls it). See the header.
  function latitudeFactor(lat_deg, mode) {
    if (mode === "mercator") {
      var c = Math.cos((+lat_deg) * Math.PI / 180);
      return (isFinite(c) && Math.abs(c) > 1e-9) ? 1 / c : 1;
    }
    return 1;   // 'stereo' (default) / 'none' -> projected metres are already true at the tile
  }

  // ---- arrow angle math (pure) ---------------------------------------------------------------------
  // North needle rotation (rad, CSS-clockwise, 0 = screen-up) on a screen whose "up" is the camera
  // forward. North (bearing 0) sits at -heading; as the camera heading turns clockwise, North swings CCW.
  function northArrowRotationRad(headingRad) { return normalizeAngleRad(-headingRad); }

  // Sun needle rotation (rad, CSS-clockwise, 0 = screen-up). Absolute North-up frame by default
  // (rotation = sun azimuth); pass the camera heading to render it in the camera-relative rose.
  function sunArrowRotationRad(sunAzRad, cameraHeadingRad) {
    return normalizeAngleRad((+sunAzRad || 0) - (cameraHeadingRad ? +cameraHeadingRad : 0));
  }

  // Fraction of the sun DIRECTION vector lying in the ground plane = cos(elevation), in [0,1]. A sun on
  // the horizon (el=0) -> 1 (fully in-plane, long shadow-ward arrow); at zenith (el=90) -> 0. Real
  // geometry, used to scale the sun arrow length so a grazing sun reads as a long low arrow. Clamped so a
  // below-horizon sun (el<0) still returns 0..1.
  function sunGroundProjection(sunElRad) {
    var c = Math.cos(+sunElRad || 0);
    if (!isFinite(c)) return 0;
    return c < 0 ? 0 : (c > 1 ? 1 : c);
  }

  // ---- readout formatting (pure) -------------------------------------------------------------------
  // Structured lon/lat/elev/slope/local-E-N strings for the cursor readout. A null / non-finite field
  // renders as the em-dash placeholder (matches geofmt.fmtLL). The DOM writer (renderReadout) maps these
  // rows to nodes; keeping the formatting pure makes it node-testable without a browser.
  function _num(v, dec, suffix) {
    return (v == null || !isFinite(+v)) ? "—" : (+v).toFixed(dec) + suffix;
  }
  function formatReadout(r) {
    r = r || {};
    return [
      { key: "lat", label: "Lat", value: _num(r.lat, 4, "°") },
      { key: "lon", label: "Lon", value: _num(r.lon, 4, "°") },
      { key: "elev", label: "Elev", value: _num(r.elev_m, 1, " m") },
      { key: "slope", label: "Slope", value: _num(r.slope_deg, 1, "°") },
      { key: "e", label: "E", value: _num(r.e_m, 1, " m") },
      { key: "n", label: "N", value: _num(r.n_m, 1, " m") },
    ];
  }

  // ---- DOM HUD writers (createElement / textContent only; no HTML-string sink) ---------------------
  function _hasDom(dom) { return !!dom && typeof document !== "undefined"; }
  function _hud(dom) { if (!dom.__stewieHud) dom.__stewieHud = {}; return dom.__stewieHud; }
  function _el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }

  // Dynamic scale bar: a fixed-width horizontal rule + its distance label. Hidden when lengthPx <= 0.
  function renderScaleBar(dom, bar) {
    if (!_hasDom(dom)) return;
    bar = bar || {};
    var h = _hud(dom), s = h.scaleBar;
    if (!s) {
      var wrap = _el("div", "stewie-sb");
      wrap.style.position = "relative";
      wrap.style.pointerEvents = "none";
      var rule = _el("div", "stewie-sb-rule");
      rule.style.height = "4px";
      rule.style.background = "#e8eef7";
      rule.style.borderLeft = "2px solid #e8eef7";
      rule.style.borderRight = "2px solid #e8eef7";
      rule.style.boxSizing = "border-box";
      var label = _el("div", "stewie-sb-label");
      label.style.font = "600 12px Inter, system-ui, sans-serif";
      label.style.color = "#e8eef7";
      label.style.marginTop = "3px";
      label.style.textAlign = "center";
      label.style.textShadow = "0 1px 2px rgba(0,0,0,0.8)";
      wrap.appendChild(rule);
      wrap.appendChild(label);
      dom.appendChild(wrap);
      s = h.scaleBar = { wrap: wrap, rule: rule, label: label };
    }
    var len = +bar.lengthPx;
    if (!isFinite(len) || len <= 0 || !bar.label) {
      s.wrap.style.display = "none";
      return;
    }
    s.wrap.style.display = "block";
    s.rule.style.width = Math.round(len) + "px";
    s.label.style.width = Math.round(len) + "px";
    s.label.textContent = bar.label;
  }

  // North arrow: a rotatable needle + a fixed "N" glyph. Rotation from northArrowRotationRad(headingRad).
  function renderNorthArrow(dom, headingRad) {
    if (!_hasDom(dom)) return;
    var h = _hud(dom), a = h.northArrow;
    if (!a) {
      var wrap = _el("div", "stewie-north");
      wrap.style.position = "relative";
      wrap.style.width = "40px";
      wrap.style.height = "40px";
      wrap.style.pointerEvents = "none";
      var needle = _el("div", "stewie-north-needle");
      needle.style.position = "absolute";
      needle.style.left = "50%";
      needle.style.top = "50%";
      needle.style.width = "0";
      needle.style.height = "0";
      needle.style.borderLeft = "5px solid transparent";
      needle.style.borderRight = "5px solid transparent";
      needle.style.borderBottom = "18px solid #ff5a4d";
      needle.style.transformOrigin = "50% 100%";
      var glyph = _el("div", "stewie-north-glyph");
      glyph.style.position = "absolute";
      glyph.style.left = "0";
      glyph.style.top = "0";
      glyph.style.width = "100%";
      glyph.style.textAlign = "center";
      glyph.style.font = "700 11px Inter, system-ui, sans-serif";
      glyph.style.color = "#e8eef7";
      glyph.style.textShadow = "0 1px 2px rgba(0,0,0,0.8)";
      glyph.textContent = "N";
      wrap.appendChild(needle);
      wrap.appendChild(glyph);
      dom.appendChild(wrap);
      a = h.northArrow = { wrap: wrap, needle: needle };
    }
    var deg = northArrowRotationRad(headingRad) * 180 / Math.PI;
    // center the needle base at the widget center, then rotate about that base
    a.needle.style.transform = "translate(-50%,-100%) rotate(" + deg.toFixed(2) + "deg)";
  }

  // Sun arrow: a needle whose bearing is the sun azimuth and whose length shrinks as the sun climbs
  // (cos(elevation)); dimmed/short when the sun is near zenith or below the horizon.
  function renderSunArrow(dom, sunAzRad, sunElRad) {
    if (!_hasDom(dom)) return;
    var h = _hud(dom), a = h.sunArrow;
    if (!a) {
      var wrap = _el("div", "stewie-sun");
      wrap.style.position = "relative";
      wrap.style.width = "40px";
      wrap.style.height = "40px";
      wrap.style.pointerEvents = "none";
      var needle = _el("div", "stewie-sun-needle");
      needle.style.position = "absolute";
      needle.style.left = "50%";
      needle.style.top = "50%";
      needle.style.width = "3px";
      needle.style.height = "18px";
      needle.style.background = "#ffd27a";
      needle.style.borderRadius = "2px";
      needle.style.transformOrigin = "50% 100%";
      var glyph = _el("div", "stewie-sun-glyph");
      glyph.style.position = "absolute";
      glyph.style.left = "0";
      glyph.style.top = "0";
      glyph.style.width = "100%";
      glyph.style.textAlign = "center";
      glyph.style.font = "700 12px Inter, system-ui, sans-serif";
      glyph.style.color = "#ffd27a";
      glyph.style.textShadow = "0 1px 2px rgba(0,0,0,0.8)";
      glyph.textContent = "☀";   // sun glyph
      wrap.appendChild(needle);
      wrap.appendChild(glyph);
      dom.appendChild(wrap);
      a = h.sunArrow = { wrap: wrap, needle: needle };
    }
    var deg = sunArrowRotationRad(sunAzRad) * 180 / Math.PI;
    var proj = sunGroundProjection(sunElRad);            // 0 (zenith/below-horizon) .. 1 (horizon)
    var scaleY = 0.25 + 0.75 * proj;                     // never fully vanish so the widget stays visible
    a.needle.style.transform = "translate(-50%,-100%) rotate(" + deg.toFixed(2) + "deg) scaleY(" + scaleY.toFixed(3) + ")";
    a.needle.style.opacity = ((sunElRad <= 0) ? 0.35 : (0.5 + 0.5 * proj)).toFixed(2);
  }

  // Cursor readout: one row per formatReadout() field, label + value. Idempotent -- rows are built once,
  // then only their value text is rewritten (a hover-off passes nulls -> em-dashes, clearing the panel).
  function renderReadout(dom, r) {
    if (!_hasDom(dom)) return;
    var rows = formatReadout(r);
    var h = _hud(dom), ro = h.readout;
    if (!ro) {
      var wrap = _el("div", "stewie-readout");
      wrap.style.font = "500 12px ui-monospace, SFMono-Regular, Menlo, monospace";
      wrap.style.color = "#e8eef7";
      wrap.style.pointerEvents = "none";
      wrap.style.lineHeight = "1.5";
      wrap.style.textShadow = "0 1px 2px rgba(0,0,0,0.8)";
      ro = h.readout = { wrap: wrap, cells: {} };
      for (var i = 0; i < rows.length; i++) {
        var row = _el("div", "stewie-readout-row");
        var lab = _el("span", "stewie-readout-label");
        lab.style.display = "inline-block";
        lab.style.width = "44px";
        lab.style.opacity = "0.75";
        lab.textContent = rows[i].label;
        var val = _el("span", "stewie-readout-value");
        row.appendChild(lab);
        row.appendChild(val);
        wrap.appendChild(row);
        ro.cells[rows[i].key] = val;
      }
      dom.appendChild(wrap);
    }
    for (var j = 0; j < rows.length; j++) {
      var cell = ro.cells[rows[j].key];
      if (cell) cell.textContent = rows[j].value;
    }
  }

  return {
    metresPerPixel: metresPerPixel,
    niceScaleBar: niceScaleBar,
    formatDistance: formatDistance,
    latitudeFactor: latitudeFactor,
    normalizeAngleRad: normalizeAngleRad,
    northArrowRotationRad: northArrowRotationRad,
    sunArrowRotationRad: sunArrowRotationRad,
    sunGroundProjection: sunGroundProjection,
    formatReadout: formatReadout,
    renderScaleBar: renderScaleBar,
    renderNorthArrow: renderNorthArrow,
    renderSunArrow: renderSunArrow,
    renderReadout: renderReadout,
  };
});
