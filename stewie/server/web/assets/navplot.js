// FS-24: the Navigation-pane CANVAS PLOTTERS -- pure top-down 2D drawings of the SLAM/drive
// estimator surfaces. Each takes the target <canvas> element + the server payload and paints it; no
// globals, no DOM lookups (the cockpit's nav* handlers resolve $("navplot") etc. and pass the canvas
// in via thin binding aliases, per the existing window.STEWIE_* module pattern). Extracted verbatim
// from cockpit.js (PRD FS-24); behaviour is preserved exactly. The auto-scale/projection is the same
// pad+min-fit transform every nav plot used inline, hoisted to _fit() so the four plots share it.
// node:test'able (a stub 2D context records the calls).
(function (root) {
  "use strict";

  // shared auto-fit: world bounds over `pts` -> a canvas transform {X, Y} CENTERED on the data
  // bounding box with ~10% padding. 2026-07-01 frontend-audit "live-data plots don't scale": the old
  // transform anchored the min corner at pad with a 1e-6 minSpan, so a degenerate/near-degenerate
  // traverse rendered as one dot pinned bottom-left. The default minimum world span is now 10 m
  // (site-frame plots: drawTrajectory/drawDrive/drawReal); drawFix keeps its tight 0.5 m DEM rig.
  function _fit(cv, pts, pad, minSpan) {
    pad = pad == null ? 26 : pad; minSpan = minSpan == null ? 10 : minSpan;
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const minx = Math.min(...xs), maxx = Math.max(...xs), miny = Math.min(...ys), maxy = Math.max(...ys);
    const spanx = Math.max(minSpan, maxx - minx) * 1.1, spany = Math.max(minSpan, maxy - miny) * 1.1;
    const s = Math.min((cv.width - 2 * pad) / spanx, (cv.height - 2 * pad) / spany);
    const cx = (minx + maxx) / 2, cy = (miny + maxy) / 2;
    return { s: s, X: (x) => cv.width / 2 + (x - cx) * s, Y: (y) => cv.height / 2 - (y - cy) * s };
  }

  // P1.4: the fused-estimate vs dead-reckoning trajectory (the /slam estimator surface).
  function drawTrajectory(cv, est, base) {
    const g = cv.getContext("2d");
    g.clearRect(0, 0, cv.width, cv.height);
    const t = _fit(cv, est.concat(base)), X = t.X, Y = t.Y;
    const line = (path, color, w) => {
      g.strokeStyle = color; g.lineWidth = w; g.beginPath();
      path.forEach((p, i) => (i ? g.lineTo(X(p[0]), Y(p[1])) : g.moveTo(X(p[0]), Y(p[1]))));
      g.stroke();
    };
    line(base, "#e0a23a", 2); line(est, "#36d1dc", 2);
    g.font = "10px system-ui"; g.fillStyle = "#36d1dc"; g.fillText("— fused estimate", 26, 14);
    g.fillStyle = "#e0a23a"; g.fillText("— dead reckoning", 26 + 104, 14);
  }

  // FS-05 end-to-end DRIVE PREVIEW: the planned route (amber dashed) vs the executed trajectory (cyan)
  // + start/goal + recovery backups. `res` = the /nav/run response.
  function drawDrive(cv, res) {
    const g = cv.getContext("2d"); g.clearRect(0, 0, cv.width, cv.height);
    const route = res.waypoints || [], traj = res.trajectory || [];
    const all = route.concat(traj);
    if (!all.length) {                                       // council #238: honest in-canvas empty-state (was a blank dark box reading as "broken")
      g.font = "12px system-ui"; g.fillStyle = "#5a6472"; g.textAlign = "center";
      g.fillText("No drive yet — press ▶ Run drive preview", cv.width / 2, cv.height / 2);
      g.textAlign = "left"; return;
    }
    const t = _fit(cv, all), X = t.X, Y = t.Y;
    const line = (path, color, w, dash) => {
      g.strokeStyle = color; g.lineWidth = w; g.setLineDash(dash || []); g.beginPath();
      path.forEach((p, i) => (i ? g.lineTo(X(p[0]), Y(p[1])) : g.moveTo(X(p[0]), Y(p[1]))));
      g.stroke(); g.setLineDash([]);
    };
    line(route, "#e0a23a", 2, [5, 3]);                       // planned corridor (amber dashed)
    line(traj, "#36d1dc", 2);                                // executed drive (cyan)
    const dot = (p, color, r) => { g.fillStyle = color; g.beginPath(); g.arc(X(p[0]), Y(p[1]), r, 0, 2 * Math.PI); g.fill(); };
    if (route.length) { dot(route[0], "#3fa34d", 5); dot(route[route.length - 1], "#e8273f", 5); }   // start green / goal red
    (res.recovery_events || []).forEach((e) => {             // recovery backups: orange ring at the recovered pose
      if (e.xy) { g.strokeStyle = "#ff8c00"; g.lineWidth = 2; g.beginPath(); g.arc(X(e.xy[0]), Y(e.xy[1]), 6, 0, 2 * Math.PI); g.stroke(); } });
    g.font = "10px system-ui"; g.fillStyle = "#e0a23a"; g.fillText("--- planned route", 26, 12);
    g.fillStyle = "#36d1dc"; g.fillText("— executed", 26 + 96, 12);
    g.fillStyle = "#3fa34d"; g.fillText("● start", 26 + 162, 12); g.fillStyle = "#e8273f"; g.fillText("● goal", 26 + 208, 12);
  }

  // #148 REAL terrain-fix est-vs-truth on the real Haworth DEM: odometry (drifts) vs fused (real DEM
  // fixes) vs truth (white dashed). The /localize/traverse response's three xy paths.
  function drawReal(cv, trueXY, fusedXY, odomXY) {
    const g = cv.getContext("2d"); g.clearRect(0, 0, cv.width, cv.height);
    const t = _fit(cv, trueXY.concat(fusedXY, odomXY)), X = t.X, Y = t.Y;
    const line = (path, color, w, dash) => {
      g.strokeStyle = color; g.lineWidth = w; g.setLineDash(dash || []); g.beginPath();
      path.forEach((p, i) => (i ? g.lineTo(X(p[0]), Y(p[1])) : g.moveTo(X(p[0]), Y(p[1]))));
      g.stroke(); g.setLineDash([]);
    };
    line(odomXY, "#e0a23a", 2);                            // dead reckoning (drifts)
    line(trueXY, "#cfe3ff", 1.5, [4, 3]);                  // truth (white dashed)
    line(fusedXY, "#36d1dc", 2);                           // fused (real DEM fixes)
    g.font = "10px system-ui"; g.fillStyle = "#36d1dc"; g.fillText("— fused (real DEM fix)", 26, 14);
    g.fillStyle = "#e0a23a"; g.fillText("— odometry", 26 + 124, 14);
    g.fillStyle = "#cfe3ff"; g.fillText("--- truth", 26 + 200, 14);
  }

  // top-down DEM-frame plot of the real relocalization fix (matched landmarks + covariance ring +
  // drift/fix/true markers). `res` = the /localize/render response. minSpan is 0.5 m here (tight rig).
  function drawFix(cv, res) {
    const g = cv.getContext("2d"); g.clearRect(0, 0, cv.width, cv.height);
    const pts = res.landmarks_xy.concat([res.fix_xy, res.true_xy, res.seed_xy]);
    const t = _fit(cv, pts, 26, 0.5), s = t.s, X = t.X, Y = t.Y;
    g.fillStyle = "#667";                                // matched landmarks (DEM coordinates)
    res.landmarks_xy.forEach((p) => { g.beginPath(); g.arc(X(p[0]), Y(p[1]), 2, 0, 2 * Math.PI); g.fill(); });
    g.strokeStyle = "#36d1dc"; g.lineWidth = 1.5;        // covariance around the fix
    g.beginPath(); g.arc(X(res.fix_xy[0]), Y(res.fix_xy[1]), Math.max(3, res.fix_sigma_m * s), 0, 2 * Math.PI); g.stroke();
    const dot = (p, c) => { g.fillStyle = c; g.beginPath(); g.arc(X(p[0]), Y(p[1]), 4, 0, 2 * Math.PI); g.fill(); };
    dot(res.seed_xy, "#e0a23a"); dot(res.fix_xy, "#36d1dc");      // drifted prior (amber), recovered fix (cyan)
    g.strokeStyle = "#3ad17a"; g.lineWidth = 2;          // truth (green cross)
    const tx = X(res.true_xy[0]), ty = Y(res.true_xy[1]);
    g.beginPath(); g.moveTo(tx - 5, ty); g.lineTo(tx + 5, ty); g.moveTo(tx, ty - 5); g.lineTo(tx, ty + 5); g.stroke();
    g.fillStyle = "#9aa"; g.font = "10px system-ui"; g.fillText("● landmarks  ● drift  ● fix  ✛ true  (DEM frame, m)", 6, 14);
  }

  var API = { _fit: _fit, drawTrajectory: drawTrajectory, drawDrive: drawDrive,
              drawReal: drawReal, drawFix: drawFix };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_NAVPLOT = API;                                         // browser (window)
})(typeof window !== "undefined" ? window : null);
