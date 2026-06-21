// REHEARSE (mission-ops screen 2: "Rehearse and compare") -- PURE renderer for the candidate-plan
// cards. No DOM lookups, no network, no module globals: the cockpit's thin wrapper POSTs the current
// mission to /resync/compare (lode.resync.forward_compare, director-gated) and passes the response in,
// mirroring the existing window.STEWIE_* render pattern (fleet_render.js / construction_render.js).
//
//   rehearseCardsHTML(compare, esc) -> the side-by-side candidate cards from the REAL forward-compare
//                                      ensemble, FEASIBILITY-FIRST, with an honest empty state.
//
// INVARIANT (review §"Rehearse and compare"): never render an infeasible candidate above a feasible one.
// The route already returns futures[] feasible-first ordered; this renderer PRESERVES that order and
// never re-sorts on a weighted score. node:test'able (esc is injected); CSP-safe (no inline handlers).
(function (root) {
  "use strict";

  function _hours(s) { return (Number(s || 0) / 3600).toFixed(2); }
  function _mj(j) { return (Number(j || 0) / 1e6).toFixed(2); }

  // a labelled metric line inside a card.
  function _metric(label, value, esc, opts) {
    var o = opts || {};
    var color = o.color ? ';color:' + o.color : '';
    return '<div style="display:flex;justify-content:space-between;gap:8px;font-size:11px;padding:2px 0">'
      + '<span style="color:var(--muted)">' + esc(label) + '</span>'
      + '<b style="font-variant-numeric:tabular-nums' + color + '">' + esc(value) + '</b></div>';
  }

  function _card(f, esc, recommended) {
    var feasible = !!f.feasible;
    // color rules (review): green = verified within limits; red = violated limit/infeasible.
    var GREEN = "#4caf72", RED = "#e8273f", AMBER = "#e07b39";
    var badge = feasible
      ? '<span style="background:' + GREEN + ';color:#04140b;font-weight:700;font-size:10px;'
        + 'padding:2px 8px;border-radius:8px;letter-spacing:.06em">FEASIBLE</span>'
      : '<span style="background:' + RED + ';color:#fff;font-weight:700;font-size:10px;'
        + 'padding:2px 8px;border-radius:8px;letter-spacing:.06em">INFEASIBLE</span>';
    var rec = (recommended != null && f.algorithm === recommended && feasible)
      ? ' <span style="border:1px solid ' + GREEN + ';color:' + GREEN + ';font-size:9px;'
        + 'padding:2px 6px;border-radius:8px;letter-spacing:.06em">RECOMMENDED</span>' : "";

    var rtl = f.return_to_lander || {};
    var rtlFeasible = !!rtl.feasible;
    var rtlMarginMJ = typeof rtl.margin_J === "number" ? _mj(rtl.margin_J) + " MJ" : "—";
    var rtlColor = rtlFeasible ? GREEN : RED;

    // objective completion: orders the plan resolved minus any blocked legs.
    var total = Number(f.objectives_total || 0);
    var blocked = Number(f.blocked_legs || 0);
    var completed = Math.max(0, total - blocked);
    var compColor = blocked > 0 ? AMBER : (total > 0 ? GREEN : "var(--muted)");

    var opt = f.objective_exact ? esc(f.optimality || "") + " (exact for objective)"
      : esc(f.optimality || "heuristic") + " (no optimality bound)";

    // FEASIBILITY FIRST, then minimum margins, completion, duration, energy, charge cycles, optimality.
    var body = badge + rec
      + '<div style="font-weight:700;font-size:13px;margin:6px 0 2px">' + esc(f.algorithm)
      + (f.resolved && f.resolved !== f.algorithm
          ? ' <span style="opacity:.6;font-size:10px;font-weight:400">→ ' + esc(f.resolved) + "</span>" : "")
      + "</div>"
      + _metric("return-to-lander", (rtlFeasible ? "OK · " : "VIOLATED · ") + rtlMarginMJ + " margin",
                esc, { color: rtlColor })
      + _metric("objectives", completed + "/" + total, esc, { color: compColor })
      + _metric("duration", _hours(f.time_s) + " h", esc)
      + _metric("energy", Number(f.energy_MJ || 0).toFixed(2) + " MJ", esc)
      + _metric("charge cycles", String(f.charges != null ? f.charges : (f.recharges || 0)), esc)
      + _metric("optimality", opt, esc)
      + _metric("rehearsal wall", _secsLabel(f.wall_s), esc);

    if (!feasible) {
      var reasons = Array.isArray(f.infeasible_reasons) ? f.infeasible_reasons : [];
      var reasonHTML = reasons.length
        ? reasons.map(function (r) { return "<li>" + esc(r) + "</li>"; }).join("")
        : "<li>" + esc("planner returned infeasible (no detailed reason)") + "</li>";
      body += '<div style="margin-top:6px;font-size:10px;color:' + RED + '">'
        + '<div style="font-weight:600">infeasible because:</div>'
        + '<ul style="margin:2px 0 0 14px;padding:0">' + reasonHTML + "</ul></div>";
    }

    var border = feasible ? "var(--line)" : RED;
    return '<div style="border:1px solid ' + border + ';border-radius:10px;padding:10px 12px;'
      + 'min-width:220px;flex:1 1 220px;background:rgba(255,255,255,.02)">' + body + "</div>";
  }

  function _secsLabel(s) {
    var v = Number(s || 0);
    return (v < 1 ? (v * 1000).toFixed(0) + " ms" : v.toFixed(2) + " s");
  }

  // the side-by-side candidate cards from /resync/compare. `compare` is the route payload
  // ({ok, objective, recommended, futures:[...]}); futures arrive feasible-first ordered.
  function rehearseCardsHTML(compare, esc) {
    var c = compare || {};
    var futures = Array.isArray(c.futures) ? c.futures : [];
    if (!futures.length) {
      return '<div class="empty">No candidates to rehearse yet. Add at least one order (Plan tab), '
        + "then run the forward-compare; the re-simulated candidate futures from the conserved "
        + "planner appear here side-by-side, feasibility first.</div>";
    }
    var anyFeasible = futures.some(function (f) { return !!f.feasible; });
    var banner = anyFeasible
      ? '<div style="font-size:11px;color:var(--muted);margin-bottom:8px">Objective <b>'
        + esc(c.objective || "duration") + "</b> · " + esc(futures.length)
        + " candidate(s) re-simulated faster-than-realtime · ranked <b>feasibility first</b>"
        + (c.recommended != null
            ? ' · recommended <b style="color:#4caf72">' + esc(c.recommended) + "</b>" : "")
        + "</div>"
      : '<div style="font-size:11px;color:#e8273f;font-weight:600;margin-bottom:8px">'
        + "No feasible candidate. Every re-simulated future violates a route or battery limit "
        + "(no plan is recommended). Adjust the orders, charger, or reserve and rehearse again.</div>";
    var cards = futures.map(function (f) { return _card(f, esc, c.recommended); }).join("");
    return banner
      + '<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:stretch">' + cards + "</div>";
  }

  var API = { rehearseCardsHTML: rehearseCardsHTML };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_REHEARSE_RENDER = API;                                 // browser (window)
})(typeof window !== "undefined" ? window : null);
