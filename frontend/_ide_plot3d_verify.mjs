import { chromium } from "@playwright/test";

// Round-trip: open Mission Plan, pick the Cut tool, note order count; open the 3D panel via the "3D" button;
// Shift+click the terrain; return to Mission Plan and check the order count increased. Also screenshot the
// 3D marker. Detects the "MissionPlan unmounts on task-switch -> onPlot dropped" risk.
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 950 } });
const errs = [];
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 160)); });
p.on("pageerror", (e) => errs.push("PAGEERROR " + (e.message || e).slice(0, 160)));

const step = {};
const openMissionPlan = async () => {
  await p.getByText("Map & Tools", { exact: false }).first().click({ timeout: 6000 }).catch(() => {});
  await p.waitForTimeout(600);
  try { await p.getByText("Mission Plan", { exact: false }).first().click({ timeout: 4000 }); }
  catch (_) { await p.getByText(/^Plan$/, { exact: false }).first().click({ timeout: 3000 }).catch(()=>{});
              await p.waitForTimeout(300); await p.getByText("Mission Plan", { exact: false }).first().click({ timeout: 4000 }).catch(()=>{}); }
  await p.waitForTimeout(1200);
};
const orderCount = () => p.evaluate(() => {
  const el = [...document.querySelectorAll("div")].find((d) => /^Order queue \(\d+\)/.test(d.textContent || ""));
  if (!el) return null;
  const m = (el.textContent || "").match(/Order queue \((\d+)\)/);
  return m ? +m[1] : null;
});

await p.goto("https://artemis.stewie.space/ide/", { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 8000 }).then(()=>step.theme=1).catch(()=>step.theme="FAIL");
await p.waitForTimeout(8000);

await openMissionPlan();
// pick the Cut tool
await p.locator("[data-stewie-tool='cut']").first().click({ timeout: 5000 }).then(()=>step.cut=1).catch((e)=>step.cut="FAIL "+(e.message||e).slice(0,50));
await p.waitForTimeout(600);
step.orders_before = await orderCount();

// open the 3D panel via the new button
await p.locator("[data-stewie-open3d]").first().click({ timeout: 5000 }).then(()=>step.open3d=1).catch((e)=>step.open3d="FAIL "+(e.message||e).slice(0,50));
await p.waitForTimeout(6000);
// wait for the 3D terrain to load a mesh
const meshReady = await p.evaluate(async () => {
  for (let i=0;i<20;i++){ if (window.STEWIE_VIZ && window.STEWIE_VIZ.hasMesh) return true; await new Promise(r=>setTimeout(r,500)); }
  return !!(window.STEWIE_VIZ && window.STEWIE_VIZ.hasMesh);
});
step.meshReady = meshReady;

// Shift+click the 3D terrain canvas center
const canvas = p.locator("[data-stewie-terrain3d] canvas").first();
const box = await canvas.boundingBox().catch(()=>null);
if (box) {
  await p.mouse.move(box.x + box.width/2, box.y + box.height/2);
  await p.keyboard.down("Shift");
  await p.mouse.down(); await p.mouse.up();
  await p.keyboard.up("Shift");
  step.shiftclick = 1;
} else { step.shiftclick = "NO_CANVAS"; }
await p.waitForTimeout(4000); // site_lonlat + placeAt async hops
await p.screenshot({ path: "/tmp/ide_plot3d.png" });

// back to Mission Plan, re-read order count
await openMissionPlan();
step.orders_after = await orderCount();

console.log(JSON.stringify({ step, delta: (step.orders_after!=null && step.orders_before!=null) ? step.orders_after-step.orders_before : "n/a", errs: errs.slice(0,6) }, null, 2));
await b.close();
