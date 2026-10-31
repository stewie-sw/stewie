import { chromium } from "@playwright/test";

// #56 auto-float: open Mission Plan (docked, NOT floated) -> click the "3D" button -> a Terrain 3D FLOATING
// card appears AND the Mission Plan palette is still present (coexistence in one click, plan not hidden).
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
step.titles_before = await winTitles();                  // [] — MP is docked, no floating windows yet
// click the "3D" button WITHOUT floating MP first
step.click3d = await domClick("[data-stewie-open3d]");
await p.waitForTimeout(4500);
step.titles_after = await winTitles();                   // expect ["Terrain 3D"] — floated in one click
step.mp_still_visible = await p.locator("[data-stewie-palette]").count();   // MP palette still present (not hidden)
step.meshReady = await p.evaluate(async()=>{for(let i=0;i<20;i++){if(window.STEWIE_VIZ?.hasMesh)return true;await new Promise(r=>setTimeout(r,500));}return !!(window.STEWIE_VIZ?.hasMesh);});

await p.screenshot({ path:"/tmp/ide_autofloat.png" });
console.log(JSON.stringify({ step, terrain3d_floated: (step.titles_after||[]).includes("Terrain 3D"), errs:errs.slice(0,5) }, null, 2));
await b.close();
