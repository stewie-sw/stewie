import { chromium } from "@playwright/test";

// Prove the /viz analysis drapes + lat/lon graticule + km grid work: load Haworth, drape SLOPE with
// both gridlines on, screenshot; then swap to HAZARD, screenshot. Capture any layer errors.
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
const errs = [];
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 180)); });
p.on("pageerror", (e) => errs.push("PAGEERROR " + (e.message || e).slice(0, 180)));

await p.goto("https://artemis.stewie.space/viz", { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(9000); // heightfield load + mesh

// turn on both gridlines
await p.locator("#viz-grid").check().catch(() => {});
await p.locator("#viz-grat").check().catch(() => {});
await p.waitForTimeout(1500);

// drape: slope
await p.locator("#viz-layer").selectOption("slope").catch(() => {});
await p.waitForTimeout(4000);
const s1 = await p.evaluate(() => ({ layer: window.STEWIE_VIZ?.layerKind, status: (document.getElementById("viz-status")||{}).textContent?.slice(0,120) }));
await p.screenshot({ path: "/tmp/viz_slope_grid.png" });

// drape: hazard
await p.locator("#viz-layer").selectOption("hazard").catch(() => {});
await p.waitForTimeout(4000);
const s2 = await p.evaluate(() => ({ layer: window.STEWIE_VIZ?.layerKind }));
await p.screenshot({ path: "/tmp/viz_hazard_grid.png" });

console.log(JSON.stringify({ slope: s1, hazard: s2, errs }, null, 2));
await b.close();
