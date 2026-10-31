import { chromium } from "@playwright/test";

// GW-11 increment 1: verify the frame wiring on the standalone /viz page (local origin, bypasses CF).
const URL = process.env.VIZ_URL || "http://127.0.0.1:8083/viz";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
const errs = [];
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 160)); });
p.on("pageerror", (e) => errs.push("PAGEERR " + (e.message || e).slice(0, 160)));

await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
let ready = false;
for (let i = 0; i < 45; i++) {
  ready = await p.evaluate(() => !!(window.STEWIE_VIZ && window.STEWIE_VIZ.hasMesh && window.STEWIE_VIZ.meta));
  if (ready) break;
  await p.waitForTimeout(1000);
}
const flat = await p.evaluate(() => ({
  frameLoaded: typeof window.STEWIEFrame !== "undefined",
  ready: window.STEWIE_VIZ.ready, hasMesh: window.STEWIE_VIZ.hasMesh,
  meta: window.STEWIE_VIZ.meta && { n: window.STEWIE_VIZ.meta.n, window_m: window.STEWIE_VIZ.meta.window_m,
    z_min: Math.round(window.STEWIE_VIZ.meta.z_min), z_max: Math.round(window.STEWIE_VIZ.meta.z_max) },
  globe: window.STEWIE_VIZ.globe, globeAvailable: window.STEWIE_VIZ.globeAvailable, vex: window.STEWIE_VIZ.vertExag,
}));

// hover the relief -> coordinate readout
const canvas = await p.$("#viz-root canvas");
const box = await canvas.boundingBox();
for (const [fx, fy] of [[0.5, 0.55], [0.48, 0.5], [0.55, 0.52]]) {
  await p.mouse.move(box.x + box.width * fx, box.y + box.height * fy); await p.waitForTimeout(500);
}
await p.waitForTimeout(700);
const hudFlat = (await p.evaluate(() => (document.querySelector("#viz-hud") || {}).textContent) || "").replace(/\s+/g, " ").trim();
const dbgFlat = await p.evaluate(() => window.STEWIE_VIZ._dbg);
await p.screenshot({ path: "/tmp/claude-1000/-mnt-projects/0e6e85aa-70b0-4aae-8bf9-42ab645b19e0/scratchpad/viz_flat.png" });

// toggle globe on
await p.click("#viz-globe").catch(() => {});
await p.waitForTimeout(3000);
const globeState = await p.evaluate(() => ({ globe: window.STEWIE_VIZ.globe, hasMesh: window.STEWIE_VIZ.hasMesh, vex: window.STEWIE_VIZ.vertExag }));
const dbgGlobe = await p.evaluate(() => window.STEWIE_VIZ._dbg);
await p.screenshot({ path: "/tmp/claude-1000/-mnt-projects/0e6e85aa-70b0-4aae-8bf9-42ab645b19e0/scratchpad/viz_globe.png" });

// vex up (in globe mode) then back flat
await p.evaluate(() => window.STEWIE_VIZ.setVertExag(3));
await p.waitForTimeout(900);
const vexAfter = await p.evaluate(() => window.STEWIE_VIZ.vertExag);
await p.screenshot({ path: "/tmp/claude-1000/-mnt-projects/0e6e85aa-70b0-4aae-8bf9-42ab645b19e0/scratchpad/viz_globe_vex3.png" });

await b.close();
console.log(JSON.stringify({ ready, flat, hudFlat, dbgFlat, globeState, dbgGlobe, vexAfter, console_errors: errs.filter((e) => !/favicon/i.test(e)).slice(0, 10) }, null, 2));
