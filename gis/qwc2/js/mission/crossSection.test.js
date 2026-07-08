// #45 cross-section geometry: densify a transect + derive the profile chart series / PSR bands. Pure, node-testable.
const assert = require("node:assert");
const { test } = require("node:test");
const X = require("./crossSection.js");

test("densify: a straight 2-point line -> N evenly spaced points by arc length", () => {
  const d = X.densify([[0, 0], [100, 0]], 5);
  assert.strictEqual(d.length, 5);
  assert.deepStrictEqual(d[0], [0, 0]);
  assert.deepStrictEqual(d[2], [50, 0]);
  assert.deepStrictEqual(d[4], [100, 0]);
});

test("densify: an L-shaped polyline spaces by arc length across the corner", () => {
  const d = X.densify([[0, 0], [100, 0], [100, 100]], 5);   // total 200, 4 gaps of 50
  assert.deepStrictEqual(d, [[0, 0], [50, 0], [100, 0], [100, 50], [100, 100]]);
});

test("densify: clamps N to [2,512] and handles a degenerate line", () => {
  assert.strictEqual(X.densify([[0, 0], [10, 0]], 1).length, 2);         // N<2 -> 2
  assert.strictEqual(X.densify([[0, 0], [10, 0]], 99999).length, 512);   // N>512 -> 512
  assert.deepStrictEqual(X.densify([[5, 5]], 4), [[5, 5]]);              // <2 vertices -> as-is
  assert.deepStrictEqual(X.densify([[5, 5], [5, 5]], 4), [[5, 5], [5, 5]]); // zero-length -> 2 copies
});

test("series: extracts {dist,value} for a field, dropping null / out-of-bounds", () => {
  const samples = [
    { dist_m: 0, elevation_m: 100.0, psr: false },
    { dist_m: 50, elevation_m: null, psr: null },     // out of bounds -> dropped, never invented
    { dist_m: 100, elevation_m: 102.5, psr: true },
  ];
  assert.deepStrictEqual(X.series(samples, "elevation_m"), [{ dist: 0, value: 100.0 }, { dist: 100, value: 102.5 }]);
});

test("extent: [min,max], widened when flat, [0,1] when empty", () => {
  assert.deepStrictEqual(X.extent([{ dist: 0, value: 3 }, { dist: 1, value: 7 }, { dist: 2, value: 5 }]), [3, 7]);
  assert.deepStrictEqual(X.extent([{ dist: 0, value: 4 }, { dist: 1, value: 4 }]), [4, 5]);   // flat -> widened
  assert.deepStrictEqual(X.extent([]), [0, 1]);
});

test("psrBands: contiguous psr===true runs become [start,end] distance ranges", () => {
  const samples = [
    { dist_m: 0, psr: false }, { dist_m: 10, psr: true }, { dist_m: 20, psr: true },
    { dist_m: 30, psr: false }, { dist_m: 40, psr: true }, { dist_m: 50, psr: null },
  ];
  assert.deepStrictEqual(X.psrBands(samples), [[10, 20], [40, 40]]);
});
