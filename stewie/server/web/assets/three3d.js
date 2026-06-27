/* STEWIE in-cockpit 3D playback (#165 slice 2): an orbitable WebGL view of the work-area DEM, in the
 * SAME order frame the planner uses (x East, y North, both metres from the site origin), fed by
 * GET /dem/heightfield. The rover and its planned path (slice 3) animate along LAST_TIMELINE and
 * sample the SAME surface, so the dry-run rover sits on the real terrain -- the "watch before uplink"
 * 3D view. Exposed on window.STEWIE3D so the classic cockpit.js can drive it without being a module.
 *
 * Honesty: this shows physics TRUTH (the conserved timeline + the real DEM) and, when given the
 * estimator track, the estimator BELIEF -- never a live rover. Three.js r170, MIT, self-hosted.
 */
import * as THREE from "./three.module.min.js";

const S = { ready: false };

function mount(container) {
  if (S.renderer) { _resize(container); return true; }
  const w = container.clientWidth || 520, h = container.clientHeight || 380;
  S.scene = new THREE.Scene();
  S.scene.background = new THREE.Color(0x05060c);
  S.camera = new THREE.PerspectiveCamera(48, w / h, 0.1, 200000);
  S.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  S.renderer.setSize(w, h);
  S.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  S.renderer.shadowMap.enabled = true;                      // #181: real sun shadows on the terrain
  S.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.innerHTML = "";
  container.appendChild(S.renderer.domElement);

  S.sun = new THREE.DirectionalLight(0xfff4e8, 2.4);
  S.sun.castShadow = true;                                  // #181: the sun casts shadows (ephemeris-driven)
  S.sun.shadow.mapSize.set(2048, 2048);
  S.scene.add(S.sun);
  S.scene.add(S.sun.target);                                // a directional light aims at its target
  S.scene.add(new THREE.AmbientLight(0x3a4456, 0.7));
  S.group = new THREE.Group();
  S.scene.add(S.group);
  S.raycaster = new THREE.Raycaster();                       // path-def: click -> terrain-surface waypoint

  // orbit state (spherical around target); drag = rotate, wheel = zoom
  S.az = Math.PI * 0.25; S.el = Math.PI * 0.34; S.dist = 600;
  S.target = new THREE.Vector3(0, 0, 0);
  // fly/move-through state (vs orbit): a free first-person camera through the real DEM world
  S.fly = false; S.walk = false; S.flyPos = new THREE.Vector3(); S.flyYaw = 0; S.flyPitch = -0.3; S.keys = {};
  // 3D plotting toolbox state: live cursor coord readout, plotted coordinate markers, distance measures
  S._coordReadout = false; S.markers = []; S.measures = []; S._measPts = [];
  _bindControls(container);
  _bindFlyKeys(container);

  S._ro = new ResizeObserver(() => _resize(container));
  S._ro.observe(container);
  S.ready = true;
  _loop();
  return true;
}

function _resize(container) {
  if (!S.renderer) return;
  const w = container.clientWidth || 520, h = container.clientHeight || 380;
  S.renderer.setSize(w, h, false);
  S.camera.aspect = w / h;
  S.camera.updateProjectionMatrix();
}

function _bindControls(el) {
  let drag = false, px = 0, py = 0, dx0 = 0, dy0 = 0;
  el.style.cursor = "grab";
  el.addEventListener("pointerdown", (e) => { drag = true; px = e.clientX; py = e.clientY; dx0 = e.clientX; dy0 = e.clientY; el.style.cursor = "grabbing"; el.setPointerCapture(e.pointerId); });
  el.addEventListener("pointerup", (e) => {
    drag = false; el.style.cursor = (S._editPath || S._plotMode || S._measureMode) ? "crosshair" : "grab";
    try { el.releasePointerCapture(e.pointerId); } catch (_) { /* */ }
    // a CLICK (not an orbit-drag), never in fly: route to the active tool on the terrain surface
    if (S.fly || Math.hypot(e.clientX - dx0, e.clientY - dy0) >= 6) return;
    if (S._editPath) _pickWaypoint(el, e);                 // path-def: drop a goto waypoint
    else if (S._plotMode) _plotPick(el, e);                // plot: drop a labeled coordinate marker
    else if (S._measureMode) _measurePick(el, e);          // measure: pick a 3D distance endpoint
  });
  el.addEventListener("pointermove", (e) => {
    if (!drag) { if (S._coordReadout && !S.fly) _hoverPick(el, e); return; }  // live cursor coord readout
    if (S.fly) {                                          // fly mode: drag = mouse-look (yaw/pitch)
      S.flyYaw -= (e.clientX - px) * 0.005;
      S.flyPitch = Math.max(-1.45, Math.min(1.45, S.flyPitch - (e.clientY - py) * 0.005));
    } else {                                              // orbit mode: drag = rotate around target
      S.az -= (e.clientX - px) * 0.006;
      S.el = Math.max(0.06, Math.min(1.5, S.el - (e.clientY - py) * 0.006));
    }
    px = e.clientX; py = e.clientY;
  });
  el.addEventListener("wheel", (e) => { e.preventDefault(); S.dist = Math.max(20, Math.min(20000, S.dist * (1 + Math.sign(e.deltaY) * 0.12))); }, { passive: false });
}

