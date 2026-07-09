// node --test for viz3d/scalebar.js. Covers the PURE perspective/scale/angle/format math against
// hand-computed values, and the DOM HUD writers against a MINIMAL fake `document` (a legitimate test
// boundary -- the double stands in for the browser environment, no synthetic DATA is fabricated). Also
// asserts the writers no-op (never throw) when there is no DOM, so importing the module in node is safe.
const test = require("node:test");
const assert = require("node:assert");
const SB = require("./scalebar.js");

const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) <= eps, `${a} !~= ${b} (eps ${eps})`);
const rowVal = (rows, key) => rows.find((r) => r.key === key).value;

// ---- metresPerPixel: real perspective math -------------------------------------------------------
test("metresPerPixel: 90deg FOV (tan45 = 1) -> 1 m/px", () => {
  // 2*d*tan(fov/2)/vh = 2*100*tan45/200 = 1.0 (tan45 is 0.9999999999999999 in IEEE754, hence the eps)
  near(SB.metresPerPixel({ cameraDistance_m: 100, fovYRad: Math.PI / 2, viewportHeightPx: 200 }), 1, 1e-12);
  near(SB.metresPerPixel({ cameraDistance_m: 500, fovYRad: Math.PI / 2, viewportHeightPx: 1000 }), 1, 1e-12);
});

test("metresPerPixel: matches hand-computed for viz3d's 48deg camera", () => {
  // d=1000 m, fovY=48deg, vh=600 px -> 2*1000*tan(24deg)/600. tan(24deg)=0.445228685308536.
  //   = 890.457370617072 / 600 = 1.48409561769512  (independently computed)
  const mpp = SB.metresPerPixel({ cameraDistance_m: 1000, fovYRad: 48 * Math.PI / 180, viewportHeightPx: 600 });
  near(mpp, 1.48409561769512, 1e-9);
  // farther camera -> proportionally more ground per pixel
  const far = SB.metresPerPixel({ cameraDistance_m: 4000, fovYRad: 48 * Math.PI / 180, viewportHeightPx: 600 });
  near(far, 4 * 1.48409561769512, 1e-9);
});

test("metresPerPixel: degenerate input returns 0 (no NaN propagation)", () => {
  assert.strictEqual(SB.metresPerPixel({ cameraDistance_m: 0, fovYRad: 1, viewportHeightPx: 600 }), 0);
  assert.strictEqual(SB.metresPerPixel({ cameraDistance_m: 1000, fovYRad: 0, viewportHeightPx: 600 }), 0);
  assert.strictEqual(SB.metresPerPixel({ cameraDistance_m: 1000, fovYRad: 1, viewportHeightPx: 0 }), 0);
  assert.strictEqual(SB.metresPerPixel({}), 0);
});

// ---- niceScaleBar: 1/2/5 x 10^n rounding + m<->km label at several zooms --------------------------
test("niceScaleBar: picks a 1/2/5x10^n distance nearest targetPx, m label", () => {
  const a = SB.niceScaleBar(0.01, 120);   // targetM 1.2 -> 1 m
  assert.strictEqual(a.metres, 1);
  assert.strictEqual(a.label, "1 m");
  near(a.lengthPx, 100, 1e-9);

  const b = SB.niceScaleBar(1, 120);       // targetM 120 -> 100 m
  assert.strictEqual(b.metres, 100);
  assert.strictEqual(b.label, "100 m");
  near(b.lengthPx, 100, 1e-9);
});

test("niceScaleBar: switches to km label >= 1000 m", () => {
  const c = SB.niceScaleBar(10, 120);      // targetM 1200 -> 1000 m = 1 km
  assert.strictEqual(c.metres, 1000);
  assert.strictEqual(c.label, "1 km");
  near(c.lengthPx, 100, 1e-9);

  const d = SB.niceScaleBar(100, 120);     // targetM 12000 -> 10000 m = 10 km
  assert.strictEqual(d.metres, 10000);
  assert.strictEqual(d.label, "10 km");
  near(d.lengthPx, 100, 1e-9);
});

test("niceScaleBar: every chosen distance is a 1/2/5 x 10^n number", () => {
  const isNice = (m) => {
    const e = Math.round(Math.log10(m / [1, 2, 5].reduce((best, k) => {
      const p = Math.pow(10, Math.round(Math.log10(m / k)));
      return Math.abs(k * p - m) < Math.abs(best - m) ? k * p : best;
    }, Infinity)));
    return e === 0; // reconstructed value equals m
  };
  for (const mpp of [0.002, 0.05, 0.7, 3, 17, 240, 5000]) {
    const r = SB.niceScaleBar(mpp, 120);
    const base = r.metres / Math.pow(10, Math.floor(Math.log10(r.metres)));
    assert.ok([1, 2, 5].some((k) => Math.abs(k - base) < 1e-6),
      `metres ${r.metres} has leading digit ${base}, expected 1/2/5`);
    // pixel width is within a factor of ~2.5 of target (the nice-rounding envelope)
    assert.ok(r.lengthPx >= 120 / 2.5 && r.lengthPx <= 120 * 2.5, `lengthPx ${r.lengthPx} off-target`);
  }
});

