/* artemis.stewie.space/viz -- standalone FULL-RESOLUTION lunar 3D terrain viewer (Haworth default; site-parametrized).
 *
 * Aaron's reference pattern (rasterio DEM -> height grid -> Three.js PlaneGeometry vertices), at NATIVE
 * resolution: fetch /dem/heightfield_full (compact float32 BINARY, not the decimated n<=257 /dem/heightfield),
 * build the relief, drape a SELECTABLE analysis raster (/dem/heightfield_full/layer.png -- registered
 * cell-for-cell over the SAME window), overlay an accurate coordinate readout (order metres + selenographic
 * lon/lat via /dem/site_lonlat) and gridlines (a metric km grid + the curved lon/lat graticule from
 * /dem/graticule). Reuses three3d.js's geometry/normals/hand-rolled-orbit patterns. Vendored THREE, NO CDN
 * (the CSP blocks external hosts). Exposed on window.STEWIE_VIZ.
 */
import * as THREE from "/assets/three.module.min.js";

const S = { ready: false, vex: 1, layerKind: "elevation", site: "haworth", meta: null, z: null,
  // task #79: measure/waypoints tool -- click-to-add points (order-local lx/ly + absolute elev_m + lat/lon,
  // filled in a beat later by the debounced /dem/site_lonlat lookup, same as the hover + plot tools).
  _measureOn: false, _measurePts: [], _measureGroup: null, _onMeasure: null };
const WIRE = { color: 0x35e0d0, base: 0.10, dim: 0.04 };
// Above this per-side vertex count, THREE.WireframeGeometry's internal edge Set overflows V8's 2^24
// element cap (a full-res 2000x2000 grid has ~24M edges -> "Set maximum size exceeded"), and a wireframe
// that dense is an opaque mass anyway. So the wire is built LAZILY (only when toggled on) and skipped
// above this size. The relief mesh itself renders fine at full res (Uint32 indices); only the wire is capped.
const WIRE_MAX_N = 1200;

// [GW-11 geospatial] THE placement transform (viz3d/frame.js, UMD global window.STEWIEFrame). Every
// renderable position (mesh verts, km grid, graticule, markers, measure) routes through
// FRAME.place(e_m, n_m, absolute_elev_m) so a flat<->globe toggle is a pure re-place() and overlays never
// de-register (design STEWIE_viz3d_geospatial_upgrade §8). frame.js exaggerates ABOUT the mean elevation,
// so place() ENU returns an ABSOLUTE-datum render Y (meanElev + vex*(elev-meanElev)), NOT the old
// zmin-relative hh*vex. If the module never loaded (script tag absent) a minimal ENU-identity fallback keeps
// the viewer rendering flat (globe disabled). NOTE: /dem/site_meta is 401 on the live backend (not
// key-injected), so the coarse metres->lonlat grid is sampled over the RENDERED WINDOW via /dem/site_lonlat
// (key-injected, already used by _hoverPick) -- see _configureFrame; no client-side proj4.
const FRAME = (typeof window !== "undefined" && window.STEWIEFrame && window.STEWIEFrame.makeFrame)
  ? window.STEWIEFrame.makeFrame({ bodyRadius: 1737400 })   // MOON_ME sphere (IAU_2015:30135)
  : (function () {                       // fallback: a REAL flat frame (vex + meanElev honoured; no globe) so a
      let _vex = 1, _mean = 0;           // host that hasn't loaded frame.js yet (e.g. the /ide plugin) keeps a
      return {                            // fully working flat viewer -- exaggeration + hover intact, no regression.
        place: function (e, n, el) { return { x: e, y: _mean + _vex * (el - _mean), z: n }; },
        exaggerate: function (h) { return _mean + _vex * (h - _mean); },
        setVex: function (k) { _vex = +k; }, setMeanElev: function (m) { _mean = +m; },
        setOrigin: function () {}, setLonLatGrid: function () {}, setMode: function () {}, mode: "enu",
      };
    })();
const FRAME_LOADED = !!(typeof window !== "undefined" && window.STEWIEFrame && window.STEWIEFrame.makeFrame);

// [systems-eng] bounded fetch: a hung/slow backend read (heightfield_full is a few MB) must ABORT after
// `ms` and reject legibly, never hang the viewer forever. Self-contained here -- viz3d.js is a standalone
// /assets ES module, separate from the qwc2 mission bundle's fetchWithTimeout.js (same contract, no shared
// import across the two bundles). The timer clears the instant the request settles; on timeout it aborts the
// socket AND rejects on its own so the bound holds even if the runtime's fetch ignores the signal.
const HEIGHTFIELD_TIMEOUT_MS = 60000;   // few-MB native-resolution binary: a generous bound for a big transfer
const DEM_READ_TIMEOUT_MS = 20000;      // graticule (JSON polylines)
const HOVER_TIMEOUT_MS = 15000;         // debounced selenographic lon/lat lookup
const LAYER_TIMEOUT_MS = 45000;         // draped analysis raster (server-side O(P^2..P^3) illumination/PSR render can stall)
function _fetchT(url, ms) {
  const ctrl = (typeof AbortController !== "undefined") ? new AbortController() : null;
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      if (ctrl) { try { ctrl.abort(); } catch (e) { /* free the socket */ } }
      reject(new Error("request timed out after " + ms + " ms: " + url));
    }, ms);
    fetch(url, ctrl ? { signal: ctrl.signal } : {}).then((r) => {
      if (settled) return;
      settled = true; clearTimeout(timer); resolve(r);
    }, (e) => {
      if (settled) return;
      settled = true; clearTimeout(timer); reject(e);
    });
  });
}

// [GW-11] a monotonically-incrementing session generation for the async plot/measure lonlat emits, plus a
// render-loop token. `_plotGen` is bumped on every loadSite (site switch) and dispose so an in-flight
// /dem/site_lonlat lookup started against the OLD site/context is dropped instead of emitting a wrong-site
// waypoint (mirrors the _llGen hover guard). `_rafToken` ensures only the latest _loop() rAF chain survives a
// re-mount, so a second mount (or a mount racing a pre-dispose pending rAF) never double-runs the loop.
let _plotGen = 0, _rafToken = 0;

function mount(container) {
  if (S.ready || S.renderer) { dispose(); }   // already mounted (or a pre-dispose remount) -> tear the old renderer/loop down first, so exactly one exists
  const w = container.clientWidth || 900, h = container.clientHeight || 600;
  S.container = container;
  S.scene = new THREE.Scene();
  S.scene.background = new THREE.Color(0x05060c);
  S.camera = new THREE.PerspectiveCamera(48, w / h, 0.1, 4000000);
  S.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  S.renderer.setSize(w, h);
  S.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  container.replaceChildren();          // safe DOM clear (MT-03: no HTML-injection sink)
  container.appendChild(S.renderer.domElement);

  S.sun = new THREE.DirectionalLight(0xfff4e8, 2.4);
  S.scene.add(S.sun);
  S.scene.add(S.sun.target);
  S.scene.add(new THREE.AmbientLight(0x3a4456, 0.8));
  S.group = new THREE.Group();
  S.scene.add(S.group);
  S.raycaster = new THREE.Raycaster();

  S.az = Math.PI * 0.25; S.el = Math.PI * 0.34; S.dist = 8000;
  S.target = new THREE.Vector3(0, 0, 0);
  _bindControls(container);
  S._ro = new ResizeObserver(() => _resize());
  S._ro.observe(container);
  S.ready = true;
  _loop(++_rafToken);            // token-gated: a superseded loop (older token) bails instead of double-rendering
  return true;
}