function _loop() {
  if (!S.ready) return;
  requestAnimationFrame(_loop);
  if (S.fly) {
    _flyStep();                                           // first-person move-through the world
  } else {
    // camera orbits the target
    const cx = S.target.x + S.dist * Math.cos(S.el) * Math.cos(S.az);
    const cy = S.target.y + S.dist * Math.sin(S.el);
    const cz = S.target.z + S.dist * Math.cos(S.el) * Math.sin(S.az);
    S.camera.position.set(cx, cy, cz);
    S.camera.lookAt(S.target);
  }
  S.renderer.render(S.scene, S.camera);
}

// hf: { n, window_m, cell_m, z[], z_min, z_max } -- z row-major y-then-x (z[j*n+i] at x=i*step, y=j*step)
function render(hf) {
  if (!S.scene || !hf || !hf.z) return false;
  if (S.mesh) { S.group.remove(S.mesh); S.mesh.geometry.dispose(); S.mesh.material.dispose(); S.mesh = null; }
  if (S.wire) { S.group.remove(S.wire); S.wire.geometry.dispose(); S.wire.material.dispose(); S.wire = null; }
  if (S.markerGroup || S.measureGroup) clearPlots();        // a new site = fresh annotations (stale order coords)
  const n = hf.n, win = hf.window_m, step = win / (n - 1);
  const zmin = hf.z_min, span = Math.max(1e-6, hf.z_max - hf.z_min);
  const pos = new Float32Array(n * n * 3), col = new Float32Array(n * n * 3);
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const k = j * n + i, h = hf.z[k] - zmin;
      pos[k * 3] = i * step; pos[k * 3 + 1] = h; pos[k * 3 + 2] = j * step;  // x=E, y=up, z=N
      const t = h / span;                                                     // low=slate, high=regolith tan
      col[k * 3] = 0.26 + 0.50 * t; col[k * 3 + 1] = 0.27 + 0.36 * t; col[k * 3 + 2] = 0.30 + 0.12 * t;
    }
  }
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
  geo.setIndex(idx);
  geo.computeVertexNormals();
  const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.96, metalness: 0.0 });
  S.mesh = new THREE.Mesh(geo, mat);
  S.mesh.castShadow = true; S.mesh.receiveShadow = true;    // #181: self-shadowing terrain under the ephemeris sun
  S.group.add(S.mesh);
  // #180: the depth/heightfield as a WIRE overlay -- the structural backdrop the convergence viz
  // composites ephemeris sun/shadows + the lander/AprilTags onto (Aaron 2026-06-17). A neon wireframe
  // over the lit surface; toggleable via setWireframe (default on).
  S.wire = new THREE.LineSegments(new THREE.WireframeGeometry(geo),
    new THREE.LineBasicMaterial({ color: 0x35e0d0, transparent: true, opacity: 0.28 }));
  S.wire.visible = (S._wireOn !== false);
  S.group.add(S.wire);

  S.win = win; S.n = n; S.step = step; S.zmin = zmin; S.hf = hf;
  S.target.set(win / 2, span * 0.35, win / 2);
  S.dist = win * 1.5;
  setSun(S._sunAz ?? 135, S._sunEl ?? 18);   // grazing south-pole sun by default
  return true;
}