test("niceScaleBar: degenerate mPerPx -> empty bar", () => {
  assert.deepStrictEqual(SB.niceScaleBar(0, 120), { label: "", lengthPx: 0, metres: 0 });
  assert.deepStrictEqual(SB.niceScaleBar(NaN, 120), { label: "", lengthPx: 0, metres: 0 });
  assert.deepStrictEqual(SB.niceScaleBar(-1, 120), { label: "", lengthPx: 0, metres: 0 });
});

test("formatDistance: sub-metre, metre, and km labels", () => {
  assert.strictEqual(SB.formatDistance(0.5), "0.5 m");
  assert.strictEqual(SB.formatDistance(2), "2 m");
  assert.strictEqual(SB.formatDistance(500), "500 m");
  assert.strictEqual(SB.formatDistance(1000), "1 km");
  assert.strictEqual(SB.formatDistance(5000), "5 km");
  assert.strictEqual(SB.formatDistance(0), "");
});

// ---- latitudeFactor: projected-metres hook (default 1, NOT web mercator) --------------------------
test("latitudeFactor: default (polar-stereo) is 1 at every latitude", () => {
  assert.strictEqual(SB.latitudeFactor(85), 1);
  assert.strictEqual(SB.latitudeFactor(-88.5, "stereo"), 1);
  assert.strictEqual(SB.latitudeFactor(0, "none"), 1);
});

test("latitudeFactor: 'mercator' mode returns the genuine 1/cos(phi) correction", () => {
  assert.strictEqual(SB.latitudeFactor(0, "mercator"), 1);        // cos0 = 1
  near(SB.latitudeFactor(60, "mercator"), 2, 1e-9);              // 1/cos60 = 2
  assert.strictEqual(SB.latitudeFactor(90, "mercator"), 1);      // cos90 ~ 0 -> guarded to 1
});

// ---- arrow angle math ----------------------------------------------------------------------------
test("northArrowRotationRad: needle points opposite the camera heading", () => {
  assert.strictEqual(SB.northArrowRotationRad(0), 0);
  near(SB.northArrowRotationRad(Math.PI / 2), -Math.PI / 2, 1e-12);
  near(SB.northArrowRotationRad(-Math.PI / 2), Math.PI / 2, 1e-12);
  near(SB.northArrowRotationRad(Math.PI), Math.PI, 1e-12);        // -PI normalized to PI
});

test("sunArrowRotationRad: absolute azimuth by default, camera-relative when heading passed", () => {
  assert.strictEqual(SB.sunArrowRotationRad(0), 0);
  near(SB.sunArrowRotationRad(Math.PI / 2), Math.PI / 2, 1e-12);
  near(SB.sunArrowRotationRad(Math.PI / 2, Math.PI / 2), 0, 1e-12);   // sun ahead of camera -> up
  near(SB.sunArrowRotationRad(Math.PI, Math.PI / 2), Math.PI / 2, 1e-12);   // South sun, camera East -> sun to the right
});

test("sunGroundProjection: cos(elevation), clamped to [0,1]", () => {
  near(SB.sunGroundProjection(0), 1, 1e-12);              // horizon -> fully in-plane
  near(SB.sunGroundProjection(Math.PI / 3), 0.5, 1e-12);  // 60deg -> 0.5
  near(SB.sunGroundProjection(Math.PI / 2), 0, 1e-12);    // zenith -> 0
  assert.strictEqual(SB.sunGroundProjection(Math.PI), 0); // cos(180) = -1 -> clamped 0
});

test("normalizeAngleRad: wraps into (-PI, PI]", () => {
  near(SB.normalizeAngleRad(0), 0, 1e-12);
  near(SB.normalizeAngleRad(3 * Math.PI), Math.PI, 1e-12);
  near(SB.normalizeAngleRad(-3 * Math.PI), Math.PI, 1e-12);
  assert.strictEqual(SB.normalizeAngleRad(NaN), 0);
});

// ---- formatReadout: lon/lat/elev/slope/local-E-N formatting --------------------------------------
test("formatReadout: formats a full hover pick", () => {
  const rows = SB.formatReadout({ lon: -23.4567, lat: -86.1234, elev_m: 1234.56, slope_deg: 12.34, e_m: 100.5, n_m: 200.5 });
  assert.strictEqual(rowVal(rows, "lat"), "-86.1234°");
  assert.strictEqual(rowVal(rows, "lon"), "-23.4567°");
  assert.strictEqual(rowVal(rows, "elev"), "1234.6 m");
  assert.strictEqual(rowVal(rows, "slope"), "12.3°");
  assert.strictEqual(rowVal(rows, "e"), "100.5 m");
  assert.strictEqual(rowVal(rows, "n"), "200.5 m");
});

