// GW-11 — pure helpers for the MissionTerrain3D panel (the full-resolution 3D terrain view INSIDE the QWC2
// lunar IDE, synced to the 2D map's active site). The analysis-drape list + the WS site-sync decision + the
// hover coordinate-readout formatting. No DOM / React / Three here -> node-testable. UMD (browser <script> +
// node --test), matching workspace.js / reqGuard.js / crossSection.js.
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { root.STEWIETerrain3D = factory(); }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // The analysis rasters STEWIE_VIZ.setLayer(kind) can drape over the relief. Ids are exactly the backend
  // /dem/heightfield_full/layer.png?kind= values (the same set the standalone viz page offers); the labels are
  // the panel selector text. "elevation" is the height-ramp vertex colouring (no raster fetch); the rest fetch
  // a layer.png registered cell-for-cell over the SAME window as the heightfield.
  var DRAPE_KINDS = [
    { id: "elevation", label: "Elevation (height ramp)" },
    { id: "dem", label: "Hillshade (sun 315/45)" },
    { id: "slope", label: "Slope (deg)" },
    { id: "aspect", label: "Aspect (gradient azimuth)" },
    { id: "curvature", label: "Curvature (Laplacian)" },
    { id: "roughness", label: "Roughness (RMS slope)" },
    { id: "hazard", label: "Hazard / no-go" },
    { id: "illumination", label: "Shadow (sun horizon)" },
    { id: "psr", label: "PSR (never lit)" },
    { id: "cost", label: "Traversability cost" }
  ];

  function isKnownDrape(id) {
    for (var i = 0; i < DRAPE_KINDS.length; i++) { if (DRAPE_KINDS[i].id === id) { return true; } }
    return false;
  }

  // The GW-11 site-sync decision. Reload the 3D view IFF the workspace's active site is a non-empty string that
  // differs from the one currently shown. This guards the WS.subscribe callback so an unrelated workspace change
  // (body / profile / source) or a redundant same-site emit never thrashes a full-resolution reload.
  function shouldReload(loadedSite, wsSite) {
    return typeof wsSite === "string" && wsSite.length > 0 && wsSite !== loadedSite;
  }

  function fmt(v, d) {
    if (v == null || (typeof v === "number" && isNaN(v))) { return "—"; }   // em dash for missing
    return (+v).toFixed(d == null ? 1 : d);
  }

  // Format a STEWIE_VIZ.onHover payload ({e_m,n_m,elev_m,lat,lon}) into the panel's coordinate-readout strings
  // (order-frame E/N metres + absolute elevation + selenographic lon/lat), matching the standalone viz page's
  // HUD. A null payload (the pointer left the relief) -> null so the panel can dim the readout. lon/lat arrive
  // a beat later than E/N (debounced /dem/site_lonlat lookup), so a payload without them renders "lat — lon —".
  function formatHover(h) {
    if (!h) { return null; }
    var hasLL = h.lat != null && h.lon != null && !isNaN(+h.lat) && !isNaN(+h.lon);
    return {
      en: "E " + fmt(h.e_m, 1) + " m N " + fmt(h.n_m, 1) + " m",
      elev: "elev " + fmt(h.elev_m, 1) + " m",
      lonlat: hasLL ? ("lat " + fmt(h.lat, 5) + "° lon " + fmt(h.lon, 5) + "°")
        : "lat — lon —"
    };
  }

  // F29 — the "send measured route to plan" decision. A 3D measure point only carries lon/lat once its async
  // /dem/site_lonlat lookup resolves; a point without lon/lat cannot reproject into the planner's order frame.
  // The old _sendRoute SILENTLY filtered those out and emitted the survivors, so a route with an unresolved
  // INTERIOR waypoint cut a straight leg PAST the dropped point while the confirmation still said "Sent N".
  // This refuses to send when ANY point is still unresolved (reporting the count) rather than thinning the
  // route; only a fully-resolved route of >=2 points emits. Pure/node-tested -> the controller just applies the
  // decision. Returns { emit:boolean, points:Array, unresolved:number, msg:string }.
  function routeSendDecision(points) {
    var pts = Array.isArray(points) ? points : [];
    var usable = [];
    for (var i = 0; i < pts.length; i++) {
      var q = pts[i];
      if (q && q.lat != null && q.lon != null) { usable.push(q); }
    }
    var unresolved = pts.length - usable.length;
    if (unresolved > 0) {
      return {
        emit: false, points: [], unresolved: unresolved,
        msg: unresolved + " waypoint" + (unresolved === 1 ? "" : "s") +
          " unresolved — none sent (sending would skip an interior point). Wait for the lon/lat readout, then resend."
      };
    }
    if (usable.length >= 2) {
      return { emit: true, points: usable, unresolved: 0, msg: "Sent " + usable.length + " waypoints to plan." };
    }
    return {
      emit: false, points: [], unresolved: 0,
      msg: "Need at least 2 waypoints with resolved lon/lat — measure a bit more."
    };
  }

  return {
    DRAPE_KINDS: DRAPE_KINDS, isKnownDrape: isKnownDrape, shouldReload: shouldReload,
    fmt: fmt, formatHover: formatHover, routeSendDecision: routeSendDecision
  };
});