// bilinear height (metres above zmin) at order (x, y), for placing the rover ON the surface
function heightAt(x, y) {
  if (!S.hf) return 0;
  const n = S.n, step = S.step, z = S.hf.z, zmin = S.zmin;
  let fc = x / step, fr = y / step;
  fc = Math.max(0, Math.min(n - 1.001, fc)); fr = Math.max(0, Math.min(n - 1.001, fr));
  const c0 = Math.floor(fc), r0 = Math.floor(fr), tc = fc - c0, tr = fr - r0;
  const z00 = z[r0 * n + c0], z01 = z[r0 * n + c0 + 1], z10 = z[(r0 + 1) * n + c0], z11 = z[(r0 + 1) * n + c0 + 1];
  return (1 - tr) * ((1 - tc) * z00 + tc * z01) + tr * ((1 - tc) * z10 + tc * z11) - zmin;
}

function setSun(azDeg, elDeg) {
  S._sunAz = azDeg; S._sunEl = elDeg;
  if (!S.sun) return;
  const a = azDeg * Math.PI / 180, e = Math.max(2, elDeg) * Math.PI / 180;
  const win = S.win || 600, R = win * 2, cx = win / 2, cz = win / 2;
  // #181: from-north-eastward azimuth (the /ephemeris + shadow-layer convention) -- az=0 -> +z (North),
  // az=90 -> +x (East); frame is x=E, y=up, z=N. Anchored on the terrain centre so the shadow camera covers it.
  S.sun.position.set(cx + R * Math.cos(e) * Math.sin(a), R * Math.sin(e), cz + R * Math.cos(e) * Math.cos(a));
  if (S.sun.target) { S.sun.target.position.set(cx, 0, cz); S.sun.target.updateMatrixWorld(); }
  const sc = S.sun.shadow && S.sun.shadow.camera;           // size the ortho shadow frustum to the terrain
  if (sc) {
    sc.left = -win; sc.right = win; sc.top = win; sc.bottom = -win;
    sc.near = Math.max(1, R * 0.2); sc.far = R * 3; sc.updateProjectionMatrix();
  }
}

// #180: toggle the depth/heightfield wire overlay (the convergence-viz structural backdrop)
function setWireframe(on) {
  S._wireOn = !!on;
  if (S.wire) S.wire.visible = S._wireOn;
}

// slice-3 hooks: place a rover marker on the surface at order (x,y), and draw a path polyline
function setRover(x, y) {
  if (!S.scene) return;
  if (!S.rover) {
    S.rover = new THREE.Mesh(new THREE.SphereGeometry(Math.max(1.5, (S.win || 300) * 0.012), 16, 12),
      new THREE.MeshStandardMaterial({ color: 0xe8273f, emissive: 0x661018, roughness: 0.4 }));
    S.rover.castShadow = true;                              // #181: the rover casts a shadow under the sun
    S.group.add(S.rover);
  }
  S.rover.position.set(x, heightAt(x, y) + (S.rover.geometry.parameters.radius || 2), y);
}

// #144 tier-1: the LIVE ROS rover on the main DEM view, in the ORDER frame (the caller applies the ROS
// map-frame -> order transform: order_y = -ros_y, since frames.py is y=-row and this view is y=+row).
// Cyan, distinct from the red dry-run rover. HONESTLY GATED to the loaded DEM window [0, win]: a pose
// off the loaded terrain is HIDDEN and returns false (no misleading edge-clamp), so the live rover only
// appears where its coords actually fall on the loaded DEM -- it never implies a position it can't ground.
function setLiveRover(x, y) {
  if (!S.scene) return false;
  const win = S.win || 0;
  const onDem = win > 0 && x >= 0 && x <= win && y >= 0 && y <= win;
  if (!S.liveRover) {
    S.liveRover = new THREE.Mesh(new THREE.SphereGeometry(Math.max(1.5, (S.win || 300) * 0.012), 16, 12),
      new THREE.MeshStandardMaterial({ color: 0x22d3ee, emissive: 0x0a4a55, roughness: 0.4 }));
    S.liveRover.castShadow = true;
    S.group.add(S.liveRover);
  }
  S.liveRover.visible = onDem;
  if (onDem) S.liveRover.position.set(x, heightAt(x, y) + (S.liveRover.geometry.parameters.radius || 2), y);
  return onDem;
}

function clearLiveRover() { if (S.liveRover) S.liveRover.visible = false; }

