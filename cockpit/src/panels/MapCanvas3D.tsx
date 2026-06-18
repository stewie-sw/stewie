/* Phase 4 — the local 3D world canvas, a THIN React boundary around an imperative Three.js scene. The
 * renderer/scene are created ONCE on mount (ref + effect); prop changes are applied imperatively in a
 * separate effect (the canvas is never re-rendered by React); everything is disposed on unmount. This is
 * the pattern every WebGL surface in the cockpit uses.
 *
 * It draws the spatial SCAFFOLD only — a reference ground grid + lunar lighting + a rover marker. The real
 * elevation mesh binds to GET /dem/heightfield when the backend is up (no fabricated terrain here). The
 * planetary Cesium globe is the GPU-gated sibling view (needs a real browser + tile service to confirm). */
import { useEffect, useRef } from "react";
import * as THREE from "three";

export function MapCanvas3D({ accent = "#e8273f" }: { accent?: string }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const markerRef = useRef<THREE.MeshStandardMaterial | null>(null);

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
    const camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 1000);
    camera.position.set(11, 8, 11);
    camera.lookAt(0, 0, 0);

    // reference ground grid — the SCAFFOLD; the real DEM heightfield mesh binds via /dem/heightfield
    scene.add(new THREE.GridHelper(20, 20, 0x34343c, 0x18181d));

    // lunar lighting: dim ambient + a low directional "sun"
    scene.add(new THREE.AmbientLight(0x404048, 1.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.5);
    sun.position.set(6, 10, 4);
    scene.add(sun);

    // rover marker (drum-red); its material is the one prop-driven object
    const mat = new THREE.MeshStandardMaterial({ color: new THREE.Color(accent), emissive: new THREE.Color(accent), emissiveIntensity: 0.3, roughness: 0.5 });
    const marker = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.6, 2.0), mat);
    marker.position.y = 0.3;
    scene.add(marker);
    markerRef.current = mat;

    let raf = 0;
    let t = 0;
    const loop = () => {
      t += 0.004;
      camera.position.x = Math.cos(t) * 15;
      camera.position.z = Math.sin(t) * 15;
      camera.lookAt(0, 0, 0);
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
      renderer.dispose();
      if (renderer.domElement.parentNode === el) el.removeChild(renderer.domElement);
      markerRef.current = null;
    };
  }, []); // mount once — NEVER re-create the scene on a prop change

  // prop update applied imperatively (no scene rebuild): recolor the rover marker
  useEffect(() => {
    const mat = markerRef.current;
    if (!mat) return;
    mat.color.set(accent);
    mat.emissive.set(accent);
  }, [accent]);

  return <div ref={mountRef} style={{ position: "absolute", inset: 0 }} aria-label="3D world canvas" />;
}
