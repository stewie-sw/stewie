import { chromium } from "@playwright/test";

// [REQ:GI-03] END-TO-END: author a plan in the /ide, then the "Download Plan GeoJSON" control fetches the
// backend /export/geojson (RFC-7946) and yields a real FeatureCollection. Deployed artemis /ide, real GPU.
const URL = process.env.IDE_URL || "http://127.0.0.1:8083/ide/";
const SCR = "/tmp/claude-1000/-mnt-projects/0e6e85aa-70b0-4aae-8bf9-42ab645b19e0/scratchpad";
const b = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=gl-egl", "--enable-gpu", "--ignore-gpu-blocklist"] });
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
const errs = [];
p.on("pageerror", (e) => errs.push(String(e.message || e).slice(0, 140)));

// capture the /api/export/geojson request + response the button triggers.
let exportResp = null, reqMissionMarkers = "unseen";
p.on("request", (r) => {
  if (r.url().includes("/api/export/geojson")) {
    try { const m = JSON.parse(new URLSearchParams(r.url().split("?")[1]).get("mission")); reqMissionMarkers = JSON.stringify(m.markers || "absent"); } catch (e) { reqMissionMarkers = "parse-err"; }
  }
});
p.on("response", async (r) => {
  if (r.url().includes("/api/export/geojson")) {
    try { exportResp = { status: r.status(), body: await r.text() }; } catch (e) { exportResp = { status: r.status(), body: null }; }
  }
});

await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 6000 }).catch(() => {});
await p.waitForTimeout(3000);

const steps = [];
// open Mission Plan
await p.evaluate(() => window.qwc2.setCurrentTask("MissionPlan"));
await p.waitForTimeout(2500);
steps.push("missionplan");

// activate the Cut tool + click the map centre to author a build order.
await p.locator('[data-stewie-tool="cut"]').first().click({ timeout: 5000 }).then(() => steps.push("cut-tool")).catch(() => steps.push("cut-tool-FAIL"));
await p.waitForTimeout(800);
const canvas = p.locator(".ol-viewport canvas, canvas.ol-unselectable").first();
const box = await canvas.boundingBox().catch(() => null);
if (box) {
  // two clicks -> two orders (so the export carries a route between them).
  await p.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await p.waitForTimeout(500);
  await p.mouse.click(box.x + box.width * 0.55, box.y + box.height * 0.52);
  await p.waitForTimeout(600);
}
const orderCount = await p.evaluate(() => (window.__stewieRun ? window.__stewieRun.orderCount() : -1));
steps.push("orders=" + orderCount);

// [REQ:GI-03] also drop a place-object marker (annotation) -> it must appear in the exported GeoJSON.
await p.locator('[data-stewie-object="beacon"]').first().click({ timeout: 5000 }).then(() => steps.push("beacon-tool")).catch(() => steps.push("beacon-tool-FAIL"));
await p.waitForTimeout(800);
if (box) {
  await p.mouse.click(box.x + box.width * 0.45, box.y + box.height * 0.48);
  await p.waitForTimeout(1500);   // the marker POSTs through the edit session
}
const markerCount = await p.evaluate(() => (window.__stewieRun && window.__stewieRun.markers ? window.__stewieRun.markers().length : -1));
steps.push("markers=" + markerCount);

// Plan mission -> the planner runs on the real Haworth DEM; the export control appears once a plan exists.
await p.locator('[data-stewie-plan="1"]').first().click({ timeout: 5000 }).then(() => steps.push("plan")).catch(() => steps.push("plan-FAIL"));
let planned = false;
for (let i = 0; i < 30; i++) {
  planned = await p.locator('[data-stewie-export-geojson="1"]').count().then((c) => c > 0).catch(() => false);
  if (planned) break;
  await p.waitForTimeout(1000);
}
steps.push("exportBtn=" + planned);

// click the Download control -> triggers the /api/export/geojson fetch (captured above).
let clicked = false;
if (planned) {
  await p.locator('[data-stewie-export-geojson="1"]').first().click({ timeout: 5000 }).then(() => { clicked = true; }).catch(() => {});
  for (let i = 0; i < 15; i++) { if (exportResp) break; await p.waitForTimeout(500); }
}
await p.screenshot({ path: SCR + "/ide_export_geojson.png" }).catch(() => {});
await b.close().catch(() => {});

// verify: the export returned a real GeoJSON FeatureCollection.
let fcOk = false, features = 0, markerFeatures = 0, markerLabel = null;
if (exportResp && exportResp.status === 200 && exportResp.body) {
  try {
    const fc = JSON.parse(exportResp.body);
    fcOk = fc.type === "FeatureCollection";
    features = (fc.features || []).length;
    const ms = (fc.features || []).filter((f) => (f.properties || {}).feature === "marker");
    markerFeatures = ms.length;
    markerLabel = ms.length ? ms[0].properties.label : null;   // [REQ:GI-03] the annotation rode the export
  } catch (e) { /* */ }
}
console.log(JSON.stringify({
  pass: !!(planned && clicked && fcOk && features > 0 && markerFeatures > 0),
  steps, orderCount, exportButtonRendered: planned, clicked,
  exportStatus: exportResp ? exportResp.status : null, isFeatureCollection: fcOk, features,
  markerFeatures, markerLabel, reqMissionMarkers,
  pageerrs: errs.slice(0, 5),
}, null, 2));
