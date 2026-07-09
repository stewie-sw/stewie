// node:test for fetchWithTimeout.js -- the bounded-fetch wrapper. No network: a FAKE fetch is injected (4th
// arg) so the timeout / pass-through / error-propagation behaviour is exercised deterministically.
//   Run: node --test gis/qwc2/js/mission/fetchWithTimeout.test.js
const test = require("node:test");
const assert = require("node:assert");
const FT = require("./fetchWithTimeout.js");

test("exports the wrapper + the two timeout bands", () => {
  assert.strictEqual(typeof FT.fetchWithTimeout, "function");
  assert.strictEqual(FT.DEFAULT_MS, 20000);
  assert.strictEqual(FT.HEAVY_MS, 60000);
  assert.ok(FT.HEAVY_MS > FT.DEFAULT_MS, "heavy band must be more generous than the default read band");
});

test("resolves with the underlying Response when fetch settles in time (timer cleared)", async () => {
  const fakeResp = { ok: true, status: 200, json: () => Promise.resolve({ ok: true }) };
  const fake = () => Promise.resolve(fakeResp);
  const r = await FT.fetchWithTimeout("/world/point", {}, 1000, fake);
  assert.strictEqual(r, fakeResp);
  const body = await r.json();
  assert.deepStrictEqual(body, { ok: true });
});

test("rejects with a legible timeout error when the fetch never settles", async () => {
  const never = () => new Promise(() => {});              // a hung backend: never resolves, never rejects
  await assert.rejects(
    () => FT.fetchWithTimeout("/world/site-suitability?site=haworth", {}, 20, never),
    (e) => {
      assert.ok(/timed out after 20 ms/.test(e.message), "message states the bound: " + e.message);
      assert.ok(/site-suitability/.test(e.message), "message names the url: " + e.message);
      return true;
    }
  );
});

test("the timeout fires even if the underlying fetch ignores the abort signal", async () => {
  // A runtime whose fetch does NOT reject on abort: the wrapper's own timer must still reject.
  const ignoresAbort = () => new Promise(() => {});
  await assert.rejects(() => FT.fetchWithTimeout("/dem/heightfield_full", {}, 15, ignoresAbort),
    /timed out after 15 ms/);
});

test("propagates a NON-timeout fetch error verbatim (not masked as a timeout)", async () => {
  const boom = () => Promise.reject(new Error("network down"));
  await assert.rejects(() => FT.fetchWithTimeout("/api/evidence", {}, 1000, boom),
    (e) => { assert.strictEqual(e.message, "network down"); return true; });
});

test("passes the caller's opts through (method/body) and adds an abort signal, without mutating opts", async () => {
  let seenUrl = null; let seenOpts = null;
  const spy = (u, o) => { seenUrl = u; seenOpts = o; return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }); };
  const callerOpts = { method: "POST", credentials: "same-origin", body: '{"site":"haworth"}' };
  await FT.fetchWithTimeout("/world/transect", callerOpts, 1000, spy);
  assert.strictEqual(seenUrl, "/world/transect");
  assert.strictEqual(seenOpts.method, "POST");
  assert.strictEqual(seenOpts.credentials, "same-origin");
  assert.strictEqual(seenOpts.body, '{"site":"haworth"}');
  assert.ok(seenOpts.signal, "an AbortSignal was threaded in");
  assert.strictEqual(callerOpts.signal, undefined, "the caller's own opts object was NOT mutated");
});

test("rejects 'no fetch' when no fetch is available and none injected", async () => {
  // global fetch exists in node 18+, so force the no-fetch path by injecting a non-function and stubbing global.
  const savedFetch = global.fetch;
  try {
    // eslint-disable-next-line no-global-assign
    delete global.fetch;
    await assert.rejects(() => FT.fetchWithTimeout("/world/point", {}, 100), /no fetch/);
  } finally {
    if (savedFetch !== undefined) { global.fetch = savedFetch; }
  }
});
