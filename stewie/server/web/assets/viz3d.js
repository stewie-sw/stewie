/* viz.stewie.space -- standalone FULL-RESOLUTION lunar 3D terrain viewer (Haworth default; site-parametrized).
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

const S = { ready: false, vex: 1, layerKind: "elevation", site: "haworth", meta: null, z: null };
const WIRE = { color: 0x35e0d0, base: 0.10, dim: 0.04 };

function mount(container) {
  const w = container.clientWidth || 900, h = container.clientHeight || 600;
  S.container = container;
  S.scene = new THREE.Scene();
  S.scene.background = new THREE.Color(0x05060c);
  S.camera = new THREE.PerspectiveCamera(48, w / h, 0.1, 4000000);
  S.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  S.renderer.setSize(w, h);
  S.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  container.innerHTML = "";
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
  _loop();
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
  el.addEventListener("pointerdown", (e) => { drag = true; px = e.clientX; py = e.clientY; dx0 = e.clientX; dy0 = e.clientY; el.style.cursor = "grabbing"; el.setPointerCapture(e.pointerId); });
  el.addEventListener("pointerup", (e) => { drag = false; el.style.cursor = "grab"; try { el.releasePointerCapture(e.pointerId); } catch (_) { /* */ } });
  el.addEventListener("pointermove", (e) => {
    if (!drag) { if (S._onHover) _hoverPick(el, e); return; }
    S.az -= (e.clientX - px) * 0.006;
    S.el = Math.max(0.05, Math.min(1.5, S.el - (e.clientY - py) * 0.006));
    px = e.clientX; py = e.clientY;
  });
  el.addEventListener("wheel", (e) => { e.preventDefault(); S.dist = Math.max(30, Math.min(3000000, S.dist * (1 + Math.sign(e.deltaY) * 0.12))); }, { passive: false });
}

function _loop() {
  if (!S.ready) return;
  requestAnimationFrame(_loop);
  const cx = S.target.x + S.dist * Math.cos(S.el) * Math.cos(S.az);
  const cy = S.target.y + S.dist * Math.sin(S.el);
  const cz = S.target.z + S.dist * Math.cos(S.el) * Math.sin(S.az);
  S.camera.position.set(cx, cy, cz);
  S.camera.lookAt(S.target);
  S.renderer.render(S.scene, S.camera);
}

// ---- full-res load + mesh ------------------------------------------------------------------------
// Fetch the native float32 heightfield BINARY + its X-Dem-* header meta, then build the relief. Returns the
// meta (also stashed on S) so the page can show the resolution / z-range. Any window/site is renderable.
async function loadSite(site, opts) {
  opts = opts || {};
  S.site = site || S.site || "haworth";
  const qp = new URLSearchParams({ site: S.site });
  if (opts.window_m != null) qp.set("window_m", String(opts.window_m));
  if (opts.x0 != null) qp.set("x0", String(opts.x0));
  if (opts.y0 != null) qp.set("y0", String(opts.y0));
  if (opts.max_dim != null) qp.set("max_dim", String(opts.max_dim));
  const r = await fetch("/dem/heightfield_full?" + qp.toString());
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
  _buildMesh();
  // frame the whole tile
  S.target.set(meta.window_m / 2, ((meta.z_max - meta.z_min) * S.vex) * 0.3, meta.window_m / 2);
  S.dist = meta.window_m * 1.35;
  setLayer(S.layerKind);
  if (S._gridOn) buildMetricGrid();
  if (S._gratOn) loadGraticule();
  return meta;
}

