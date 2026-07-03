// [REQ:FS-28] the command-authority EVIDENCE card (Execute pane) -- a PURE function that turns the
// RS-01 CommandEligibility verdict (GET /rc/eligibility) into the innerHTML string. No DOM, no fetch,
// no globals: cockpit.js rcEligibility() fetches the verdict, calls this, and writes it into
// $("rceligibility"). Extracted verbatim from cockpit.js (behaviour preserved) per the window.STEWIE_*
// module pattern; esc() is injected so the same SEC-04 HTML-escaping (htmlesc.js) hardens the sink.
// node:test'able. Renders each named command-authority gate pass/fail BEFORE a command is sent, and on
// an ineligible verdict shows the LEGIBLE refusal reason rather than only surfacing it on a refusal.
(function (root) {
  "use strict";

  function commandAuthorityHTML(d, esc) {
    d = d || {};
    // the command-authority gates (role/released/SAFE/link/watchdog); perception-freshness fields are
    // FS-27/PM-17, not shown here.
    var gates = [["role", d.mode_ok], ["released", d.released], ["SAFE-clear", d.safe_inactive],
                 ["link", d.link_ack], ["watchdog", d.watchdog_alive]];
    var chips = gates.map(function (g) {
      var ok = g[1];
      return '<span style="color:' + (ok ? "var(--accent)" : "var(--muted)") + '">'
        + (ok ? "✓" : "✗") + " " + esc(g[0]) + "</span>";
    }).join(" · ");
    var head = d.eligible
      ? '<b style="color:var(--accent)">ELIGIBLE</b>'
      : '<b style="color:var(--muted)">INELIGIBLE</b> <span style="color:var(--muted)">('
        + esc(String(d.reason)) + ")</span>";
    return '<span title="RS-01 CommandEligibility contract">command authority: ' + head
      + "</span> — " + chips;
  }

  // [REQ:FS-28] the Release-pane FROZEN command-authority card: a released revision displays every
  // authority field -- the immutable plan hash, director sign-off, runtime + sensor profile, deployment
  // namespace, AG-08 authorization, and the SF-01 watchdog deadline. "" when nothing has been released.
  function releaseAuthorityHTML(ca, esc) {
    if (!ca) return "";
    return '<div style="margin-top:8px;color:var(--muted)">command authority — '
      + "plan <code>" + esc(String(ca.plan_hash).slice(0, 16)) + "…</code>"
      + " · signed by " + esc(ca.signed_by)
      + " · runtime <code>" + esc(ca.runtime_profile) + "</code>"
      + " · namespace <code>" + esc(ca.namespace) + "</code>"
      + " · sensor <code>" + esc(ca.sensor_profile) + "</code>"
      + " · AG-08 " + (ca.authorized ? "authorized ✓" : "—")
      + " · SF-01 watchdog " + esc(String(ca.watchdog_deadline_s)) + "s</div>";
  }

  var API = { commandAuthorityHTML: commandAuthorityHTML, releaseAuthorityHTML: releaseAuthorityHTML };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_COMMAND_AUTHORITY = API;                               // browser (window)
})(typeof window !== "undefined" ? window : null);
