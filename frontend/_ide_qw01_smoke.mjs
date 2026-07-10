import { chromium } from "@playwright/test";

// [REQ:QW-01] the served /ide/ front door is a QWC2 SPA whose appConfig registers the STEWIE Mission* plugins
// over an OpenLayers map; this signed-in browser smoke opens EACH Mission* plugin at desktop + phone widths
// and asserts ZERO BLOCKING console errors. "Blocking" = an uncaught JS exception (pageerror) or a console
// error that is NOT a network-resource failure (external LROC/Trek WMS tiles legitimately 404 at some zooms —
// a missing tile is a non-blocking network warning, not a broken app). Runs against the deployed artemis /ide.
const URL = process.env.IDE_URL || "http://127.0.0.1:8083/ide/";
const SCR = "/tmp/claude-1000/-mnt-projects/0e6e85aa-70b0-4aae-8bf9-42ab645b19e0/scratchpad";

// the Mission* plugins appConfig registers as SideBar tasks (openable via window.qwc2.setCurrentTask).
const PLUGINS = [
  "MissionPlan", "MissionProgram", "MissionLayers", "MissionUserLayer", "MissionAssets",
  "MissionTerrain3D", "MissionCrossSection", "MissionTerramech", "MissionRuntime",
  "MissionEvidence", "MissionEngPanel", "MissionHUD", "SelectionInspector",
];
const WIDTHS = [{ name: "desktop", w: 1600, h: 1000 }, { name: "phone", w: 390, h: 844 }];

// a console 'error' is BLOCKING unless it is a network-resource failure or a favicon miss.
const isBlocking = (t) => !/Failed to load resource|net::ERR|favicon|status of 40[34]|status of 5\d\d/i.test(t);

const b = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=gl-egl", "--enable-gpu", "--ignore-gpu-blocklist"] });
const results = [];
const allBlocking = [];

for (const vp of WIDTHS) {
  const page = await b.newPage({ viewport: { width: vp.w, height: vp.h } });
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error" && isBlocking(m.text())) errs.push({ src: "console", t: m.text().slice(0, 160) }); });
  page.on("pageerror", (e) => errs.push({ src: "pageerror", t: String(e.message || e).slice(0, 160) }));

  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForTimeout(7000);
  await page.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 6000 }).catch(() => {});
  await page.waitForTimeout(3000);

  // the OpenLayers map is present (the substrate the plugins overlay).
  const hasMap = await page.locator(".ol-viewport, canvas.ol-unselectable, .map-container canvas").count().catch(() => 0);
  // appConfig actually registered the plugins (the running app knows them).
  const apiOk = await page.evaluate(() => !!(window.qwc2 && typeof window.qwc2.setCurrentTask === "function"));

  const opened = {};
  for (const id of PLUGINS) {
    const before = errs.length;
    // dispatch the task, then let React re-render + the SideBar mount + any lazy chunk load...
    await page.evaluate((pid) => { window.qwc2.setCurrentTask(null); window.qwc2.setCurrentTask(pid); }, id).catch(() => {});
    await page.waitForTimeout(1100);
    // ...THEN read the settled state: the task is active AND the plugin's DOM root mounted.
    const activated = await page.evaluate((pid) => {
      const st = window.qwc2.getState ? window.qwc2.getState() : null;
      const taskOk = !!(st && st.task && st.task.id === pid);
      const domOk = document.querySelectorAll("#" + pid).length > 0;
      return { taskOk, domOk, ok: taskOk && domOk };
    }, id);
    const newErrs = errs.slice(before);
    opened[id] = { activated: activated.ok, taskOk: activated.taskOk, domOk: activated.domOk, newBlocking: newErrs.length };
    newErrs.forEach((e) => allBlocking.push({ width: vp.name, plugin: id, ...e }));
  }
  await page.screenshot({ path: `${SCR}/ide_qw01_${vp.name}.png` }).catch(() => {});
  results.push({ width: vp.name, hasMap: hasMap > 0, apiOk, opened, totalBlocking: errs.length });
  await page.close().catch(() => {});
}
await b.close().catch(() => {});

// PASS: every plugin activated at both widths, the map is present, and ZERO blocking console errors anywhere.
const allActivated = results.every((r) => r.hasMap && r.apiOk && PLUGINS.every((id) => r.opened[id].activated === true));
const zeroBlocking = allBlocking.length === 0;
console.log(JSON.stringify({
  pass: allActivated && zeroBlocking,
  allActivated, zeroBlocking, blockingCount: allBlocking.length,
  perWidth: results.map((r) => ({ width: r.width, hasMap: r.hasMap, apiOk: r.apiOk,
    notActivated: PLUGINS.filter((id) => r.opened[id].activated !== true) })),
  blocking: allBlocking.slice(0, 12),
}, null, 2));