function _buildMesh() {
  const m = S.meta, z = S.z, n = m.n, step = m.step_m, zmin = m.z_min;
  const span = Math.max(1e-6, m.z_max - m.z_min), vex = S.vex;
  if (S.mesh) { S.group.remove(S.mesh); S.mesh.geometry.dispose(); S.mesh.material.dispose(); S.mesh = null; }
  if (S.wire) { S.group.remove(S.wire); S.wire.geometry.dispose(); S.wire.material.dispose(); S.wire = null; }
  const pos = new Float32Array(n * n * 3), col = new Float32Array(n * n * 3), uv = new Float32Array(n * n * 2);
  const baseH = new Float32Array(n * n);
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const k = j * n + i, hh = z[k] - zmin;
      baseH[k] = hh;
      pos[k * 3] = i * step; pos[k * 3 + 1] = hh * vex; pos[k * 3 + 2] = j * step;   // x=E, y=up, z=N
      uv[k * 2] = i / (n - 1); uv[k * 2 + 1] = j / (n - 1);                            // North-up drape (flipud raster)
      const t = hh / span;
      col[k * 3] = 0.26 + 0.50 * t; col[k * 3 + 1] = 0.27 + 0.36 * t; col[k * 3 + 2] = 0.30 + 0.12 * t;
    }
  }
  S.baseH = baseH;
  const idx = [];
  for (let j = 0; j < n - 1; j++) {
    for (let i = 0; i < n - 1; i++) {
      const a = j * n + i, b = a + 1, c = a + n, d = c + 1;
      idx.push(a, c, b, b, c, d);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  geo.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  geo.setIndex(idx.length > 65535 ? new THREE.Uint32BufferAttribute(idx, 1) : idx);
  geo.computeVertexNormals();
  const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.96, metalness: 0.0 });
  S.mesh = new THREE.Mesh(geo, mat);
  S.group.add(S.mesh);
  S.wire = new THREE.LineSegments(new THREE.WireframeGeometry(geo),
    new THREE.LineBasicMaterial({ color: WIRE.color, transparent: true, opacity: S._wireOn ? WIRE.base : 0 }));
  S.wire.visible = !!S._wireOn;
  S.group.add(S.wire);
  setSun(S._sunAz ?? 135, S._sunEl ?? 20);
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
  const qp = new URLSearchParams({ site: S.site, window_m: m.window_m, x0: m.x0, y0: m.y0, kind: S.layerKind,
    sun_az: Math.round(S._sunAz ?? 315), sun_el: Math.round(S._sunEl ?? 45) });
  new THREE.TextureLoader().load("/dem/heightfield_full/layer.png?" + qp.toString(), (tex) => {
    if (!S.mesh || S.layerKind !== kind) { tex.dispose(); return; }
    tex.colorSpace = THREE.SRGBColorSpace; tex.minFilter = THREE.LinearFilter; tex.magFilter = THREE.LinearFilter;
    const mm = S.mesh.material;
    if (mm.map) mm.map.dispose();
    mm.map = tex; mm.vertexColors = false; mm.color.setHex(0xffffff); mm.needsUpdate = true;
  }, undefined, () => { if (S.layerKind === kind) { if (S._onLayerError) S._onLayerError(kind); setLayer("elevation"); } });
}

function setVertExag(k) {
  k = Math.max(1, Math.min(5, +k || 1));
  S.vex = k;
  if (!S.mesh || !S.baseH) return;
  const pos = S.mesh.geometry.attributes.position, bh = S.baseH;
  for (let i = 0; i < bh.length; i++) pos.array[i * 3 + 1] = bh[i] * k;
  pos.needsUpdate = true; S.mesh.geometry.computeVertexNormals();
  if (S.wire) { S.group.remove(S.wire); S.wire.geometry.dispose(); S.wire.material.dispose();
    S.wire = new THREE.LineSegments(new THREE.WireframeGeometry(S.mesh.geometry),
      new THREE.LineBasicMaterial({ color: WIRE.color, transparent: true, opacity: S._wireOn ? WIRE.base : 0 }));
    S.wire.visible = !!S._wireOn; S.group.add(S.wire); }
  if (S._gridOn) buildMetricGrid();     // re-drape the grid at the new relief
  if (S._gratGroup) _redrapeGraticule();
}

function setWireframe(on) { S._wireOn = !!on; if (S.wire) { S.wire.visible = on; S.wire.material.opacity = on ? ((S.layerKind !== "elevation") ? WIRE.dim : WIRE.base) : 0; } }

function setSun(azDeg, elDeg) {
  S._sunAz = azDeg; S._sunEl = elDeg;
  if (!S.sun || !S.meta) { return; }
  const a = azDeg * Math.PI / 180, e = Math.max(2, elDeg) * Math.PI / 180;
  const win = S.meta.window_m, R = win * 2, cx = win / 2, cz = win / 2;
  S.sun.position.set(cx + R * Math.cos(e) * Math.sin(a), R * Math.sin(e), cz + R * Math.cos(e) * Math.cos(a));
  if (S.sun.target) { S.sun.target.position.set(cx, 0, cz); S.sun.target.updateMatrixWorld(); }
  if (S.layerKind === "dem" || S.layerKind === "hillshade" || S.layerKind === "illumination") setLayer(S.layerKind);
}

