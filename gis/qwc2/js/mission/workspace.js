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
  // task #77: a SEPARATE plot-event channel (3D terrain Shift+click -> Mission Plan order queue). Deliberately
  // NOT routed through set()/KEYS -- a plotted point is a transient event (an order to place), not a piece of
  // durable, URL-hydratable workspace state, so it gets its own pub/sub instead of joining the whitelisted store.
  var _plotSubs = [];

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

  // task #77: emit a plotted point (from the 3D terrain Shift+click) to every subscriber. A throwing
  // subscriber never breaks delivery to the rest (same defensive try/catch as set()'s notify loop).
  function emitPlot(point) {
    _plotSubs.slice().forEach(function (fn) { try { fn(point); } catch (e) { /* a bad subscriber never breaks emitPlot() */ } });
  }

  function onPlot(fn) {
    if (typeof fn !== "function") { return function () {}; }
    _plotSubs.push(fn);
    return function () { var i = _plotSubs.indexOf(fn); if (i >= 0) { _plotSubs.splice(i, 1); } };
  }

  // task #56 auto-float: one plugin (e.g. MissionPlan's "3D" button) asks another plugin (by id) to pop
  // itself into a floating ResizeableWindow card. A transient event channel like emitPlot -- NOT routed
  // through set()/KEYS (floating is UI state, not durable workspace state).
  var _floatSubs = [];
  function requestFloat(id) {
    _floatSubs.slice().forEach(function (fn) { try { fn(id); } catch (e) { /* a bad subscriber never breaks requestFloat() */ } });
  }
  function onFloatRequest(fn) {
    if (typeof fn !== "function") { return function () {}; }
    _floatSubs.push(fn);
    return function () { var i = _floatSubs.indexOf(fn); if (i >= 0) { _floatSubs.splice(i, 1); } };
  }

  // task #80: a route-event channel (the 3D measure tool's waypoints -> Mission Plan's Traverse authoring).
  // Same transient-event shape as emitPlot/onPlot -- NOT routed through set()/KEYS (a pushed route is an
  // authoring action to replay, not durable workspace state).
  var _routeSubs = [];
  function emitRoute(points) {
    _routeSubs.slice().forEach(function (fn) { try { fn(points); } catch (e) { /* a bad subscriber never breaks emitRoute() */ } });
  }
  function onRoute(fn) {
    if (typeof fn !== "function") { return function () {}; }
    _routeSubs.push(fn);
    return function () { var i = _routeSubs.indexOf(fn); if (i >= 0) { _routeSubs.splice(i, 1); } };
  }

  return {
    get: get, site: site, set: set, subscribe: subscribe,
    hydrateFromQuery: hydrateFromQuery, toQuery: toQuery, reset: reset, DEFAULT: DEFAULT,
    emitPlot: emitPlot, onPlot: onPlot,
    requestFloat: requestFloat, onFloatRequest: onFloatRequest,
    emitRoute: emitRoute, onRoute: onRoute,
  };
});