function _resize() {
  if (!S.renderer || !S.container) return;
  const w = S.container.clientWidth || 900, h = S.container.clientHeight || 600;
  S.renderer.setSize(w, h, false);
  S.camera.aspect = w / h; S.camera.updateProjectionMatrix();
}

function _bindControls(el) {
  let drag = false, px = 0, py = 0, dx0 = 0, dy0 = 0;
  el.style.cursor = "grab";
  // [GW-11] scope every listener to an AbortController so dispose() removes them all at once (ctrl.abort()) --
  // an embedded host (the /ide floating card) that mounts/unmounts on task change must not accumulate a fresh
  // pointer/wheel handler set on the container per re-mount. (Older runtimes without AbortController: no signal,
  // same pre-existing behavior; jsdom + evergreen browsers support it.)
  const ctrl = (typeof AbortController !== "undefined") ? new AbortController() : null;
  S._ctrlAbort = ctrl;
  const sig = ctrl ? ctrl.signal : undefined;
  const opt = sig ? { signal: sig } : undefined;
  el.addEventListener("pointerdown", (e) => { drag = true; px = e.clientX; py = e.clientY; dx0 = e.clientX; dy0 = e.clientY; el.style.cursor = "grabbing"; el.setPointerCapture(e.pointerId); }, opt);
  el.addEventListener("pointerup", (e) => {
    drag = false; el.style.cursor = "grab"; try { el.releasePointerCapture(e.pointerId); } catch (_) { /* */ }
    // "Stay the spin" (task #77): the drag-orbit above stays fully active even with Shift held -- no mode
    // toggle. A Shift+CLICK that did not drag (pointer moved < 5px since pointerdown) plots the active
    // Mission-Plan tool at the raycast point; a Shift+DRAG only orbits (the pointermove handler already ran),
    // it never plots. (task #79) A plain (non-Shift) click-without-drag while measure mode is on instead
    // drops a measure/waypoint point -- mutually exclusive on the shift key, so a #77 plot-click never also
    // measures and a measure-click never also plots. Either way a real orbit-drag does neither.
    const moved = Math.hypot(e.clientX - dx0, e.clientY - dy0);
    if (e.shiftKey) {
      if (moved < 5) { _plotAt(el, e); }
    } else if (S._measureOn && moved < 5) {
      _measureAt(el, e);
    }
  }, opt);
  el.addEventListener("pointermove", (e) => {
    if (!drag) { if (S._onHover) _hoverPick(el, e); return; }
    S.az -= (e.clientX - px) * 0.006;
    S.el = Math.max(0.05, Math.min(1.5, S.el - (e.clientY - py) * 0.006));
    px = e.clientX; py = e.clientY;
  }, opt);
  el.addEventListener("wheel", (e) => { e.preventDefault(); S.dist = Math.max(30, Math.min(3000000, S.dist * (1 + Math.sign(e.deltaY) * 0.12))); }, sig ? { passive: false, signal: sig } : { passive: false });
}

function _loop(token) {
  if (!S.ready || token !== _rafToken) return;   // stopped (dispose set ready=false) or superseded by a newer mount's loop
  requestAnimationFrame(() => _loop(token));
  const cx = S.target.x + S.dist * Math.cos(S.el) * Math.cos(S.az);
  const cy = S.target.y + S.dist * Math.sin(S.el);
  const cz = S.target.z + S.dist * Math.cos(S.el) * Math.sin(S.az);
  S.camera.position.set(cx, cy, cz);
  S.camera.lookAt(S.target);
  S.renderer.render(S.scene, S.camera);
  _renderHud();
}

// [GW-11] scale bar + north + sun HUD (viz3d/scalebar.js, window.STEWIE_SCALEBAR). Throttled to ~6 Hz -- the
// perspective math is cheap + the DOM writers are idempotent, but per-frame DOM churn is wasteful. No-op when
// no HUD is wired (an embedded host that never called setHud) or scalebar.js didn't load.
function _renderHud() {
  const SB = (typeof window !== "undefined") ? window.STEWIE_SCALEBAR : null;
  if (!S._hud || !SB || !S.camera || !S.container) return;
  if (((S._hudTick = (S._hudTick || 0) + 1) % 10) !== 0) return;   // ~6 Hz at 60fps
  const mpp = SB.metresPerPixel({ cameraDistance_m: S.dist, fovYRad: S.camera.fov * Math.PI / 180,
    viewportHeightPx: S.container.clientHeight || 600 });
  if (S._hud.scale) SB.renderScaleBar(S._hud.scale, SB.niceScaleBar(mpp, 120));
  // north: ground-projected camera forward is (-cos az, -sin az) in (E=+x, N=+z); bearing = atan2(fwdE, fwdN).
  const heading = Math.atan2(-Math.cos(S.az), -Math.sin(S.az));
  if (S._hud.north) SB.renderNorthArrow(S._hud.north, heading);
  // sun arrow in the SAME camera-relative rose as north (subtract heading; renderSunArrow is North-up otherwise)
  // so it aligns with the cast shadows the operator sees as the view orbits.
  if (S._hud.sun) SB.renderSunArrow(S._hud.sun, (S._sunAz ?? 135) * Math.PI / 180 - heading, (S._sunEl ?? 20) * Math.PI / 180);
}

// [GW-11] wire the HUD container nodes {scale, north, sun}. The page owns the DOM; viz3d only renders into
// whatever it is given (decoupled from any specific page). Pass null/{} to clear.
function setHud(dom) { S._hud = dom || null; }

