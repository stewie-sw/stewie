import { chromium } from "@playwright/test";
const URL = process.env.IDE_URL || "https://artemis.stewie.space/ide/";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1700, height: 1000 } });
const cesiumReqs = [], errs = [];
p.on("response", (r) => { if (/\/cesium\//.test(r.url())) cesiumReqs.push(r.status() + " " + (r.url().split("/cesium/")[1] || "").slice(0, 36)); });
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 140)); });
p.on("pageerror", (e) => errs.push("PAGEERR " + (e.message || e).slice(0, 140)));

await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 6000 }).catch(() => {});
await p.waitForTimeout(4000);

const steps = [];
await p.locator(".appmenu-button").first().click({ timeout: 5000 }).then(() => steps.push("appmenu")).catch(() => steps.push("appmenu-FAIL"));
await p.waitForTimeout(700);
await p.locator(".appmenu-submenu", { hasText: "Plan" }).first().click({ timeout: 4000 }).then(() => steps.push("click-plan")).catch(() => steps.push("click-plan-FAIL"));
await p.waitForTimeout(900);
const menuNow = await p.evaluate(() => [...document.querySelectorAll(".appmenu-menu-item, .appmenu-submenu-entry, .appmenu-menu a, .appmenu-menu div[tabindex]")]
  .map((e) => ((e.className || "").slice(0, 34)) + " :: " + (e.textContent || "").replace(/\s+/g, " ").trim().slice(0, 26))
  .filter((t) => t.split("::")[1] && t.split("::")[1].trim().length > 1).slice(0, 40));

let clickedGlobe = await p.getByText("Whole Moon", { exact: false }).first().click({ timeout: 4000 }).then(() => true).catch(() => false);
steps.push("wholemoon:" + clickedGlobe);
await p.waitForTimeout(10000);

const state = await p.evaluate(() => {
  const txt = (document.body.innerText || "").replace(/\s+/g, " ");
  const big = [...document.querySelectorAll("canvas")].map((c) => ({ w: c.width, h: c.height, cls: (c.className || "").slice(0, 44) })).filter((c) => c.w > 300 && c.h > 300);
  return { windowCesium: typeof window.Cesium, cesiumBaseUrl: window.CESIUM_BASE_URL || null, hasCesiumViewer: !!document.querySelector(".cesium-viewer, .cesium-widget"), bigCanvases: big.slice(0, 5), unavailableMsg: /window\.Cesium is undefined|globe unavailable|Cesium\.js loaded but/i.test(txt), sawSpinGlobe: /Spin the globe/i.test(txt) };
});
await p.screenshot({ path: "/tmp/claude-1000/-mnt-projects/0e6e85aa-70b0-4aae-8bf9-42ab645b19e0/scratchpad/ide_globe.png" });
await b.close();
console.log(JSON.stringify({ steps, menuNow, clickedGlobe, cesium_requests: cesiumReqs.slice(0, 12), console_errors: errs.filter((e) => !/favicon/i.test(e)).slice(0, 8), state }, null, 2));
