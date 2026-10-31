import { chromium } from "@playwright/test";

// GW-11 increment A: verify the scale bar + north + sun HUD on /viz, and the north-arrow SIGN across an orbit.
const URL = process.env.VIZ_URL || "http://127.0.0.1:8083/viz";
const SCR = "/tmp/claude-1000/-mnt-projects/0e6e85aa-70b0-4aae-8bf9-42ab645b19e0/scratchpad";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
const errs = [];
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 160)); });
p.on("pageerror", (e) => errs.push("PAGEERR " + (e.message || e).slice(0, 160)));

await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
for (let i = 0; i < 45; i++) { if (await p.evaluate(() => !!(window.STEWIE_VIZ && window.STEWIE_VIZ.hasMesh))) break; await p.waitForTimeout(1000); }
await p.waitForTimeout(1800); // let the throttled HUD render a few frames

const snap = () => p.evaluate(() => {
  const q = (s) => document.querySelector(s);
  const rot = (el) => { if (!el) return null; const m = /rotate\(([-\d.]+)deg\)/.exec(el.style.transform || ""); return m ? +m[1] : null; };
  return {
    scaleLabel: (q("#viz-scale .stewie-sb-label") || {}).textContent || null,
    scaleWidthPx: (q("#viz-scale .stewie-sb-rule") || {}).style?.width || null,
    northDeg: rot(q("#viz-north .stewie-north-needle")),
    sunDeg: rot(q("#viz-sun .stewie-sun-needle")),
    scalebarLoaded: typeof window.STEWIE_SCALEBAR !== "undefined",
  };
});
const hud1 = await snap();
await p.screenshot({ path: SCR + "/viz_hud_az1.png" });

// orbit ~ +400px drag horizontally -> S.az decreases by 400*0.006 rad
const box = await (await p.$("#viz-root canvas")).boundingBox();
await p.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
await p.mouse.down();
await p.mouse.move(box.x + box.width * 0.5 + 420, box.y + box.height * 0.5, { steps: 12 });
await p.mouse.up();
await p.waitForTimeout(1400);
const hud2 = await snap();
await p.screenshot({ path: SCR + "/viz_hud_az2.png" });

await b.close();
console.log(JSON.stringify({ hud1, hud2, northDelta: (hud1.northDeg != null && hud2.northDeg != null) ? +(hud2.northDeg - hud1.northDeg).toFixed(2) : null, console_errors: errs.filter((e) => !/favicon/i.test(e)).slice(0, 8) }, null, 2));
