// TR-02/03/04 Trainer dashboard: PURE renderers for the Trainer pane. No DOM lookups, no network, no
// module globals -- the cockpit's thin wrapper fetches /trainer/history, /session/{id}/divergence, and
// /session/{id}/debrief and passes the payloads in, mirroring the fleet_render.js / models_render.js
// module pattern. CSP-safe (no inline script); node:test'able (esc is injected). Three builders:
//   programBoardHTML(history, esc)            -> TR-03 PROGRAM: leaderboard + session-history table over
//                                                the persisted scorecards (makespan-vs-optimal trend,
//                                                objectives met). Operator+. Honest empty state.
//   truthBoardHTML(history, esc)              -> TR-02 DIRECTOR truth board: believed-vs-true divergence
//                                                (energy + pose mean/max) per recorded session. Truth =
//                                                MAGENTA (MO-04, directors-only); the cockpit only calls
//                                                this when history.is_director is true.
//   debriefScrubberHTML(debrief, idx, esc)    -> TR-04 DEBRIEF scrubber: ONE step of a recorded session,
//                                                showing seen-vs-estimated-vs-truth for that leg. The
//                                                cockpit owns the step index; this renders the frame.
(function (root) {
  "use strict";

  var TRUTH = "#e040fb";   // MO-04: truth is magenta, directors-only

  function _num(v, d) { var n = Number(v); return Number.isFinite(n) ? n : (d === undefined ? 0 : d); }
  function _ratioWarn(r) { return _num(r, 1) > 1.15; }   // a run >15% slower than optimal is flagged

  // ---- TR-03 PROGRAM board: leaderboard + session-history over the persisted scorecards ----------
  function programBoardHTML(history, esc) {
    var sessions = (history && Array.isArray(history.sessions)) ? history.sessions : [];
    if (!sessions.length) {
      return '<div class="empty">No recorded sessions yet. Start a training session (Plan tab → '
        + 'Start session) and open its scorecard; recorded runs appear here as a leaderboard and '
        + 'history.</div>';
    }
    // leaderboard: rank by makespan ratio ASC (closest to optimal first), tie-break objectives DESC.
    var ranked = sessions.slice().sort(function (a, b) {
      var ra = _num(a.makespan && a.makespan.makespan_ratio, 1e9);
      var rb = _num(b.makespan && b.makespan.makespan_ratio, 1e9);
      if (ra !== rb) return ra - rb;
      return _num((b.public || {}).objectives_total) - _num((a.public || {}).objectives_total);
    });
    var medal = ["🥇", "🥈", "🥉"];
    var lbRows = ranked.map(function (s, i) {
      var pub = s.public || {}, mk = s.makespan || {};
      var ratio = _num(mk.makespan_ratio, 1);
      return "<tr>"
        + '<td style="text-align:center">' + (medal[i] || (i + 1)) + "</td>"
        + '<td style="font-weight:600"><code>' + esc(String(s.session_id).slice(0, 8)) + "</code></td>"
        + "<td>" + esc(String(s.profile || "?")) + "</td>"
        + '<td style="text-align:center">' + (pub.completed ? "✓" : "✗") + " "
          + _num(pub.objectives_total) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + _num(mk.makespan_s).toFixed(0) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums'
          + (_ratioWarn(ratio) ? ";color:#e8273f" : "") + '">' + ratio.toFixed(2) + "×</td>"
        + "</tr>";
    });
    // makespan trend (newest-first history order): a downward ratio over time = learning.
    var trend = sessions.map(function (s) {
      return _num(s.makespan && s.makespan.makespan_ratio, 1);
    });
    var trendNote = "";
    if (trend.length >= 2) {
      var newest = trend[0], oldest = trend[trend.length - 1];   // history is newest-first
      var dir = newest < oldest ? "improving (makespan ratio trending down)"
        : newest > oldest ? "regressing (makespan ratio trending up)" : "flat";
      trendNote = '<div style="font-size:11px;color:var(--muted);margin:6px 0 10px">Trend across '
        + trend.length + " recorded runs: <b>" + esc(dir) + "</b> — oldest " + oldest.toFixed(2)
        + "× → newest " + newest.toFixed(2) + "×.</div>";
    }
    var histRows = sessions.map(function (s) {
      var pub = s.public || {}, mk = s.makespan || {};
      return "<tr>"
        + '<td><code>' + esc(String(s.session_id).slice(0, 8)) + "</code></td>"
        + "<td>" + esc(String(s.profile || "?")) + "</td>"
        + "<td>" + esc(String(s.objective || "?")) + "</td>"
        + '<td style="text-align:center">' + (pub.completed ? "✓" : "✗") + " " + _num(pub.objectives_total) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">'
          + _num(pub.legs_delivered) + "/" + _num(pub.legs_total) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">'
          + (_num(pub.comm_delivered_frac) * 100).toFixed(0) + "%</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + _num(mk.makespan_s).toFixed(0) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + _num(mk.makespan_ratio, 1).toFixed(2) + "×</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + _num(pub.energy_MJ).toFixed(2) + "</td>"
        + "</tr>";
    });
    return '<div class="cap" style="margin-bottom:6px"><span>LEADERBOARD — closest-to-optimal first '
      + "(" + sessions.length + " recorded runs)</span></div>"
      + '<table style="width:100%;border-collapse:collapse;font-size:11px;margin-bottom:10px">'
      + '<thead><tr style="text-align:left;color:var(--muted);border-bottom:1px solid var(--line)">'
      + "<th style='text-align:center'>#</th><th>session</th><th>link</th>"
      + "<th style='text-align:center'>objectives</th><th style='text-align:right'>makespan s</th>"
      + "<th style='text-align:right'>makespan/opt</th></tr></thead>"
      + "<tbody>" + lbRows.join("") + "</tbody></table>"
      + trendNote
      + '<div class="cap" style="margin-bottom:6px"><span>SESSION HISTORY — every recorded run '
      + "(newest first)</span></div>"
      + '<table style="width:100%;border-collapse:collapse;font-size:11px">'
      + '<thead><tr style="text-align:left;color:var(--muted);border-bottom:1px solid var(--line)">'
      + "<th>session</th><th>link</th><th>objective</th><th style='text-align:center'>met</th>"
      + "<th style='text-align:right'>legs</th><th style='text-align:right'>comm</th>"
      + "<th style='text-align:right'>makespan s</th><th style='text-align:right'>/opt</th>"
      + "<th style='text-align:right'>energy MJ</th></tr></thead>"
      + "<tbody>" + histRows.join("") + "</tbody></table>";
  }

  // ---- TR-02 DIRECTOR truth board: believed-vs-true divergence per recorded session (MO-04 magenta) -
  function truthBoardHTML(history, esc) {
    if (!history || history.is_director !== true) {
      return '<div class="empty">The truth divergence board is director-only (MO-04).</div>';
    }
    var sessions = (history && Array.isArray(history.sessions)) ? history.sessions : [];
    var withTruth = sessions.filter(function (s) { return s.truth; });
    if (!withTruth.length) {
      return '<div class="empty">No recorded sessions with truth data yet. The believed-vs-true '
        + "divergence (energy + pose) appears here once a session is recorded.</div>";
    }
    var rows = withTruth.map(function (s) {
      var t = s.truth || {};
      var poseMean = _num(t.pose_divergence_mean_m), poseMax = _num(t.pose_divergence_max_m);
      var missed = Array.isArray(t.operator_missed_legs) ? t.operator_missed_legs.length : 0;
      return "<tr>"
        + '<td><code>' + esc(String(s.session_id).slice(0, 8)) + "</code></td>"
        + "<td>" + esc(String(s.profile || "?")) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums;color:' + TRUTH + '">'
          + poseMean.toFixed(2) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums;color:' + TRUTH + '">'
          + poseMax.toFixed(2) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums;color:' + TRUTH + '">'
          + _num(t.energy_divergence_J).toFixed(0) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + missed + "</td>"
        + "</tr>";
    });
    return '<div style="font-size:11px;color:var(--muted);margin-bottom:6px">'
      + '<span style="color:' + TRUTH + '">●</span> Truth fields are <b style="color:' + TRUTH
      + '">magenta</b>, directors-only (MO-04). The believed pose is the dead-reckoned estimate the '
      + "operator sees; the true pose is the conserved-physics ground truth.</div>"
      + '<table style="width:100%;border-collapse:collapse;font-size:11px">'
      + '<thead><tr style="text-align:left;color:var(--muted);border-bottom:1px solid var(--line)">'
      + "<th>session</th><th>link</th><th style='text-align:right'>pose err mean m</th>"
      + "<th style='text-align:right'>pose err max m</th>"
      + "<th style='text-align:right'>energy div J</th><th style='text-align:right'>legs operator missed</th>"
      + "</tr></thead><tbody>" + rows.join("") + "</tbody></table>";
  }

  // ---- TR-04 DEBRIEF scrubber: ONE step of a recorded session (seen vs estimated vs truth) ----------
  // `debrief` is the /session/{id}/debrief payload (director-gated: carries the full per-leg track incl.
  // true_J / slope / slip). `idx` is the leg index the cockpit's scrubber slider points at. The cockpit
  // hides this whole board for non-directors (the debrief route is director-only on the server).
  function debriefScrubberHTML(debrief, idx, esc) {
    var legs = (debrief && Array.isArray(debrief.legs)) ? debrief.legs : [];
    if (!legs.length) {
      return '<div class="empty">No recorded run loaded. Pick a session in the history table above '
        + "(or start one), then step through its legs here.</div>";
    }
    var i = Math.max(0, Math.min(legs.length - 1, _num(idx, 0) | 0));
    var leg = legs[i];
    var missed = Array.isArray(debrief.operator_missed_legs) ? debrief.operator_missed_legs : [];
    var seenThisLeg = missed.indexOf(leg.leg) < 0;        // did the operator's link deliver this leg?
    var bx = _num(leg.bx), by = _num(leg.by), tx = _num(leg.tx), ty = _num(leg.ty);
    var poseErr = Math.hypot(bx - tx, by - ty);
    var cell = function (label, val, color) {
      return '<div style="border:1px solid var(--line);border-radius:6px;padding:5px 9px;min-width:120px">'
        + '<div style="font-size:9px;color:var(--muted);letter-spacing:.06em">' + esc(label) + "</div>"
        + '<div style="font-size:13px;font-variant-numeric:tabular-nums'
        + (color ? ";color:" + color : "") + '">' + esc(String(val)) + "</div></div>";
    };
    var seenChip = seenThisLeg
      ? '<span style="color:#4caf72">delivered to operator</span>'
      : '<span style="color:#e8273f">DROPPED (operator never saw this leg)</span>';
    return '<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:8px;font-size:12px">'
      + "<b>leg " + (i + 1) + " / " + legs.length + "</b>"
      + "<span><b>" + esc(String(leg.leg)) + "</b></span>"
      + "<span>" + seenChip + "</span></div>"
      + '<div style="display:flex;gap:8px;flex-wrap:wrap">'
      // SEEN (what the operator's link delivered) -- white/observed
      + cell("SEEN (operator)", seenThisLeg ? ("(" + bx.toFixed(1) + ", " + by.toFixed(1) + ")") : "—")
      // ESTIMATED (the believed/dead-reckoned pose) -- forecast cyan
      + cell("ESTIMATED pose", "(" + bx.toFixed(1) + ", " + by.toFixed(1) + ")", "#37d0ff")
      // TRUTH (the conserved-physics ground truth) -- magenta, directors-only
      + cell("TRUTH pose", "(" + tx.toFixed(1) + ", " + ty.toFixed(1) + ")", TRUTH)
      + cell("pose error m", poseErr.toFixed(2), poseErr > 1 ? "#e8273f" : undefined)
      + cell("SoC", _num(leg.soc).toFixed(2))
      + cell("slip", _num(leg.slip).toFixed(3), TRUTH)
      + cell("slope°", _num(leg.slope_deg).toFixed(1), TRUTH)
      + cell("true J", _num(leg.true_J).toFixed(0), TRUTH)
      + cell("nominal J", _num(leg.nominal_J).toFixed(0))
      + "</div>";
  }

  var API = { programBoardHTML: programBoardHTML, truthBoardHTML: truthBoardHTML,
              debriefScrubberHTML: debriefScrubberHTML, TRUTH: TRUTH };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_TRAINER_BOARDS = API;                                  // browser (window)
})(typeof window !== "undefined" ? window : null);
