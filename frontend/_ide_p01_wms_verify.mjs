import { chromium } from "@playwright/test";

// P0-1: does /ide render the lunar WMS map (nonblank) with no localhost + no blocking errors?
const URL = "https://artemis.stewie.space/ide/";

async function run(label, viewport) {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport });
  const localhostReqs = [], owsReq = [], failed = [], errs = [];
  const owsStatus = {};
  p.on("request", (r) => {
    const u = r.url();
    if (/8082/.test(u)) localhostReqs.push(u.slice(0, 100));
    if (/\/ows\//.test(u)) owsReq.push(u);
  });
  const bad = [];
  p.on("response", (res) => { if (/\/ows\//.test(res.url())) owsStatus[res.status()] = (owsStatus[res.status()] || 0) + 1;
    if (res.status() >= 400) bad.push(res.status() + " " + res.url().slice(0, 90)); });
  p.on("requestfailed", (r) => failed.push((r.failure()?.errorText || "?") + " " + r.url().slice(0, 90)));
  p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 120)); });
  p.on("pageerror", (e) => errs.push("PAGEERROR " + (e.message || e).slice(0, 120)));

  await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
  await p.waitForTimeout(8000);
  // select the lunar theme/site (the WMS theme) — mirrors the working route-verify
  await p.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 8000 }).catch(() => {});
  await p.waitForTimeout(9000);
  // nonblank check: sample the largest canvas' pixels for variance (a real raster is not uniform)
  const nonblank = await p.evaluate(() => {
    const cs = [...document.querySelectorAll("canvas")].sort((a, b) => b.width * b.height - a.width * a.height);
    for (const c of cs.slice(0, 3)) {
      try {
        const g = c.getContext("2d") || c.getContext("webgl") || c.getContext("webgl2");
        if (!g || !c.width || !c.height) continue;
        // webgl canvases won't readback via 2d; try 2d only
        if (c.getContext("2d")) {
          const d = c.getContext("2d").getImageData(0, 0, Math.min(c.width, 200), Math.min(c.height, 200)).data;
          const seen = new Set(); let opaque = 0;
          for (let i = 0; i < d.length; i += 4) { if (d[i + 3] > 10) { opaque++; seen.add(d[i] + "," + d[i + 1] + "," + d[i + 2]); } }
          if (opaque > 500 && seen.size > 8) return { ok: true, w: c.width, h: c.height, colors: seen.size, opaque };
        }
      } catch (e) { /* tainted or webgl */ }
    }
    return { ok: false, canvases: cs.length, sizes: cs.slice(0, 3).map((c) => c.width + "x" + c.height) };
  });
  const state = await p.evaluate(() => ({
    splashVisible: !!document.querySelector("#splash") && getComputedStyle(document.querySelector("#splash")).display !== "none",
    hasMapEl: !!document.querySelector(".map, .ol-viewport, #map"),
    bodyText: (document.body.innerText || "").replace(/\s+/g, " ").slice(0, 160),
  }));
  await p.screenshot({ path: `/tmp/ide_p01_${label}.png` });
  await b.close();
  return { label, localhost_requests: localhostReqs.length, ows_requests: owsReq.length, ows_status: owsStatus,
    nonblank, bad_responses: bad.slice(0, 8), failed: failed.slice(0, 6), console_errors: errs.filter((e) => !/favicon/i.test(e)).slice(0, 6) };
}

console.log(JSON.stringify({ desktop: await run("desktop", { width: 1700, height: 1000 }), mobile: await run("mobile", { width: 390, height: 780 }) }, null, 2));
