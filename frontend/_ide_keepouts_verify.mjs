import { chromium } from "@playwright/test";

// Verify the derive-keepouts-from-hazard button renders keep-out polygons on the live /ide map.
const OUT = process.env.OUT || "/tmp/ide_keepouts.png";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 950 } });
const errors = [];
p.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 160)); });
p.on("pageerror", (e) => errors.push("PAGEERROR " + e.message.slice(0, 160)));

const step = {};
await p.goto("https://artemis.stewie.space/ide/", { waitUntil: "domcontentloaded", timeout: 45000 });
await p.waitForTimeout(7000);
await p.getByText("STEWIE Lunar South Pole", { exact: false }).first().click({ timeout: 8000 }).then(() => step.theme = 1).catch(() => step.theme = "FAIL");
await p.waitForTimeout(8000);
await p.getByText("Map & Tools", { exact: false }).first().click({ timeout: 6000 }).then(() => step.menu = 1).catch(() => step.menu = "FAIL");
await p.waitForTimeout(700);
try {
  await p.getByText("Mission Plan", { exact: false }).first().click({ timeout: 4000 }); step.plan = "direct";
} catch (_) {
  try { await p.getByText(/^Plan$/, { exact: false }).first().click({ timeout: 3000 }); await p.waitForTimeout(400);
        await p.getByText("Mission Plan", { exact: false }).first().click({ timeout: 4000 }); step.plan = "via-plan"; }
  catch (e) { step.plan = "FAIL"; }
}
await p.waitForTimeout(1500);

// count map vector features BEFORE, click derive, count AFTER
const beforeMsg = await p.evaluate(() => { const n = document.querySelector("[data-stewie-derive-msg]"); return n ? n.textContent.trim() : null; });
try {
  await p.getByText(/Derive keep-outs from hazard/i).first().click({ timeout: 5000 });
  step.derive = 1;
} catch (e) { step.derive = "FAIL " + (e.message || e).slice(0, 60); }

let state = null;
for (let i = 0; i < 16; i++) {
  await p.waitForTimeout(2000);
  state = await p.evaluate(() => {
    const g = (a) => { const n = document.querySelector(`[${a}]`); return n ? (n.getAttribute(a) || n.textContent || "").trim().slice(0, 80) : null; };
    return { msg: g("data-stewie-derive-msg"), err: g("data-stewie-derive-err"), present: !!document.querySelector("[data-stewie-derive-keepouts]") };
  });
  if (state && (state.msg || state.err)) break;
}
await p.screenshot({ path: OUT });
console.log(JSON.stringify({ step, beforeMsg, state, errors: errors.slice(0, 8) }, null, 2));
await b.close();
