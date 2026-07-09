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

// F29: _sendRoute used to SILENTLY filter out measure points whose async /dem/site_lonlat lookup had not
// resolved (lat/lon still null) and emit only the survivors -- so a route with an unresolved INTERIOR point
// cut a straight leg past the dropped waypoint while the confirmation still said "Sent N". The decision now
// REFUSES to send when any point is still unresolved and reports the count, instead of thinning the route.
test("routeSendDecision: all points resolved -> emit them with a 'Sent N' confirmation", () => {
  const d = T.routeSendDecision([{ lat: -88.1, lon: 45.6 }, { lat: -88.2, lon: 45.7 }, { lat: -88.3, lon: 45.8 }]);
  assert.strictEqual(d.emit, true);
  assert.strictEqual(d.points.length, 3);
  assert.strictEqual(d.unresolved, 0);
  assert.match(d.msg, /Sent 3/);
});

test("routeSendDecision: an unresolved INTERIOR point REFUSES the send (F29 — no silent thinning)", () => {
  const d = T.routeSendDecision([{ lat: -88.1, lon: 45.6 }, { lat: null, lon: null }, { lat: -88.3, lon: 45.8 }]);
  assert.strictEqual(d.emit, false, "must NOT emit a 2-point route past the dropped middle waypoint");
  assert.strictEqual(d.points.length, 0, "nothing is sent");
  assert.strictEqual(d.unresolved, 1);
  assert.match(d.msg, /unresolved/, "surfaces the unresolved count, not a false 'Sent 2'");
  assert.match(d.msg, /1 waypoint/);
});

test("routeSendDecision: an unresolved TRAILING point also refuses (any drop is a refusal)", () => {
  const d = T.routeSendDecision([{ lat: -88.1, lon: 45.6 }, { lat: -88.2, lon: 45.7 }, { lat: null, lon: null }]);
  assert.strictEqual(d.emit, false);
  assert.strictEqual(d.unresolved, 1);
});

test("routeSendDecision: fewer than 2 resolved points -> refuse with the 'measure more' hint", () => {
  const d = T.routeSendDecision([{ lat: -88.1, lon: 45.6 }]);
  assert.strictEqual(d.emit, false);
  assert.strictEqual(d.unresolved, 0);
  assert.match(d.msg, /at least 2/);
});

test("routeSendDecision: empty / non-array input -> refuse, no throw", () => {
  assert.strictEqual(T.routeSendDecision([]).emit, false);
  assert.strictEqual(T.routeSendDecision(null).emit, false);
  assert.strictEqual(T.routeSendDecision(undefined).emit, false);
});