// ---- full-res load + mesh ------------------------------------------------------------------------
// Fetch the native float32 heightfield BINARY + its X-Dem-* header meta, then build the relief. Returns the
// meta (also stashed on S) so the page can show the resolution / z-range. Any window/site is renderable.
async function loadSite(site, opts) {
  opts = opts || {};
  S.site = site || S.site || "haworth";
  _plotGen++;            // site/context switch: invalidate any in-flight plot/measure lonlat emit from the prior site
  const qp = new URLSearchParams({ site: S.site });
  if (opts.window_m != null) qp.set("window_m", String(opts.window_m));
  if (opts.x0 != null) qp.set("x0", String(opts.x0));
  if (opts.y0 != null) qp.set("y0", String(opts.y0));
  if (opts.max_dim != null) qp.set("max_dim", String(opts.max_dim));
  const r = await _fetchT("/dem/heightfield_full?" + qp.toString(), HEIGHTFIELD_TIMEOUT_MS);
  if (!r.ok) { throw new Error("heightfield_full " + r.status + " for site " + S.site); }
  const meta = {
    site: r.headers.get("X-Dem-Site") || S.site,
    n: +r.headers.get("X-Dem-N"), native_n: +r.headers.get("X-Dem-Native-N"),
    cell_m: +r.headers.get("X-Dem-Cell-M"), window_m: +r.headers.get("X-Dem-Window-M"),
    step_m: +r.headers.get("X-Dem-Step-M"), stride: +r.headers.get("X-Dem-Stride"),
    x0: +r.headers.get("X-Dem-X0"), y0: +r.headers.get("X-Dem-Y0"),
    z_min: +r.headers.get("X-Dem-Z-Min"), z_max: +r.headers.get("X-Dem-Z-Max"),
    lod: r.headers.get("X-Dem-Lod") === "1",
  };
  const z = new Float32Array(await r.arrayBuffer());
  if (z.length !== meta.n * meta.n) { throw new Error("heightfield payload " + z.length + " != n^2 " + meta.n); }
  S.meta = meta; S.z = z;
  await _configureFrame(meta);   // [GW-11] window-grid metres->lonlat + FRAME origin/meanElev/vex (globe-ready)
  clearPlots();          // task #77: plot markers are site-local (order-frame lx/ly) -> drop stale ones on a site switch
  clearMeasure();        // task #79: measure waypoints are also site-local (order-frame lx/ly) -> drop stale ones
  _buildMesh();
  _frameCamera();        // [GW-11] frame the tile CENTER via FRAME.place (mode-agnostic: flat or globe)
  setLayer(S.layerKind);
  if (S._gridOn) buildMetricGrid();
  if (S._gratOn) loadGraticule();
  return meta;
}

// [GW-11] Configure FRAME for the loaded tile. site_meta is 401 on the live backend (and not key-injected),
// so the coarse K×K metres->lonlat grid is sampled over the RENDERED WINDOW via /dem/site_lonlat (which IS
// key-injected + already used by _hoverPick) -- no client proj4. Cached per (site,window). Flat mode never
// reads the grid, so a fetch failure only disables globe (S._frameReady=false); the flat viewer still renders.
async function _configureFrame(meta) {
  FRAME.setOrigin(meta.x0, meta.y0);
  FRAME.setMeanElev((meta.z_min + meta.z_max) / 2);
  FRAME.setVex(S.vex);
  if (!FRAME_LOADED) { S._frameReady = false; return; }
  if (!S._frameGridCache) S._frameGridCache = {};
  const key = S.site + "@" + meta.x0 + "," + meta.y0 + "," + meta.window_m;
  if (S._frameGridCache[key]) { FRAME.setLonLatGrid(S._frameGridCache[key]); S._frameReady = true; return; }
  const K = 9, win = meta.window_m, lon = new Array(K * K), lat = new Array(K * K);
  try {
    const jobs = [];
    for (let j = 0; j < K; j++) for (let i = 0; i < K; i++) {
      const X = meta.x0 + (i / (K - 1)) * win, Y = meta.y0 + (j / (K - 1)) * win, idx = j * K + i;
      jobs.push(_fetchT("/dem/site_lonlat?x=" + X + "&y=" + Y + "&site=" + encodeURIComponent(S.site), HOVER_TIMEOUT_MS)
        .then((r) => r.json())
        .then((d) => { if (!d || !d.ok) throw new Error("site_lonlat !ok"); lon[idx] = d.lon; lat[idx] = d.lat; }));
    }
    await Promise.all(jobs);
    const grid = { x0: meta.x0, y0: meta.y0, dE: win / (K - 1), dN: win / (K - 1), cols: K, rows: K, lon: lon, lat: lat };
    S._frameGridCache[key] = grid;
    FRAME.setLonLatGrid(grid);
    S._frameReady = true;
  } catch (_) {
    S._frameReady = false;   // globe unavailable; flat ENU still renders (place() flat path ignores the grid)
  }
}

// [GW-11] Point the camera at the tile CENTER through FRAME.place so framing is correct in BOTH flat
// (y=meanElev) and globe (recentred cap) modes, at the same 1.35x window standoff.
function _frameCamera() {
  const m = S.meta; if (!m) return;
  const c = FRAME.place(m.window_m / 2, m.window_m / 2, (m.z_min + m.z_max) / 2);
  S.target.set(c.x, c.y, c.z);
  S.dist = m.window_m * 1.35;
}

function _buildMesh() {
  const m = S.meta, z = S.z, n = m.n, step = m.step_m, zmin = m.z_min;
  const span = Math.max(1e-6, m.z_max - m.z_min);
  if (S.mesh) { S.group.remove(S.mesh); S.mesh.geometry.dispose(); S.mesh.material.dispose(); S.mesh = null; }
  if (S.wire) { S.group.remove(S.wire); S.wire.geometry.dispose(); S.wire.material.dispose(); S.wire = null; }
  const pos = new Float32Array(n * n * 3), col = new Float32Array(n * n * 3), uv = new Float32Array(n * n * 2);
  const baseH = new Float32Array(n * n);
  const nanMask = new Uint8Array(n * n);   // [GW-11] 1 where z is nodata (NaN) -> its triangles are dropped
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const k = j * n + i, zk = z[k], isNan = !(zk === zk), hh = isNan ? 0 : zk - zmin;
      baseH[k] = hh; nanMask[k] = isNan ? 1 : 0;
      const p = FRAME.place(i * step, j * step, isNan ? zmin : zk);   // [GW-11] absolute elev; exaggerate-about-mean
      pos[k * 3] = p.x; pos[k * 3 + 1] = p.y; pos[k * 3 + 2] = p.z;   // flat: x=E,y=up,z=N | globe: curved cap
      uv[k * 2] = i / (n - 1); uv[k * 2 + 1] = j / (n - 1);                            // North-up drape (flipud raster)
      const t = hh / span;
      col[k * 3] = 0.26 + 0.50 * t; col[k * 3 + 1] = 0.27 + 0.36 * t; col[k * 3 + 2] = 0.30 + 0.12 * t;
    }
  }
  S.baseH = baseH; S._nanMask = nanMask;
  const idx = [];
  for (let j = 0; j < n - 1; j++) {
    for (let i = 0; i < n - 1; i++) {
      const a = j * n + i, b = a + 1, c = a + n, d = c + 1;
      // [GW-11] drop a triangle touching a nodata vertex (masked terrain edge); Haworth has none -> no-op there
      if (!nanMask[a] && !nanMask[c] && !nanMask[b]) idx.push(a, c, b);
      if (!nanMask[b] && !nanMask[c] && !nanMask[d]) idx.push(b, c, d);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  geo.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  // 32-bit indices are only needed when a VERTEX INDEX can exceed 65535, i.e. when the vertex count n*n > 65536
  // -- not when the index COUNT (6*(n-1)^2) does. Gate on n*n so medium grids (~n=105..255) keep a 2-byte Uint16
  // buffer (half the index VRAM/upload); a plain array lets three pick Uint16 whenever the max index fits.
  geo.setIndex(n * n > 65536 ? new THREE.Uint32BufferAttribute(idx, 1) : idx);
  geo.computeVertexNormals();
  // [GW-11] DoubleSide: the globe cap's ENU->(x,y,z) mapping is left-handed relative to the flat frame, which
  // flips the effective triangle winding so single-sided normals would face INTO the body (terrain goes black
  // in globe mode). DoubleSide lights whichever face the camera sees, in both modes; a heightfield is never
  // meaningfully viewed from beneath, so the cost is nil.
  const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.96, metalness: 0.0, side: THREE.DoubleSide });
  S.mesh = new THREE.Mesh(geo, mat);
  S.group.add(S.mesh);
  S.wire = null;                     // built lazily + size-guarded (_buildWire) -- see WIRE_MAX_N
  if (S._wireOn) _buildWire();
  setSun(S._sunAz ?? 135, S._sunEl ?? 20);
}

