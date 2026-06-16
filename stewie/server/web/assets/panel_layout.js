// FS-21: per-operator sidebar layout. PURE order logic only -- the DOM drag-and-drop glue lives in
// cockpit.js (wirePanelLayout). The "panes" are the top-level collapsible groups that collapseSidebar()
// builds from the sidebar's h3s; an operator can drag to reorder them and the order persists in
// localStorage under KEY. Layout is a VIEW preference ONLY: reordering never changes which controls a
// pane holds, command authority, AG-08 gating, role gates, or which contract a pane consumes.
(function (root) {
  "use strict";
  var KEY = "stewie_panel_order";

  // Reconcile a saved order with the panes actually present now: keep the saved order for panes that
  // still exist, then append any pane the saved layout did not know about (a pane added in a later
  // build) in its current position. So an old saved layout can never hide a new pane, and a removed
  // pane silently drops out. Pure.
  function mergeOrder(savedKeys, currentKeys) {
    var present = (currentKeys || []).slice();
    var seen = Object.create(null);
    var out = [];
    (savedKeys || []).forEach(function (k) {
      if (present.indexOf(k) !== -1 && !seen[k]) { out.push(k); seen[k] = true; }
    });
    present.forEach(function (k) { if (!seen[k]) { out.push(k); seen[k] = true; } });
    return out;
  }

  // Move draggedKey to sit immediately before targetKey (or to the end when targetKey is null/absent).
  // Pure; the DOM glue decides targetKey from the cursor position. Returns a NEW array.
  function reorder(order, draggedKey, targetKey) {
    var rest = (order || []).filter(function (k) { return k !== draggedKey; });
    if (targetKey == null) { rest.push(draggedKey); return rest; }
    var i = rest.indexOf(targetKey);
    if (i === -1) { rest.push(draggedKey); return rest; }
    rest.splice(i, 0, draggedKey);
    return rest;
  }

  var API = { KEY: KEY, mergeOrder: mergeOrder, reorder: reorder };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.STEWIE_PANEL_LAYOUT = API;
})(typeof window !== "undefined" ? window : null);