function setPath(pts, colorHex) {  // pts: [[x,y],...] in order frame; e.g. truth (amber) or estimate (cyan)
  if (!S.scene || !pts || !pts.length) return;
  const key = colorHex === 0x35e0d0 ? "estPath" : "truthPath";
  if (S[key]) { S.group.remove(S[key]); S[key].geometry.dispose(); S[key].material.dispose(); }
  const v = [];
  for (const p of pts) v.push(p[0], heightAt(p[0], p[1]) + 1.0, p[1]);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(v, 3));
  S[key] = new THREE.Line(g, new THREE.LineBasicMaterial({ color: colorHex }));
  S.group.add(S[key]);
}

function clearTracks() {
  for (const key of ["truthPath", "estPath"]) {
    if (S[key]) { S.group.remove(S[key]); S[key].geometry.dispose(); S[key].material.dispose(); S[key] = null; }
  }
}

// slice 3: walk the rover along an order-frame polyline on a looping clock (the "watch the rover
// drive the plan" dry-run). Interpolates between poses; samples the surface for z via setRover.
function animateRover(points, durationMs) {
  stopRoverAnim();
  if (!points || !points.length) return;
  if (points.length === 1) { setRover(points[0][0], points[0][1]); return; }
  const dur = Math.max(1500, durationMs || 9000), seg = points.length - 1;
  let start = null;
  function step(ts) {
    if (start === null) start = ts;
    const f = ((ts - start) % dur) / dur;                 // 0..1, looping
    const g = f * seg, i = Math.min(seg - 1, Math.floor(g)), t = g - i;
    const a = points[i], b = points[i + 1];
    setRover(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t);
    S._roverRAF = requestAnimationFrame(step);
  }
  S._roverRAF = requestAnimationFrame(step);
}
function stopRoverAnim() { if (S._roverRAF) { cancelAnimationFrame(S._roverRAF); S._roverRAF = 0; } }

// #182: render the lander at order (x, y) with AprilTag (tag36h11 id-0, the REAL beacon tag) faces -- the
// pose-fix fiducial the AprilTag localization path keys on, composited into the convergence-viz scene.
function setLander3D(x, y) {
  if (!S.scene) return;
  if (S.lander) {
    S.group.remove(S.lander);
    S.lander.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material && o.material.dispose) o.material.dispose(); });
    S.lander = null;
  }
  if (x == null || y == null) return;
  const s = Math.max(12, (S.win || 300) * 0.05);           // legible beacon footprint at the tile scale (the tag must read)
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(s, s * 0.7, s),
    new THREE.MeshStandardMaterial({ color: 0xb8c0cc, metalness: 0.35, roughness: 0.55 }));
  body.castShadow = true; body.receiveShadow = true;
  g.add(body);
  // AprilTag beacon panels on the 4 vertical faces (unlit MeshBasic so the bits read under any sun;
  // NearestFilter keeps the 10x10 tag36h11 id-0 grid crisp -- the actual beacon tag, not a stand-in)
  const tex = new THREE.TextureLoader().load("/assets/tags/tag36_11_id0.png");
  tex.magFilter = THREE.NearestFilter; tex.minFilter = THREE.NearestFilter;
  const tagMat = new THREE.MeshBasicMaterial({ map: tex });
  const ts = s * 0.55, off = s * 0.5 + 0.05, ty = s * 0.05;
  [[0, 0, off], [Math.PI, 0, -off], [Math.PI / 2, off, 0], [-Math.PI / 2, -off, 0]].forEach(([ry, px, pz]) => {
    const q = new THREE.Mesh(new THREE.PlaneGeometry(ts, ts), tagMat);
    q.position.set(px, ty, pz); q.rotation.y = ry; g.add(q);
  });
  g.position.set(x, heightAt(x, y) + s * 0.35, y);
  S.lander = g; S.group.add(g);
}

