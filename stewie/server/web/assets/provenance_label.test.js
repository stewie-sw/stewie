// FS-03 (node:test): the epistemic provenance-label component is pure -> unit-testable without a
// browser. Run: node --test stewie/server/web/assets/provenance_label.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const P = require("./provenance_label.js");

// a minimal element/document pair standing in for the DOM (the module only reads attributes,
// writes innerHTML, and queries by the data-epistemic selector).
function el(kind, live) {
  const attrs = { "data-epistemic": kind };
  if (live) attrs["data-live"] = live;
  return {
    innerHTML: "",
    getAttribute: (k) => (k in attrs ? attrs[k] : null),
    setAttribute: (k, v) => { attrs[k] = v; },
  };
}
function doc(els) {
  return {
    querySelectorAll: (sel) => sel === '[data-epistemic="live"]'
      ? els.filter((e) => e.getAttribute("data-epistemic") === "live")
      : els,
  };
}

test("the vocabulary is exactly truth/belief/forecast/live", () => {
  assert.deepStrictEqual(P.epistemicKinds().sort(), ["belief", "forecast", "live", "truth"]);
});

test("badgeHTML names the kind in TEXT (never colour alone) and carries the epis class", () => {
  for (const kind of ["truth", "belief", "forecast"]) {
    const h = P.badgeHTML(kind);
    assert.ok(h.includes(kind.toUpperCase()), `${kind} chip must name itself`);
    assert.ok(h.includes(`class="epis epis-${kind}"`), `${kind} chip must carry .epis`);
    assert.ok(h.includes("title="), `${kind} chip must explain its meaning`);
  }
});

test("an unknown kind throws (no silent mislabelling)", () => {
  assert.throws(() => P.badgeHTML("guess"), /unknown epistemic kind/);
});

test("the live chip is IDLE unless explicitly flowing", () => {
  assert.ok(P.badgeHTML("live").includes("LIVE·IDLE"), "default live chip must read idle");
  assert.ok(P.badgeHTML("live", "idle").includes("LIVE·IDLE"));
  const on = P.badgeHTML("live", "on");
  assert.ok(on.includes(">LIVE<"), "flowing live chip reads LIVE");
  assert.ok(!on.includes(">LIVE·IDLE<"));
});

test("applyProvenanceLabels renders every placeholder", () => {
  const els = [el("truth"), el("forecast"), el("live", "idle")];
  assert.strictEqual(P.applyProvenanceLabels(doc(els)), 3);
  assert.ok(els[0].innerHTML.includes("TRUTH"));
  assert.ok(els[1].innerHTML.includes("FORECAST"));
  assert.ok(els[2].innerHTML.includes("LIVE·IDLE"));
});

test("setLiveState flips only the live labels, both directions", () => {
  const els = [el("truth"), el("live", "idle")];
  assert.strictEqual(P.setLiveState(doc(els), true), 1);
  assert.strictEqual(els[1].getAttribute("data-live"), "on");
  assert.ok(els[1].innerHTML.includes(">LIVE<") && !els[1].innerHTML.includes(">LIVE·IDLE<"));
  assert.strictEqual(P.setLiveState(doc(els), false), 1);
  assert.strictEqual(els[1].getAttribute("data-live"), "idle");
  assert.ok(els[1].innerHTML.includes("LIVE·IDLE"));
  assert.strictEqual(els[0].innerHTML, "", "non-live labels untouched");
});
