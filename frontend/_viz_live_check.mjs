import { chromium } from "@playwright/test";

// Reproduce what Aaron sees at artemis.stewie.space/viz: capture console errors, page errors,
// the status line, WebGL context acquisition, and a screenshot.
const OUT = process.env.OUT || "/tmp/viz_live.png";
const URL = process.env.URL || "https://artemis.stewie.space/viz";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
const console_errors = [];
const console_all = [];
const failed_req = [];
p.on("console", (m) => { console_all.push(m.type() + ": " + m.text().slice(0, 200)); if (m.type() === "error") console_errors.push(m.text().slice(0, 240)); });
p.on("pageerror", (e) => console_errors.push("PAGEERROR " + (e.message || e).slice(0, 240)));
p.on("requestfailed", (r) => failed_req.push(r.url().slice(0, 120) + " :: " + (r.failure()?.errorText || "?")));

await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(9000); // allow the 16MB heightfield fetch + mesh build

const state = await p.evaluate(() => {
  const q = (id) => { const n = document.getElementById(id); return n ? (n.textContent || "").trim().slice(0, 160) : `#${id} MISSING`; };
  const canvas = document.querySelector("#viz-root canvas");
  let gl = null;
  if (canvas) { try { gl = !!(canvas.getContext("webgl2") || canvas.getContext("webgl")); } catch (e) { gl = "ctx-err:" + e.message; } }
  return {
    STEWIE_VIZ: typeof window.STEWIE_VIZ,
    THREE_import_ok: !!(window.STEWIE_VIZ && window.STEWIE_VIZ.mount),
    status: q("viz-status"),
    hud: q("viz-hud"),
    root_present: !!document.getElementById("viz-root"),
    canvas_present: !!canvas,
    canvas_size: canvas ? `${canvas.width}x${canvas.height}` : null,
    webgl: gl,
    site_options: (() => { const s = document.getElementById("viz-site"); return s ? s.options.length : "no-select"; })(),
  };
});
await p.screenshot({ path: OUT });
console.log(JSON.stringify({ url: URL, state, console_errors, failed_req, console_tail: console_all.slice(-12) }, null, 2));
await b.close();
