import { chromium } from "@playwright/test";

// Playwright verification of the public full-res 3D viewer at artemis.stewie.space/viz.
// usage: OUT=/path/shot.png node _viz_verify.mjs [site]
const OUT = process.env.OUT || "/tmp/viz_shot.png";
const site = process.argv[2] || "haworth";
const url = `https://artemis.stewie.space/viz?site=${site}`;

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
p.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
p.on("pageerror", (e) => errors.push("PAGEERROR " + e.message));
p.on("requestfailed", (r) => errors.push("REQFAIL " + r.url() + " " + (r.failure()?.errorText || "")));

await p.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
// full-res heightfield binary (a few MB) + mesh build + drape + graticule
await p.waitForTimeout(+(process.env.WAIT || 13000));

// optional: switch the analysis drape (arg 2) + toggle graticule, to verify the layer.png drape renders
const drape = process.argv[3];
if (drape) {
  await p.selectOption("#viz-layer", drape).catch(() => {});
  await p.check("#viz-grat").catch(() => {});
  await p.waitForTimeout(6000);
}

const status = await p.locator("#viz-status").textContent().catch(() => "(no #viz-status)");
const siteVal = await p.locator("#viz-site").inputValue().catch(() => "(no #viz-site)");
const optCount = await p.locator("#viz-site option").count().catch(() => -1);

// WebGL "did the relief render" probe (secondary; the screenshot is authoritative)
const lit = await p.evaluate(() => {
  const c = document.querySelector("#viz-root canvas") || document.querySelector("canvas");
  if (!c) return "no-canvas";
  const gl = c.getContext("webgl2") || c.getContext("webgl");
  if (!gl) return "no-gl";
  const px = new Uint8Array(4); let n = 0;
  const pts = [[0.5, 0.5], [0.5, 0.65], [0.4, 0.6], [0.6, 0.55], [0.5, 0.4]];
  for (const [fx, fy] of pts) {
    gl.readPixels(Math.floor(c.width * fx), Math.floor(c.height * fy), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
    if (px[0] + px[1] + px[2] > 40) n++;
  }
  return `${n}/5 sampled pixels lit`;
});

await p.screenshot({ path: OUT });
console.log(JSON.stringify({ url, site_selected: siteVal, site_options: optCount, status, glProbe: lit, errors: errors.slice(0, 10) }, null, 2));
await b.close();
