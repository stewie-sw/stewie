import { chromium } from "@playwright/test";

const SCR = process.env.SCR;
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
await p.goto("https://artemis.stewie.space/", { waitUntil: "domcontentloaded", timeout: 40000 });
await p.waitForTimeout(6000);
await p.getByText("Skip — show everything").click().catch(() => {});
await p.waitForTimeout(3500);

const pins = await p.locator(".artemis-site-pin").count();
const labels = await p.locator(".artemis-site-pin").allTextContents();
console.log(`pins on Artemis map: ${pins} (labels: ${labels.join(",")})`);
await p.screenshot({ path: `${SCR}/artemis-map-pins.png` });

if (pins > 0) {
  // click the first pin and confirm it navigates to the terrain view
  await p.locator(".artemis-site-pin").first().click();
  await p.waitForTimeout(6000);
  const url = p.url();
  const hud = await p.locator("text=/LOLA 5 m terrain/").first().textContent().catch(() => "(no terrain hud)");
  console.log(`after pin click -> url has terrain=? ${url.includes("terrain=")} | ${url.split("?")[1] || ""}`);
  console.log(`  terrain view loaded: "${(hud || "").trim().slice(0, 50)}"`);
  await p.screenshot({ path: `${SCR}/artemis-pin-launched.png` });
}
await b.close();
