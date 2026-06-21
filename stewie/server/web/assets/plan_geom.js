// FS-24: the Plan-pane (2D plancanvas) AUTHORING GEOMETRY + GLYPH helpers. PURE functions only --
// the world<->canvas extent/transform math, the branded feature glyphs, and the precedence-text
// parser. No DOM lookups and no module-level globals: cockpit.js resolves ORDERS / KEEPOUTS /
// _placeXY / koBounds / the #qprec value and passes them in via thin binding aliases, exactly the
// existing window.STEWIE_* module pattern (the navplot.js / panel_layout.js precedent). Extracted
// verbatim from cockpit.js (PRD FS-24); behaviour is preserved exactly -- drawGlyph and planXform are
// byte-for-byte the inline bodies, planExtent/parsePrec are the same logic with the globals/DOM read
// hoisted to parameters. node:test'able (a stub 2D context records the calls).
(function (root) {
  "use strict";

  // The plan-canvas world extent: a padded AABB over the charger (0,0), every order's footprint
  // square, every keep-out's bounds, and the click-to-place marker. `koBounds(k)` returns a keep-out's
  // local-frame AABB (any shape). Degenerate spans get a 10 m fallback. Pure.
  function planExtent(orders, keepouts, placeXY, koBounds, footprintBounds) {
    const xs = [0], ys = [0];                                // include the charger at (0,0)
    // GIS S-3: frame each order by its REAL footprint AABB when a bounds fn is supplied (an oriented
    // corridor/rect/polygon), else the legacy sqrt(footprint_m2) square -- behaviour-preserving.
    orders.forEach((o) => {
      if (footprintBounds) { const b = footprintBounds(o); xs.push(b.x0, b.x1); ys.push(b.y0, b.y1); return; }
      const h = Math.sqrt(o.footprint_m2) / 2; xs.push(o.x - h, o.x + h); ys.push(o.y - h, o.y + h);
    });
    keepouts.forEach((k) => { const b = koBounds(k); xs.push(b.x0, b.x1); ys.push(b.y0, b.y1); });
    if (placeXY) { xs.push(placeXY.x); ys.push(placeXY.y); }
    let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    if (x1 - x0 < 1) { x0 -= 10; x1 += 10; } if (y1 - y0 < 1) { y0 -= 10; y1 += 10; }
    const px = Math.max(5, (x1 - x0) * 0.15), py = Math.max(5, (y1 - y0) * 0.15);
    return { x0: x0 - px, x1: x1 + px, y0: y0 - py, y1: y1 + py };
  }

  // The fit transform: a uniform-scale, centred world->canvas projection for the given extent. Returns
  // {s, ox, oy, X, Y} (canvas Y is flipped so site +y is up). Pure.
  function planXform(cv, ext) {
    const W = cv.width, H = cv.height;
    const s = Math.min(W / (ext.x1 - ext.x0), H / (ext.y1 - ext.y0));
    const ox = (W - s * (ext.x1 - ext.x0)) / 2, oy = (H - s * (ext.y1 - ext.y0)) / 2;
    return { s, ox, oy, X: (wx) => ox + (wx - ext.x0) * s, Y: (wy) => H - (oy + (wy - ext.y0) * s) };
  }

  // #178: draw a keep-out on the 2D plan (poly/rect/disc) under the given world->canvas transform.
  // The shape predicates/bounds (koIsPoly/koIsRect/koBounds) live in keepout_geom.js; the cockpit
  // passes them in. Pure (the caller sets fill/stroke style before calling).
  function fillKeepout(ctx, k, X, Y, s, koIsPoly, koIsRect, koBounds) {
    if (koIsPoly(k)) {
      ctx.beginPath();
      k.points.forEach((p, i) => { const px = X(p[0]), py = Y(p[1]); if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py); });
      ctx.closePath(); ctx.fill(); ctx.stroke();
    } else if (koIsRect(k)) {
      const b = koBounds(k), x0 = X(b.x0), y0 = Y(b.y1), x1 = X(b.x1), y1 = Y(b.y0);   // site Y up, canvas Y down
      ctx.fillRect(x0, y0, x1 - x0, y1 - y0); ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    } else {
      ctx.beginPath(); ctx.arc(X(k.x), Y(k.y), Math.max(2, k.r * s), 0, 7); ctx.fill(); ctx.stroke();
    }
  }

  // #29: the branded feature glyphs -- ONE drawing function so map, queue, and legend agree.
  function drawGlyph(ctx, kind, x, y, r) {
    r = r || 5;
    ctx.save();
    if (kind === "cut") {                                    // drum-down chevron (excavate)
      ctx.strokeStyle = "#4f9cff"; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.moveTo(x - r, y - r * 0.5); ctx.lineTo(x, y + r * 0.7);
      ctx.lineTo(x + r, y - r * 0.5); ctx.stroke();
    } else if (kind === "fill") {                            // berm mound
      ctx.strokeStyle = "#e07b39"; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.arc(x, y + r * 0.4, r, Math.PI, 0); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x - r, y + r * 0.4); ctx.lineTo(x + r, y + r * 0.4); ctx.stroke();
    } else if (kind === "goto") {                            // waypoint node
      ctx.fillStyle = "#e8273f"; ctx.beginPath(); ctx.arc(x, y, r * 0.8, 0, 7); ctx.fill();
    } else if (kind === "keepout") {                         // exclusion ring
      ctx.strokeStyle = "#e8273f"; ctx.lineWidth = 1.6; ctx.setLineDash([3, 2]);
      ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.stroke(); ctx.setLineDash([]);
    } else if (kind === "charger") {                         // power bolt (square + tick)
      ctx.fillStyle = "#3fa34d"; ctx.fillRect(x - r * 0.6, y - r * 0.6, r * 1.2, r * 1.2);
      ctx.strokeStyle = "#0a0a0c"; ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.moveTo(x + r * 0.3, y - r * 0.5); ctx.lineTo(x - r * 0.2, y + r * 0.1);
      ctx.lineTo(x + r * 0.2, y + r * 0.1); ctx.lineTo(x - r * 0.3, y + r * 0.6); ctx.stroke();
    }
    ctx.restore();
  }

  // precedence text "Grade road > Build berm, Dig pit > Fill" -> [[before, after], ...] (I9). Pure;
  // the cockpit reads the #qprec field value and passes it in.
  function parsePrec(text) {
    return (text || "").split(",").map(s => s.trim()).filter(Boolean)
      .map(s => s.split(">").map(x => x.trim())).filter(p => p.length === 2 && p[0] && p[1]);
  }

  var API = { planExtent: planExtent, planXform: planXform, fillKeepout: fillKeepout,
              drawGlyph: drawGlyph, parsePrec: parsePrec };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.STEWIE_PLAN_GEOM = API;
})(typeof window !== "undefined" ? window : null);
