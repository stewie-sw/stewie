// ICON-SET (node:test): the toolbar icon inventory is pure -> unit-testable without a browser.
// Run: node --test stewie/server/web/assets/icons.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const I = require("./icons.js");

// Every toolbar button that the prior emoji sweep left showing a TEXT WORD must have a named icon here.
const REQUIRED = [
  "plot", "measure", "fly", "coords", "edit", "delete",
  "box", "keepout", "note", "pause", "play", "clear",
  "alert", "settings", "sun", "save", "snapshot", "compass",
];

test("every required toolbar icon is present in the inventory", () => {
  for (const name of REQUIRED) {
    assert.ok(I.names().includes(name), `missing icon '${name}'`);
  }
});

test("each named icon returns a single valid <svg> with the brand stroke contract", () => {
  for (const name of I.names()) {
    const svg = I.icon(name);
    assert.match(svg, /^<svg /, `${name}: must start with <svg`);
    assert.match(svg, /<\/svg>$/, `${name}: must end with </svg>`);
    assert.match(svg, /viewBox="0 0 24 24"/, `${name}: must use the 24x24 viewBox`);
    assert.match(svg, /stroke="currentColor"/, `${name}: must inherit brand color via currentColor`);
    assert.match(svg, /fill="none"/, `${name}: must be stroke-based (fill none)`);
    assert.match(svg, /class="ic/, `${name}: must carry the .ic sizing class`);
    // exactly one opening and one closing <svg> tag
    assert.strictEqual((svg.match(/<svg/g) || []).length, 1, `${name}: exactly one <svg>`);
    assert.strictEqual((svg.match(/<\/svg>/g) || []).length, 1, `${name}: exactly one </svg>`);
  }
});

test("no icon contains a <script> tag or an inline event handler (CSP-safe)", () => {
  for (const name of I.names()) {
    const svg = I.icon(name);
    assert.doesNotMatch(svg, /<script/i, `${name}: must not contain <script>`);
    assert.doesNotMatch(svg, /\son\w+=/i, `${name}: must not contain inline on* handlers`);
    assert.doesNotMatch(svg, /javascript:/i, `${name}: must not contain a javascript: URL`);
  }
});

test("no icon reintroduces a color emoji (the zero-emoji invariant holds)", () => {
  // Match common pictographic/emoji ranges; the icon set is monochrome line-art only.
  const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2190}-\u{21FF}\u{2300}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/u;
  for (const name of I.names()) {
    assert.doesNotMatch(I.icon(name), EMOJI, `${name}: must not contain emoji/pictographic glyphs`);
  }
});

test("an extra class and a title can be attached without breaking the shell", () => {
  const svg = I.icon("plot", { cls: "big", title: "plot <points>" });
  assert.match(svg, /class="ic big"/);
  assert.match(svg, /<title>plot &lt;points&gt;<\/title>/);  // title is HTML-escaped
});

test("an unknown icon name throws (no silent empty render)", () => {
  assert.throws(() => I.icon("nope"), /unknown icon/);
});
