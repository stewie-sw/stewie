import { chromium } from "@playwright/test";

// GW-11 clause 4 END-TO-END: author keep-outs on the 2D map (Derive-from-hazard) -> they appear in the 3D view.
const URL = process.env.IDE_URL || "http://127.0.0.1:8083/ide/";
const SCR = "/tmp/claude-1000/-mnt-projects/0e6e85aa-70b0-4aae-8bf9-42ab645b19e0/scratchpad";
const b = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=gl-egl", "--enable-gpu", "--ignore-gpu-blocklist"] });
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
const errs = [];
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 140)); });
p.on("pageerror", (e) => errs.push("PAGEERR " + (e.message || e).slice(0, 140)));

await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 6000 }).catch(() => {});
await p.waitForTimeout(4000);

const steps = [];
// open Mission Plan (loads planAuthor -> mints the edit-session)
await p.locator(".appmenu-button").first().click({ timeout: 5000 }).catch(() => {});
await p.waitForTimeout(700);
await p.locator(".appmenu-submenu", { hasText: "Plan" }).first().click({ timeout: 4000 }).catch(() => {});
await p.waitForTimeout(700);
await p.getByText("Mission Plan", { exact: false }).first().click({ timeout: 4000 }).then(() => steps.push("missionplan")).catch(() => steps.push("mp-FAIL"));
await p.waitForTimeout(3500);
// float the Terrain 3D card via the Mission Plan "3D" button
await p.locator("[data-stewie-open3d]").first().click({ timeout: 5000 }).then(() => steps.push("open3d")).catch(() => steps.push("open3d-FAIL"));
let ready = false;
for (let i = 0; i < 40; i++) { ready = await p.evaluate(() => !!(window.STEWIE_VIZ && window.STEWIE_VIZ.hasMesh && window.STEWIE_VIZ.meta)); if (ready) break; await p.waitForTimeout(1000); }
await p.waitForTimeout(1500);
const before = await p.evaluate(() => (window.STEWIE_VIZ._dbg || {}).missionFeatures);

// author keep-outs on the 2D map: Derive from hazard (24 real hazard polygons for Haworth)
await p.locator("[data-stewie-derive-keepouts]").first().click({ timeout: 5000 }).then(() => steps.push("derive")).catch(() => steps.push("derive-FAIL"));
await p.waitForTimeout(9000);   // fetch hazard + reproject + POST keep-outs -> _adoptEditState -> WS.emitFeatures -> 3D
const after = await p.evaluate(() => (window.STEWIE_VIZ._dbg || {}).missionFeatures);
const koVer = await p.evaluate(() => { const el = document.querySelector("[data-stewie-ko-version]"); return el ? el.getAttribute("data-stewie-ko-version") : null; });
const diag = await p.evaluate(() => {
  const h = window.__stewieTerrain3D; if (!h) return { noHandle: true };
  const ws = h.ws(), specs = h.specs(), meta = h.meta();
  const f0 = ws && ws.features[0];
  return {
    wsFeatures: ws ? ws.features.length : -1, wsMarkers: ws ? ws.markers.length : -1,
    wsSample: f0 ? { kind: f0.kind, cx: f0.cx, cy: f0.cy, r: f0.r, ringLen: f0.ring ? f0.ring.length : null, ring0: f0.ring ? f0.ring[0] : null } : null,
    specsKeepouts: specs ? specs.keepouts.length : -1,
    meta: meta ? { x0: Math.round(meta.x0), y0: Math.round(meta.y0), window_m: Math.round(meta.window_m) } : null,
  };
});
await p.screenshot({ path: SCR + "/ide_features_e2e.png" });

await b.close().catch(() => {});
console.log(JSON.stringify({ steps, ready, before, after, koVersion: koVer, diag, console_errors: errs.filter((e) => !/favicon/i.test(e)).slice(0, 8) }, null, 2));