// Build the wireframe overlay from the current mesh geometry, but ONLY when it is small enough that
// WireframeGeometry's edge Set stays under V8's cap (WIRE_MAX_N). Returns whether a wire now exists.
function _buildWire() {
  if (S.wire) { S.group.remove(S.wire); S.wire.geometry.dispose(); S.wire.material.dispose(); S.wire = null; }
  if (!S.mesh || !S.meta || S.meta.n > WIRE_MAX_N) return false;
  try {
    const op = (S.layerKind !== "elevation") ? WIRE.dim : WIRE.base;
    S.wire = new THREE.LineSegments(new THREE.WireframeGeometry(S.mesh.geometry),
      new THREE.LineBasicMaterial({ color: WIRE.color, transparent: true, opacity: op }));
    S.wire.visible = !!S._wireOn;
    S.group.add(S.wire);
    return true;
  } catch (_) { S.wire = null; return false; }   // belt-and-suspenders if the Set still overflows
}

// bilinear height (metres above z_min) at order-local (lx, ly)
function heightAt(lx, ly) {
  const m = S.meta; if (!m || !S.z) return 0;
  const n = m.n, step = m.step_m, z = S.z, zmin = m.z_min;
  let fc = lx / step, fr = ly / step;
  fc = Math.max(0, Math.min(n - 1.001, fc)); fr = Math.max(0, Math.min(n - 1.001, fr));
  const c0 = Math.floor(fc), r0 = Math.floor(fr), tc = fc - c0, tr = fr - r0;
  const z00 = z[r0 * n + c0], z01 = z[r0 * n + c0 + 1], z10 = z[(r0 + 1) * n + c0], z11 = z[(r0 + 1) * n + c0 + 1];
  return (1 - tr) * ((1 - tc) * z00 + tc * z01) + tr * ((1 - tc) * z10 + tc * z11) - zmin;
}

// ---- draped analysis raster (registered over the SAME window) -------------------------------------
function setLayer(kind) {
  S.layerKind = kind || "elevation";
  if (!S.mesh) return;
  const mat = S.mesh.material;
  if (S.wire) S.wire.material.opacity = (S.layerKind !== "elevation" && S._wireOn) ? WIRE.dim : (S._wireOn ? WIRE.base : 0);
  if (S.layerKind === "elevation") {
    if (mat.map) { mat.map.dispose(); mat.map = null; }
    mat.vertexColors = true; mat.color.setHex(0xffffff); mat.needsUpdate = true;
    return;
  }
  const m = S.meta;
  // The "dem" drape is labeled "Hillshade (315/45)" in the picker (viz_haworth_page.js), and dem.py renders
  // layer.png?kind=dem at whatever sun it is handed -- so pin dem's sun to 315/45 to match the label. The other
  // sun-following kinds (illumination/cost) use the LIVE sun sliders (default 135/20, set by _buildMesh->setSun
  // before any layer request). The old `?? 315`/`?? 45` fallbacks were dead (setSun always runs first).
  const fixedHill = (S.layerKind === "dem");
  const qp = new URLSearchParams({ site: S.site, window_m: m.window_m, x0: m.x0, y0: m.y0, kind: S.layerKind,
    sun_az: fixedHill ? 315 : Math.round(S._sunAz ?? 135), sun_el: fixedHill ? 45 : Math.round(S._sunEl ?? 20) });
  // [systems-eng] bounded layer read: layer.png can trigger a server-side O(P^2..P^3) illumination/PSR render
  // that stalls -- route the fetch through _fetchT (LAYER_TIMEOUT_MS) so a hang ABORTS and reverts to elevation
  // (the onError path), mirroring every other read in this module. The fetched bytes are then decoded via a blob
  // object URL + TextureLoader (preserves the exact flipY/colorSpace drape orientation); the local decode can't
  // hang, and the object URL is revoked either way so nothing leaks.
  const url = "/dem/heightfield_full/layer.png?" + qp.toString();
  const onErr = () => { if (S.layerKind === kind) { if (S._onLayerError) S._onLayerError(kind); setLayer("elevation"); } };
  _fetchT(url, LAYER_TIMEOUT_MS)
    .then((r) => { if (!r.ok) throw new Error("layer.png " + r.status + " for kind " + kind); return r.blob(); })
    .then((blob) => {
      const obj = URL.createObjectURL(blob);
      const revoke = () => { try { URL.revokeObjectURL(obj); } catch (_) { /* */ } };
      new THREE.TextureLoader().load(obj, (tex) => {
        revoke();
        if (!S.mesh || S.layerKind !== kind) { tex.dispose(); return; }
        tex.colorSpace = THREE.SRGBColorSpace; tex.minFilter = THREE.LinearFilter; tex.magFilter = THREE.LinearFilter;
        const mm = S.mesh.material;
        if (mm.map) mm.map.dispose();
        mm.map = tex; mm.vertexColors = false; mm.color.setHex(0xffffff); mm.needsUpdate = true;
      }, undefined, () => { revoke(); onErr(); });
    })
    .catch(onErr);
}

function setVertExag(k) {
  k = Math.max(1, Math.min(5, +k || 1));
  S.vex = k;
  FRAME.setVex(k);                                  // [GW-11] keep the frame's exaggeration in lockstep
  if (!S.mesh || !S.baseH) return;
  const pos = S.mesh.geometry.attributes.position, bh = S.baseH, zmin = S.meta.z_min;
  if (FRAME.mode === "globe") {
    // globe: radial displacement scales x,y,z -> re-place every vertex (in place, keeps geometry + drape)
    const n = S.meta.n, step = S.meta.step_m;
    for (let j = 0, kk = 0; j < n; j++) for (let i = 0; i < n; i++, kk++) {
      const pp = FRAME.place(i * step, j * step, bh[kk] + zmin);
      pos.array[kk * 3] = pp.x; pos.array[kk * 3 + 1] = pp.y; pos.array[kk * 3 + 2] = pp.z;
    }
  } else {
    // flat: only Y changes -> cheap per-vertex re-lift through the frame's (absolute-datum) exaggeration
    for (let i = 0; i < bh.length; i++) pos.array[i * 3 + 1] = FRAME.exaggerate(bh[i] + zmin);
  }
  pos.needsUpdate = true; S.mesh.geometry.computeVertexNormals();
  if (S._wireOn) _buildWire();          // rebuild the wire against the re-lifted geometry (size-guarded)
  if (S._gridOn) buildMetricGrid();     // re-drape the grid at the new relief
  if (S._gratGroup) _redrapeGraticule();
  // task #77: re-place each plotted marker onto the re-exaggerated surface (full place() -- globe needs x,z too).
  if (S._plotGroup) {
    S._plotGroup.children.forEach((mk) => {
      const pp = FRAME.place(mk.userData.lx, mk.userData.ly, heightAt(mk.userData.lx, mk.userData.ly) + zmin);
      mk.position.set(pp.x, pp.y + mk.userData.r, pp.z);
    });
  }
  // task #79: full rebuild so BOTH the markers AND the connecting polyline re-drape onto the re-exaggerated surface.
  if (S._measureGroup) _redrawMeasure();
}

