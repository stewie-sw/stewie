import { chromium } from "@playwright/test";
// Probe: how can a smoke open each Mission* plugin programmatically? Discover window globals + whether the
// QWC2 redux store / setCurrentTask is reachable, and enumerate the registered plugins from the running app.
const URL = process.env.IDE_URL || "http://127.0.0.1:8083/ide/";
const b = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=gl-egl", "--enable-gpu", "--ignore-gpu-blocklist"] });
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 6000 }).catch(() => {});
await p.waitForTimeout(3000);

const probe = await p.evaluate(() => {
  const out = { globals: [], hasStore: false, storePaths: [], taskDispatch: null, redux: false };
  for (const k of Object.keys(window)) {
    if (/qwc|store|redux|stewie|__|task|App/i.test(k)) out.globals.push(k);
  }
  // common QWC2 store exposures
  const cands = ["ReduxStore", "store", "qwc2", "__REDUX_STORE__", "__qwc2_store__"];
  for (const c of cands) { if (window[c]) { out.storePaths.push(c); if (window[c].dispatch) out.hasStore = true; } }
  // QWC2 keeps the store in a module; some builds expose window.qwc2?.store or a redux devtools hook
  if (window.__REDUX_DEVTOOLS_EXTENSION__) out.redux = true;
  return out;
});
// also: does a URL task param work? try ?t=MissionPlan style deep-links QWC2 sometimes supports
const hashProbe = await p.evaluate(() => ({ hash: location.hash, search: location.search }));
await b.close().catch(() => {});
console.log(JSON.stringify({ probe, hashProbe }, null, 2));
