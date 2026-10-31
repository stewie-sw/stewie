import { chromium } from "@playwright/test";

// GW-11 clause 4: verify viz3d.renderMissionFeatures draws keep-out rings + markers on the relief (/viz).
const URL = process.env.VIZ_URL || "http://127.0.0.1:8083/viz";
const SCR = "/tmp/claude-1000/-mnt-projects/0e6e85aa-70b0-4aae-8bf9-42ab645b19e0/scratchpad";
const b = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=gl-egl", "--enable-gpu", "--ignore-gpu-blocklist"] });
const p = await b.newPage({ viewport: { width: 1280, height: 820 } });
const errs = [];
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 140)); });
p.on("pageerror", (e) => errs.push("PAGEERR " + (e.message || e).slice(0, 140)));

await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
for (let i = 0; i < 45; i++) { if (await p.evaluate(() => !!(window.STEWIE_VIZ && window.STEWIE_VIZ.hasMesh && window.STEWIE_VIZ.meta))) break; await p.waitForTimeout(1000); }

// order-frame specs: a keep-out ring (circle at tile centre) + a marker near it. Real relief; test render input.
const res = await p.evaluate(() => {
  const V = window.STEWIE_VIZ, m = V.meta, W = m.window_m, cx = W * 0.5, cy = W * 0.55, r = W * 0.16;
  const ring = [];
  for (let i = 0; i <= 48; i++) { const t = (i / 48) * Math.PI * 2; ring.push([cx + r * Math.cos(t), cy + r * Math.sin(t)]); }
  V.renderMissionFeatures({ keepouts: [{ fid: "ko1", kind: "circle", ring }], markers: [{ fid: "m1", lx: cx, ly: cy * 0.6, otype: "beacon", label: "A" }] });
  return { requested: 2 };
});
await p.waitForTimeout(1200);
const flat = await p.evaluate(() => ({ missionFeatures: (window.STEWIE_VIZ._dbg || {}).missionFeatures }));
await p.screenshot({ path: SCR + "/viz_features_flat.png" });

// re-drape survives a vex change + a globe toggle
await p.evaluate(() => window.STEWIE_VIZ.setVertExag(2.5));
await p.waitForTimeout(800);
const afterVex = await p.evaluate(() => ({ missionFeatures: (window.STEWIE_VIZ._dbg || {}).missionFeatures }));
await p.evaluate(() => window.STEWIE_VIZ.setGlobe(true));
await p.waitForTimeout(2500);
const afterGlobe = await p.evaluate(() => ({ globe: window.STEWIE_VIZ.globe, missionFeatures: (window.STEWIE_VIZ._dbg || {}).missionFeatures }));
await p.screenshot({ path: SCR + "/viz_features_globe.png" });

// clear
await p.evaluate(() => window.STEWIE_VIZ.clearMissionFeatures());
await p.waitForTimeout(400);
const afterClear = await p.evaluate(() => ({ missionFeatures: (window.STEWIE_VIZ._dbg || {}).missionFeatures }));

await b.close().catch(() => {});
console.log(JSON.stringify({ res, flat, afterVex, afterGlobe, afterClear, console_errors: errs.filter((e) => !/favicon/i.test(e)).slice(0, 8) }, null, 2));