function setWireframe(on) {
  S._wireOn = !!on;
  if (on && !S.wire) _buildWire();      // lazy: only pay the WireframeGeometry cost when first toggled on
  if (S.wire) { S.wire.visible = on; S.wire.material.opacity = on ? ((S.layerKind !== "elevation") ? WIRE.dim : WIRE.base) : 0; }
}

function setSun(azDeg, elDeg) {
  S._sunAz = azDeg; S._sunEl = elDeg;
  if (!S.sun || !S.meta) { return; }
  const a = azDeg * Math.PI / 180, e = Math.max(2, elDeg) * Math.PI / 180;
  const win = S.meta.window_m, R = win * 2, cx = win / 2, cz = win / 2;
  S.sun.position.set(cx + R * Math.cos(e) * Math.sin(a), R * Math.sin(e), cz + R * Math.cos(e) * Math.cos(a));
  if (S.sun.target) { S.sun.target.position.set(cx, 0, cz); S.sun.target.updateMatrixWorld(); }
  // the "dem" drape is sun-pinned to 315/45 (see setLayer) so a sun move no longer re-requests it; only the
  // genuinely sun-following drapes re-render on a sun change.
  if (S.layerKind === "hillshade" || S.layerKind === "illumination") setLayer(S.layerKind);
  // [GW-11] sun-dependent draped overlays (illumination/cost/hillshade) re-fetch at the new sun geometry.
  if (S._layerList && S._layerList.some((l) => l && l.sunDependent)) _buildOverlays();
}

// ---- [GW-11] draped LAYER STACK: N transparent analysis-raster overlays composited over the base relief.
// The page owns the stack MODEL (viz3d/layers.js makeLayerStack) + the panel; viz3d renders whatever ordered,
// visible layer list it is handed. Each overlay SHARES the base mesh geometry (so it follows a vex/globe
// re-place for free) with its own MeshBasicMaterial{map,transparent,opacity,depthWrite:false,polygonOffset
// -(i+1)} at renderOrder i+1 -> it draws over the relief (renderOrder 0) in stack order. Textures are cached
// by (id + sun for sun-dependent kinds) so panel edits / globe toggles never re-hit the backend.
let _layerGen = 0;
function _layerKey(lyr) {
  return lyr.id + (lyr.sunDependent ? "|" + Math.round(S._sunAz ?? 135) + "," + Math.round(S._sunEl ?? 20) : "");
}
function _disposeLayerGroup() {
  if (!S._layerGroup) return;
  S.group.remove(S._layerGroup);
  S._layerGroup.children.forEach((o) => { if (o.material) o.material.dispose(); });   // shared geometry + cached textures survive
  S._layerGroup = null;
}
function _buildOverlays() {
  _disposeLayerGroup();
  if (!S.mesh || !S._layerList) return;
  const drapes = S._layerList.filter((l) => l && l.render !== "base" && l.sourceUrl);
  if (!drapes.length) return;
  setLayer("elevation");                          // any active stack -> base stays the relief; overlays composite on top
  const grp = new THREE.Group(); S._layerGroup = grp; S.group.add(grp);
  if (!S._layerTex) S._layerTex = {};
  const gen = ++_layerGen;
  drapes.forEach((lyr, i) => {
    const place = (tex) => {
      if (gen !== _layerGen || !S.mesh || S._layerGroup !== grp) return;    // superseded by a newer _buildOverlays
      const om = new THREE.Mesh(S.mesh.geometry, new THREE.MeshBasicMaterial({
        map: tex, transparent: true, opacity: lyr.opacity, depthWrite: false,
        polygonOffset: true, polygonOffsetFactor: -(i + 1), polygonOffsetUnits: -(i + 1), side: THREE.DoubleSide }));
      om.renderOrder = i + 1;
      grp.add(om);
    };
    const key = _layerKey(lyr);
    if (S._layerTex[key]) { place(S._layerTex[key]); return; }
    let url = lyr.sourceUrl;
    if (lyr.sunDependent) url += "&sun_az=" + Math.round(S._sunAz ?? 135) + "&sun_el=" + Math.round(S._sunEl ?? 20);
    _fetchT(url, LAYER_TIMEOUT_MS)
      .then((r) => { if (!r.ok) throw new Error("layer.png " + r.status + " for " + lyr.kind); return r.blob(); })
      .then((blob) => {
        const obj = URL.createObjectURL(blob);
        new THREE.TextureLoader().load(obj, (tex) => {
          try { URL.revokeObjectURL(obj); } catch (_) { /* */ }
          tex.colorSpace = THREE.SRGBColorSpace; tex.minFilter = THREE.LinearFilter; tex.magFilter = THREE.LinearFilter;
          S._layerTex[key] = tex;
          place(tex);
        }, undefined, () => { try { URL.revokeObjectURL(obj); } catch (_) { /* */ } if (S._onLayerError) S._onLayerError(lyr.kind); });
      })
      .catch(() => { if (S._onLayerError) S._onLayerError(lyr.kind); });
  });
}
// Public: render an ordered, visible list of layer models (viz3d/layers.js visibleOrdered()) as the drape stack.
function renderLayerStack(layers) { S._layerList = Array.isArray(layers) ? layers.slice() : []; _buildOverlays(); }
function clearLayerStack() { S._layerList = null; _disposeLayerGroup(); }

// ---- gridlines: metric km grid (pure STEWIE_VIZGRID) draped on the surface ------------------------
function _lineOnSurface(coords2, subdiv, color, yLift) {
  const pts = [], zmin = (S.meta && S.meta.z_min) || 0, lift = (yLift || 1.0);
  for (let s = 0; s < coords2.length - 1; s++) {
    const [ax, ay] = coords2[s], [bx, by] = coords2[s + 1];
    for (let t = 0; t <= subdiv; t++) {
      const f = t / subdiv, lx = ax + (bx - ax) * f, ly = ay + (by - ay) * f;
      const p = FRAME.place(lx, ly, heightAt(lx, ly) + zmin);   // [GW-11] absolute elev through the frame
      pts.push(new THREE.Vector3(p.x, p.y + lift, p.z));         // lift along local render up (drape above surface)
    }
  }
  const g = new THREE.BufferGeometry().setFromPoints(pts);
  return new THREE.Line(g, new THREE.LineBasicMaterial({ color: color, transparent: true, opacity: 0.85 }));
}

