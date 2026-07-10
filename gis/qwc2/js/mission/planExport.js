// [REQ:GI-03] surface the backend /export/geojson (GI-03 'offline mission-package export') in the /ide:
// build the download URL from the current authored+planned mission (the EXACT object planAuthor POSTs to
// /api/plan — body:'moon', site, orders, keepouts, algorithm, objective, max_traverse_slope_deg, lat, lon).
// /export/geojson runs the planner on that mission server-side and serializes the build orders + keep-outs +
// routed traverse + typed footprints to RFC-7946 GeoJSON in selenographic lon/lat (the real interchange a
// GIS consumer — QGIS/ArcGIS — loads). The route is require_auth-gated; the artemis edge injects the shared
// key for /api/export/geojson exactly like /api/plan (server-side; the browser never sees it). Pure logic
// (no DOM/fetch) so it is node-testable; the controller does the fetch+blob download.
(function (root) {
  "use strict";

  // buildExportUrl(mission) -> { ok, url, filename } | { ok:false, error }. `mission` is the /api/plan payload
  // (planAuthor._lastPlanPayload). A mission with no orders cannot be exported (nothing planned yet); a
  // non-moon mission has no georeferenced lunar DEM so the backend would 400 -> refuse here with a legible
  // reason rather than build a URL that fails.
  function buildExportUrl(mission) {
    if (!mission || typeof mission !== "object") { return { ok: false, error: "no mission to export" }; }
    if (!Array.isArray(mission.orders) || mission.orders.length === 0) {
      return { ok: false, error: "plan a mission first — there are no orders to export" };
    }
    if (mission.body && mission.body !== "moon") {
      return { ok: false, error: "GeoJSON export needs a georeferenced lunar (moon) mission; got " + mission.body };
    }
    var q = [];
    // the mission body itself (orders + keep-outs the backend planner consumes) — URL-encoded JSON.
    q.push("mission=" + encodeURIComponent(JSON.stringify(mission)));
    // the /export/geojson query levers, mirrored from the mission so the export matches what was planned.
    q.push("site=" + encodeURIComponent(mission.site || "haworth"));
    if (mission.algorithm) { q.push("algorithm=" + encodeURIComponent(mission.algorithm)); }
    if (mission.objective) { q.push("objective=" + encodeURIComponent(mission.objective)); }
    if (isFinite(+mission.max_traverse_slope_deg)) {
      q.push("max_traverse_slope_deg=" + (+mission.max_traverse_slope_deg));
    }
    // the M11 anchor (order-frame origin) so the server reprojects to the same lon/lat the plan used.
    if (isFinite(+mission.lat) && isFinite(+mission.lon)) {
      q.push("lat=" + (+mission.lat));
      q.push("lon=" + (+mission.lon));
    }
    return {
      ok: true,
      url: "/api/export/geojson?" + q.join("&"),
      filename: (mission.site || "mission") + "_plan.geojson",
    };
  }

  var API = { buildExportUrl: buildExportUrl };
  if (typeof module !== "undefined" && module.exports) { module.exports = API; }   // node:test + `import X from`
  if (root) { root.STEWIE_PLAN_EXPORT = API; }                                     // browser (window)
})(typeof window !== "undefined" ? window : null);
