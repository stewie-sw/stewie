import { chromium } from "@playwright/test";

// #56: reliable path — open Mission Plan (menu, retried) -> float; open Terrain 3D via the in-panel "3D"
// button (DOM-click, no menu) -> float; assert BOTH ResizeableWindows coexist; drag; Shift+click 3D -> order.
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1700, height: 1000 } });
const errs = [];
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 140)); });
p.on("pageerror", (e) => errs.push("PAGEERROR " + (e.message || e).slice(0, 140)));
const step = {};
const winTitles = () => p.evaluate(() => [...document.querySelectorAll(".resizeable-window-titlebar-title")].map(n => (n.textContent||"").trim()));
const domClick = (sel) => p.evaluate((s)=>{const el=document.querySelector(s); if(el){el.click(); return true;} return false;}, sel);
const openMP = async () => {
  for (let a=0;a<4;a++){
    await p.getByText("Map & Tools",{exact:false}).first().click({timeout:6000}).catch(()=>{});
    await p.waitForTimeout(800);
    await p.getByText("Mission Plan",{exact:false}).first().click({timeout:3500}).catch(()=>{});
    await p.waitForTimeout(400);
    await p.getByText(/^Plan$/,{exact:false}).first().click({timeout:2000}).catch(()=>{});
    await p.waitForTimeout(300);
    await p.getByText("Mission Plan",{exact:false}).first().click({timeout:3000}).catch(()=>{});
    await p.waitForTimeout(1400);
    if(await p.locator("[data-stewie-palette]").count() > 0) return true;
  }
  return false;
};

await p.goto("https://artemis.stewie.space/ide/", { waitUntil:"domcontentloaded", timeout:45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole",{exact:false}).first().click({timeout:8000}).catch(()=>{});
await p.waitForTimeout(8000);

step.openMP = await openMP();
await domClick("[data-stewie-tool='cut']");
await p.waitForTimeout(400);
step.floatMP = await domClick("[data-stewie-float]");     // MP's float button (only one shown while docked)
await p.waitForTimeout(1800);
step.after_mp = await winTitles();                        // ["Mission Plan"]

// open Terrain 3D via the "3D" button inside the (now floating) MP card
step.open3d = await domClick("[data-stewie-open3d]");
await p.waitForTimeout(4500);
step.meshReady = await p.evaluate(async()=>{for(let i=0;i<24;i++){if(window.STEWIE_VIZ?.hasMesh)return true;await new Promise(r=>setTimeout(r,500));}return !!(window.STEWIE_VIZ?.hasMesh);});
step.float3D = await domClick("[data-stewie-float]");     // now the only docked float button is Terrain 3D's
await p.waitForTimeout(2500);
step.titles = await winTitles();                          // expect BOTH "Mission Plan" and "Terrain 3D"

// drag Mission Plan window by titlebar
const tb = await p.locator(".resizeable-window-titlebar",{hasText:"Mission Plan"}).first().boundingBox().catch(()=>null);
if(tb){ await p.mouse.move(tb.x+40,tb.y+8); await p.mouse.down(); await p.mouse.move(tb.x+60,tb.y+320,{steps:8}); await p.mouse.up(); step.dragged=1; }
await p.waitForTimeout(800);

// plot: Shift+click the 3D card canvas -> order in the MP card queue
// count real order rows (each has a "remove order" button) — reliable vs the queue-count text
const orderCount = () => p.evaluate(()=> document.querySelectorAll('[title="remove order"]').length);
// ensure the floating 3D card's mesh finished reloading before we click
step.meshReady2 = await p.evaluate(async()=>{for(let i=0;i<30;i++){if(window.STEWIE_VIZ?.hasMesh)return true;await new Promise(r=>setTimeout(r,500));}return !!(window.STEWIE_VIZ?.hasMesh);});
step.orders_before = await orderCount();
const cb = await p.locator("[data-stewie-terrain3d] canvas").first().boundingBox().catch(()=>null);
if(cb){
  // three shift-clicks across the relief to be robust to exact geometry
  for (const [fx,fy] of [[0.5,0.45],[0.42,0.55],[0.6,0.4]]) {
    await p.mouse.move(cb.x+cb.width*fx, cb.y+cb.height*fy);
    await p.keyboard.down("Shift"); await p.mouse.down(); await p.mouse.up(); await p.keyboard.up("Shift");
    await p.waitForTimeout(1800);
  }
  step.shiftclick=1;
} else step.shiftclick="NO_CANVAS";
await p.waitForTimeout(3000);
step.orders_after = await orderCount();

await p.screenshot({ path:"/tmp/ide_floatcards.png" });
console.log(JSON.stringify({ step, coexist:(step.titles||[]).filter(t=>/Mission Plan|Terrain 3D/.test(t)), errs:errs.slice(0,5) }, null, 2));
await b.close();
