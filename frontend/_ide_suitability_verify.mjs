import { chromium } from "@playwright/test";

// Verify the #52 site-suitability card renders + fetches inside the live QWC2 /ide Mission Plan.
const OUT = process.env.OUT || "/tmp/ide_suitability.png";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 950 } });
const errors = [];
p.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 160)); });
p.on("pageerror", (e) => errors.push("PAGEERROR " + e.message.slice(0, 160)));

const step = {};
await p.goto("https://artemis.stewie.space/ide/", { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 8000 }).then(() => step.theme = 1).catch((e) => step.theme = "FAIL");
await p.waitForTimeout(8000);
await p.getByText("Map & Tools", { exact: false }).first().click({ timeout: 6000 }).then(() => step.menu = 1).catch(() => step.menu = "FAIL");
await p.waitForTimeout(700);
// open Mission Plan (under Plan). Try direct text; else expand Plan first.
try {
  await p.getByText("Mission Plan", { exact: false }).first().click({ timeout: 4000 });
  step.plan = "direct";
} catch (_) {
  try { await p.getByText(/^Plan$/, { exact: false }).first().click({ timeout: 3000 }); await p.waitForTimeout(400);
        await p.getByText("Mission Plan", { exact: false }).first().click({ timeout: 4000 }); step.plan = "via-plan"; }
  catch (e) { step.plan = "FAIL " + (e.message || e).slice(0, 60); }
}
await p.waitForTimeout(1500);

// click the survey/suitability trigger (button text likely "Survey" or "Site suitability")
try {
  await p.getByText("Survey site suitability", { exact: false }).first().click({ timeout: 5000 });
  step.survey = 1;
} catch (e) { step.survey = "FAIL " + (e.message || e).slice(0, 60); }

// wait for the score to populate via the data hooks
let state = null;
for (let i = 0; i < 14; i++) {
  await p.waitForTimeout(1500);
  state = await p.evaluate(() => {
    const el = document.querySelector("[data-stewie-survey], [data-stewie-suit-score]");
    const g = (a) => { const n = document.querySelector(`[${a}]`); return n ? (n.getAttribute(a) || n.textContent || "").trim().slice(0, 40) : null; };
    return { present: !!el, score: g("data-stewie-suit-score"), grade: g("data-stewie-suit-grade"), binding: g("data-stewie-suit-binding") };
  });
  if (state && (state.score || state.grade)) break;
}
await p.screenshot({ path: OUT });
console.log(JSON.stringify({ step, state, errors: errors.slice(0, 8) }, null, 2));
await b.close();
