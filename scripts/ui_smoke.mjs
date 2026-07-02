#!/usr/bin/env node
// [REQ:FS-09] cockpit browser SMOKE tier -- the ~5.9k-line cockpit shell (tab wiring, pane reveal,
// role gates, the /program board) had zero automated browser coverage: every recent frontend
// regression (unrun JS tier, stale asset stamps, pane wiring) lived in exactly that layer, below
// the pure node:test modules and above the TestClient route tests. This script boots the REAL
// server (dev-open loopback -> the seeded csrf cookie + /auth/me director reveal the cockpit, see
// stewie/server/test_dev_open_index.py), drives the six ConOps spine tabs in a real Chromium, and
// fails on ANY unexpected console error. Playwright NODE API on purpose: no python dependency ->
// no hashed-lock regeneration; CI pins the npm package version exactly.
//
// Usage:  node scripts/ui_smoke.mjs [python] [port]
//   python  the interpreter that boots uvicorn (default "python3"; CI passes its venv "python")
//   port    loopback port (default 8797)
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

// The six spine tabs (Plan - Rehearse - Validate - Release - Execute(metrics) - Report) -> the pane
// each must activate (cockpit.js VIEW_PANE; plan's stage is the globe, so its pane is null) and one
// landmark element that must exist AND carry real content once the tab is active. Rehearse + Release
// are director-gated (data-minrole) -- the dev-open loopback grant reveals them via gateChrome().
export const SPINE = [
  { view: "plan", pane: null, landmark: "#ctx-plan" },
  { view: "rehearse", pane: "#pane_rehearse", landmark: "#rehearsecards" },
  { view: "validate", pane: "#navview", landmark: "#navview" },
  { view: "release", pane: "#pane_release", landmark: "#releasebtn" },
  { view: "metrics", pane: "#execview", landmark: "#execview" },
  { view: "report", pane: "#pane-report", landmark: "#pane-report" },
  // the operator-gated More-cluster work areas (same dev-open director grant reveals them); these are
  // exactly the FS-03/FS-15 panes with recent wiring churn the smoke exists to guard
  { view: "fleet", pane: "#pane_fleet", landmark: "#pane_fleet" },
  { view: "construction", pane: "#pane_construction", landmark: "#pane_construction" },
  { view: "models", pane: "#pane_models", landmark: "#pane_models" },
];

// The vendored Cesium bundle is docker-cp'd into server/cesium/ (gitignored; nginx serves it in
// prod) -> it is legitimately absent on the CI dev server and the cockpit degrades by design
// ("planning all works without the globe", cockpit.js). ONLY the /cesium/ bundle-load failures are
// tolerated, in their two observed shapes: a failed resource fetch (the error's location IS the
// /cesium/ url) or Chromium's strict-MIME refusal of the dev route's JSON 404 (the page url in the
// location, the /cesium/ url in the text). Every other console error fails the smoke.
export function isAllowedConsoleError({ url, text } = {}) {
  if (typeof url === "string" && url.includes("/cesium/")) return true;
  return typeof text === "string"
    && /^Refused to (apply style|execute script) from '[^']*\/cesium\//.test(text);
}

// Fold captured console errors into violations (pure -> node:test'd in ui_smoke.test.mjs).
export function consoleViolations(errors) {
  return errors.filter((e) => !isAllowedConsoleError(e));
}

// Render the readable pass/fail report; ok iff every check passed (pure -> node:test'd).
export function summarize(checks) {
  const lines = checks.map((c) => `${c.ok ? "PASS" : "FAIL"}  ${c.name}${c.detail ? ` -- ${c.detail}` : ""}`);
  return { ok: checks.every((c) => c.ok), lines };
}

