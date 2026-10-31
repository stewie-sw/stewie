import { chromium } from "@playwright/test";

// Tight confirm: Cut tool -> open 3D -> Shift+click TWO spots -> reopen Mission Plan -> screenshot the panel
// + read the "Order queue (N)" count. Expect N == 2.
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 950 } });
const step = {};
await p.goto("https://artemis.stewie.space/ide/", { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 8000 }).catch(()=>{});
await p.waitForTimeout(8000);

const openMP = async () => {
  await p.getByText("Map & Tools", { exact: false }).first().click({ timeout: 6000 }).catch(()=>{});
  await p.waitForTimeout(700);
  await p.getByText("Mission Plan", { exact: false }).first().click({ timeout: 5000 }).catch(()=>{});
  await p.waitForTimeout(1500);
  // confirm the plan palette is present (panel really mounted+visible)
  return p.locator("[data-stewie-palette]").count();
};
step.mp_palette = await openMP();
await p.locator("[data-stewie-tool='cut']").first().click({ timeout: 5000 }).catch(()=>{});
await p.waitForTimeout(500);

await p.locator("[data-stewie-open3d]").first().click({ timeout: 5000 }).catch(()=>{});
await p.waitForTimeout(6000);
await p.evaluate(async () => { for (let i=0;i<20;i++){ if (window.STEWIE_VIZ?.hasMesh) return; await new Promise(r=>setTimeout(r,500)); } });
const canvas = p.locator("[data-stewie-terrain3d] canvas").first();
const box = await canvas.boundingBox();
for (const [fx,fy] of [[0.42,0.45],[0.6,0.6]]) {
  await p.mouse.move(box.x + box.width*fx, box.y + box.height*fy);
  await p.keyboard.down("Shift"); await p.mouse.down(); await p.mouse.up(); await p.keyboard.up("Shift");
  await p.waitForTimeout(2500); // site_lonlat + placeAt
}
// reopen Mission Plan + read the order queue
step.mp_palette2 = await openMP();
await p.screenshot({ path: "/tmp/ide_plot3d_confirm.png" });
step.orders = await p.evaluate(() => {
  const el = [...document.querySelectorAll("div,span")].map(n=>n.textContent||"").find(t=>/Order queue \(\d+\)/.test(t));
  const m = el && el.match(/Order queue \((\d+)\)/); return m ? +m[1] : null;
});
console.log(JSON.stringify(step, null, 2));
await b.close();
