// frontend-audit C (2026-07-01): PURE formatters for the four ops chips -- the header health chip
// (/healthz dot + uptime), the Live RC link-state chip (SSE lifecycle), the Report provenance stamp
// ("plan forecast · solved HH:MM"), and the compact mission-time chip (elapsed/total of a run's
// forecast timeline). No DOM, no fetch, no globals: cockpit.js resolves the elements + the live
// payloads and passes them in, per the existing window.STEWIE_* module pattern. node:test'able.
(function (root) {
  "use strict";

  function _pad2(n) { return String(n).padStart(2, "0"); }

  // wall-clock HH:MM (local operator time) for a Date.now() timestamp
  function hhmm(ts) {
    const d = new Date(ts);
    return _pad2(d.getHours()) + ":" + _pad2(d.getMinutes());
  }

  // Report dashstrip provenance chip: these numbers are a FORECAST, stamped with when it was solved
  function solvedStamp(ts) { return "plan forecast · solved " + hhmm(ts); }

  // sidebar "Last plan" block: the planned-at wall-clock stamp
  function plannedStamp(ts) { return "planned " + hhmm(ts); }

  // compact h/m duration ("0h00m", "12h04m", long missions collapse to whole hours: "2449h")
  function fmtDur(s) {
    if (!isFinite(s) || s < 0) s = 0;
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h >= 100 ? String(h) + "h" : String(h) + "h" + _pad2(m) + "m";
  }

  // mission-time chip text: elapsed / total of the active (or last-loaded) run
  function missionClock(elapsedS, totalS) {
    return "T+" + fmtDur(elapsedS) + " / " + fmtDur(totalS);
  }

  // compact uptime ("3m", "3h 12m", "2d 5h")
  function fmtUp(s) {
    s = Math.max(0, Math.floor(+s || 0));
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    if (d) return d + "d " + h + "h";
    if (h) return h + "h " + m + "m";
    return m + "m";
  }

  // header health chip view from a /healthz payload (null/undefined = the poll failed -> unreachable).
  // ok = green; degraded (audit or revocation subsystem) = amber; unreachable = red.
  function healthChipView(h) {
    if (!h || !h.status) return { level: "down", color: "#e8273f", text: "● HEALTH UNREACHABLE" };
    if (h.status === "degraded") {
      const what = [];
      if (h.audit && h.audit.degraded) what.push("audit");
      if (h.revocation && h.revocation.degraded) what.push("revocation");
      return { level: "degraded", color: "#e0b300",
               text: "● DEGRADED" + (what.length ? " (" + what.join("+") + ")" : "") + " · up " + fmtUp(h.uptime_s) };
    }
    return { level: "ok", color: "#19c37d", text: "● OK · up " + fmtUp(h.uptime_s) };
  }

  // alert to fire on a health-level TRANSITION (null = no alert: first poll, or no change)
  function healthTransition(prevLevel, nextLevel) {
    if (prevLevel == null || prevLevel === nextLevel) return null;
    if (nextLevel === "degraded") return { sev: "warn", text: "server health DEGRADED — audit/revocation subsystem (System pane → SERVER for detail)" };
    if (nextLevel === "down") return { sev: "error", text: "server health check unreachable — /healthz is not answering" };
    return { sev: "info", text: "server health recovered — /healthz ok" };
  }

  // Live RC link chip from the SSE stream lifecycle. intervalS = the operator-set push interval
  // (seconds per frame -> the advertised rate is its reciprocal).
  function linkChipView(state, intervalS) {
    if (state === "connecting") return { text: "CONNECTING…", color: "#e0b300" };
    if (state === "live") {
      const hz = (+intervalS > 0) ? 1 / +intervalS : 0;
      const hzTxt = (Math.round(hz * 10) / 10) + " Hz";
      return { text: "LIVE " + hzTxt, color: "#19c37d" };
    }
    if (state === "dropped") return { text: "DROPPED · retrying", color: "#e8273f" };
    return { text: "NO LINK", color: "#8a8a93" };            // default: not connected by choice
  }

  var API = { hhmm: hhmm, solvedStamp: solvedStamp, plannedStamp: plannedStamp, fmtDur: fmtDur,
              missionClock: missionClock, fmtUp: fmtUp, healthChipView: healthChipView,
              healthTransition: healthTransition, linkChipView: linkChipView };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_OPS_CHIPS = API;                                       // browser (window)
})(typeof window !== "undefined" ? window : null);