function buildMetricGrid() {
  _disposeGroup(S._gridGroup); S._gridGroup = null;
  if (!S.meta || !window.STEWIE_VIZGRID) return;
  const grp = new THREE.Group();
  const g = window.STEWIE_VIZGRID.metricGrid(S.meta.window_m);
  const sub = Math.max(8, Math.min(240, Math.round(S.meta.window_m / Math.max(1, g.step) * 2)));
  g.lines.forEach((ln) => grp.add(_lineOnSurface(ln.coords, sub, 0x8899aa, 1.2)));
  S._gridGroup = grp; S.group.add(grp);
}

function setMetricGrid(on) { S._gridOn = !!on; if (on) buildMetricGrid(); else { _disposeGroup(S._gridGroup); S._gridGroup = null; } }

// ---- gridlines: the curved lon/lat graticule (server /dem/graticule, mirrors graticule.js) --------
async function loadGraticule() {
  if (!S.meta) return;
  const qp = new URLSearchParams({ site: S.site, window_m: S.meta.window_m, x0: S.meta.x0, y0: S.meta.y0 });
  try {
    const r = await _fetchT("/dem/graticule?" + qp.toString(), DEM_READ_TIMEOUT_MS);
    if (!r.ok) { S._gratData = null; return; }
    const body = await r.json();
    S._gratData = (body && body.ok) ? body.lines : null;
  } catch (_) { S._gratData = null; }
  _redrapeGraticule();
}

// Small offscreen-canvas text label (task #79): rasterizes `text` in `color` onto a CanvasTexture-backed
// THREE.Sprite (screen-facing, depthTest off so it never z-fights/disappears behind the relief). One label
// per graticule line is all that's needed here, so this stays a minimal one-off, not a general text system.
// Returns {sprite, aspect} so the caller can scale it to a readable world size without distorting the text.
function _textSprite(text, color) {
  const px = 64;                                      // rasterize at a fixed pixel size, scale in world-space
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  const font = "600 " + px + "px Inter, system-ui, sans-serif";
  ctx.font = font;
  const pad = px * 0.3;
  canvas.width = Math.max(1, Math.ceil(ctx.measureText(text).width + pad * 2));
  canvas.height = Math.ceil(px * 1.4);
  ctx.font = font;                                     // canvas resize resets 2D context state -- reapply
  ctx.textBaseline = "middle";
  ctx.fillStyle = "#" + ("000000" + color.toString(16)).slice(-6);
  ctx.fillText(text, pad, canvas.height / 2);
  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true });
  return { sprite: new THREE.Sprite(mat), aspect: canvas.width / canvas.height };
}

function _redrapeGraticule() {
  _disposeGroup(S._gratGroup); S._gratGroup = null;
  if (!S._gratData || !S._gratOn) return;
  const grp = new THREE.Group();
  const win = (S.meta && S.meta.window_m) ? S.meta.window_m : 1000;
  const labelW = win * 0.05;                            // readable world size relative to the tile window
  S._gratData.forEach((ln) => {
    if (!ln.coords || ln.coords.length < 2) return;
    const color = ln.kind === "meridian" ? 0x6cd8ff : 0xffd27a;
    grp.add(_lineOnSurface(ln.coords, 1, color, 2.0));      // graticule is already densely sampled
    if (ln.label) {
      const [x0, y0] = ln.coords[0];
      const t = _textSprite(ln.label, color);
      t.sprite.scale.set(labelW, labelW / t.aspect, 1);
      const lp = FRAME.place(x0, y0, heightAt(x0, y0) + ((S.meta && S.meta.z_min) || 0));   // [GW-11]
      t.sprite.position.set(lp.x, lp.y + 6.0, lp.z);   // a small offset above the line's yLift
      grp.add(t.sprite);
    }
  });
  S._gratGroup = grp; S.group.add(grp);
}

function setGraticule(on) { S._gratOn = !!on; if (on) { if (S._gratData) _redrapeGraticule(); else loadGraticule(); } else { _disposeGroup(S._gratGroup); S._gratGroup = null; } }

// ---- accurate coordinate readout (order metres + selenographic lon/lat) ---------------------------
function _raycastSurface(el, e) {
  if (!S.mesh || !S.raycaster || !S.meta) return null;
  const rect = el.getBoundingClientRect();
  const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
  S.raycaster.setFromCamera(ndc, S.camera);
  const hits = S.raycaster.intersectObject(S.mesh, false);
  if (!hits.length) return null;
  // [GW-11] recover ORDER-LOCAL (e_m,n_m) + absolute elev from the hit's interpolated UV -- invariant to
  // flat/globe placement, so hover/plot/measure need no place() inverse (frame.js has none; the globe-cap
  // inverse is ill-posed). uv.x=i/(n-1), uv.y=j/(n-1) -> e_m=uv.x*(n-1)*step, n_m=uv.y*(n-1)*step.
  const h = hits[0], m = S.meta, span = (m.n - 1) * m.step_m;
  let e_m, n_m;
  if (h.uv) { e_m = h.uv.x * span; n_m = h.uv.y * span; }
  else { e_m = h.point.x; n_m = h.point.z; }   // fallback (flat, S=1): world x/z are e/n
  return { e_m: e_m, n_m: n_m, elev_m: heightAt(e_m, n_m) + m.z_min, point: h.point };
}

let _llTimer = 0, _llGen = 0;
function _hoverPick(el, e) {
  const hit = _raycastSurface(el, e);
  if (!hit) { if (S._onHover) S._onHover(null); return; }
  const m = S.meta, lx = hit.e_m, ly = hit.n_m, elev = hit.elev_m;   // [GW-11] UV-derived order-local E/N + absolute elev
  const out = { e_m: lx, n_m: ly, elev_m: elev, lat: null, lon: null };
  if (S._onHover) S._onHover(out);
  // debounced selenographic lookup (tile-pixel metres = x0+lx, y0+ly -> /dem/site_lonlat)
  if (_llTimer) clearTimeout(_llTimer);
  const gen = ++_llGen;
  _llTimer = setTimeout(async () => {
    try {
      const r = await _fetchT("/dem/site_lonlat?x=" + (m.x0 + lx) + "&y=" + (m.y0 + ly) + "&site=" + encodeURIComponent(S.site), HOVER_TIMEOUT_MS);
      const d = await r.json();
      if (gen !== _llGen || !S._onHover) return;
      if (d && d.ok) { out.lat = d.lat; out.lon = d.lon; S._onHover(out); }
    } catch (_) { /* */ }
  }, 120);
}

function onHover(cb) { S._onHover = cb; }
function onLayerError(cb) { S._onLayerError = cb; }

// ---- plot-to-plan (task #77): Shift+click drops a visible marker + emits the plotted point ---------------
// (e_m/n_m/elev_m/lat/lon) via onPlot(cb). The QWC2 MissionPlan controller (js/mission/workspace.js
// WS.emitPlot) turns this into a queued order, mirroring the 2D map's singleclick -> placeAt(coord). Reuses
// the SAME raycast + e_m/n_m/elev_m derivation _hoverPick uses, and the SAME bounded /dem/site_lonlat fetch
// (_fetchT + HOVER_TIMEOUT_MS) -- so a hung lookup can never hang the viewer.
function _plotMarkerAt(lx, ly) {
  if (!S._plotGroup) { S._plotGroup = new THREE.Group(); S.group.add(S._plotGroup); }
  const win = (S.meta && S.meta.window_m) ? S.meta.window_m : 1000;
  const r = Math.max(1, win * 0.006);           // a few px world size relative to the window
  const geo = new THREE.SphereGeometry(r, 10, 8);
  const mat = new THREE.MeshStandardMaterial({ color: 0x39ff14, emissive: 0x123a0c, emissiveIntensity: 0.7, roughness: 0.5 });
  const mk = new THREE.Mesh(geo, mat);
  mk.userData.lx = lx; mk.userData.ly = ly; mk.userData.r = r;
  const mp = FRAME.place(lx, ly, heightAt(lx, ly) + ((S.meta && S.meta.z_min) || 0));   // [GW-11]
  mk.position.set(mp.x, mp.y + r, mp.z);
  S._plotGroup.add(mk);
  return mk;
}