// --- path definition (Aaron 2026-06-17): click the 3D terrain to drop waypoints ON the real surface, so
// a path is defined against the actual relief (the Cesium globe is general plotting; THIS is accurate).
// Markers + a polyline ride the surface; per-leg length/slope come from the same bilinear heightAt. ---
function _raycastSurface(el, e) {                          // screen px -> the terrain hit point (world frame) or null
  if (!S.mesh || !S.raycaster) return null;
  const rect = el.getBoundingClientRect();
  const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1,
                                -((e.clientY - rect.top) / rect.height) * 2 + 1);
  S.raycaster.setFromCamera(ndc, S.camera);
  const hits = S.raycaster.intersectObject(S.mesh, false);
  return hits.length ? hits[0].point : null;
}
function _pickWaypoint(el, e) {
  const p = _raycastSurface(el, e);
  if (p) _addWaypoint(p.x, p.z);                           // world x=East=order x, z=North=order y
}
function _addWaypoint(x, y) {
  S.waypoints = S.waypoints || [];
  S.waypoints.push([x, y]);
  _redrawPlan();
  if (S._onPath) S._onPath(getWaypoints());
}
function _redrawPlan() {
  if (S.planGroup) {
    S.group.remove(S.planGroup);
    S.planGroup.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material && o.material.dispose) o.material.dispose(); });
  }
  S.planGroup = new THREE.Group();
  const wp = S.waypoints || [], r = Math.max(1.2, (S.win || 300) * 0.01), v = [];
  wp.forEach(([x, y], i) => {
    const h = heightAt(x, y) + r;
    const m = new THREE.Mesh(new THREE.SphereGeometry(r, 12, 10),
      new THREE.MeshStandardMaterial({ color: i === 0 ? 0x39d98a : 0x8affd0, emissive: 0x0c3a28, roughness: 0.4 }));
    m.position.set(x, h, y); S.planGroup.add(m);
    v.push(x, h, y);
  });
  if (v.length >= 6) {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(v, 3));
    S.planGroup.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0x39d98a })));
  }
  S.group.add(S.planGroup);
}
function setPathEdit(on) {
  S._editPath = !!on;
  if (S.renderer && S.renderer.domElement.parentElement)
    S.renderer.domElement.parentElement.style.cursor = on ? "crosshair" : "grab";
}
function onPathChange(cb) { S._onPath = cb; }
function getWaypoints() { return (S.waypoints || []).map((p) => [p[0], p[1]]); }
function undoWaypoint() { if (S.waypoints && S.waypoints.length) { S.waypoints.pop(); _redrawPlan(); if (S._onPath) S._onPath(getWaypoints()); } }
function clearWaypoints() { S.waypoints = []; _redrawPlan(); if (S._onPath) S._onPath([]); }
function pathStats() {
  const wp = S.waypoints || [], legs = []; let total = 0, maxslope = 0;
  for (let i = 1; i < wp.length; i++) {
    const dx = wp[i][0] - wp[i - 1][0], dy = wp[i][1] - wp[i - 1][1];
    const dz = heightAt(wp[i][0], wp[i][1]) - heightAt(wp[i - 1][0], wp[i - 1][1]);
    const horiz = Math.hypot(dx, dy), len = Math.hypot(horiz, dz);
    const slope = horiz > 1e-6 ? Math.atan2(Math.abs(dz), horiz) * 180 / Math.PI : 0;
    legs.push({ len_m: len, slope_deg: slope }); total += len; maxslope = Math.max(maxslope, slope);
  }
  return { legs, total_len_m: total, max_slope_deg: maxslope, n: wp.length };
}

