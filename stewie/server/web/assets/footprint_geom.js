// GIS S-3: typed build-order FOOTPRINT-SHAPE geometry for the Plan pane (2D plancanvas). PURE
// functions only -- no DOM lookups, no module-level globals. cockpit.js builds the shape dict from the
// authoring form and passes ORDERS in; this module turns a shape into a local-frame boundary ring, the
// planar area, and the canvas outline. The ring/area math is the JS twin of the backend CP-05 schema
// (lode.mission_planner.footprint_shape_area_m2 + lode.gis_export._footprint_ring_xy) so an authored
// shape rasterizes server-side to the SAME geometry it previews here. node:test'able (a stub 2D context
// records the calls). The legacy scalar -> axis-aligned square path is preserved: an order with no
// `shape` still renders/round-trips exactly as before (footprintRingXY returns the square ring).
//
// Supported kinds (local order frame, centred on the order's (x,y), orientation theta_deg CCW):
//   rectangle {kind, w, h, theta_deg}      -- an oriented box (a 15x2 road is a real 15x2, not a square)
//   corridor  {kind, length, width, theta_deg} -- an oriented haul/grade strip (rect alias for authoring)
//   circle    {kind, r}                     -- a disc (orientation-free)
//   polygon   {kind, vertices:[[x,y],...]}  -- an arbitrary planar polygon
(function (root) {
  "use strict";

  // CP-05 planar area [m^2] of a typed footprint shape. The JS twin of
  // lode.mission_planner.footprint_shape_area_m2 (same shoelace, same circle/rect/corridor formulas).
  // Returns NaN on an unknown/degenerate shape so the caller can fall back to the scalar path rather
  // than fabricate an area. Pure.
  function shapeArea(shape) {
    if (!shape) return NaN;
    var k = String(shape.kind || "").toLowerCase();
    if (k === "rectangle") {
      var w = +shape.w, h = +shape.h;
      return (w > 0 && h > 0) ? w * h : NaN;
    }
    if (k === "corridor") {
      var L = +shape.length, cw = +shape.width;
      return (L > 0 && cw > 0) ? L * cw : NaN;
    }
    if (k === "circle") {
      var r = +shape.r;
      return (r > 0) ? Math.PI * r * r : NaN;
    }
    if (k === "polygon") {
      var v = shape.vertices;
      if (!Array.isArray(v) || v.length < 3) return NaN;
      var a = 0;
      for (var i = 0; i < v.length; i++) {
        var p = v[i], q = v[(i + 1) % v.length];
        a += (+p[0]) * (+q[1]) - (+q[0]) * (+p[1]);
      }
      var area = Math.abs(a) * 0.5;
      return area > 0 ? area : NaN;
    }
    return NaN;
  }

  // Rotate+translate a list of local [x,y] by theta (radians) about, then offset to, the order centre.
  // Pure helper.
  function _place(local, cx, cy, theta) {
    var ct = Math.cos(theta), st = Math.sin(theta);
    return local.map(function (p) {
      var lx = +p[0], ly = +p[1];
      return [cx + lx * ct - ly * st, cy + lx * st + ly * ct];
    });
  }

  // The CLOSED boundary ring (local order-frame metres) of a build order's footprint, centred on the
  // order's (x,y). The JS twin of lode.gis_export._footprint_ring_xy for the typed-shape kinds, PLUS a
  // legacy fall-back: an order with no usable shape yields the axis-aligned square of side
  // sqrt(footprint_m2) -- byte-for-byte the existing scalar->square the canvas already draws, so the
  // default path is preserved. `n` = circle sample count. Returns null only when neither a shape nor a
  // positive scalar footprint is available. Pure.
  function footprintRingXY(order, n) {
    n = n || 32;
    var cx = +order.x || 0, cy = +order.y || 0;
    var shape = order && order.shape;
    var area = shapeArea(shape);
    if (shape && area === area) {                         // a usable typed shape (area is not NaN)
      var k = String(shape.kind).toLowerCase();
      var theta = (Number(shape.theta_deg) || 0) * Math.PI / 180;
      var ring;
      if (k === "rectangle") {
        var w = (+shape.w) / 2, h = (+shape.h) / 2;
        ring = _place([[-w, -h], [w, -h], [w, h], [-w, h]], cx, cy, theta);
      } else if (k === "corridor") {
        var L = (+shape.length) / 2, cw = (+shape.width) / 2;
        ring = _place([[-L, -cw], [L, -cw], [L, cw], [-L, cw]], cx, cy, theta);
      } else if (k === "circle") {
        var r = +shape.r;
        ring = [];
        for (var i = 0; i < n; i++) {
          ring.push([cx + r * Math.cos(2 * Math.PI * i / n), cy + r * Math.sin(2 * Math.PI * i / n)]);
        }
      } else if (k === "polygon") {
        ring = _place(shape.vertices.map(function (v) { return [+v[0], +v[1]]; }), cx, cy, theta);
      } else {
        ring = null;
      }
      if (ring) {
        if (ring.length && (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1])) {
          ring = ring.concat([ring[0]]);                  // close the ring
        }
        return ring;
      }
    }
    // legacy scalar -> axis-aligned square (the pre-CP-05 default; NOT a fabricated typed shape)
    var fp = +order.footprint_m2;
    if (!(fp > 0)) return null;
    var s = Math.sqrt(fp) / 2;
    return [[cx - s, cy - s], [cx + s, cy - s], [cx + s, cy + s], [cx - s, cy + s], [cx - s, cy - s]];
  }

  // Whether an order carries a real (non-square) typed footprint. Pure -- lets the canvas/queue decide
  // between the shape outline and the legacy square without re-deriving the area.
  function hasTypedShape(order) {
    return !!(order && order.shape && shapeArea(order.shape) === shapeArea(order.shape));
  }

  // Build a CP-05 shape dict from the authoring form's raw values, or null when the operator chose the
  // default "square" mode (kind == "" / "square") -> the legacy scalar path. Coerces + validates so an
  // invalid entry returns null (the caller keeps the scalar footprint). For polygon, `vertices` is the
  // already-parsed [[x,y],...] (parsePolyVerts does the text parse). Pure.
  function shapeFromForm(kind, vals) {
    kind = String(kind || "").toLowerCase();
    vals = vals || {};
    if (kind === "rectangle") {
      var w = +vals.w, h = +vals.h;
      if (!(w > 0 && h > 0)) return null;
      return { kind: "rectangle", w: w, h: h, theta_deg: +vals.theta_deg || 0 };
    }
    if (kind === "corridor") {
      var L = +vals.length, cw = +vals.width;
      if (!(L > 0 && cw > 0)) return null;
      return { kind: "corridor", length: L, width: cw, theta_deg: +vals.theta_deg || 0 };
    }
    if (kind === "circle") {
      var r = +vals.r;
      if (!(r > 0)) return null;
      return { kind: "circle", r: r };
    }
    if (kind === "polygon") {
      var v = vals.vertices;
      if (!Array.isArray(v) || v.length < 3) return null;
      var s = { kind: "polygon", vertices: v.map(function (p) { return [+p[0], +p[1]]; }) };
      return shapeArea(s) === shapeArea(s) ? s : null;     // reject a degenerate (zero-area) polygon
    }
    return null;                                           // "" / "square" / unknown -> legacy scalar path
  }

  // Parse a polygon-vertices text field "x,y; x,y; x,y" -> [[x,y],...]. Tolerates spaces and trailing
  // separators. Returns [] when fewer than 3 valid vertices. Pure.
  function parsePolyVerts(text) {
    var out = [];
    String(text || "").split(/[;\n]/).forEach(function (tok) {
      var t = tok.trim();
      if (!t) return;
      var xy = t.split(",").map(function (s) { return parseFloat(s.trim()); });
      if (xy.length === 2 && xy[0] === xy[0] && xy[1] === xy[1]) out.push([xy[0], xy[1]]);
    });
    return out.length >= 3 ? out : [];
  }

  // Draw an order's footprint OUTLINE on the 2D plan canvas under the world->canvas transform (X, Y).
  // Uses the real ring (oriented rect / corridor / circle / polygon); a no-shape order falls back to
  // its legacy square ring, so the default render is unchanged. The caller sets fillStyle/strokeStyle
  // before calling (kind colours stay in cockpit.js). Returns true if it drew, false if no geometry.
  function drawFootprint(ctx, order, X, Y) {
    var ring = footprintRingXY(order);
    if (!ring || ring.length < 2) return false;
    ctx.beginPath();
    for (var i = 0; i < ring.length; i++) {
      var px = X(ring[i][0]), py = Y(ring[i][1]);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    return true;
  }

  // The local-frame AABB of an order's footprint (for plan-extent fitting). Mirrors planExtent's
  // sqrt(footprint_m2) square for no-shape orders, but uses the real ring for a typed shape so an
  // oriented road/corridor is framed correctly. Returns {x0,y0,x1,y1}. Pure.
  function footprintBounds(order) {
    var ring = footprintRingXY(order);
    var cx = +order.x || 0, cy = +order.y || 0;
    if (!ring || !ring.length) return { x0: cx, y0: cy, x1: cx, y1: cy };
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    ring.forEach(function (p) {
      if (p[0] < x0) x0 = p[0]; if (p[0] > x1) x1 = p[0];
      if (p[1] < y0) y0 = p[1]; if (p[1] > y1) y1 = p[1];
    });
    return { x0: x0, y0: y0, x1: x1, y1: y1 };
  }

  var API = {
    shapeArea: shapeArea, footprintRingXY: footprintRingXY, hasTypedShape: hasTypedShape,
    shapeFromForm: shapeFromForm, parsePolyVerts: parsePolyVerts, drawFootprint: drawFootprint,
    footprintBounds: footprintBounds,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.STEWIE_FOOTPRINT_GEOM = API;
})(typeof window !== "undefined" ? window : null);
