// #133: idle auto-logout. PURE state machine only -- the DOM activity listeners and the actual
// /auth/logout call live in cockpit.js (wireIdleLogout). A signed-in cockpit left unattended is a
// standing-authority risk (it can command a live rover), so after a window of no user activity the
// monitor fires onIdle, which signs the operator out and re-raises the blocking sign-in gate.
//
// Design: a timestamp + a periodic check, NOT a single re-armed setTimeout. Browsers throttle (and
// laptops suspend) background timers, so a lone timeout fires unpredictably late; comparing now() to
// the last-activity timestamp on each tick means a tab that was hidden or a machine that slept past the
// window logs out on the very next tick after it wakes. The decision is the pure isExpired predicate.
//
// This is a client-side control: it depends on the page's JS running. It composes with the server-side
// guarantees that DO hold regardless (the absolute TOKEN_TTL_S cap + jti revocation on logout). A
// server-enforced sliding/idle session is the stronger defence-in-depth follow-up (task #158-adjacent).
(function (root) {
  "use strict";
  var DEFAULT_MIN = 30;             // default idle window if none/garbage is configured
  var MIN_MIN = 1, MAX_MIN = 240;   // floor (never "instant logout") + ceiling (4 h)

  // Coerce a configured minutes value to a sane integer; junk/<=0 -> the default, then clamp + round.
  function clampMinutes(m) {
    m = Number(m);
    if (!isFinite(m) || m <= 0) return DEFAULT_MIN;
    return Math.max(MIN_MIN, Math.min(MAX_MIN, Math.round(m)));
  }

  // Pure: has the idle window elapsed since the last activity? (>= so the boundary counts as expired.)
  function isExpired(lastActivityMs, idleMs, nowMs) {
    return (nowMs - lastActivityMs) >= idleMs;
  }

  // Idle monitor. opts.now / setInterval / clearInterval are injected so the whole thing is
  // deterministic under test; cockpit.js passes the real window functions. onIdle fires AT MOST once
  // per start() (a fired monitor stops itself); start() again to re-arm after a fresh sign-in.
  function IdleMonitor(opts) {
    opts = opts || {};
    var idleMs = clampMinutes(opts.idleMinutes) * 60000;
    var checkMs = (opts.checkMs != null) ? opts.checkMs : 20000;   // how often to test the window
    var onIdle = opts.onIdle || function () {};
    var now = opts.now || function () { return Date.now(); };
    var setIv = opts.setInterval, clearIv = opts.clearInterval;
    var last = 0, iv = null, running = false;

    function tick() {
      if (!running) return;
      if (isExpired(last, idleMs, now())) {
        running = false;
        if (iv != null) { clearIv(iv); iv = null; }
        onIdle();
      }
    }
    function start() {
      running = true; last = now();
      if (iv == null) iv = setIv(tick, checkMs);
    }
    function stop() {
      running = false;
      if (iv != null) { clearIv(iv); iv = null; }
    }
    function touch() { if (running) last = now(); }   // record activity (cheap; no re-arm needed)
    function setIdleMinutes(m) { idleMs = clampMinutes(m) * 60000; if (running) last = now(); }   // live reconfigure (Settings)

    return {
      start: start, stop: stop, touch: touch, tick: tick, setIdleMinutes: setIdleMinutes,
      isRunning: function () { return running; },
      idleMs: function () { return idleMs; },
      remainingMs: function () { return Math.max(0, idleMs - (now() - last)); },
    };
  }

  var API = { IdleMonitor: IdleMonitor, clampMinutes: clampMinutes, isExpired: isExpired,
              DEFAULT_MIN: DEFAULT_MIN, MIN_MIN: MIN_MIN, MAX_MIN: MAX_MIN };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.STEWIE_IDLE = API;
})(typeof window !== "undefined" ? window : null);
