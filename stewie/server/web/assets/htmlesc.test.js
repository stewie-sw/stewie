// FS-24 (node:test): the HTML-entity escape helper is pure -> unit-testable without a browser.
// Run: node --test stewie/server/web/assets/htmlesc.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const H = require("./htmlesc.js");

test("esc: the five HTML-significant characters become entities", () => {
  assert.strictEqual(H.esc(`&<>"'`), "&amp;&lt;&gt;&quot;&#39;");
});

test("esc: an <img onerror> payload renders inert", () => {
  assert.strictEqual(H.esc('<img src=x onerror="alert(1)">'),
    "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
});

test("esc: null and undefined coerce to empty string", () => {
  assert.strictEqual(H.esc(null), "");
  assert.strictEqual(H.esc(undefined), "");
});

test("esc: numbers and plain text pass through unchanged", () => {
  assert.strictEqual(H.esc(42), "42");
  assert.strictEqual(H.esc("operator@example.com"), "operator@example.com");
});
