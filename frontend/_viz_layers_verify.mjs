import { chromium } from "@playwright/test";

// GW-11 increment B: verify the draped layer stack on /viz. Resilient: prints flat-mode data even if the
// globe+overlays render (heavy full-res mesh) crashes the headless renderer. Tries GPU-enabled chromium.
const URL = process.env.VIZ_URL || "http://127.0.0.1:8083/viz";
const SCR = "/tmp/claude-1000/-mnt-projects/0e6e85aa-70b0-4aae-8bf9-42ab645b19e0/scratchpad";
const b = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=gl-egl", "--enable-gpu", "--ignore-gpu-blocklist", "--enable-unsafe-webgpu"] });
const p = await b.newPage({ viewport: { width: 1280, height: 820 } });
const errs = [];
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 160)); });
p.on("pageerror", (e) => errs.push("PAGEERR " + (e.message || e).slice(0, 160)));

const out = { init: null, afterSlope: null, after2: null, afterEdit: null, gl: null, globe: null, globeErr: null };
try {
  await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
  for (let i = 0; i < 45; i++) { if (await p.evaluate(() => !!(window.STEWIE_VIZ && window.STEWIE_VIZ.hasMesh && window.STEWIE_VIZ.meta))) break; await p.waitForTimeout(1000); }
  out.gl = await p.evaluate(() => { const c = document.querySelector("#viz-root canvas"); const g = c && (c.getContext("webgl2") || c.getContext("webgl")); if (!g) return "no-gl"; const dbg = g.getExtension("WEBGL_debug_renderer_info"); return dbg ? g.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : "gl-ok"; });
  out.init = await p.evaluate(() => ({ layersLoaded: typeof window.STEWIEViz3DLayers !== "undefined", panelRows: document.querySelectorAll("#viz-layers .lyr-row").length, count: (document.querySelector("#viz-layers-count") || {}).textContent }));

  await p.locator(".lyr-row", { hasText: "Hillshade" }).locator("input[type=checkbox]").check().catch(() => {});
  await p.waitForTimeout(2500);
  out.afterSlope = await p.evaluate(() => ({ count: (document.querySelector("#viz-layers-count") || {}).textContent, overlays: (window.STEWIE_VIZ._dbg || {}).layerOverlays }));

  await p.locator(".lyr-row", { hasText: "Aspect" }).locator("input[type=checkbox]").check().catch(() => {});
  await p.waitForTimeout(3500);
  out.after2 = await p.evaluate(() => ({ count: (document.querySelector("#viz-layers-count") || {}).textContent, overlays: (window.STEWIE_VIZ._dbg || {}).layerOverlays }));
  await p.screenshot({ path: SCR + "/viz_layers_2.png" });

  await p.locator(".lyr-row", { hasText: "Hillshade" }).locator("input[type=range]").fill("0.35").catch(() => {});
  await p.waitForTimeout(1000);
  await p.locator(".lyr-row", { hasText: "Aspect" }).locator("button", { hasText: "↑" }).click().catch(() => {});
  await p.waitForTimeout(1200);
  out.afterEdit = await p.evaluate(() => ({ count: (document.querySelector("#viz-layers-count") || {}).textContent, overlays: (window.STEWIE_VIZ._dbg || {}).layerOverlays }));
  await p.screenshot({ path: SCR + "/viz_layers_edit.png" });

  try {
    await p.locator("#viz-globe").check({ timeout: 5000 });
    await p.waitForTimeout(3500);
    out.globe = await p.evaluate(() => ({ globe: window.STEWIE_VIZ.globe, overlays: (window.STEWIE_VIZ._dbg || {}).layerOverlays }));
    await p.screenshot({ path: SCR + "/viz_layers_globe.png" });
  } catch (e) { out.globeErr = String(e).split("\n")[0].slice(0, 120); }
} catch (e) { out.fatal = String(e).split("\n")[0].slice(0, 140); }
await b.close().catch(() => {});
console.log(JSON.stringify({ ...out, console_errors: errs.filter((e) => !/favicon/i.test(e)).slice(0, 10) }, null, 2));