// --- 3D plotting toolbox (Aaron 2026-06-17): overlay EXACT coordinate positions in the 3D world.
// The picked surface point carries the planner's order frame directly: world x = East (m), world z =
// North (m), both metres from the window SW origin (the same frame goto waypoints use); world y is the
// height above the window minimum, so absolute elevation = world.y + S.zmin (raw DEM metres). Tools:
// live cursor readout (onHover), plotted coordinate markers with floating labels, and 3D distance
// measures (slant / horizontal / vertical / slope). ---
function _coordOf(p) { return { e: p.x, n: p.z, elev: p.y + (S.zmin || 0) }; }   // world hit -> exact order coords
function _hoverPick(el, e) {
  const p = _raycastSurface(el, e);
  if (p && S._onHover) S._onHover(_coordOf(p));
  else if (!p && S._onHover) S._onHover(null);
}
function _textSprite(text, color) {                        // a depth-test-off canvas label that always reads
  const fs = 34, pad = 7, cv = document.createElement("canvas"), ctx = cv.getContext("2d");
  ctx.font = `${fs}px monospace`;
  cv.width = Math.ceil(ctx.measureText(text).width) + pad * 2; cv.height = fs + pad * 2;
  ctx.font = `${fs}px monospace`;
  ctx.fillStyle = "rgba(8,11,15,0.82)"; ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = color || "#39ff14"; ctx.textBaseline = "middle";
  ctx.fillText(text, pad, cv.height / 2);
  const tex = new THREE.CanvasTexture(cv); tex.minFilter = THREE.LinearFilter;
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  const h = Math.max(5, (S.win || 300) * 0.035);
  spr.scale.set(h * cv.width / cv.height, h, 1);
  return spr;
}
function _disposeGroup(g) {
  if (!g) return;
  S.group.remove(g);
  g.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) { if (o.material.map) o.material.map.dispose(); if (o.material.dispose) o.material.dispose(); } });
}
function _plotPick(el, e) {
  const p = _raycastSurface(el, e); if (!p) return;
  S.markers = S.markers || [];
  S.markers.push({ x: p.x, z: p.z, elev: p.y + (S.zmin || 0), wy: p.y });
  _redrawMarkers();
  if (S._onMarkers) S._onMarkers(getMarkers());
}
function _redrawMarkers() {
  _disposeGroup(S.markerGroup);
  S.markerGroup = new THREE.Group();
  const r = Math.max(1.2, (S.win || 300) * 0.011);
  (S.markers || []).forEach((m, i) => {
    const dot = new THREE.Mesh(new THREE.SphereGeometry(r, 14, 12),
      new THREE.MeshStandardMaterial({ color: 0x39ff14, emissive: 0x103a08, roughness: 0.4 }));
    dot.position.set(m.x, m.wy + r, m.z); S.markerGroup.add(dot);
    const lab = _textSprite(`#${i + 1} E${m.x.toFixed(1)} N${m.z.toFixed(1)} ${m.elev.toFixed(1)}m`, "#9dff7a");
    lab.position.set(m.x, m.wy + r * 3.2, m.z); S.markerGroup.add(lab);
  });
  S.group.add(S.markerGroup);
}
function _measurePick(el, e) {
  const p = _raycastSurface(el, e); if (!p) return;
  S._measPts = S._measPts || [];
  S._measPts.push(p.clone());
  if (S._measPts.length === 2) {
    const a = S._measPts[0], b = S._measPts[1];
    const dx = b.x - a.x, dz = b.z - a.z, dy = b.y - a.y;
    const horiz = Math.hypot(dx, dz), slant = Math.hypot(horiz, dy);
    const slope = horiz > 1e-6 ? Math.atan2(Math.abs(dy), horiz) * 180 / Math.PI : 0;
    S.measures = S.measures || [];
    S.measures.push({ a: a.clone(), b: b.clone(), slant, horiz, vert: dy, slope });
    S._measPts = [];
    _redrawMeasures();
    if (S._onMeasure) S._onMeasure({ slant_m: slant, horiz_m: horiz, vert_m: dy, slope_deg: slope });
  } else { _redrawMeasures(); }                            // show the pending first endpoint immediately
}
function _redrawMeasures() {
  _disposeGroup(S.measureGroup);
  S.measureGroup = new THREE.Group();
  const r = Math.max(1.0, (S.win || 300) * 0.009);
  const endpt = (p, col) => {
    const m = new THREE.Mesh(new THREE.SphereGeometry(r, 12, 10),
      new THREE.MeshStandardMaterial({ color: col, emissive: 0x222, roughness: 0.4 }));
    m.position.copy(p); S.measureGroup.add(m);
  };
  (S.measures || []).forEach((seg) => {
    endpt(seg.a, 0xffd23f); endpt(seg.b, 0xffd23f);
    const g = new THREE.BufferGeometry().setFromPoints([seg.a, seg.b]);
    S.measureGroup.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0xffd23f })));
    const mid = seg.a.clone().add(seg.b).multiplyScalar(0.5);
    const lab = _textSprite(`${seg.slant.toFixed(1)} m  (${seg.slope.toFixed(0)} deg)`, "#ffd23f");
    lab.position.set(mid.x, mid.y + r * 3, mid.z); S.measureGroup.add(lab);
  });
  (S._measPts || []).forEach((p) => endpt(p, 0xff8c1a)); // pending endpoint
  S.group.add(S.measureGroup);
}
function setCoordReadout(on) { S._coordReadout = !!on; if (!on && S._onHover) S._onHover(null); }
function onHover(cb) { S._onHover = cb; }
function setPlotMode(on) {
  S._plotMode = !!on;
  if (on) { S._measureMode = false; setPathEdit(false); }
  if (S.renderer && S.renderer.domElement.parentElement)
    S.renderer.domElement.parentElement.style.cursor = (on || S._editPath || S._measureMode) ? "crosshair" : "grab";
}
function setMeasureMode(on) {
  S._measureMode = !!on; S._measPts = [];
  if (on) { S._plotMode = false; setPathEdit(false); }
  if (S.renderer && S.renderer.domElement.parentElement)
    S.renderer.domElement.parentElement.style.cursor = (on || S._editPath || S._plotMode) ? "crosshair" : "grab";
}
function onMarkers(cb) { S._onMarkers = cb; }
function onMeasure(cb) { S._onMeasure = cb; }
function getMarkers() { return (S.markers || []).map((m) => ({ e: m.x, n: m.z, elev: m.elev })); }
function clearPlots() {
  S.markers = []; S.measures = []; S._measPts = [];
  _disposeGroup(S.markerGroup); S.markerGroup = null;
  _disposeGroup(S.measureGroup); S.measureGroup = null;
  if (S._onMarkers) S._onMarkers([]);
}

