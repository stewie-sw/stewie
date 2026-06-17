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

  // orbit state (spherical around target); drag = rotate, wheel = zoom
  S.az = Math.PI * 0.25; S.el = Math.PI * 0.34; S.dist = 600;
  S.target = new THREE.Vector3(0, 0, 0);
  _bindControls(container);

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
  let drag = false, px = 0, py = 0;
  el.style.cursor = "grab";
  el.addEventListener("pointerdown", (e) => { drag = true; px = e.clientX; py = e.clientY; el.style.cursor = "grabbing"; el.setPointerCapture(e.pointerId); });
  el.addEventListener("pointerup", (e) => { drag = false; el.style.cursor = "grab"; try { el.releasePointerCapture(e.pointerId); } catch (_) { /* */ } });
  el.addEventListener("pointermove", (e) => {
    if (!drag) return;
    S.az -= (e.clientX - px) * 0.006;
    S.el = Math.max(0.06, Math.min(1.5, S.el - (e.clientY - py) * 0.006));
    px = e.clientX; py = e.clientY;
  });
  el.addEventListener("wheel", (e) => { e.preventDefault(); S.dist = Math.max(20, Math.min(20000, S.dist * (1 + Math.sign(e.deltaY) * 0.12))); }, { passive: false });
}

function _loop() {
  if (!S.ready) return;
  requestAnimationFrame(_loop);
  // camera orbits the target
  const cx = S.target.x + S.dist * Math.cos(S.el) * Math.cos(S.az);
  const cy = S.target.y + S.dist * Math.sin(S.el);
  const cz = S.target.z + S.dist * Math.cos(S.el) * Math.sin(S.az);
  S.camera.position.set(cx, cy, cz);
  S.camera.lookAt(S.target);
  S.renderer.render(S.scene, S.camera);
}

// hf: { n, window_m, cell_m, z[], z_min, z_max } -- z row-major y-then-x (z[j*n+i] at x=i*step, y=j*step)
function render(hf) {
  if (!S.scene || !hf || !hf.z) return false;
  if (S.mesh) { S.group.remove(S.mesh); S.mesh.geometry.dispose(); S.mesh.material.dispose(); S.mesh = null; }
  if (S.wire) { S.group.remove(S.wire); S.wire.geometry.dispose(); S.wire.material.dispose(); S.wire = null; }
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

window.STEWIE3D = { mount, render, setRover, setPath, setSun, setWireframe, setLander3D, clearTracks, heightAt,
  animateRover, stopRoverAnim, get available() { return true; },
  get sunState() { return { az: S._sunAz, el: S._sunEl, shadows: !!(S.renderer && S.renderer.shadowMap && S.renderer.shadowMap.enabled) }; },
  get hasLander() { return !!S.lander; } };
