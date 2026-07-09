// [systems-eng] fetchWithTimeout -- the ONE bounded-fetch wrapper every Mission panel's backend read goes
// through. A hung or slow backend read (/api, /world, /dem) must ABORT after a bounded timeout and surface a
// legible error the panel can show, NEVER hang the panel forever. It wraps the runtime fetch with an
// AbortController + a setTimeout(ctrl.abort, ms); the timer is CLEARED the instant the request settles (resolve
// OR reject) so a fast response never leaks a timer or fires a late abort, and the timeout rejects on its OWN
// (not only via the fetch abort-rejection) so the bound holds even on a runtime whose fetch ignores the signal.
// This is a pure last-resort BOUND -- it does NOT replace a panel's reqGuard (last-request-wins): a panel keeps
// its reqGuard for the site-switch race and adds THIS for the hung-backend case; the two compose (a request can
// be both aborted-late-and-ignored AND stale). Plain UMD (browser <script> global + node --test), matching
// reqGuard.js / workspace.js -- no framework coupling.
//   Run: node --test gis/qwc2/js/mission/fetchWithTimeout.test.js
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { root.STEWIE_FETCH_TIMEOUT = factory(); }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var DEFAULT_MS = 20000;   // panel READS: generous for a slow-but-alive backend, bounded so a hung read
                            // can't wedge the panel; the task's 15-20s band.
  var HEAVY_MS = 60000;     // heavy binaries / compute (the few-MB /dem/heightfield_full, a planner run):
                            // a much longer bound so a legitimately large-but-alive transfer is not aborted.

  // Resolve the fetch to use: an explicitly injected one (node tests) wins, else the runtime global fetch.
  function _resolveFetch(injected) {
    if (typeof injected === "function") { return injected; }
    if (typeof fetch !== "undefined") { return fetch; }
    return null;
  }

  // fetch(url, opts) with a bounded timeout. `ms` defaults to DEFAULT_MS. `fetchImpl` (4th arg) injects a fetch
  // for node tests. Resolves to the SAME Response the underlying fetch resolves to, so every caller's existing
  // `.then(r => r.ok ? r.json() : ...)` chain is UNCHANGED; only the hung/slow case differs (a legible reject).
  function fetchWithTimeout(url, opts, ms, fetchImpl) {
    opts = opts || {};
    ms = (typeof ms === "number" && ms > 0) ? ms : DEFAULT_MS;
    var f = _resolveFetch(fetchImpl);
    if (!f) { return Promise.reject(new Error("no fetch")); }

    var ctrl = (typeof AbortController !== "undefined") ? new AbortController() : null;
    var merged = opts;
    if (ctrl) {                                   // thread our abort signal in WITHOUT mutating the caller's opts
      merged = {};
      for (var k in opts) { if (Object.prototype.hasOwnProperty.call(opts, k)) { merged[k] = opts[k]; } }
      merged.signal = ctrl.signal;
    }

    return new Promise(function (resolve, reject) {
      var settled = false;
      var timer = setTimeout(function () {
        if (settled) { return; }
        settled = true;
        if (ctrl) { try { ctrl.abort(); } catch (e) { /* free the socket; ignore an abort throw */ } }
        reject(new Error("request timed out after " + ms + " ms: " + url));
      }, ms);
      f(url, merged).then(function (r) {
        if (settled) { return; }                  // the timeout already rejected -> drop the late resolve
        settled = true; clearTimeout(timer); resolve(r);
      }, function (e) {
        if (settled) { return; }                  // the timeout already rejected -> swallow the abort rejection
        settled = true; clearTimeout(timer); reject(e);
      });
    });
  }

  return { fetchWithTimeout: fetchWithTimeout, DEFAULT_MS: DEFAULT_MS, HEAVY_MS: HEAVY_MS };
});
