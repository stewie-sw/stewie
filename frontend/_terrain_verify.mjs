import { chromium } from "@playwright/test";

// usage: node _terrain_verify.mjs "Site04&lat=-85&lon=0&zoom=3.5"  (first token = site, rest = extra params)
const SCR = process.env.SCR;
const arg = process.argv[2] || "Site04";
const site = arg.split("&")[0];
const label = arg.replace(/[^A-Za-z0-9]/g, "_");
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
p.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

await p.goto(`https://artemis.stewie.space/?terrain=${arg}`, { waitUntil: "domcontentloaded", timeout: 40000 });
await p.waitForTimeout(9000);
const hud = await p.locator("text=/pts ·|error:/").first().textContent().catch(() => "(no hud)");
// crude "did anything render" probe: sample the center pixel region is non-black
const nonBlack = await p.evaluate(() => {
  const c = document.querySelector("canvas");
  if (!c) return "no-canvas";
  const gl = c.getContext("webgl2") || c.getContext("webgl");
  if (!gl) return "no-gl";
  const px = new Uint8Array(4);
  const pts = [[0.5, 0.5], [0.5, 0.7], [0.35, 0.6], [0.65, 0.6]];
  let lit = 0;
  for (const [fx, fy] of pts) {
    gl.readPixels(Math.floor(c.width * fx), Math.floor(c.height * fy), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
    if (px[0] + px[1] + px[2] > 40) lit++;
  }
  return `${lit}/4 sampled pixels lit`;
});
console.log(`${arg}: hud="${(hud || "").trim().slice(0, 70)}" | ${nonBlack}`);
if (errors.filter((e) => !e.includes("cloudflareinsights")).length)
  console.log("  errs:", errors.filter((e) => !e.includes("cloudflareinsights")).slice(0, 3).join(" || ").slice(0, 260));
await p.screenshot({ path: `${SCR}/artemis-terrain-${label}.png` });
await b.close();
