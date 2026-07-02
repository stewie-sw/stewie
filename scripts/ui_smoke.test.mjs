// [REQ:FS-09] pure-logic coverage for the cockpit UI smoke (scripts/ui_smoke.mjs): the spine-tab
// table, the narrowly-scoped console-error allowance, and the pass/fail report fold. Importing the
// script must NOT boot a server or a browser (the main() is argv-guarded).
import { test } from "node:test";
import assert from "node:assert/strict";

import { SPINE, isAllowedConsoleError, consoleViolations, summarize } from "./ui_smoke.mjs";

test("SPINE drives exactly the six ConOps spine tabs, each with a landmark", () => {
  assert.deepEqual(SPINE.map((t) => t.view), ["plan", "rehearse", "validate", "release", "metrics", "report"]);
  for (const t of SPINE) assert.ok(t.landmark && t.landmark.startsWith("#"), `${t.view} needs a landmark selector`);
  // plan's stage is the globe under the panes (no VIEW_PANE entry); every other tab names its pane
  assert.equal(SPINE[0].pane, null);
  for (const t of SPINE.slice(1)) assert.ok(t.pane && t.pane.startsWith("#"), `${t.view} needs a pane selector`);
});

test("only /cesium/ bundle-load failures are tolerated (the gitignored globe bundle)", () => {
  // shape 1: the failed resource fetch (error located at the /cesium/ url itself)
  assert.ok(isAllowedConsoleError({ url: "http://127.0.0.1:8797/cesium/Cesium.js", text: "Failed to load resource: 404" }));
  // shape 2: Chromium's strict-MIME refusal of the dev route's JSON 404 (located at the PAGE url)
  assert.ok(isAllowedConsoleError({
    url: "http://127.0.0.1:8797/",
    text: "Refused to apply style from 'http://127.0.0.1:8797/cesium/Widgets/widgets.css' because its MIME type ('application/json') is not a supported stylesheet MIME type, and strict MIME checking is enabled.",
  }));
  assert.ok(isAllowedConsoleError({
    url: "http://127.0.0.1:8797/",
    text: "Refused to execute script from 'http://127.0.0.1:8797/cesium/Cesium.js' because its MIME type ('application/json') is not executable, and strict MIME type checking is enabled.",
  }));
  // everything else fails the smoke -- even errors that merely MENTION cesium mid-text
  assert.ok(!isAllowedConsoleError({ url: "http://127.0.0.1:8797/assets/cockpit.js", text: "Failed to load resource: 404" }));
  assert.ok(!isAllowedConsoleError({ url: "http://127.0.0.1:8797/", text: "pageerror: Cesium is not defined at /cesium/ shim" }));
  assert.ok(!isAllowedConsoleError({}));
  assert.ok(!isAllowedConsoleError());
});

test("consoleViolations keeps every non-cesium error, in order", () => {
  const errs = [
    { text: "Failed to load resource: 404", url: "http://x/cesium/Cesium.js" },
    { text: "pageerror: boom", url: "http://x/" },
    { text: "Failed to load resource: 500", url: "http://x/plan" },
  ];
  assert.deepEqual(consoleViolations(errs).map((e) => e.text), ["pageerror: boom", "Failed to load resource: 500"]);
  assert.deepEqual(consoleViolations([]), []);
});

test("summarize is green only when every check passed, and renders readable lines", () => {
  const good = summarize([{ ok: true, name: "a" }, { ok: true, name: "b", detail: "188 chips" }]);
  assert.equal(good.ok, true);
  assert.deepEqual(good.lines, ["PASS  a", "PASS  b -- 188 chips"]);
  const bad = summarize([{ ok: true, name: "a" }, { ok: false, name: "c", detail: "pane not active" }]);
  assert.equal(bad.ok, false);
  assert.equal(bad.lines[1], "FAIL  c -- pane not active");
});
