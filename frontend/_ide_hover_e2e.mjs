import { chromium } from "@playwright/test";

// GW-11 clause (c) LIVE: hover the /ide 3D relief -> the IDE coordinate display shows order metres + elev +
// selenographic lon/lat. Real GPU raycast against the loaded Haworth DEM mesh on the deployed artemis /ide.
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
await p.waitForTimeout(3000);

const steps = [];
// open Mission Plan (mounts planAuthor), then float the Terrain 3D card via its "3D" button -- the same path
// the working clause-4 features e2e uses.
await p.locator(".appmenu-button").first().click({ timeout: 5000 }).catch(() => {});
await p.waitForTimeout(700);
await p.locator(".appmenu-submenu", { hasText: "Plan" }).first().click({ timeout: 4000 }).catch(() => {});
await p.waitForTimeout(700);
await p.getByText("Mission Plan", { exact: false }).first().click({ timeout: 4000 }).then(() => steps.push("missionplan")).catch(() => steps.push("mp-FAIL"));
await p.waitForTimeout(3500);
await p.locator("[data-stewie-open3d]").first().click({ timeout: 5000 }).then(() => steps.push("open3d")).catch(() => steps.push("open3d-FAIL"));

let ready = false;
for (let i = 0; i < 40; i++) { ready = await p.evaluate(() => !!(window.STEWIE_VIZ && window.STEWIE_VIZ.hasMesh && window.STEWIE_VIZ.meta)); if (ready) break; await p.waitForTimeout(1000); }
await p.waitForTimeout(1500);

// hover the 3D canvas at several points to trigger the raycast readout; sweep so at least one hits the mesh.
const canvas = p.locator("[data-stewie-terrain3d] canvas").first();
const box = await canvas.boundingBox().catch(() => null);
const readHud = async () => p.evaluate(() => {
  const q = (s) => { const el = document.querySelector(s); return el ? el.textContent.trim() : null; };
  return { en: q("[data-stewie-hud-en]"), elev: q("[data-stewie-hud-elev]"), ll: q("[data-stewie-hud-ll]") };
});
let hud = null;
if (box) {
  const pts = [[0.5, 0.55], [0.45, 0.5], [0.55, 0.6], [0.5, 0.45], [0.6, 0.5]];
  for (const [fx, fy] of pts) {
    await p.mouse.move(box.x + box.width * fx, box.y + box.height * fy, { steps: 6 });
    await p.waitForTimeout(500);   // let the debounced /dem/site_lonlat lookup resolve (120ms debounce + fetch)
    hud = await readHud();
    if (hud.en && !/E — m/.test(hud.en)) break;   // got a real E/N reading
  }
  await p.waitForTimeout(400);
  hud = await readHud();
}
await p.screenshot({ path: SCR + "/ide_hover_e2e.png" });
await b.close().catch(() => {});

// A real reading: E/N are non-dash order metres, and lon/lat resolved to a selenographic pair (or dash if the
// lookup was mid-flight on the last sample -- E/N alone still proves the coordinate readout works).
const enOk = !!(hud && hud.en && !/E\s+—/.test(hud.en) && /E\s+-?\d/.test(hud.en));
const llOk = !!(hud && hud.ll && /lat\s+-?\d/.test(hud.ll) && !/lat\s+—/.test(hud.ll));
console.log(JSON.stringify({ steps, ready, hud, enOk, llOk, hasBox: !!box, console_errors: errs.filter((e) => !/favicon/i.test(e)).slice(0, 6) }, null, 2));