// --- fly / move-through the 3D world (Aaron 2026-06-17): a first-person free camera through the REAL
// DEM (vs the orbit camera). Drag = look; W/A/S/D = move; R/Space up, F/Shift down. Walk mode clamps to
// the terrain surface at eye height so you walk the regolith. Speed scales to the scene extent. ---
function _flyForward() {
  const cp = Math.cos(S.flyPitch);
  return new THREE.Vector3(Math.sin(S.flyYaw) * cp, Math.sin(S.flyPitch), Math.cos(S.flyYaw) * cp);
}
function _bindFlyKeys() {
  const typing = (e) => e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.isContentEditable);
  window.addEventListener("keydown", (e) => {
    if (!S.fly || typing(e)) return;
    const k = e.key.toLowerCase(); S.keys[k] = true;
    if ("wasdrf ".includes(k)) e.preventDefault();      // stop page scroll while flying
  });
  window.addEventListener("keyup", (e) => { S.keys[e.key.toLowerCase()] = false; });
}
function _flyStep() {
  const fwd = _flyForward();
  const right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0)).normalize();
  const sp = Math.max(0.5, (S.win || 300) * 0.012);     // per-frame step, scaled to the scene extent
  const k = S.keys, v = new THREE.Vector3();
  if (k.w) v.add(fwd); if (k.s) v.sub(fwd);
  if (k.d) v.add(right); if (k.a) v.sub(right);
  if (k.r || k[" "]) v.y += 1; if (k.f || k.shift) v.y -= 1;
  if (v.lengthSq() > 0) S.flyPos.addScaledVector(v.normalize(), sp);
  if (S.walk) S.flyPos.y = heightAt(S.flyPos.x, S.flyPos.z) + 2.0;   // ride the surface at ~eye height
  S.camera.position.copy(S.flyPos);
  S.camera.lookAt(S.flyPos.clone().add(fwd));
}
function setFlyMode(on, walk) {
  S.fly = !!on; S.walk = !!walk;
  if (S.fly) {                                          // seed from the current orbit view so it's seamless
    S.flyPos.copy(S.camera.position);
    const dir = new THREE.Vector3().subVectors(S.target, S.camera.position).normalize();
    S.flyYaw = Math.atan2(dir.x, dir.z);
    S.flyPitch = Math.asin(Math.max(-1, Math.min(1, dir.y)));
    if (S.walk) S.flyPos.y = heightAt(S.flyPos.x, S.flyPos.z) + 2.0;
    if (S._editPath) setPathEdit(false);                // fly + path-edit are mutually exclusive
  }
  S.keys = {};
}
function getCamPos() { return S.camera ? [S.camera.position.x, S.camera.position.y, S.camera.position.z] : null; }

window.STEWIE3D = { mount, render, setRover, setLiveRover, clearLiveRover, setPath, setSun, setWireframe, setLander3D, clearTracks, heightAt,
  animateRover, stopRoverAnim, setPathEdit, onPathChange, getWaypoints, undoWaypoint, clearWaypoints, pathStats,
  setFlyMode, getCamPos,
  setCoordReadout, onHover, setPlotMode, setMeasureMode, onMarkers, onMeasure, getMarkers, clearPlots,
  get available() { return true; },
  get sunState() { return { az: S._sunAz, el: S._sunEl, shadows: !!(S.renderer && S.renderer.shadowMap && S.renderer.shadowMap.enabled) }; },
  get liveRoverState() {   // #144 tier-1 introspection (verification): the live ROS rover's placement
    return S.liveRover ? { pos: [S.liveRover.position.x, S.liveRover.position.y, S.liveRover.position.z],
      visible: S.liveRover.visible } : null; },
  get hasLander() { return !!S.lander; } };
