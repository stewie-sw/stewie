// GIS S-2 (TerriaJS workbench-card model): the PURE Contents tree. ONE ordered checkbox layer tree over
// the cockpit's EXISTING plan/layer state -- it does not own any state, it presents it. The cockpit's thin
// wrapper reads its live state (LAYER_ON, ORDERS, KEEPOUTS, LANDER/charger markers) into a plain snapshot,
// passes it to buildTree(), then renderTree() builds the DOM and wires each row's checkbox/zoom/remove back
// to cockpit handlers. No DOM lookups, no network, no module globals here -> node:test'able, CSP-safe
// (createElement only, no innerHTML), mirroring fleet_render.js / construction_render.js.
//
// Groups (ordered, stepper-coherent -- see plan_stepper.js STEP_SECTIONS):
//   Basemap  (Site)   · the imagery basemap layer
//   Terrain  (Site)   · DEM, slope, 3D terrain, reconstruction twin
//   Sun      (Site)   · illumination / incidence / PSR shadow rasters
//   Safety   (Orders) · keep-out obstacles (each = a selectable feature row) + the hazard raster
//   Operations(Orders)· build ORDERS as a real feature layer (each queued order = a tree row with its
//                       shape/kind, zoom-to + remove) + the lander/charger markers
//
// A row shape:
//   { id, label, kind, group, visible (bool|null), selected (bool), ref,
//     canZoom (bool), canRemove (bool), badge (string|"") }
//   kind: "layer" | "keepout" | "order" | "marker"
//   ref : for a layer = its layer id; for an order/keepout = its index; for a marker = "lander"|"charger"
//   visible=null => the row has no visibility toggle (e.g. an always-present marker is shown via its layer).
(function (root) {
  "use strict";

  // group order + which stepper section each belongs to (kept in lockstep with plan_stepper STEP_SECTIONS).
  var GROUPS = [
    { id: "basemap", name: "Basemap", section: "1" },
    { id: "terrain", name: "Terrain", section: "1" },
    { id: "sun", name: "Sun", section: "1" },
    { id: "safety", name: "Safety", section: "4" },
    { id: "operations", name: "Operations", section: "4" },
  ];

  // which LAYER_ON ids belong to which group, and their display names. Ordered within the group.
  var LAYER_GROUPS = {
    basemap: [["imagery", "Imagery basemap"]],
    terrain: [["dem", "Haworth DEM"], ["slope", "Slope"], ["topology", "Topology"],
              ["terrain3d", "3D Terrain"], ["recon_twin", "Reconstruction twin"], ["grid", "Site grid"]],
    sun: [["illumination", "Shadow (mission-time sun)"], ["incidence", "Sun incidence"], ["psr", "PSR shadow"]],
  };

  function orderShapeLabel(o) {
    if (!o) return "";
    if (o.kind === "goto") return "goto";
    var sh = o.shape;
    if (!sh) return "square";
    var t = sh.theta_deg ? " @" + Number(sh.theta_deg).toFixed(0) + "°" : "";
    if (sh.kind === "rectangle") return "rect " + fx(sh.w) + "×" + fx(sh.h) + t;
    if (sh.kind === "corridor") return "corridor " + fx(sh.length) + "×" + fx(sh.width) + t;
    if (sh.kind === "circle") return "circle r" + fx(sh.r);
    if (sh.kind === "polygon") return "poly (" + ((sh.vertices || []).length) + "v)";
    return "square";
  }
  function fx(v) { return v === undefined || v === null ? "—" : Number(v).toFixed(1).replace(/\.0$/, ""); }

  function orderLabel(o, i) {
    var base = (o && o.action) ? String(o.action) : ((o && o.kind) ? String(o.kind) : "order");
    var loc = (o && o.x !== undefined && o.y !== undefined) ? " @ " + fx(o.x) + "," + fx(o.y) + " m" : "";
    return (i + 1) + " · " + base + loc;
  }

  // Build the ordered tree from a plain state snapshot. PURE -- no DOM, no globals.
  //   state = {
  //     layerOn:   { <id>: bool, ... },              // the cockpit LAYER_ON map
  //     orders:    [ { kind, action, x, y, shape, footprint_m2, depth_m }, ... ],   // ORDERS
  //     keepouts:  [ { x, y, r } | { x0,y0,x1,y1 } | { vertices } , ... ],          // KEEPOUTS
  //     selectedOrder: <int>,                        // SELECTED_ORDER (-1 = none)
  //     hazardOn:  bool,                             // LAYER_ON.hazard
  //     markers:   { lander: {present, x, y}, charger: {present, x, y} },
  //     koLabel:   function(k) -> string             // injected keepout labeller (keepout_geom.koLabel)
  //   }
  // Returns [ { id, name, section, rows: [row,...] }, ... ] in group order; empty groups are dropped.
  function buildTree(state) {
    state = state || {};
    var layerOn = state.layerOn || {};
    var orders = Array.isArray(state.orders) ? state.orders : [];
    var keepouts = Array.isArray(state.keepouts) ? state.keepouts : [];
    var sel = (typeof state.selectedOrder === "number") ? state.selectedOrder : -1;
    var koLabel = (typeof state.koLabel === "function") ? state.koLabel : defaultKoLabel;
    var markers = state.markers || {};

    var byGroup = {};
    GROUPS.forEach(function (g) { byGroup[g.id] = []; });

    // 1..3: raster/vector LAYER rows from LAYER_ON (only ids the cockpit actually knows about).
    ["basemap", "terrain", "sun"].forEach(function (gid) {
      LAYER_GROUPS[gid].forEach(function (pair) {
        var lid = pair[0];
        if (!Object.prototype.hasOwnProperty.call(layerOn, lid)) return;   // only layers the cockpit serves
        byGroup[gid].push({
          id: "layer:" + lid, label: pair[1], kind: "layer", group: gid,
          visible: !!layerOn[lid], selected: false, ref: lid,
          canZoom: true, canRemove: false, badge: "",
        });
      });
    });

    // 4 Safety: the hazard raster (visibility) + each keep-out obstacle as a selectable feature row.
    if (Object.prototype.hasOwnProperty.call(layerOn, "hazard")) {
      byGroup.safety.push({
        id: "layer:hazard", label: "Hazard / no-go", kind: "layer", group: "safety",
        visible: !!layerOn.hazard, selected: false, ref: "hazard",
        canZoom: true, canRemove: false, badge: "",
      });
    }
    keepouts.forEach(function (k, i) {
      byGroup.safety.push({
        id: "keepout:" + i, label: "Keep-out: " + koLabel(k), kind: "keepout", group: "safety",
        visible: !!layerOn.hazard, selected: false, ref: i,
        canZoom: true, canRemove: true, badge: "obstacle",
      });
    });

    // 5 Operations: build ORDERS as a real feature layer (each = a row) + lander/charger markers.
    orders.forEach(function (o, i) {
      byGroup.operations.push({
        id: "order:" + i, label: orderLabel(o, i), kind: "order", group: "operations",
        visible: !!layerOn.excavation, selected: i === sel, ref: i,
        canZoom: true, canRemove: true, badge: orderShapeLabel(o),
      });
    });
    var lander = markers.lander || {};
    if (lander.present) {
      byGroup.operations.push({
        id: "marker:lander", label: "Lander · " + fx(lander.x) + "," + fx(lander.y) + " m",
        kind: "marker", group: "operations",
        visible: !!layerOn.lander, selected: false, ref: "lander",
        canZoom: true, canRemove: false, badge: "marker",
      });
    }
    var charger = markers.charger || {};
    if (charger.present) {
      byGroup.operations.push({
        id: "marker:charger", label: "Charger · " + fx(charger.x) + "," + fx(charger.y) + " m",
        kind: "marker", group: "operations",
        visible: null, selected: false, ref: "charger",
        canZoom: true, canRemove: false, badge: "marker",
      });
    }

    return GROUPS.map(function (g) {
      return { id: g.id, name: g.name, section: g.section, rows: byGroup[g.id] };
    }).filter(function (g) { return g.rows.length > 0; });
  }

  function defaultKoLabel(k) {
    if (k && Array.isArray(k.vertices)) return "polygon (" + k.vertices.length + " pts)";
    if (k && k.x0 !== undefined) return "box";
    return "circle @ " + fx(k && k.x) + "," + fx(k && k.y) + " · r " + fx(k && k.r) + " m";
  }

  // Render the tree into `container` (CSP-safe: createElement only). `handlers` dispatch back to the cockpit:
  //   handlers.onToggle(row, checked)  -- the visibility checkbox flipped
  //   handlers.onZoom(row)             -- the zoom-to (⌖) button
  //   handlers.onRemove(row)           -- the remove (✕) button (only on canRemove rows)
  //   handlers.onSelect(row)           -- a row's label clicked (selection; orders highlight on the canvas)
  // Returns the count of rows rendered. The container is cleared first.
  function renderTree(container, tree, doc, handlers) {
    if (!container) return 0;
    doc = doc || (typeof document !== "undefined" ? document : null);
    if (!doc) return 0;
    handlers = handlers || {};
    while (container.firstChild) container.removeChild(container.firstChild);
    var n = 0;
    tree.forEach(function (group) {
      var det = doc.createElement("details");
      det.open = true;
      det.className = "ct-group";
      det.setAttribute("data-group", group.id);
      var sum = doc.createElement("summary");
      sum.style.cssText = "cursor:pointer;font-weight:600;font-size:11px;padding:2px 0";
      sum.appendChild(doc.createTextNode(group.name + " (" + group.rows.length + ")"));
      det.appendChild(sum);
      group.rows.forEach(function (row) {
        det.appendChild(rowEl(row, doc, handlers));
        n++;
      });
      container.appendChild(det);
    });
    if (!n) {
      var empty = doc.createElement("div");
      empty.className = "empty";
      empty.style.cssText = "opacity:.6;font-size:11px;padding:4px 0";
      empty.appendChild(doc.createTextNode("No layers, keep-outs, or orders yet."));
      container.appendChild(empty);
    }
    return n;
  }

  function rowEl(row, doc, handlers) {
    var el = doc.createElement("div");
    el.className = "ct-row" + (row.selected ? " ct-selected" : "");
    el.setAttribute("data-row", row.id);
    el.style.cssText = "display:flex;align-items:center;gap:5px;font-size:11px;padding:2px 0 2px 8px" +
      (row.selected ? ";outline:1px solid var(--accent);border-radius:4px" : "");

    // visibility checkbox (drives the existing LAYER_ON show/hide flags via onToggle)
    if (row.visible === null) {
      var spacer = doc.createElement("span");
      spacer.style.cssText = "display:inline-block;width:13px";
      el.appendChild(spacer);
    } else {
      var cb = doc.createElement("input");
      cb.type = "checkbox"; cb.checked = !!row.visible;
      cb.className = "ct-vis";
      cb.title = "show / hide";
      cb.onchange = function () { if (handlers.onToggle) handlers.onToggle(row, cb.checked); };
      el.appendChild(cb);
    }

    var lab = doc.createElement("span");
    lab.className = "ct-label";
    lab.style.cssText = "flex:1 1 auto;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis";
    lab.appendChild(doc.createTextNode(row.label));
    lab.onclick = function () { if (handlers.onSelect) handlers.onSelect(row); };
    el.appendChild(lab);

    if (row.badge) {
      var bg = doc.createElement("span");
      bg.className = "ct-badge";
      bg.style.cssText = "font-size:8px;color:var(--dim);border:1px solid var(--line);border-radius:3px;padding:0 3px";
      bg.appendChild(doc.createTextNode(row.badge));
      el.appendChild(bg);
    }

    if (row.canZoom) {
      var z = doc.createElement("button");
      z.className = "ct-zoom"; z.title = "zoom to";
      z.style.cssText = "background:none;border:1px solid var(--line);border-radius:4px;color:var(--txt);cursor:pointer;font-size:10px";
      z.appendChild(doc.createTextNode("⌖"));
      z.onclick = function () { if (handlers.onZoom) handlers.onZoom(row); };
      el.appendChild(z);
    }
    if (row.canRemove) {
      var r = doc.createElement("button");
      r.className = "ct-remove"; r.title = "remove";
      r.style.cssText = "background:none;border:1px solid var(--line);border-radius:4px;color:var(--txt);cursor:pointer;font-size:10px";
      r.appendChild(doc.createTextNode("✕"));
      r.onclick = function () { if (handlers.onRemove) handlers.onRemove(row); };
      el.appendChild(r);
    }
    return el;
  }

  var API = {
    GROUPS: GROUPS,
    LAYER_GROUPS: LAYER_GROUPS,
    buildTree: buildTree,
    renderTree: renderTree,
    orderShapeLabel: orderShapeLabel,
    orderLabel: orderLabel,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.STEWIE_CONTENTS_TREE = API;
})(typeof window !== "undefined" ? window : null);