function _plotAt(el, e) {
  const hit = _raycastSurface(el, e);
  if (!hit || !S.meta) return;                  // no terrain under the click -- nothing to plot
  const m = S.meta, lx = hit.e_m, ly = hit.n_m, elev_m = hit.elev_m;   // [GW-11] UV-derived
  const gen = _plotGen, site0 = S.site;         // capture the session gen + site; drop the emit if either changed mid-lookup
  _plotMarkerAt(lx, ly);
  _fetchT("/dem/site_lonlat?x=" + (m.x0 + lx) + "&y=" + (m.y0 + ly) + "&site=" + encodeURIComponent(S.site), HOVER_TIMEOUT_MS)
    .then((r) => r.json())
    .then((d) => {
      if (gen !== _plotGen || S.site !== site0) return;   // a site switch/dispose superseded this click -- no stale wrong-site emit
      if (d && d.ok && S._onPlot) { S._onPlot({ e_m: lx, n_m: ly, elev_m: elev_m, lat: d.lat, lon: d.lon }); }
    })
    .catch(() => { /* the lonlat lookup failed -- skip the emit; the consumer requires a real lat/lon */ });
}

function onPlot(cb) { S._onPlot = cb; }
function clearPlots() { _disposeGroup(S._plotGroup); S._plotGroup = null; }

// ---- measure / waypoints tool (task #79): plain click-without-drag (measure mode on, no Shift) drops a
// waypoint; consecutive waypoints are joined by a draped polyline and the running PLANAR horizontal distance
// (order-frame lx/ly, ignoring elevation) is reported via onMeasure(cb). Reuses the same raycast + lx/ly/
// elev_m derivation as _hoverPick/_plotAt, and the same bounded /dem/site_lonlat lookup (_fetchT +
// HOVER_TIMEOUT_MS) for the selenographic lat/lon of each waypoint (best-effort: a failed lookup keeps the
// point with lat/lon null -- distance is computed from lx/ly and does not depend on it).
function setMeasureMode(on) { S._measureOn = !!on; }

function _measureAt(el, e) {
  const hit = _raycastSurface(el, e);
  if (!hit || !S.meta) return;                  // no terrain under the click -- nothing to measure
  const m = S.meta, lx = hit.e_m, ly = hit.n_m, elev_m = hit.elev_m;   // [GW-11] UV-derived
  const gen = _plotGen, site0 = S.site;         // capture the session gen + site; drop the async fill if either changed mid-lookup
  const pt = { lx: lx, ly: ly, elev_m: elev_m, lat: null, lon: null };
  S._measurePts.push(pt);
  _redrawMeasure();
  _emitMeasure();
  _fetchT("/dem/site_lonlat?x=" + (m.x0 + lx) + "&y=" + (m.y0 + ly) + "&site=" + encodeURIComponent(S.site), HOVER_TIMEOUT_MS)
    .then((r) => r.json())
    .then((d) => { if (gen !== _plotGen || S.site !== site0) return; if (d && d.ok) { pt.lat = d.lat; pt.lon = d.lon; _emitMeasure(); } })
    .catch(() => { /* lonlat lookup failed -- keep the point with lat/lon null; distance still works from lx/ly */ });
}

// Per-consecutive-pair PLANAR horizontal distances (metres), ignoring elevation -- shared by the polyline's
// drape subdivision (denser sampling over a longer segment) and _emitMeasure's per-segment/cumulative report.
function _measureSegDists() {
  const pts = S._measurePts, out = [];
  for (let i = 1; i < pts.length; i++) { out.push(Math.hypot(pts[i].lx - pts[i - 1].lx, pts[i].ly - pts[i - 1].ly)); }
  return out;
}

// Dispose + rebuild the measure group: a draped polyline through the waypoints (_lineOnSurface, like the km
// grid/graticule) plus a small sphere marker at each point (styled like the task #77 plot marker). NOTE: on a
// setVertExag() change only the markers are re-lifted (cheap position.y trick, see that function) -- the
// polyline itself is only re-draped here, on the next _redrawMeasure() (a new point, or clearMeasure()). This
// matches the literal task #79 spec (reuse the marker re-lift pattern) but is a known, flagged trade-off: the
// connecting line can go slightly stale relative to the markers if vertical exaggeration changes with 2+
// points already placed. See the CLAUDE-facing report for the alternative (call _redrawMeasure() itself from
// setVertExag, matching the grid/graticule's full-rebuild pattern) if that staleness proves visually confusing.
function _redrawMeasure() {
  _disposeGroup(S._measureGroup); S._measureGroup = null;
  if (!S._measurePts.length) return;
  const grp = new THREE.Group();
  const win = (S.meta && S.meta.window_m) ? S.meta.window_m : 1000;
  const cell = (S.meta && S.meta.cell_m) ? S.meta.cell_m : Math.max(1, win / 200);
  const r = Math.max(1, win * 0.004);
  if (S._measurePts.length > 1) {
    const dists = _measureSegDists();
    const maxSeg = Math.max.apply(null, dists);
    const sub = Math.max(8, Math.min(200, Math.round(maxSeg / cell)));   // denser drape over a longer segment
    const coords2 = S._measurePts.map((pt) => [pt.lx, pt.ly]);
    grp.add(_lineOnSurface(coords2, sub, 0xffcc33, 3.0));
  }
  S._measurePts.forEach((pt) => {
    const geo = new THREE.SphereGeometry(r, 10, 8);
    const mat = new THREE.MeshStandardMaterial({ color: 0xffcc33, emissive: 0x4a3400, emissiveIntensity: 0.6, roughness: 0.5 });
    const mk = new THREE.Mesh(geo, mat);
    mk.userData.lx = pt.lx; mk.userData.ly = pt.ly; mk.userData.r = r;
    const wp = FRAME.place(pt.lx, pt.ly, heightAt(pt.lx, pt.ly) + ((S.meta && S.meta.z_min) || 0));   // [GW-11]
    mk.position.set(wp.x, wp.y + r, wp.z);
    grp.add(mk);
  });
  S._measureGroup = grp; S.group.add(grp);
}

function _emitMeasure() {
  if (!S._onMeasure) return;
  const pts = S._measurePts, segments = _measureSegDists();
  let total = 0; segments.forEach((d) => { total += d; });
  const last = pts.length ? pts[pts.length - 1] : null;
  S._onMeasure({
    count: pts.length,
    totalDist_m: total,
    lastLat: last ? last.lat : null,
    lastLon: last ? last.lon : null,
    segments: segments,
  });
}

