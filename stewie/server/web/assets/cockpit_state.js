// Phase 2 / FS-16: the cockpit's single routeable STATE MODEL. One state object for the selected
// mission / site / vehicle / body / time / mode / role / work-area / selected-entity / source; pure
// transitions that enforce the enums, plus URL-hash (de)serialization so a link restores a view and
// desktop + mobile are alternate views of the SAME state (not separate logic). No DOM -> node:test'able.
(function (root) {
  "use strict";

  var WORK_AREAS = ["plan", "fleet", "navigation", "perception", "construction",
                    "models", "system", "report", "admin"];
  var SOURCES = ["live", "sim", "eval"];      // PO-10: which truth source the panes label
  var MODES = ["sandbox", "live"];            // AG-07 namespace

  function defaultState() {
    return { mission: null, site: "haworth", vehicle: null, body: "moon", timeS: 0,
             mode: "live", role: "guest", workArea: "plan", selectedEntity: null, source: "sim" };
  }

  function setState(state, patch) {
    var next = Object.assign({}, state, patch);
    if (patch.workArea !== undefined && WORK_AREAS.indexOf(next.workArea) < 0)
      throw new Error("unknown workArea " + patch.workArea);
    if (patch.source !== undefined && SOURCES.indexOf(next.source) < 0)
      throw new Error("unknown source " + patch.source);
    if (patch.mode !== undefined && MODES.indexOf(next.mode) < 0)
      throw new Error("unknown mode " + patch.mode);
    return next;
  }

  // the routeable subset -> a URL hash fragment (a link restores the view)
  function toHash(state) {
    var parts = [];
    ["workArea", "site", "mission", "vehicle", "source", "mode"].forEach(function (k) {
      if (state[k]) parts.push(k + "=" + encodeURIComponent(state[k]));
    });
    if (state.timeS) parts.push("t=" + state.timeS);
    return parts.join("&");
  }

  function fromHash(hash, base) {
    var state = Object.assign(defaultState(), base || {});
    (hash || "").replace(/^#/, "").split("&").forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf("=");
      if (i < 0) return;
      var k = kv.slice(0, i), v = decodeURIComponent(kv.slice(i + 1));
      if (k === "t") state.timeS = parseFloat(v) || 0;
      else if (k in state) state[k] = v;
    });
    return state;
  }

  var API = { WORK_AREAS: WORK_AREAS, SOURCES: SOURCES, MODES: MODES,
              defaultState: defaultState, setState: setState, toHash: toHash, fromHash: fromHash };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.STEWIE_STATE = API;
})(typeof window !== "undefined" ? window : null);
