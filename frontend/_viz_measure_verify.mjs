import { chromium } from "@playwright/test";

// #79 verify on /viz: enable the 📏 measure toggle, click 3 points on the relief, confirm the readout shows
// a point count + distance; screenshot shows the measure path + the labeled lat/lon graticule.
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
const errs = [];
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 150)); });
p.on("pageerror", (e) => errs.push("PAGEERROR " + (e.message || e).slice(0, 150)));
const step = {};

await p.goto("https://artemis.stewie.space/viz", { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(9000); // heightfield + mesh
step.meshReady = await p.evaluate(async()=>{for(let i=0;i<24;i++){if(window.STEWIE_VIZ?.hasMesh)return true;await new Promise(r=>setTimeout(r,500));}return !!(window.STEWIE_VIZ?.hasMesh);});
step.measureToggleExists = await p.locator("#viz-measure").count();

// enable measure mode
await p.locator("#viz-measure").check().catch(()=>{});
await p.waitForTimeout(500);
step.measureModeApi = await p.evaluate(() => typeof window.STEWIE_VIZ?.setMeasureMode);

// click 3 points across the relief (measure mode -> waypoints)
const root = p.locator("#viz-root canvas").first();
const box = await root.boundingBox();
for (const [fx,fy] of [[0.4,0.45],[0.55,0.55],[0.65,0.4]]) {
  await p.mouse.move(box.x+box.width*fx, box.y+box.height*fy);
  await p.mouse.down(); await p.mouse.up();  // plain click (no shift) in measure mode
  await p.waitForTimeout(1600); // site_lonlat + redraw
}
step.readout = await p.evaluate(() => { const el=document.getElementById("viz-measure-out"); return el ? (el.textContent||"").trim() : "MISSING"; });
await p.screenshot({ path: "/tmp/viz_measure.png" });

// clear
step.clearApi = await p.evaluate(() => typeof window.STEWIE_VIZ?.clearMeasure);
await p.locator("#viz-measure-clear").click().catch(()=>{});
await p.waitForTimeout(600);
step.readout_after_clear = await p.evaluate(() => { const el=document.getElementById("viz-measure-out"); return el ? (el.textContent||"").trim() : "MISSING"; });

console.log(JSON.stringify({ step, errs: errs.slice(0,5) }, null, 2));
await b.close();
