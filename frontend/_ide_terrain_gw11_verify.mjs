import { chromium } from "@playwright/test";

// GW-11 increment C: verify the /ide MissionTerrain3D now loads frame/scalebar/layers -> globe + scale/north HUD.
const URL = process.env.IDE_URL || "http://127.0.0.1:8083/ide/";
const SCR = "/tmp/claude-1000/-mnt-projects/0e6e85aa-70b0-4aae-8bf9-42ab645b19e0/scratchpad";
const b = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=gl-egl", "--enable-gpu", "--ignore-gpu-blocklist"] });
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
const errs = [];
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 160)); });
p.on("pageerror", (e) => errs.push("PAGEERR " + (e.message || e).slice(0, 160)));

await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 6000 }).catch(() => {});
await p.waitForTimeout(4000);

const steps = [];
await p.locator(".appmenu-button").first().click({ timeout: 5000 }).then(() => steps.push("appmenu")).catch(() => steps.push("appmenu-FAIL"));
await p.waitForTimeout(700);
await p.locator(".appmenu-submenu", { hasText: "Validate" }).first().click({ timeout: 4000 }).then(() => steps.push("validate")).catch(() => steps.push("validate-FAIL"));
await p.waitForTimeout(700);
await p.getByText("Terrain 3D", { exact: false }).first().click({ timeout: 4000 }).then(() => steps.push("terrain3d")).catch(() => steps.push("terrain3d-FAIL"));

let ready = false;
for (let i = 0; i < 40; i++) { ready = await p.evaluate(() => !!(window.STEWIE_VIZ && window.STEWIE_VIZ.hasMesh && window.STEWIE_VIZ.meta)); if (ready) break; await p.waitForTimeout(1000); }
await p.waitForTimeout(2500);
const state = await p.evaluate(() => ({
  frameLoaded: typeof window.STEWIEFrame !== "undefined",
  scalebarLoaded: typeof window.STEWIE_SCALEBAR !== "undefined",
  layersLoaded: typeof window.STEWIEViz3DLayers !== "undefined",
  hasMesh: !!(window.STEWIE_VIZ && window.STEWIE_VIZ.hasMesh),
  globeAvailable: !!(window.STEWIE_VIZ && window.STEWIE_VIZ.globeAvailable),
  globe: !!(window.STEWIE_VIZ && window.STEWIE_VIZ.globe),
  scaleHud: !!document.querySelector("[data-stewie-scale] .stewie-sb-label"),
  scaleLabel: (document.querySelector("[data-stewie-scale] .stewie-sb-label") || {}).textContent || null,
  northHud: !!document.querySelector("[data-stewie-north] .stewie-north-needle"),
  sunHud: !!document.querySelector("[data-stewie-sun] .stewie-sun-needle"),
}));
await p.screenshot({ path: SCR + "/ide_terrain_flat.png" });

let globeState = null, globeErr = null;
try {
  await p.locator("[data-stewie-globe]").check({ timeout: 5000 });
  await p.waitForTimeout(3500);
  globeState = await p.evaluate(() => ({ globe: !!(window.STEWIE_VIZ && window.STEWIE_VIZ.globe), hasMesh: !!(window.STEWIE_VIZ && window.STEWIE_VIZ.hasMesh) }));
  await p.screenshot({ path: SCR + "/ide_terrain_globe.png" });
} catch (e) { globeErr = String(e).split("\n")[0].slice(0, 120); }

await b.close().catch(() => {});
console.log(JSON.stringify({ steps, ready, state, globeState, globeErr, console_errors: errs.filter((e) => !/favicon/i.test(e)).slice(0, 10) }, null, 2));
