// viz3d layer stack -- the PURE draped-layer model for the full-res 3D terrain viewer (viz3d.js).
//
// Increment C of the viz3d geospatial upgrade (design/STEWIE_viz3d_geospatial_upgrade_2026-07-09.md
// section 1 + section 7-C). Extends viz3d.js's single-drape `setLayer` into an ordered STACK of draped
// analysis rasters with per-layer visibility / opacity / z-order + a legend descriptor -- driving a
// legend/opacity/visibility DOM panel. This file is the MODEL only: no THREE, no DOM, no fetch. It is
// UMD (browser <script> + `node --test`, like gis/qwc2/js/mission/reqGuard.js), so the ordering / clamp /
// round-trip logic is node-tested with zero browser.
//
// ---- backend ground truth (run-verified 2026-07-09 against the real Haworth LOLA crop) ----------------
// The drape kinds come from the server route `GET /dem/heightfield_full/layer.png?kind=...`
// (stewie/server/routers/dem.py `dem_heightfield_full_layer`), which dispatches:
//   kind in {cost, blocking}          -> gis_layers._costmap_rgba
//   kind in _PHYSICS_KINDS            -> gis_layers._physics_rgba
//   else                              -> gis_layers._layer_rgba
// and returns HTTP 400 when the helper returns None (unknown kind). Verified by calling the pure helpers
// on a 12x12 real-DEM subsample: hillshade, slope, aspect, roughness, illumination, dem, cost, blocking
// all return an RGBA array; `elevation` and `traffic` return None (=> 400). So:
//   * `elevation` is NOT a layer.png drape -- it is the base vertex-coloured relief the viewer already
//     builds from the /dem/heightfield_full binary (viz3d.js `setLayer("elevation")` special case).
//     Modelled here as render:"base", sourceUrl -> the heightfield_full binary (the real source of that
//     colouring), available:true.
//   * `traffic` (TW-11 traversal hardening) IS a real backend layer, but only via /layers/raster + the
//     globe drape (gis_layers._render_globe_traffic) -- NOT the order-frame layer.png route the 3D viewer
//     drapes through. Modelled available:false, sourceUrl:null (no fabricated source).
// Legend ranges are pulled from what the backend actually defines (slope_vmax default 30 deg; aspect 0..360)
// or left null with a note where the backend renders a per-tile percentile stretch / a binary classification
// (roughness, cost, illumination, hillshade, elevation) -- never a fabricated fixed range.
//
// ---- resolveTexture(layer) contract (implemented in viz3d.js, NOT here) --------------------------------
// viz3d.js turns a LayerModel into a rendered surface. The exact contract the integration MUST honour:
//   render === "base"  (elevation): no drape texture. Keep the existing vertex-coloured terrain mesh
//       (mat.vertexColors = true, mat.map = null). This layer's `opacity` is ignored (the base is opaque);
//       toggling its `visible` off is not meaningful (it is the relief itself). It sits at the BOTTOM of
//       the stack (lowest zOrder).
//   render === "drape" (all others): build the drape URL:
//         url = layer.sourceUrl;                    // "/dem/heightfield_full/layer.png?...&kind=<kind>"
//         if (layer.sunDependent) url += "&sun_az=" + Math.round(sunAz) + "&sun_el=" + Math.round(sunEl);
//       then fetch it through viz3d.js's bounded _fetchT(url, LAYER_TIMEOUT_MS) -> blob -> object URL ->
//       THREE.TextureLoader.load, set tex.colorSpace = SRGBColorSpace, min/magFilter = LinearFilter, and
//       apply it as a STACKED transparent overlay of the terrain geometry (a clone of S.mesh.geometry with
//       a MeshBasicMaterial{ map: tex, transparent: true, opacity: layer.opacity, depthWrite: false,
//       polygonOffset: true, polygonOffsetFactor: -(drawIndex + 1) }), added to S.group with
//       renderOrder = drawIndex. The base terrain mesh renders first (renderOrder 0); each drape renders on
//       top in stack order. Revoke the object URL after decode (as setLayer already does).
// The DRAW LIST + ORDER is exactly `stack.visibleOrdered()` (bottom -> top). On a stack change (add/remove/
// reorder/opacity/visibility) viz3d.js rebuilds/updates the overlay meshes from visibleOrdered(); on a vex
// or globe re-place it re-drapes the overlay geometry the same way the grid/graticule re-drape. A per-layer
// legend/opacity/visibility DOM panel is driven off `stack.ordered()` (each row: label + legend swatch from
// layer.legend + an opacity slider -> setOpacity + a visibility checkbox -> setVisible + up/down -> move).
//
// LayerModel shape (all JSON-serialisable; no functions on an instance):
//   { id, kind, label, visible, opacity(0..1), zOrder, legend, sourceUrl, render, sunDependent }
// `legend` = { min, max, units, colormap, note? } (min/max may be null where the backend has no fixed range).
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { root.STEWIEViz3DLayers = factory(); }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ---- catalog: the REAL backend drape kinds (verified server-side; see the header) -------------------
  // Each entry: { kind, label, available, render, sunDependent, legend, sourceUrl(site,window_m,x0,y0), note? }
  // `available:true`  -> sourceUrl is a builder returning a URL that hits a REAL backend route.
  // `available:false` -> sourceUrl is null (the backend does not render this kind on the layer.png drape route).
  function drapeUrl(kind) {
    return function (site, window_m, x0, y0) {
      return "/dem/heightfield_full/layer.png?site=" + encodeURIComponent(String(site)) +
        "&window_m=" + Number(window_m) + "&x0=" + Number(x0) + "&y0=" + Number(y0) +
        "&kind=" + encodeURIComponent(kind);
    };
  }
  function baseUrl() {
    // the base relief comes from the SAME native float32 heightfield the mesh is built from
    return function (site, window_m, x0, y0) {
      return "/dem/heightfield_full?site=" + encodeURIComponent(String(site)) +
        "&window_m=" + Number(window_m) + "&x0=" + Number(x0) + "&y0=" + Number(y0);
    };
  }

  var LAYER_CATALOG = [
    {
      kind: "elevation", label: "Elevation (relief)", available: true, render: "base", sunDependent: false,
      legend: { min: null, max: null, units: "m", colormap: "elevation ramp",
        note: "per-tile z-range from the X-Dem-Z-Min/X-Dem-Z-Max response headers; not a fixed range" },
      sourceUrl: baseUrl(),
      note: "base vertex-coloured relief from the /dem/heightfield_full binary; NOT a layer.png drape " +
        "(layer.png?kind=elevation returns 400 -- run-verified)",
    },
    {
      kind: "hillshade", label: "Hillshade (lambertian relief)", available: true, render: "drape", sunDependent: true,
      legend: { min: null, max: null, units: "", colormap: "grayscale hillshade",
        note: "relative shading 0..255; backend default sun 315/45 (kind=dem is the 315/45 sun-pinned alias)" },
      sourceUrl: drapeUrl("hillshade"),
    },
    {
      kind: "slope", label: "Slope (deg)", available: true, render: "drape", sunDependent: false,
      legend: { min: 0, max: 30, units: "deg", colormap: "green -> red",
        note: "ramp domain = backend slope_vmax default 30 deg (gis_layers._layer_rgba)" },
      sourceUrl: drapeUrl("slope"),
    },
    {
      kind: "aspect", label: "Aspect (downslope azimuth)", available: true, render: "drape", sunDependent: false,
      legend: { min: 0, max: 360, units: "deg", colormap: "cyclic HSV hue wheel",
        note: "gradient azimuth 0..360 (gis_layers.aspect_deg); 0 and 360 share a hue" },
      sourceUrl: drapeUrl("aspect"),
    },
    {
      kind: "roughness", label: "Roughness (window-RMS slope)", available: true, render: "drape", sunDependent: false,
      legend: { min: null, max: null, units: "", colormap: "pale -> deep",
        note: "robust 2nd/98th-percentile per-tile stretch (lode.costmap_layers._roughness); no fixed range" },
      sourceUrl: drapeUrl("roughness"),
    },
    {
      kind: "cost", label: "Traversability cost", available: true, render: "drape", sunDependent: true,
      legend: { min: null, max: null, units: "", colormap: "green -> amber -> red",
        note: "plan-independent FORGE costmap, robust 2nd/98th-percentile per-tile stretch (COST_RAMP); no fixed range" },
      sourceUrl: drapeUrl("cost"),
    },
    {
      kind: "illumination", label: "Shadow (horizon-clipped sun)", available: true, render: "drape", sunDependent: true,
      legend: { min: null, max: null, units: "", colormap: "shadow overlay (blue = unlit)",
        note: "binary lit/shadow at the commanded sun geometry (dart.illumination.horizon_clip); transparent where lit" },
      sourceUrl: drapeUrl("illumination"),
    },
    {
      // available:false -- a REAL backend layer, but not on the layer.png drape route (run-verified 400)
      kind: "traffic", label: "Traffic hardening (Dr)", available: false, render: "drape", sunDependent: false,
      legend: null, sourceUrl: null,
      note: "TW-11 traversal hardening is rendered by the backend, but ONLY via /layers/raster + the globe " +
        "drape (gis_layers._render_globe_traffic). /dem/heightfield_full/layer.png?kind=traffic returns 400 " +
        "(traffic is not in _layer_rgba/_costmap_rgba/_physics_rgba). Not drapable on the full-res relief yet.",
    },
  ];

  function catalogEntry(kind) {
    for (var i = 0; i < LAYER_CATALOG.length; i++) {
      if (LAYER_CATALOG[i].kind === kind) { return LAYER_CATALOG[i]; }
    }
    return null;
  }

  // Build a LayerModel from a catalog kind + a tile window. Returns null for an unknown OR unavailable kind
  // (never fabricates a source for an available:false kind). zOrder is left undefined -> assigned on add().
  function layerFromCatalog(kind, ctx) {
    var e = catalogEntry(kind);
    if (!e || !e.available) { return null; }
    ctx = ctx || {};
    var site = ctx.site != null ? ctx.site : "haworth";
    var window_m = ctx.window_m != null ? ctx.window_m : (ctx.window != null ? ctx.window : -1);
    var x0 = ctx.x0 != null ? ctx.x0 : 0;
    var y0 = ctx.y0 != null ? ctx.y0 : 0;
    return {
      id: kind, kind: e.kind, label: e.label,
      visible: true, opacity: 1, zOrder: undefined,
      legend: e.legend ? cloneLegend(e.legend) : null,
      sourceUrl: e.sourceUrl(site, window_m, x0, y0),
      render: e.render, sunDependent: !!e.sunDependent,
    };
  }

  function cloneLegend(l) {
    if (l == null) { return null; }
    var out = {};
    for (var k in l) { if (Object.prototype.hasOwnProperty.call(l, k)) { out[k] = l[k]; } }
    return out;
  }

  function clampOpacity(v) {
    var n = Number(v);
    if (!isFinite(n)) { return null; }        // reject NaN/Infinity -> caller leaves the value unchanged
    return Math.max(0, Math.min(1, n));
  }

  // ---- the stack model --------------------------------------------------------------------------------
  // makeLayerStack(initial?) -> an ordered LayerModel stack. `initial` is an optional array of layer specs
  // (each passed through add()). Deterministic: ordered() is a STABLE sort by zOrder (insertion order breaks
  // ties), so the same operations always yield the same draw order.
  function makeLayerStack(initial) {
    var layers = [];        // internal, in INSERTION order; zOrder governs the DRAW order (ordered())

    function nextZ() {
      var mx = -1;
      for (var i = 0; i < layers.length; i++) {
        if (typeof layers[i].zOrder === "number" && layers[i].zOrder > mx) { mx = layers[i].zOrder; }
      }
      return mx + 1;        // first layer -> 0
    }

    function normalizeLayer(spec) {
      if (!spec || spec.id == null || spec.id === "") { throw new TypeError("layer requires an id"); }
      if (spec.kind == null || spec.kind === "") { throw new TypeError("layer requires a kind"); }
      var op = clampOpacity(spec.opacity == null ? 1 : spec.opacity);
      return {
        id: String(spec.id),
        kind: String(spec.kind),
        label: spec.label != null ? String(spec.label) : String(spec.kind),
        visible: spec.visible == null ? true : !!spec.visible,
        opacity: op == null ? 1 : op,
        zOrder: (typeof spec.zOrder === "number" && isFinite(spec.zOrder)) ? spec.zOrder : nextZ(),
        legend: spec.legend != null ? cloneLegend(spec.legend) : null,
        sourceUrl: spec.sourceUrl != null ? String(spec.sourceUrl) : null,
        render: spec.render === "base" ? "base" : "drape",
        sunDependent: !!spec.sunDependent,
      };
    }

    function indexOf(id) {
      for (var i = 0; i < layers.length; i++) { if (layers[i].id === id) { return i; } }
      return -1;
    }

    function get(id) {
      var i = indexOf(id);
      return i < 0 ? null : layers[i];
    }

    function add(spec) {
      var lyr = normalizeLayer(spec);       // throws on missing id/kind
      if (indexOf(lyr.id) >= 0) { throw new TypeError("duplicate layer id: " + lyr.id); }
      layers.push(lyr);
      return lyr;
    }

    function remove(id) {
      var i = indexOf(id);
      if (i < 0) { return false; }
      layers.splice(i, 1);
      return true;
    }

    function setVisible(id, on) {
      var l = get(id);
      if (!l) { return false; }
      l.visible = !!on;
      return true;
    }

    function setOpacity(id, v) {
      var l = get(id);
      if (!l) { return false; }
      var op = clampOpacity(v);
      if (op == null) { return false; }       // non-finite -> reject, leave unchanged
      l.opacity = op;
      return true;
    }

    function setZOrder(id, n) {
      var l = get(id);
      if (!l) { return false; }
      var z = Number(n);
      if (!isFinite(z)) { return false; }
      l.zOrder = z;
      return true;
    }

    // ordered(): a STABLE sort by zOrder ascending (bottom -> top). Ties keep insertion order. Returns a new
    // array of the LIVE layer objects (mutating a returned layer's fields mutates the stack; the array itself
    // is a copy). Explicit index tiebreak so stability holds regardless of the engine's sort.
    function ordered() {
      var decorated = layers.map(function (l, i) { return { l: l, i: i }; });
      decorated.sort(function (a, b) {
        if (a.l.zOrder !== b.l.zOrder) { return a.l.zOrder - b.l.zOrder; }
        return a.i - b.i;                      // stable tiebreak
      });
      return decorated.map(function (d) { return d.l; });
    }

    function visibleOrdered() {
      return ordered().filter(function (l) { return l.visible; });
    }

    // move(id, dir): reorder within the stack. dir "up"/+1 -> toward the TOP (drawn later / higher zOrder);
    // "down"/-1 -> toward the bottom. Boundary is a no-op (returns false). Deterministic: it recomputes the
    // ordered sequence, swaps the layer with its neighbour, and RENUMBERS zOrder to a contiguous 0..n-1 in
    // the new order (so it is robust even when two layers shared a zOrder).
    function move(id, dir) {
      var up = (dir === "up" || dir === 1 || dir === "+1" || dir === "top");
      var down = (dir === "down" || dir === -1 || dir === "-1" || dir === "bottom");
      if (!up && !down) { return false; }
      var ord = ordered();
      var idx = -1;
      for (var i = 0; i < ord.length; i++) { if (ord[i].id === id) { idx = i; break; } }
      if (idx < 0) { return false; }
      var j = up ? idx + 1 : idx - 1;
      if (j < 0 || j >= ord.length) { return false; }     // already at the boundary
      var tmp = ord[idx]; ord[idx] = ord[j]; ord[j] = tmp;
      for (var k = 0; k < ord.length; k++) { ord[k].zOrder = k; }   // contiguous renumber in the new order
      return true;
    }

    // toJSON(): a plain, JSON-serialisable array of the layers in INSERTION order (draw order is derived from
    // zOrder via ordered(), so it round-trips). Deep-copies legend so the snapshot cannot be mutated by ref.
    function toJSON() {
      return layers.map(function (l) {
        return {
          id: l.id, kind: l.kind, label: l.label,
          visible: l.visible, opacity: l.opacity, zOrder: l.zOrder,
          legend: l.legend != null ? cloneLegend(l.legend) : null,
          sourceUrl: l.sourceUrl, render: l.render, sunDependent: l.sunDependent,
        };
      });
    }

    // fromJSON(data): replace the stack contents from a toJSON() snapshot (an array, or { layers: [...] }).
    // Preserves each layer's stored zOrder. Returns the stack (chainable).
    function fromJSON(data) {
      var arr = Array.isArray(data) ? data : (data && Array.isArray(data.layers) ? data.layers : []);
      layers = [];
      for (var i = 0; i < arr.length; i++) { add(arr[i]); }
      return api;
    }

    var api = {
      add: add, remove: remove, get: get,
      setVisible: setVisible, setOpacity: setOpacity, setZOrder: setZOrder, move: move,
      ordered: ordered, visibleOrdered: visibleOrdered,
      toJSON: toJSON, fromJSON: fromJSON,
      size: function () { return layers.length; },
    };

    if (Array.isArray(initial)) { for (var n = 0; n < initial.length; n++) { add(initial[n]); } }
    return api;
  }

  return {
    makeLayerStack: makeLayerStack,
    LAYER_CATALOG: LAYER_CATALOG,
    catalogEntry: catalogEntry,
    layerFromCatalog: layerFromCatalog,
    clampOpacity: clampOpacity,
  };
});
