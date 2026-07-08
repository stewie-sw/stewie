// [council #57] Monotonic per-component REQUEST GUARD. Mission panels re-fetch on WS.set (a site switch);
// without a guard a SLOW site-A response that resolves AFTER the user switched to site-B overwrites B's state
// (a silent wrong-site raster / physics readout / cell inspector — the race the GW-02 propagation exposed).
// Each async load takes a token from next(); on resolve it keeps its result only if current(token) is still
// true. Starting a new load (or bump()) invalidates every in-flight token. Plain UMD (browser <script> +
// node --test), matching workspace.js — no framework coupling.
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { root.STEWIEReqGuard = factory(); }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  // A fresh guard per component instance:
  //   this._rg = makeReqGuard();                                   // once
  //   const tok = this._rg.next();                                 // at the start of each load/fetch
  //   fetch(url).then(r => { if (!this._rg.current(tok)) return; this.setState(...); });
  function makeReqGuard() {
    var seq = 0;
    return {
      next: function () { seq += 1; return seq; },          // start a new request; returns its token
      current: function (tok) { return tok === seq; },      // is this token still the latest issued?
      bump: function () { seq += 1; },                       // invalidate every in-flight token (unmount / site change)
    };
  }
  return { makeReqGuard: makeReqGuard };
});
