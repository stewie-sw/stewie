import { chromium } from "@playwright/test";

// #80: open Mission Plan -> "3D" (auto-floats the 3D card) -> enable 📏 measure -> click 3 points ->
// "Send to plan (route)" -> the Mission Plan order queue gains ~3 Traverse waypoints.
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1700, height: 1000 } });
const errs = [];
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 140)); });
p.on("pageerror", (e) => errs.push("PAGEERROR " + (e.message || e).slice(0, 140)));
const step = {};
const domClick = (sel) => p.evaluate((s)=>{const el=document.querySelector(s); if(el){el.click(); return true;} return false;}, sel);
const orderRows = () => p.evaluate(()=> document.querySelectorAll('[title="remove order"]').length);
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

await p.goto(process.env.IDE_URL || "https://artemis.stewie.space/ide/", { waitUntil:"domcontentloaded", timeout:45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole",{exact:false}).first().click({timeout:8000}).catch(()=>{});
await p.waitForTimeout(8000);

step.openMP = await openMP();
step.orders_before = await orderRows();
// "3D" button auto-floats the Terrain 3D card (task #56)
step.open3d = await domClick("[data-stewie-open3d]");
await p.waitForTimeout(4500);
step.meshReady = await p.evaluate(async()=>{for(let i=0;i<24;i++){if(window.STEWIE_VIZ?.hasMesh)return true;await new Promise(r=>setTimeout(r,500));}return !!(window.STEWIE_VIZ?.hasMesh);});
// enable measure mode
step.measureOn = await domClick("[data-stewie-measure]");
await p.waitForTimeout(600);
// click 3 measure points on the 3D card canvas
const cb = await p.locator("[data-stewie-terrain3d] canvas").first().boundingBox().catch(()=>null);
if(cb){
  for (const [fx,fy] of [[0.42,0.45],[0.55,0.55],[0.6,0.4]]) {
    await p.mouse.move(cb.x+cb.width*fx, cb.y+cb.height*fy);
    await p.mouse.down(); await p.mouse.up();  // plain click (measure mode)
    await p.waitForTimeout(1700);
  }
  step.measured = 1;
} else step.measured = "NO_CANVAS";
step.measureReadout = await p.evaluate(()=>{const el=document.querySelector("[data-stewie-measure-out]"); return el?(el.textContent||"").trim():"MISSING";});
// send to plan as route
step.sendRoute = await domClick("[data-stewie-send-route]");
await p.waitForTimeout(4000);
step.sentMsg = await p.evaluate(()=>{const el=document.querySelector("[data-stewie-send-route-msg]"); return el?(el.textContent||"").trim():"MISSING";});
step.orders_after = await orderRows();

await p.screenshot({ path:"/tmp/ide_route.png" });
console.log(JSON.stringify({ step, delta: (step.orders_after!=null&&step.orders_before!=null)?step.orders_after-step.orders_before:"n/a", errs:errs.slice(0,5) }, null, 2));
await b.close();
