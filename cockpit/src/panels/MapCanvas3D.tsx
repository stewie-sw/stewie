/* Phase 4 / 4b — the local 3D world canvas: a THIN React boundary around an imperative Three.js scene.
 * Renderer/scene created ONCE on mount; props applied imperatively in separate effects (the canvas is
 * never React-re-rendered); everything disposed on unmount.
 *   - REAL terrain: when a heightfield (from GET /dem/heightfield — real LOLA elevation) is supplied, a
 *     deformed, elevation-ramped mesh is built (no fabricated terrain; a reference grid is the fallback).
 *   - Plan authoring (4b): a pointer-down raycasts onto the terrain and reports the order-frame (x,y) so
 *     the operator can place build orders by clicking the world; placed orders render as drum-red pins.
 * The planetary Cesium globe is the GPU-gated sibling (real browser + tile service). */
import { useEffect, useRef } from "react";
import * as THREE from "three";
import type { Heightfield } from "../api";

interface Props {
  accent?: string;
  heightfield?: Heightfield | null;
  orders?: { x: number; y: number }[];
  onPlace?: (x: number, y: number) => void;
}

const VERT_EXAG = 2.5; // modest vertical exaggeration — relief over a ~300 m window is small (labelled in the UI)

export function MapCanvas3D({ accent = "#e8273f", heightfield = null, orders = [], onPlace }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const terrainRef = useRef<THREE.Object3D | null>(null);
  const markersRef = useRef<THREE.Group | null>(null);
  const roverMatRef = useRef<THREE.MeshStandardMaterial | null>(null);
  const hfRef = useRef<Heightfield | null>(heightfield);
  const onPlaceRef = useRef(onPlace);
  onPlaceRef.current = onPlace;

  useEffect(() => {
    const el = mountRef.current;
    if (!el) return;
    const w = el.clientWidth || 800;
    const h = el.clientHeight || 600;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(w, h);
    renderer.setClearColor(0x05060c, 1);
    renderer.domElement.setAttribute("data-testid", "world-canvas");
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    sceneRef.current = scene;
    const camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 6000);
    camera.position.set(230, 210, 270); // fixed oblique view -> predictable click-to-place picking
    camera.lookAt(0, 0, 0);

    scene.add(new THREE.AmbientLight(0x505058, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(140, 220, 90);
    scene.add(sun);

    const markers = new THREE.Group();
    scene.add(markers);
    markersRef.current = markers;

    const rmat = new THREE.MeshStandardMaterial({ color: new THREE.Color(accent), emissive: new THREE.Color(accent), emissiveIntensity: 0.3, roughness: 0.5 });
    const rover = new THREE.Mesh(new THREE.BoxGeometry(9, 4, 13), rmat);
    rover.position.set(0, 6, 0);
    scene.add(rover);
    roverMatRef.current = rmat;

    const raycaster = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0); // y=0 fallback
    const groundHit = new THREE.Vector3();
    const onClick = (e: MouseEvent) => {
      const hf = hfRef.current;
      if (!hf || !onPlaceRef.current) return;
      const r = renderer.domElement.getBoundingClientRect();
      ndc.x = ((e.clientX - r.left) / r.width) * 2 - 1;
      ndc.y = -((e.clientY - r.top) / r.height) * 2 + 1;
      raycaster.setFromCamera(ndc, camera);
      // prefer the terrain surface; fall back to the ground plane so a click always resolves a point
      let pt: THREE.Vector3 | null = null;
      const t = terrainRef.current;
      const hit = t ? raycaster.intersectObject(t, true)[0] : undefined;
      if (hit) pt = hit.point;
      else if (raycaster.ray.intersectPlane(groundPlane, groundHit)) pt = groundHit;
      if (!pt) return;
      const W = hf.windowM; // order frame: x East, y North in [0, window_m]; terrain centred at the origin
      onPlaceRef.current(Math.max(0, Math.min(W, pt.x + W / 2)), Math.max(0, Math.min(W, pt.z + W / 2)));
    };
    renderer.domElement.addEventListener("click", onClick);

    let raf = 0;
    const loop = () => {
      renderer.render(scene, camera);
      raf = requestAnimationFrame(loop);
    };
    loop();

    const ro = new ResizeObserver(() => {
      const cw = el.clientWidth;
      const ch = el.clientHeight;
      if (cw && ch) {
        renderer.setSize(cw, ch);
        camera.aspect = cw / ch;
        camera.updateProjectionMatrix();
      }
    });
    ro.observe(el);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      renderer.domElement.removeEventListener("click", onClick);
      renderer.dispose();
      if (renderer.domElement.parentNode === el) el.removeChild(renderer.domElement);
      sceneRef.current = null;
      terrainRef.current = null;
      markersRef.current = null;
      roverMatRef.current = null;
    };
  }, []); // mount once

  // build/replace the terrain when the real heightfield arrives (else a reference grid)
  useEffect(() => {
    hfRef.current = heightfield;
    const scene = sceneRef.current;
    if (!scene) return;
    if (terrainRef.current) {
      scene.remove(terrainRef.current);
      const old = terrainRef.current as THREE.Mesh;
      old.geometry?.dispose?.();
      terrainRef.current = null;
    }
    if (!heightfield) {
      const grid = new THREE.GridHelper(300, 30, 0x34343c, 0x18181d);
      scene.add(grid);
      terrainRef.current = grid;
      return;
    }
    const { n, windowM: W, z, zMin, zMax } = heightfield;
    const geo = new THREE.PlaneGeometry(W, W, n - 1, n - 1);
    geo.rotateX(-Math.PI / 2); // XY plane -> XZ ground plane, y up
    const pos = geo.attributes.position as THREE.BufferAttribute;
    const colors = new Float32Array(pos.count * 3);
    const span = Math.max(1e-6, zMax - zMin);
    for (let k = 0; k < pos.count; k++) {
      const zz = z[k] ?? zMin;
      pos.setY(k, (zz - zMin) * VERT_EXAG);
      const g = 0.10 + 0.5 * ((zz - zMin) / span); // graphite ramp: low dark -> high light
      colors[k * 3] = g;
      colors[k * 3 + 1] = g;
      colors[k * 3 + 2] = g * 1.06;
    }
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geo.computeVertexNormals();
    geo.computeBoundingSphere(); // raised vertices -> refresh the bounding volume so the raycaster won't early-reject
    geo.computeBoundingBox();
    const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.96, metalness: 0 });
    const mesh = new THREE.Mesh(geo, mat);
    scene.add(mesh);
    terrainRef.current = mesh;
  }, [heightfield]);

  // rebuild order pins when the queue changes
  useEffect(() => {
    const g = markersRef.current;
    if (!g) return;
    while (g.children.length) {
      const c = g.children.pop() as THREE.Mesh;
      c.geometry?.dispose?.();
    }
    const W = hfRef.current?.windowM ?? 300;
    for (const o of orders) {
      const m = new THREE.MeshStandardMaterial({ color: new THREE.Color(accent), emissive: new THREE.Color(accent), emissiveIntensity: 0.6 });
      const pin = new THREE.Mesh(new THREE.ConeGeometry(5, 18, 14), m);
      pin.position.set(o.x - W / 2, 16, o.y - W / 2);
      g.add(pin);
    }
  }, [orders, accent]);

  useEffect(() => {
    const m = roverMatRef.current;
    if (m) {
      m.color.set(accent);
      m.emissive.set(accent);
    }
  }, [accent]);

  return <div ref={mountRef} style={{ position: "absolute", inset: 0, cursor: "crosshair" }} aria-label="3D world canvas" />;
}