async function waitForHealthz(base, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${base}/healthz`);
      if (r.ok) return;
    } catch { /* server still booting */ }
    await new Promise((res) => setTimeout(res, 500));
  }
  throw new Error(`server did not answer /healthz within ${timeoutMs} ms`);
}

async function main() {
  const python = process.argv[2] || "python3";
  const port = Number(process.argv[3] || 8797);
  const base = `http://127.0.0.1:${port}`;
  const dataDir = mkdtempSync(path.join(os.tmpdir(), "stewie-ui-smoke-"));

  const server = spawn(python, ["-m", "uvicorn", "stewie.server.server:app", "--port", String(port)], {
    cwd: ROOT,
    env: { ...process.env, STEWIE_DEV_OPEN: "1", STEWIE_DATA_DIR: dataDir, PYTHONNOUSERSITE: "1", PYTHONPATH: ROOT },
    stdio: ["ignore", "inherit", "inherit"],
  });
  const killServer = () => { if (server.exitCode === null) server.kill("SIGTERM"); };
  process.on("exit", killServer);

  const checks = [];
  const consoleErrors = [];
  let browser;
  try {
    await waitForHealthz(base, 90_000);
    checks.push({ ok: true, name: "server boots and answers /healthz" });

    const { chromium } = await import("playwright");
    browser = await chromium.launch(); // headless; software GL is fine -- the globe bundle is absent anyway
    const page = await browser.newPage({ viewport: { width: 1450, height: 900 } });
    page.on("console", (m) => { if (m.type() === "error") consoleErrors.push({ text: m.text(), url: m.location().url }); });
    page.on("pageerror", (e) => consoleErrors.push({ text: `pageerror: ${e.message}`, url: page.url() }));

    await page.goto(`${base}/`, { waitUntil: "domcontentloaded", timeout: 45_000 });
    // dev-open reveal: /auth/me returns the loopback director -> gateChrome un-hides Rehearse/Release
    await page.waitForFunction(() => {
      const b = document.getElementById("vtab-rehearse");
      return !!b && b.style.display !== "none";
    }, { timeout: 30_000 });
    checks.push({ ok: true, name: "dev-open director reveal (Rehearse/Release tabs visible)" });

    for (const tab of SPINE) {
      // force-reveal via a JS click on the tab (the .vtab onclick -> setView), not a pointer click:
      // the director-gated tabs live in a flex bar whose overflow layout must not flake the smoke
      const clicked = await page.evaluate((view) => {
        const b = document.querySelector(`.vtab[data-view="${view}"]`);
        if (!b) return false;
        b.click();
        return true;
      }, tab.view);
      let ok = clicked;
      let detail = clicked ? "" : "spine tab missing from the DOM";
      if (clicked) {
        try {
          await page.waitForFunction(({ pane, landmark }) => {
            if (pane) {
              const p = document.querySelector(pane);
              if (!p || !p.classList.contains("active")) return false;
            }
            const l = document.querySelector(landmark);
            return !!l && (l.children.length > 0 || l.textContent.trim().length > 0);
          }, { pane: tab.pane, landmark: tab.landmark }, { timeout: 15_000 });
        } catch {
          ok = false;
          detail = `pane ${tab.pane || "(plan stage)"} not active or landmark ${tab.landmark} empty`;
        }
      }
      checks.push({ ok, name: `spine tab "${tab.view}" activates its pane + non-empty ${tab.landmark}`, detail });
    }

    // /program board: every committed PRD-matrix row must render as a chip (188 today -- compared
    // against the committed snapshot itself so the smoke stays truthful as the matrix evolves)
    const snapshot = await (await fetch(`${base}/program/snapshot`)).json();
    const rows = Array.isArray(snapshot.rows) ? snapshot.rows.length : 0;
    await page.goto(`${base}/program`, { waitUntil: "domcontentloaded", timeout: 45_000 });
    let chipOk = rows > 0;
    let chipDetail = rows > 0 ? "" : "committed snapshot has no rows";
    if (chipOk) {
      try {
        await page.waitForFunction((n) => document.querySelectorAll(".rowchip").length === n, rows, { timeout: 15_000 });
        chipDetail = `${rows} chips`;
      } catch {
        chipOk = false;
        const got = await page.evaluate(() => document.querySelectorAll(".rowchip").length);
        chipDetail = `expected ${rows} chips from the committed snapshot, rendered ${got}`;
      }
    }
    checks.push({ ok: chipOk, name: "/program renders one chip per committed PRD-matrix row", detail: chipDetail });

    const violations = consoleViolations(consoleErrors);
    checks.push({
      ok: violations.length === 0,
      name: "zero unexpected console errors across the cockpit + /program",
      detail: violations.map((v) => `${v.url || "?"}: ${v.text}`).join(" | "),
    });
  } catch (err) {
    checks.push({ ok: false, name: "smoke run", detail: String(err && err.message ? err.message : err) });
  } finally {
    if (browser) await browser.close().catch(() => {});
    killServer();
  }

  const { ok, lines } = summarize(checks);
  console.log("\n=== cockpit UI smoke [REQ:FS-09] ===");
  for (const line of lines) console.log(line);
  console.log(ok ? "UI SMOKE PASSED" : "UI SMOKE FAILED");
  process.exit(ok ? 0 : 1);
}

// import-safe: ui_smoke.test.mjs imports the pure helpers without booting anything
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
