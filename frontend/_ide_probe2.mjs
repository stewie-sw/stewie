import { chromium } from "@playwright/test";
const URL = "http://127.0.0.1:8083/ide/";
const b = await chromium.launch({ args: ["--use-gl=angle","--use-angle=gl-egl","--enable-gpu","--ignore-gpu-blocklist"] });
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 6000 }).catch(()=>{});
await p.waitForTimeout(3000);
const info = await p.evaluate(() => {
  const q = window.qwc2 || {};
  const keys = Object.keys(q);
  const fns = keys.filter(k => typeof q[k] === "function");
  // try to find a task setter
  const hasSetTask = typeof q.setCurrentTask === "function" || (q.store && q.store.dispatch);
  return { qwc2Keys: keys, qwc2Fns: fns, hasStore: !!(q.store && q.store.dispatch), hasSetTask };
});
// attempt: open MissionPlan via qwc2 API if available, capture console errors
const errs = [];
p.on("pageerror", e => errs.push(String(e.message||e).slice(0,120)));
let opened = null;
try {
  opened = await p.evaluate(() => {
    const q = window.qwc2;
    if (q && q.store && q.store.dispatch) { q.store.dispatch({type:"SET_CURRENT_TASK", id:"MissionPlan"}); return "store.dispatch"; }
    if (q && typeof q.setCurrentTask === "function") { q.setCurrentTask("MissionPlan"); return "qwc2.setCurrentTask"; }
    return "NO-API";
  });
} catch(e) { opened = "ERR:"+String(e.message).slice(0,80); }
await p.waitForTimeout(2500);
const planOpen = await p.locator('#MissionPlan, [data-stewie-open3d]').count().catch(()=>0);
await b.close().catch(()=>{});
console.log(JSON.stringify({ info, opened, planOpen, pageerrs: errs.slice(0,5) }, null, 2));
