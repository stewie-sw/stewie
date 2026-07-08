// GW-02 — the shared workspace-context store. ONE canonical (site, body, mission, profile, source) the
// whole lunar IDE reads, instead of each plugin/URL-builder defaulting to its own `|| "haworth"` literal.
// Pub/sub so a site pick in Mission Plan propagates to every consumer; URL-hydratable + serialisable so a
// single link restores the workspace. Plain UMD module (browser <script> + node --test), no Redux coupling.
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { root.STEWIEWorkspace = factory(); }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  // The single source of the default site. Every consumer that used to hard-code "haworth" now reads site().
  var DEFAULT = { site: "haworth", body: "moon", mission: null, profile: "desktop_sil", source: "actual" };
  var KEYS = ["site", "body", "mission", "profile", "source"];
  var _state = Object.assign({}, DEFAULT);
  var _subs = [];

  function get() { return Object.assign({}, _state); }
  function site() { return _state.site; }

  function set(patch) {
    var changed = false;
    for (var k in (patch || {})) {
      if (Object.prototype.hasOwnProperty.call(patch, k) && KEYS.indexOf(k) >= 0 && _state[k] !== patch[k]) {
        _state[k] = patch[k];
        changed = true;
      }
    }
    if (changed) {
      var snap = get();
      _subs.slice().forEach(function (fn) { try { fn(snap); } catch (e) { /* a bad subscriber never breaks set() */ } });
    }
    return get();
  }

  function subscribe(fn) {
    if (typeof fn !== "function") { return function () {}; }
    _subs.push(fn);
    return function () { var i = _subs.indexOf(fn); if (i >= 0) { _subs.splice(i, 1); } };
  }

  function _parseQuery(qs) {
    var o = {};
    String(qs == null ? "" : qs).replace(/^[?#]/, "").split("&").forEach(function (p) {
      if (!p) { return; }
      var i = p.indexOf("="), k = i < 0 ? p : p.slice(0, i), v = i < 0 ? "" : p.slice(i + 1);
      try { o[decodeURIComponent(k)] = decodeURIComponent(v.replace(/\+/g, " ")); } catch (e) { o[k] = v; }
    });
    return o;
  }

  // Accepts a "?a=b&c=d" string OR a plain object of params. Only known keys are adopted.
  function hydrateFromQuery(qs) {
    var params = (typeof qs === "string") ? _parseQuery(qs) : (qs || {});
    var patch = {};
    KEYS.forEach(function (k) { if (params[k] != null && params[k] !== "") { patch[k] = params[k]; } });
    return set(patch);
  }

  // Emit only NON-default keys so an unmodified workspace serialises to "" (a clean shareable URL).
  function toQuery() {
    var out = [];
    KEYS.forEach(function (k) {
      if (_state[k] != null && _state[k] !== DEFAULT[k]) { out.push(k + "=" + encodeURIComponent(_state[k])); }
    });
    return out.join("&");
  }

  function reset() { _state = Object.assign({}, DEFAULT); }

  return {
    get: get, site: site, set: set, subscribe: subscribe,
    hydrateFromQuery: hydrateFromQuery, toQuery: toQuery, reset: reset, DEFAULT: DEFAULT,
  };
});
