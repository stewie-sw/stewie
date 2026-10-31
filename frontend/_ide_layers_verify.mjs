import { chromium } from "@playwright/test";

// GW-11 /ide layer-stack panel: toggle drapes -> composited overlays in the MissionTerrain3D card.
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
await p.locator(".appmenu-button").first().click({ timeout: 5000 }).catch(() => {});
await p.waitForTimeout(700);
await p.locator(".appmenu-submenu", { hasText: "Validate" }).first().click({ timeout: 4000 }).catch(() => {});
await p.waitForTimeout(700);
await p.getByText("Terrain 3D", { exact: false }).first().click({ timeout: 4000 }).catch(() => {});
let ready = false;
for (let i = 0; i < 40; i++) { ready = await p.evaluate(() => !!(window.STEWIE_VIZ && window.STEWIE_VIZ.hasMesh && window.STEWIE_VIZ.meta)); if (ready) break; await p.waitForTimeout(1000); }
await p.waitForTimeout(1500);
const panel = await p.evaluate(() => ({ layerRows: document.querySelectorAll("[data-stewie-layerstack] [data-stewie-layer]").length, overlays0: (window.STEWIE_VIZ._dbg || {}).layerOverlays }));

await p.locator('[data-stewie-layer="slope"]').check().catch(() => {});
await p.waitForTimeout(2500);
const afterSlope = await p.evaluate(() => (window.STEWIE_VIZ._dbg || {}).layerOverlays);
await p.locator('[data-stewie-layer="roughness"]').check().catch(() => {});
await p.waitForTimeout(3000);
const after2 = await p.evaluate(() => (window.STEWIE_VIZ._dbg || {}).layerOverlays);
await p.screenshot({ path: SCR + "/ide_layers.png" });
await b.close().catch(() => {});
console.log(JSON.stringify({ ready, panel, afterSlope, after2, console_errors: errs.filter((e) => !/favicon/i.test(e)).slice(0, 8) }, null, 2));