function onMeasure(cb) { S._onMeasure = cb; }

// task #80: a defensive-copy snapshot of the measured waypoints, for a consumer (the MissionTerrain3D "send
// route" button) that wants the raw points rather than the onMeasure() summary (count/totalDist_m/segments).
// Each point is copied so the caller cannot mutate S._measurePts by reference.
function getMeasurePoints() {
  return (S._measurePts || []).map((q) => ({ lx: q.lx, ly: q.ly, elev_m: q.elev_m, lat: q.lat, lon: q.lon }));
}

function clearMeasure() {
  _disposeGroup(S._measureGroup); S._measureGroup = null; S._measurePts = [];
  if (S._onMeasure) { S._onMeasure({ count: 0, totalDist_m: 0, lastLat: null, lastLon: null, segments: [] }); }
}

function _disposeGroup(g) {
  if (!g) return;
  S.group.remove(g);
  g.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) { if (o.material.map) o.material.map.dispose(); if (o.material.dispose) o.material.dispose(); } });
}

// [GW-11] Tear the viewer down for an embedded host (the QWC2 MissionTerrain3D SideBar) that mounts/unmounts
// on task change: stop the RAF loop, drop the ResizeObserver + debounced lon/lat timer + hover callbacks,
// dispose every mesh/wire/grid/graticule + the WebGL renderer (forceContextLoss), and detach the canvas. The
// singleton S is left in a clean re-mountable state so a later mount() starts fresh with no leaked context or
// observer. Idempotent + never throws. (The standalone /viz page never calls this; it is additive.)
function dispose() {
  S.ready = false;                                            // stops _loop() on its next frame
  if (_llTimer) { clearTimeout(_llTimer); _llTimer = 0; } _llGen++; _plotGen++;   // drop in-flight hover + plot/measure lonlat lookups
  S._onHover = null; S._onLayerError = null; S._onPlot = null; S._onMeasure = null; S._hud = null;
  if (S._ctrlAbort) { try { S._ctrlAbort.abort(); } catch (_) { /* */ } S._ctrlAbort = null; }   // remove the pointer/wheel listeners bound in _bindControls
  if (S._ro) { try { S._ro.disconnect(); } catch (_) { /* */ } S._ro = null; }
  _disposeGroup(S._gridGroup); S._gridGroup = null;          // uses S.group -> must run before S.group is dropped
  _disposeGroup(S._gratGroup); S._gratGroup = null;
  _disposeGroup(S._plotGroup); S._plotGroup = null;
  _disposeGroup(S._measureGroup); S._measureGroup = null; S._measurePts = [];
  _disposeLayerGroup(); S._layerList = null;                 // [GW-11] drop draped overlays
  if (S._layerTex) { Object.keys(S._layerTex).forEach((k) => { try { S._layerTex[k].dispose(); } catch (_) { /* */ } }); S._layerTex = null; }
  S._gridOn = false; S._gratOn = false; S._wireOn = false; S._measureOn = false;
  if (S.wire) { if (S.group) S.group.remove(S.wire); S.wire.geometry.dispose(); S.wire.material.dispose(); S.wire = null; }
  if (S.mesh) {
    if (S.group) S.group.remove(S.mesh);
    S.mesh.geometry.dispose();
    if (S.mesh.material.map) S.mesh.material.map.dispose();
    S.mesh.material.dispose();
    S.mesh = null;
  }
  if (S.renderer) {
    S.renderer.dispose();
    try { S.renderer.forceContextLoss(); } catch (_) { /* */ }
    const dom = S.renderer.domElement;
    if (dom && dom.parentNode) { dom.parentNode.removeChild(dom); }
    S.renderer = null;
  }
  S.z = null; S.baseH = null; S.meta = null;
  S.scene = null; S.camera = null; S.group = null; S.sun = null; S.raycaster = null; S.container = null;
}

// [GW-11] flat<->globe toggle. Globe needs the metres->lonlat grid (S._frameReady); if it never loaded, stay
// flat. Re-place the mesh + re-drape every overlay through FRAME (a pure re-place, design §8), re-apply the
// active analysis drape (the mesh rebuild resets it to elevation), then reframe the camera on the tile center.
function setGlobe(on) {
  FRAME.setMode(on && S._frameReady ? "globe" : "enu");
  if (!S.mesh) return;
  const layer = S.layerKind;
  _disposeLayerGroup();                                  // overlays share the about-to-be-rebuilt geometry -> drop first
  _buildMesh();                                          // re-place all verts in the new mode (new geometry object)
  if (S._layerList && S._layerList.length) _buildOverlays();          // re-drape overlays onto the new geometry (cached textures)
  else if (layer && layer !== "elevation") setLayer(layer);           // else re-apply the single drape (rebuild reset it)
  if (S._gridOn) buildMetricGrid();
  if (S._gratGroup) _redrapeGraticule();
  if (S._plotGroup) {
    S._plotGroup.children.forEach((mk) => {
      const pp = FRAME.place(mk.userData.lx, mk.userData.ly, heightAt(mk.userData.lx, mk.userData.ly) + S.meta.z_min);
      mk.position.set(pp.x, pp.y + mk.userData.r, pp.z);
    });
  }
  if (S._measureGroup) _redrawMeasure();
  _frameCamera();
}

window.STEWIE_VIZ = {
  mount, dispose, loadSite, setLayer, setVertExag, setWireframe, setSun, setMetricGrid, setGraticule, setGlobe, setHud,
  renderLayerStack, clearLayerStack,
  onHover, onLayerError, onPlot, clearPlots, heightAt,
  setMeasureMode, clearMeasure, onMeasure, getMeasurePoints,
  get meta() { return S.meta; }, get layerKind() { return S.layerKind; }, get vertExag() { return S.vex; },
  get globe() { return FRAME.mode === "globe"; }, get globeAvailable() { return !!S._frameReady; },
  get ready() { return !!S.ready; }, get hasMesh() { return !!S.mesh; },
  // [GW-11] debug snapshot (mesh bbox / camera / sun / sample normal) for headless verification.
  get _dbg() {
    if (!S.mesh || !S.camera) return null;
    S.mesh.geometry.computeBoundingBox();
    const bb = S.mesh.geometry.boundingBox, nrm = S.mesh.geometry.attributes.normal;
    const R = (v) => v.map((x) => Math.round(x));
    return {
      mode: FRAME.mode,
      bbox_min: R([bb.min.x, bb.min.y, bb.min.z]), bbox_max: R([bb.max.x, bb.max.y, bb.max.z]),
      cam: R([S.camera.position.x, S.camera.position.y, S.camera.position.z]),
      target: R([S.target.x, S.target.y, S.target.z]),
      sun: S.sun ? R([S.sun.position.x, S.sun.position.y, S.sun.position.z]) : null,
      normal0: nrm ? [nrm.getX(0), nrm.getY(0), nrm.getZ(0)].map((v) => +v.toFixed(3)) : null,
      layerOverlays: S._layerGroup ? S._layerGroup.children.length : 0,
    };
  },
};
