// GW-11 terrain3d helpers: the drape list + the WS site-sync decision + the hover coordinate-readout
// formatting. Pure, node-testable (the React panel + viz3d embedding are Playwright-verified by the main
// thread). Run: node --test  (matches crossSection.test.js / workspace.test.js).
const assert = require("node:assert");
const { test } = require("node:test");
const T = require("./terrain3d.js");

test("DRAPE_KINDS: the 10 analysis drapes with unique ids, elevation first", () => {
  const ids = T.DRAPE_KINDS.map((d) => d.id);
  assert.deepStrictEqual(ids, ["elevation", "dem", "slope", "aspect", "curvature", "roughness",
    "hazard", "illumination", "psr", "cost"]);
  assert.strictEqual(new Set(ids).size, ids.length, "drape ids must be unique");
  T.DRAPE_KINDS.forEach((d) => assert.ok(d.label && typeof d.label === "string", "every drape has a label"));
});

test("isKnownDrape: true for a listed kind, false otherwise", () => {
  assert.strictEqual(T.isKnownDrape("slope"), true);
  assert.strictEqual(T.isKnownDrape("elevation"), true);
  assert.strictEqual(T.isKnownDrape("cost"), true);
  assert.strictEqual(T.isKnownDrape("nonsense"), false);
  assert.strictEqual(T.isKnownDrape(null), false);
  assert.strictEqual(T.isKnownDrape(undefined), false);
});

test("shouldReload: reload only on a real, different, non-empty site", () => {
  assert.strictEqual(T.shouldReload("haworth", "shackleton_rim"), true);   // site switch -> reload
  assert.strictEqual(T.shouldReload("haworth", "haworth"), false);         // same site -> no thrash
  assert.strictEqual(T.shouldReload(null, "haworth"), true);               // first load
  assert.strictEqual(T.shouldReload("haworth", ""), false);                // empty -> keep current
  assert.strictEqual(T.shouldReload("haworth", null), false);              // missing -> keep current
  assert.strictEqual(T.shouldReload("haworth", undefined), false);
  assert.strictEqual(T.shouldReload("haworth", 42), false);                // non-string -> keep current
});

test("fmt: em dash for null/NaN, fixed precision otherwise", () => {
  assert.strictEqual(T.fmt(null), "—");
  assert.strictEqual(T.fmt(NaN), "—");
  assert.strictEqual(T.fmt(undefined), "—");
  assert.strictEqual(T.fmt(3.14159), "3.1");        // default 1 dp
  assert.strictEqual(T.fmt(3.14159, 5), "3.14159");
  assert.strictEqual(T.fmt(-96, 0), "-96");
});

test("formatHover: null payload -> null (readout dims)", () => {
  assert.strictEqual(T.formatHover(null), null);
  assert.strictEqual(T.formatHover(undefined), null);
});

test("formatHover: full payload -> E/N, elevation, and lon/lat strings", () => {
  const out = T.formatHover({ e_m: 1234.56, n_m: 789.01, elev_m: -42.3, lat: -88.12345, lon: 45.6789 });
  assert.match(out.en, /^E 1234\.6 m/);
  assert.match(out.en, /N 789\.0 m$/);
  assert.strictEqual(out.elev, "elev -42.3 m");
  assert.match(out.lonlat, /lat -88\.12345°/);
  assert.match(out.lonlat, /lon 45\.67890°/);
});

test("formatHover: E/N present but lon/lat not yet resolved -> 'lat — lon —'", () => {
  const out = T.formatHover({ e_m: 10, n_m: 20, elev_m: 5, lat: null, lon: null });
  assert.strictEqual(out.en, "E 10.0 m N 20.0 m");
  assert.strictEqual(out.elev, "elev 5.0 m");
  assert.match(out.lonlat, /lat —/);
  assert.match(out.lonlat, /lon —/);
});