// ---- gridlines: metric km grid (pure STEWIE_VIZGRID) draped on the surface ------------------------
function _lineOnSurface(coords2, subdiv, color, yLift) {
  const pts = [];
  for (let s = 0; s < coords2.length - 1; s++) {
    const [ax, ay] = coords2[s], [bx, by] = coords2[s + 1];
    for (let t = 0; t <= subdiv; t++) {
      const f = t / subdiv, lx = ax + (bx - ax) * f, ly = ay + (by - ay) * f;
      pts.push(new THREE.Vector3(lx, heightAt(lx, ly) * S.vex + (yLift || 1.0), ly));
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
    const r = await fetch("/dem/graticule?" + qp.toString());
    if (!r.ok) { S._gratData = null; return; }
    const body = await r.json();
    S._gratData = (body && body.ok) ? body.lines : null;
  } catch (_) { S._gratData = null; }
  _redrapeGraticule();
}

function _redrapeGraticule() {
  _disposeGroup(S._gratGroup); S._gratGroup = null;
  if (!S._gratData || !S._gratOn) return;
  const grp = new THREE.Group();
  S._gratData.forEach((ln) => {
    if (!ln.coords || ln.coords.length < 2) return;
    const color = ln.kind === "meridian" ? 0x6cd8ff : 0xffd27a;
    grp.add(_lineOnSurface(ln.coords, 1, color, 2.0));      // graticule is already densely sampled
  });
  S._gratGroup = grp; S.group.add(grp);
}

function setGraticule(on) { S._gratOn = !!on; if (on) { if (S._gratData) _redrapeGraticule(); else loadGraticule(); } else { _disposeGroup(S._gratGroup); S._gratGroup = null; } }

// ---- accurate coordinate readout (order metres + selenographic lon/lat) ---------------------------
function _raycastSurface(el, e) {
  if (!S.mesh || !S.raycaster) return null;
  const rect = el.getBoundingClientRect();
  const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
  S.raycaster.setFromCamera(ndc, S.camera);
  const hits = S.raycaster.intersectObject(S.mesh, false);
  return hits.length ? hits[0].point : null;
}

let _llTimer = 0, _llGen = 0;
function _hoverPick(el, e) {
  const p = _raycastSurface(el, e);
  if (!p) { if (S._onHover) S._onHover(null); return; }
  const m = S.meta, lx = p.x, ly = p.z, elev = p.y / S.vex + m.z_min;   // order-local E/N + absolute elevation
  const out = { e_m: lx, n_m: ly, elev_m: elev, lat: null, lon: null };
  if (S._onHover) S._onHover(out);
  // debounced selenographic lookup (tile-pixel metres = x0+lx, y0+ly -> /dem/site_lonlat)
  if (_llTimer) clearTimeout(_llTimer);
  const gen = ++_llGen;
  _llTimer = setTimeout(async () => {
    try {
      const r = await fetch("/dem/site_lonlat?x=" + (m.x0 + lx) + "&y=" + (m.y0 + ly) + "&site=" + encodeURIComponent(S.site));
      const d = await r.json();
      if (gen !== _llGen || !S._onHover) return;
      if (d && d.ok) { out.lat = d.lat; out.lon = d.lon; S._onHover(out); }
    } catch (_) { /* */ }
  }, 120);
}

function onHover(cb) { S._onHover = cb; }
function onLayerError(cb) { S._onLayerError = cb; }

function _disposeGroup(g) {
  if (!g) return;
  S.group.remove(g);
  g.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) { if (o.material.map) o.material.map.dispose(); if (o.material.dispose) o.material.dispose(); } });
}

window.STEWIE_VIZ = {
  mount, loadSite, setLayer, setVertExag, setWireframe, setSun, setMetricGrid, setGraticule,
  onHover, onLayerError, heightAt,
  get meta() { return S.meta; }, get layerKind() { return S.layerKind; }, get vertExag() { return S.vex; },
  get ready() { return !!S.ready; }, get hasMesh() { return !!S.mesh; },
};
