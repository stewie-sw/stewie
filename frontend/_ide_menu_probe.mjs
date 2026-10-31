import { chromium } from "@playwright/test";
const URL = "https://artemis.stewie.space/ide/";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1700, height: 1000 } });
await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 6000 }).catch(() => {});
await p.waitForTimeout(4000);

const before = await p.evaluate(() => [...document.querySelectorAll("[title]")].map((e) => (e.className || e.tagName) + " | " + e.getAttribute("title")).slice(0, 60));
// open AppMenu
const am = await p.$(".AppMenu"); if (am) await am.click().catch(() => {});
await p.waitForTimeout(1200);
const after = await p.evaluate(() => {
  const titled = [...document.querySelectorAll("[title]")].map((e) => (e.className || e.tagName) + " | " + e.getAttribute("title"));
  const menuItems = [...document.querySelectorAll(".AppMenu li, .appmenu li, .AppMenu .menuitem, [role='menuitem'], .AppMenu a, .AppMenu span")].map((e) => (e.className || e.tagName) + " :: " + (e.textContent || "").replace(/\s+/g, " ").slice(0, 30)).filter((t) => t.trim().length > 4);
  const appmenuHTML = (document.querySelector(".AppMenu") || {}).outerHTML;
  return { titled: titled.slice(0, 80), menuItems: menuItems.slice(0, 60), appmenuHTML: appmenuHTML ? appmenuHTML.slice(0, 1500) : null };
});
await p.screenshot({ path: "/tmp/claude-1000/-mnt-projects/0e6e85aa-70b0-4aae-8bf9-42ab645b19e0/scratchpad/ide_menu_open.png" });
await b.close();
console.log(JSON.stringify({ titled_before: before, after }, null, 2));
