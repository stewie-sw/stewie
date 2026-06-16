// Phase 2 / FS-15: typed frontend CONTRACT ADAPTERS. Pure functions that map a backend spine-contract
// payload -> a normalized VIEW MODEL the cockpit panes render, a fetch-outcome -> a {state} the UI shows
// (loading/ok/empty/error), and a work-area -> the minimum role its command affordances need (mirroring
// the AG-01 ladder). UI components consume these view models, NEVER raw backend JSON (FS-15). No DOM, no
// network here -> unit-testable with node:test; the cockpit wires fetch + render on top.
(function (root) {
  "use strict";

  // ---- the role ladder, mirrored from the backend (AG-01) for permission mapping ----
  var ROLE_LADDER = ["guest", "trainee", "operator", "director"];
  function roleRank(role) { return ROLE_LADDER.indexOf(role); }   // -1 for unknown = fail closed

  // which role a work area's COMMAND affordances require (reads stay open to guest+)
  var WORK_AREA_MIN_ROLE = {
    plan: "guest", navigation: "guest", perception: "guest", metrics: "guest", report: "guest",
    fleet: "operator", command: "operator", admin: "director",
  };
  function canAct(workArea, role) {
    var need = WORK_AREA_MIN_ROLE[workArea] || "operator";
    return roleRank(role) >= roleRank(need);
  }

  // ---- normalizers: spine-contract payload -> view model (with a couple of derived fields) ----
  function normalizeEphemeris(payload) {
    var e = payload && payload.ephemeris;
    if (!e) return null;
    return {
      missionTimeS: e.mission_t_s,
      site: { latDeg: e.site_lat_deg, lonDeg: e.site_lon_deg, frame: e.frame },
      sun: { azDeg: e.sun_az_deg, elDeg: e.sun_el_deg, convention: e.azimuth_convention },
      uncertaintyDeg: e.uncertainty_deg, source: e.source,
      lit: e.sun_el_deg > 0,                                // derived: is the site sunlit now?
    };
  }

  function normalizeWorld(payload) {
    var w = payload && payload.world;
    if (!w) return null;
    return {
      body: w.body, frame: w.frame,
      grid: { rows: w.rows, cols: w.cols, cellM: w.cell_m },
      datumRadiusM: w.datum_radius_m, demSource: w.dem_source,
      observedFraction: w.observed_fraction, mutated: w.mutated,
      extentM: { x: w.cols * w.cell_m, y: w.rows * w.cell_m }, // derived metric span
    };
  }

  // ---- fetch-outcome -> view STATE the UI renders (FS-15 loading/error/empty mapping) ----
  function toViewState(o) {
    if (o.status === "pending") return { state: "loading", data: null };
    var bad = (typeof o.status === "number" && o.status >= 400) || !o.json || o.json.ok === false;
    if (bad) return { state: "error", error: (o.json && o.json.error) || ("HTTP " + o.status), data: null };
    var vm = o.normalize(o.json);
    return vm ? { state: "ok", data: vm } : { state: "empty", data: null };
  }

  var API = {
    ROLE_LADDER: ROLE_LADDER, roleRank: roleRank, canAct: canAct,
    WORK_AREA_MIN_ROLE: WORK_AREA_MIN_ROLE,
    normalizeEphemeris: normalizeEphemeris, normalizeWorld: normalizeWorld,
    toViewState: toViewState,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_ADAPTERS = API;                                        // browser (window)
})(typeof window !== "undefined" ? window : null);
