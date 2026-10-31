import { chromium } from "@playwright/test";
const b = await chromium.launch({ args: ["--use-gl=angle","--use-angle=gl-egl","--enable-gpu","--ignore-gpu-blocklist"] });
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
await p.goto("http://127.0.0.1:8083/ide/", { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole",{exact:false}).first().click({timeout:6000}).catch(()=>{});
await p.waitForTimeout(3000);
await p.evaluate(() => window.qwc2.setCurrentTask("MissionPlan"));
await p.waitForTimeout(1800);
const shape = await p.evaluate(() => {
  const st = window.qwc2.getState ? window.qwc2.getState() : null;
  return {
    hasGetState: !!window.qwc2.getState,
    taskKeys: st && st.task ? Object.keys(st.task) : null,
    task: st && st.task ? st.task : null,
    topKeys: st ? Object.keys(st).slice(0,20) : null,
    domMissionPlan: document.querySelectorAll("#MissionPlan").length,
  };
});
await b.close().catch(()=>{});
console.log(JSON.stringify(shape,null,2));