test("formatReadout: null / missing fields render the em-dash placeholder", () => {
  const rows = SB.formatReadout({ lon: null, lat: null, elev_m: undefined, slope_deg: NaN });
  for (const k of ["lat", "lon", "elev", "slope", "e", "n"]) assert.strictEqual(rowVal(rows, k), "—");
  const empty = SB.formatReadout();   // no arg -> all placeholders, no crash
  assert.strictEqual(rowVal(empty, "lat"), "—");
});

// ---- DOM writers: no-op without a DOM (import-in-node safety) -------------------------------------
test("renderers no-op (never throw) when there is no document or no dom", () => {
  assert.strictEqual(typeof document, "undefined", "precondition: node has no document here");
  assert.doesNotThrow(() => SB.renderScaleBar(null, { label: "1 km", lengthPx: 100 }));
  assert.doesNotThrow(() => SB.renderScaleBar({}, { label: "1 km", lengthPx: 100 }));   // dom present, document absent
  assert.doesNotThrow(() => SB.renderNorthArrow({}, 0.5));
  assert.doesNotThrow(() => SB.renderSunArrow({}, 0.5, 0.3));
  assert.doesNotThrow(() => SB.renderReadout({}, { lat: 1, lon: 2 }));
});

// ---- DOM writers: against a minimal fake `document` ----------------------------------------------
// A test double for the browser DOM (elements track children + settable style/className/textContent).
// Legitimate boundary, not synthetic data. Installed only inside these tests; removed in `finally`.
function fakeEl(tag) {
  return {
    tagName: tag, children: [], style: {}, className: "", textContent: "",
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
  };
}
function withFakeDom(fn) {
  global.document = { createElement: (t) => fakeEl(t) };
  try { fn(); } finally { delete global.document; }
}

test("renderScaleBar: builds nodes once, updates in place (idempotent), hides on empty", () => {
  withFakeDom(() => {
    const dom = fakeEl("div");
    SB.renderScaleBar(dom, SB.niceScaleBar(1, 120));   // -> "100 m", 100px
    assert.strictEqual(dom.children.length, 1, "one wrapper appended");
    const sb = dom.__stewieHud.scaleBar;
    assert.strictEqual(sb.label.textContent, "100 m");
    assert.strictEqual(sb.rule.style.width, "100px");
    assert.strictEqual(sb.wrap.style.display, "block");

    SB.renderScaleBar(dom, SB.niceScaleBar(10, 120));  // -> "1 km", 100px (reuse the SAME nodes)
    assert.strictEqual(dom.children.length, 1, "no second wrapper (idempotent)");
    assert.strictEqual(dom.__stewieHud.scaleBar.label.textContent, "1 km");

    SB.renderScaleBar(dom, { label: "", lengthPx: 0 });
    assert.strictEqual(dom.__stewieHud.scaleBar.wrap.style.display, "none", "empty bar hidden");
  });
});

test("renderNorthArrow: rotates the needle by -heading", () => {
  withFakeDom(() => {
    const dom = fakeEl("div");
    SB.renderNorthArrow(dom, Math.PI / 2);   // -90deg
    const t = dom.__stewieHud.northArrow.needle.style.transform;
    assert.ok(t.includes("rotate(-90.00deg)"), `transform was: ${t}`);
    SB.renderNorthArrow(dom, 0);             // 0deg, same node reused
    assert.strictEqual(dom.children.length, 1);
    assert.ok(dom.__stewieHud.northArrow.needle.style.transform.includes("rotate(0.00deg)"));
  });
});

test("renderSunArrow: rotates by azimuth, scales/dims by elevation", () => {
  withFakeDom(() => {
    const dom = fakeEl("div");
    SB.renderSunArrow(dom, Math.PI / 2, 0);   // az 90deg, el 0 (horizon) -> full length
    const needle = dom.__stewieHud.sunArrow.needle;
    assert.ok(needle.style.transform.includes("rotate(90.00deg)"), needle.style.transform);
    assert.ok(needle.style.transform.includes("scaleY(1.000)"), "horizon sun -> full length");

    SB.renderSunArrow(dom, 0, -0.2);          // below horizon -> dim
    assert.strictEqual(dom.children.length, 1, "idempotent");
    assert.strictEqual(needle.style.opacity, "0.35", "below-horizon sun dimmed");
  });
});

test("renderReadout: builds one row per field, rewrites values on update", () => {
  withFakeDom(() => {
    const dom = fakeEl("div");
    SB.renderReadout(dom, { lat: -86.1234, lon: -23.4567, elev_m: 100.4, slope_deg: 5.5, e_m: 10.5, n_m: 20.5 });
    assert.strictEqual(dom.children.length, 1);
    const cells = dom.__stewieHud.readout.cells;
    assert.strictEqual(cells.lat.textContent, "-86.1234°");
    assert.strictEqual(cells.elev.textContent, "100.4 m");

    SB.renderReadout(dom, {});   // hover-off -> em-dashes, no new wrapper
    assert.strictEqual(dom.children.length, 1);
    assert.strictEqual(dom.__stewieHud.readout.cells.lat.textContent, "—");
  });
});
