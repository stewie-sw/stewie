// viz3d/frame.js -- the FRAME MANAGER for the geospatial viz3d upgrade (design
// design/STEWIE_viz3d_geospatial_upgrade_2026-07-09.md §1/§2/§5). The ONE transform every renderable
// position (mesh vertices, km grid, lon/lat graticule, plotted markers, icons, paths) routes through:
//
//     const f = makeFrame({ bodyRadius: 1737400 });      // MOON_ME (IAU_2015:30135), configurable per body
//     f.setLonLatGrid(coarseGrid);                        // one batched metres->lonlat grid (design §8 trap #3)
//     f.setMeanElev(tileMeanElev);                        // exaggerate ABOUT the mean (design §8 balloon trap)
//     const p = f.place(e_m, n_m, elev_m);                // {x,y,z} -- ENU (flat) or GLOBE (curved cap)
//     f.setMode('globe');                                 // flat<->globe is a single re-place() of the same source metres
//
// Flat<->globe is a single re-place() of the SAME source order-local metres+elev, so all overlays stay
// registered by construction: nothing bakes an ENU position, everything asks the frame. PURE + deterministic,
// NO THREE import (viz3d.js adapts the plain {x,y,z} into a THREE.Vector3). Plain UMD (browser <script> +
// node --test), matching reqGuard.js / globe_ellipsoid.js -- no framework coupling.
//
// The CRS transform (30135 <-> lon/lat) is NEVER re-derived here: metresToLonLat bilinear-interpolates a
// small grid the client sampled ONCE from the server /dem/site_lonlat (design §8 trap #1 -- the #1 offset
// bug). This module only does the render-space geometry (ENU scaling; body-fixed sphere placement; the
// recentre+orient that keeps the tile patch near the world origin so Three.js float32 stays jitter-free).
//
// ------------------------------------------------------------------------------------------------------
// viz3d.js INTEGRATION NOTE (the main thread wires this; DO NOT edit viz3d.js here):
//
// (a) FETCH META + BUILD THE COARSE GRID (once per loadSite, after the heightfield_full meta is known):
//       const sm = await (await _fetchT('/dem/site_meta?site=' + encodeURIComponent(S.site), DEM_READ_TIMEOUT_MS)).json();
//       // sm = { crs, bounds_m:{x0,y0,x1,y1}, pixel_size_m, width, height, tile_m:{x,y},
//       //        nodata:'NaN', vertical_datum:{name,sphere_radius_m,z_semantics}, origin_lonlat:{lon,lat} }
//       // Sample a small K x K lon/lat grid over the FULL tile-pixel-metre extent [0, tile_m] via the
//       // AUTHORITATIVE server transform (NO client proj4). K ~ 9 (81 batched /dem/site_lonlat calls, cached
//       // per site) is plenty -- the 30135 warp is smooth over a 10 km tile; bilinear is exact to << 1 px.
//       const K = 9, txm = sm.tile_m.x, tym = sm.tile_m.y, lon = new Array(K*K), lat = new Array(K*K);
//       for (let j=0;j<K;j++) for (let i=0;i<K;i++) {
//         const X = i/(K-1)*txm, Y = j/(K-1)*tym;
//         const d = await (await _fetchT('/dem/site_lonlat?x='+X+'&y='+Y+'&site='+encodeURIComponent(S.site), HOVER_TIMEOUT_MS)).json();
//         lon[j*K+i] = d.lon; lat[j*K+i] = d.lat;                    // row-major idx = row*K + col
//       }
//       FRAME.setLonLatGrid({ x0:0, y0:0, dE:txm/(K-1), dN:tym/(K-1), cols:K, rows:K, lon, lat });
//       FRAME.setOrigin(meta.x0, meta.y0);                          // the window origin from heightfield_full headers
//       FRAME.setMeanElev((meta.z_min + meta.z_max) / 2);          // or the true grid mean; exaggerate about it
//       FRAME.setVex(S.vex); FRAME.bodyRadius is fixed at makeFrame time (MOON_ME).
//
// (b) ROUTE EVERY PLACEMENT THROUGH frame.place(e_m, n_m, elev_m):
//       - mesh: in _buildMesh, replace `pos[k*3]=i*step; pos[k*3+1]=hh*vex; pos[k*3+2]=j*step` with
//               `const p = FRAME.place(i*step, j*step, z[k]); pos[k*3]=p.x; pos[k*3+1]=p.y; pos[k*3+2]=p.z;`
//               (pass ABSOLUTE elev z[k], not hh=z-zmin -- exaggerate() re-references it about the mean).
//               MASK nodata: skip / drop triangles where Number.isNaN(z[k]) (design §8, nodata='NaN' from site_meta).
//       - km grid + graticule (_lineOnSurface / _redrapeGraticule): replace the hand-built
//               `new THREE.Vector3(lx, heightAt(lx,ly)*S.vex + yLift, ly)` with
//               `const p = FRAME.place(lx, ly, heightAt(lx,ly)+S.meta.z_min + drapeEps); new THREE.Vector3(p.x,p.y,p.z)`.
//       - markers / measure points: same place(lx, ly, elev_m + r).
//       Because place() is the ONLY source of render coords, a mode/vex change is a pure re-place() -- the
//       overlays never de-register (design §8 trap #2).
//
// (c) WIRE A GLOBE/FLAT TOGGLE (new control, calls into the frame + rebuilds):
//       function setGlobe(on) { FRAME.setMode(on ? 'globe' : 'enu'); _buildMesh();
//                               if (S._gridOn) buildMetricGrid(); if (S._gratGroup) _redrapeGraticule();
//                               if (S._plotGroup) rebuildPlots(); if (S._measureGroup) _redrawMeasure();
//                               // reframe the camera: globe recentres the patch to ~origin, so S.target -> (0,0,0)
//                               S.target.set(0,0,0); }
//       setVertExag(k) already re-lifts everything; add FRAME.setVex(k) at its top so the frame's exaggeration
//       matches the mesh. Expose STEWIE_VIZ.setGlobe + a getter get globe(){return FRAME.mode==='globe'}.
//
// Failure modes the frame closes (design §8): #1 client CRS drift (grid from the server, never re-derived);
// #2 overlay de-registration (one place(), no baked ENU); #3 per-vertex server calls (cached bilinear grid);
// #4 exaggeration balloon on globe (exaggerate about the mean radius); #7 float precision on the sphere
// (worldFromBody recentres the ~1.74e6 m body-fixed coords to the tile origin so float32 stays small).
// ------------------------------------------------------------------------------------------------------
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }   // node --test
  else { root.STEWIEFrame = factory(); }                                              // browser (window)
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var MOON_ME = 1737400.0;          // MOON_ME sphere radius, IAU_2015:30135 (design §5; per-body configurable)
  var DEG = Math.PI / 180.0;

  function _clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

  // Body-fixed (ECEF-style) position on a sphere of radius `bodyRadius`, at selenographic lat/lon (deg) with
  // an already-exaggerated radial displacement `rDisp` (metres above the sphere). PURE, no frame state, so it
  // is directly unit-testable against hand-computed values. Formula per design §5:
  //   r = bodyRadius + rDisp;  x = r*cos(lat)*cos(lon);  y = r*cos(lat)*sin(lon);  z = r*sin(lat)
  function bodyFixedR(bodyRadius, latDeg, lonDeg, rDisp) {
    var lat = latDeg * DEG, lon = lonDeg * DEG;
    var r = bodyRadius + rDisp;
    var cl = Math.cos(lat);
    return { x: r * cl * Math.cos(lon), y: r * cl * Math.sin(lon), z: r * Math.sin(lat) };
  }

  // makeFrame(opts) -> the frame manager. opts (all optional):
  //   mode 'enu'|'globe' (default 'enu'), vex vertical-exaggeration (1), scale S ENU render scale (1, viz3d uses 1),
  //   bodyRadius (MOON_ME), meanElev tile mean elevation the exaggeration is referenced to (0),
  //   x0/y0 (or origin:{x0,y0}) the window's tile-pixel-metre origin added to the order-local e_m/n_m (0,0).
  function makeFrame(opts) {
    opts = opts || {};
    var mode = (opts.mode === "globe") ? "globe" : "enu";
    var vex = (opts.vex != null) ? +opts.vex : 1;
    var S = (opts.scale != null) ? +opts.scale : 1;
    var BODY_R = (opts.bodyRadius != null) ? +opts.bodyRadius : MOON_ME;
    var meanElev = (opts.meanElev != null) ? +opts.meanElev : 0;
    var x0 = (opts.x0 != null) ? +opts.x0 : ((opts.origin && opts.origin.x0) || 0);
    var y0 = (opts.y0 != null) ? +opts.y0 : ((opts.origin && opts.origin.y0) || 0);
    var grid = null;      // coarse metres->lonlat bilinear grid (client-sampled from /dem/site_lonlat)
    var ref = null;       // cached recentre+ENU-basis reference for worldFromBody (built lazily)

    // Vertical exaggeration ABOUT the mean elevation (design §8 balloon trap): at vex=1 this is the identity,
    // so a globe tile at the mean radius does not inflate as vex rises -- only the relief about the mean scales.
    function exaggerate(h) { return meanElev + vex * (h - meanElev); }

    // Bilinear-interpolate the client-sampled lon/lat grid at absolute tile-pixel metres (E, N). The grid is
    //   { x0, y0, dE, dN, cols, rows, lon:[], lat:[] }  (lon/lat row-major, idx = row*cols + col; cols/rows >= 2).
    // NO CRS math here -- the grid already carries the authoritative server transform (design §8 trap #1).
    function metresToLonLat(E, N) {
      if (!grid) { throw new Error("frame.metresToLonLat: setLonLatGrid() required (no client-side CRS re-derivation)"); }
      var c = grid.cols, r = grid.rows;
      var fi = _clamp((E - grid.x0) / grid.dE, 0, c - 1);
      var fj = _clamp((N - grid.y0) / grid.dN, 0, r - 1);
      var i0 = Math.min(Math.floor(fi), c - 2), j0 = Math.min(Math.floor(fj), r - 2);
      var tx = fi - i0, ty = fj - j0;
      var i00 = j0 * c + i0, i10 = i00 + 1, i01 = i00 + c, i11 = i01 + 1;
      function lerp2(a) {
        var top = a[i00] + (a[i10] - a[i00]) * tx;
        var bot = a[i01] + (a[i11] - a[i01]) * tx;
        return top + (bot - top) * ty;
      }
      return { lat: lerp2(grid.lat), lon: lerp2(grid.lon) };
    }

    // Body-fixed placement using the frame's radius + its exaggeration (about the mean).
    function bodyFixed(latDeg, lonDeg, h) { return bodyFixedR(BODY_R, latDeg, lonDeg, exaggerate(h)); }

    // Build the recentre+orient reference: the tile ORIGIN (x0,y0) -> lon/lat -> local ENU basis + the
    // body-fixed origin point R0. worldFromBody then expresses any body-fixed point in this local ENU frame
    // (x=East, y=up, z=North), which (1) keeps float32 small (design §8 trap #7) and (2) makes the globe cap
    // share ENU's axes so a flat<->globe toggle stays visually registered.
    function _buildRef() {
      var ll = metresToLonLat(x0, y0);
      var lat = ll.lat * DEG, lon = ll.lon * DEG;
      var clat = Math.cos(lat), slat = Math.sin(lat), clon = Math.cos(lon), slon = Math.sin(lon);
      ref = {
        up:    { x: clat * clon,       y: clat * slon,       z: slat },   // radial (local up)
        east:  { x: -slon,             y: clon,              z: 0 },      // +East
        north: { x: -slat * clon,      y: -slat * slon,      z: clat },   // +North
        R0: bodyFixedR(BODY_R, ll.lat, ll.lon, exaggerate(meanElev)),     // origin point (radius BODY_R+meanElev)
      };
    }

    // Recentre + orient a body-fixed point into the tile-origin local ENU frame. Returns {x:East, y:up, z:North}.
    function worldFromBody(p) {
      if (!ref) { _buildRef(); }
      var dx = p.x - ref.R0.x, dy = p.y - ref.R0.y, dz = p.z - ref.R0.z;
      return {
        x: dx * ref.east.x + dy * ref.east.y + dz * ref.east.z,
        y: dx * ref.up.x + dy * ref.up.y + dz * ref.up.z,
        z: dx * ref.north.x + dy * ref.north.y + dz * ref.north.z,
      };
    }

    // THE ONE TRANSFORM. Order-local metres (e_m East, n_m North from the window origin) + absolute elevation
    // elev_m -> a render position {x,y,z}. ENU: flat, x=E*S, y=exaggerate(elev)*S, z=N*S (current viz3d behaviour
    // at S=1). GLOBE: curved cap -- metres->lonlat (cached grid) -> body-fixed sphere -> recentred to the tile
    // origin. Same source metres in both modes, so a mode switch re-places every overlay identically.
    function place(e_m, n_m, elev_m) {
      if (mode !== "globe") {
        return { x: e_m * S, y: exaggerate(elev_m) * S, z: n_m * S };
      }
      var ll = metresToLonLat(e_m + x0, n_m + y0);
      return worldFromBody(bodyFixed(ll.lat, ll.lon, elev_m));
    }

    var api = {
      place: place,
      bodyFixed: bodyFixed,             // frame-aware (uses vex/meanElev/bodyRadius)
      exaggerate: exaggerate,
      metresToLonLat: metresToLonLat,
      worldFromBody: worldFromBody,
      setMode: function (m) { mode = (m === "globe") ? "globe" : "enu"; api.mode = mode; return api; },
      setVex: function (k) { vex = +k; api.vex = vex; ref = null; return api; },     // relief scale changed
      setMeanElev: function (m) { meanElev = +m; ref = null; return api; },          // exaggeration reference moved
      setOrigin: function (nx0, ny0) { x0 = +nx0; y0 = +ny0; ref = null; return api; }, // window origin moved
      setLonLatGrid: function (g) { grid = g; ref = null; return api; },             // new cached transform grid
      // readable state (the design accesses frame.mode / frame.vex / frame.bodyRadius directly):
      mode: mode, vex: vex, bodyRadius: BODY_R, meanElev: meanElev,
    };
    return api;
  }

  return { makeFrame: makeFrame, bodyFixed: bodyFixedR, MOON_ME: MOON_ME };
});
