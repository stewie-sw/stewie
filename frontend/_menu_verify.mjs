import { chromium } from "@playwright/test";

const SCR = process.env.SCR;
const URL = process.env.URL || "http://localhost:8083/ide/";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });

await p.goto(URL, { waitUntil: "domcontentloaded", timeout: 40000 });
await p.waitForTimeout(6000);
// load the lunar theme (dismiss the theme-selection landing)
await p.getByText("STEWIE Lunar South Pole").first().click().catch(() => {});
await p.waitForTimeout(9000);
await p.screenshot({ path: `${SCR}/ide_map.png` });
// open the mission TopBar menu (the "Menu" hamburger, top-right)
await p.getByText("Map & Tools", { exact: true }).first().click().catch(() => {});
await p.waitForTimeout(2000);
await p.screenshot({ path: `${SCR}/ide_mission_menu.png` });

const secs = [];
for (const t of ["Plan", "Validate", "Release", "Execute", "Report", "Settings"]) {
  secs.push(`${t}:${await p.getByText(t, { exact: true }).count().catch(() => 0)}`);
}
// confirm the dead LayerCatalog + old SecSupport are gone from the visible menu
const dead = await p.getByText("Support & Settings").count().catch(() => 0);
console.log("section-title matches:", secs.join(" "));
console.log("old 'Support & Settings' still present:", dead);
await b.close();
