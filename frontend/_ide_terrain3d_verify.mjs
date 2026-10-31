import { chromium } from "@playwright/test";

// Verify the GW-11 MissionTerrain3D panel renders inside the live QWC2 /ide.
// Flow: load /ide/ -> pick the theme (loads the map) -> Menu -> Terrain 3D -> confirm the 3D render.
const OUT = process.env.OUT || "/tmp/ide_terrain3d.png";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 950 } });
const errors = [];
p.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 160)); });
p.on("pageerror", (e) => errors.push("PAGEERROR " + e.message.slice(0, 160)));

const step = {};
await p.goto("https://artemis.stewie.space/ide/", { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(7000);

// 1. select the theme -> loads the OL map
try {
  await p.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 8000 });
  step.themeClicked = true;
} catch (e) { step.themeClicked = "FAIL " + (e.message || e).slice(0, 80); }
await p.waitForTimeout(8000); // map + layers

// 2. open the app menu (top-right "Map & Tools")
try {
  await p.getByText("Map & Tools", { exact: false }).first().click({ timeout: 6000 });
  step.menuOpened = true;
} catch (e) { step.menuOpened = "FAIL " + (e.message || e).slice(0, 80); }
await p.waitForTimeout(800);

// 3. click Terrain 3D (try direct; else expand Validate first)
try {
  await p.getByText("Terrain 3D", { exact: false }).first().click({ timeout: 4000 });
  step.terrain3dClicked = "direct";
} catch (_) {
  try {
    await p.getByText("Validate", { exact: false }).first().click({ timeout: 4000 });
    await p.waitForTimeout(500);
    await p.getByText("Terrain 3D", { exact: false }).first().click({ timeout: 4000 });
    step.terrain3dClicked = "via-validate";
  } catch (e) { step.terrain3dClicked = "FAIL " + (e.message || e).slice(0, 80); }
}

// 4. wait for the panel + full-res render via the exposed harness handle
let state = null;
for (let i = 0; i < 22; i++) {
  await p.waitForTimeout(2000);
  state = await p.evaluate(() => {
    const h = window.__stewieTerrain3D;
    const inj = document.querySelector("script[data-stewie-viz3d]");
    return {
      handle: !!h, mounted: h ? h.mounted() : null, loadedSite: h ? h.loadedSite() : null,
      meta: h && h.meta() ? { n: h.meta().n, site: h.meta().site } : null,
      injectedSrc: inj ? inj.getAttribute("src") : null, viz: !!window.STEWIE_VIZ,
    };
  });
  if (state && state.meta) break;
}

await p.screenshot({ path: OUT });
console.log(JSON.stringify({ step, state, errors: errors.slice(0, 10) }, null, 2));
await b.close();
