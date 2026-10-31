import { chromium } from "@playwright/test";

// Show lat/lon-aligned gridlines (graticule ON, km grid OFF) + a drape, in 3D. Also probe the /dem/graticule
// payload to confirm the yellow lines are REAL selenographic lon/lat (curved meridians/parallels), not metric.
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
const errs = [];
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 160)); });
p.on("pageerror", (e) => errs.push("PAGEERROR " + (e.message || e).slice(0, 160)));

await p.goto("https://artemis.stewie.space/viz", { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(9000);

// lat/lon ONLY: graticule on, km grid off
await p.locator("#viz-grat").check().catch(() => {});
await p.locator("#viz-grid").uncheck().catch(() => {});
// drape hillshade so the terrain reads clearly under the lat/lon lines
await p.locator("#viz-layer").selectOption("dem").catch(() => {});
await p.waitForTimeout(4500);
const st = await p.evaluate(() => ({ layer: window.STEWIE_VIZ?.layerKind }));
await p.screenshot({ path: "/tmp/viz_latlon_only.png" });

// confirm the graticule payload is real lon/lat
const grat = await p.evaluate(async () => {
  const r = await fetch("/dem/graticule?site=haworth");
  if (!r.ok) return { ok: false, status: r.status };
  const j = await r.json();
  const keys = Object.keys(j);
  // sample the first meridian/parallel to show lon/lat values
  const sample = JSON.stringify(j).slice(0, 240);
  return { ok: true, keys, sample };
});
console.log(JSON.stringify({ layer: st.layer, graticule: grat, errs }, null, 2));
await b.close();
