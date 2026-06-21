// FS-24 (node:test): the role-authority ladder rank is pure -> unit-testable without a browser.
// Run: node --test stewie/server/web/assets/role_rank.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const R = require("./role_rank.js");

test("rrank: the guest<trainee<operator<director ladder is monotonic", () => {
  assert.strictEqual(R.rrank("guest"), 0);
  assert.strictEqual(R.rrank("trainee"), 1);
  assert.strictEqual(R.rrank("operator"), 2);
  assert.strictEqual(R.rrank("director"), 3);
});

test("rrank: operator clears the operator gate, trainee does not", () => {
  assert.ok(R.rrank("operator") >= R.rrank("operator"));
  assert.ok(!(R.rrank("trainee") >= R.rrank("operator")));
});

test("rrank: an unknown role is -1 (below guest, never clears a gate)", () => {
  assert.strictEqual(R.rrank("admin"), -1);
  assert.ok(!(R.rrank("admin") >= R.rrank("operator")));
});
