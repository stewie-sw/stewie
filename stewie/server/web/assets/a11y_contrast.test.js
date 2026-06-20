// WCAG-AA contrast gate for the cockpit brand tokens (Lane A11Y).
// Reads the real token values straight out of server/index.html so the test
// tracks the source of truth, then asserts the key foreground/background pairs
// clear the WCAG 2.1 AA thresholds: 4.5:1 for normal body text, 3:1 for large
// text / UI component boundaries.
//
// Run: node --test stewie/server/web/assets/a11y_contrast.test.js
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const INDEX = join(HERE, "..", "..", "index.html");

const AA_BODY = 4.5; // normal text
const AA_LARGE = 3.0; // >=18.66px bold / >=24px, and UI component contrast

// --- WCAG 2.1 relative luminance + contrast ratio ---------------------------
function srgbToLinear(channel) {
  const c = channel / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}
function relativeLuminance(hex) {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return (
    0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b)
  );
}
function contrast(a, b) {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const hi = Math.max(la, lb);
  const lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

// --- pull the token map for a given CSS selector block out of index.html -----
function readTokens(selector) {
  const css = readFileSync(INDEX, "utf8");
  // grab the first {...} block following the selector
  const start = css.indexOf(selector);
  assert.ok(start >= 0, `selector ${selector} not found in index.html`);
  const open = css.indexOf("{", start);
  const close = css.indexOf("}", open);
  const block = css.slice(open + 1, close);
  const tokens = {};
  for (const m of block.matchAll(/(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})/g)) {
    tokens[m[1]] = m[2].toLowerCase();
  }
  return tokens;
}

// Self-check the math against the WCAG reference pair (black/white = 21:1).
test("contrast math matches the WCAG reference (black/white = 21)", () => {
  assert.ok(Math.abs(contrast("#000000", "#ffffff") - 21) < 0.01);
});

const DARK = readTokens(":root");
const LIGHT = readTokens("body.light");

// The pairs the audit flagged: small gray/accent text on dark panels, plus the
// white-on-button case. Each entry: [fg, bg, threshold, label].
function pairsFor(t) {
  return [
    [t["--txt"], t["--bg"], AA_BODY, "body text on bg"],
    [t["--txt"], t["--panel"], AA_BODY, "body text on panel"],
    [t["--muted"], t["--bg"], AA_BODY, "muted on bg"],
    [t["--muted"], t["--panel"], AA_BODY, "muted on panel"],
    [t["--muted"], t["--field"], AA_BODY, "muted on field"],
    [t["--dim"], t["--bg"], AA_BODY, "dim on bg"],
    [t["--dim"], t["--panel"], AA_BODY, "dim on panel"],
    [t["--dim"], t["--field"], AA_BODY, "dim on field"],
    // --accent is used as small TEXT in many places (>=8px) -> body threshold
    [t["--accent"], t["--bg"], AA_BODY, "accent text on bg"],
    [t["--accent"], t["--panel"], AA_BODY, "accent text on panel"],
    [t["--accent"], t["--field"], AA_BODY, "accent text on field"],
    // primary action buttons paint white text on the solid --fill colour
    ["#ffffff", t["--fill"], AA_BODY, "white on fill (button)"],
    // accent is also used as a solid badge/avatar bg with white text -> large/UI
    ["#ffffff", t["--accent"], AA_LARGE, "white on accent (badge)"],
  ];
}

for (const [name, tokens] of [["DARK", DARK], ["LIGHT", LIGHT]]) {
  test(`${name} theme token pairs meet WCAG-AA`, () => {
    for (const [fg, bg, thr, label] of pairsFor(tokens)) {
      assert.ok(fg && bg, `${name}: missing token for "${label}"`);
      const c = contrast(fg, bg);
      assert.ok(
        c >= thr,
        `${name}: ${label} (${fg} on ${bg}) = ${c.toFixed(2)} < ${thr}`,
      );
    }
  });
}
