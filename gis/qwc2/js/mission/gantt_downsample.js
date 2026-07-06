// VERBATIM LIFT of stewie/server/web/assets/gantt_downsample.js (pure, tested).
// Present only to satisfy rover_hud.js's static require("./gantt_downsample.js"); unmodified.
// frontend-audit D (2026-07-01): PURE downsampling math for the UI-17 activity Gantt. At mission
// scale (92 recharge cycles / 2449 h -> thousands of frames over ~460 plot px) the one-bar-per-frame
// renderer aliased into a solid mass and the battery polyline into noise. These helpers reduce the
// timeline to what a pixel column can honestly show: per-lane covered-pixel RUNS (adjacent same-phase
// bars whose bars/gaps fall under ~2 px merge into one run) and a per-column MIN/MAX ENVELOPE for the
// battery curve. Short runs stay raw (shouldDownsample). No DOM, no canvas: rover_hud.js drawGantt
// maps the output to fillRect/lineTo. node:test'able.
(function (root) {
  "use strict";

  var MERGE_PX = 2;      // bars/gaps under this many pixels merge -- the "~2 px" aliasing threshold

  // raw per-frame bars stay legible while every bar averages >= ~3 px of plot width
  function shouldDownsample(nFrames, plotW) {
    return (+nFrames || 0) > (+plotW || 0) / 3;
  }

  // one lane's bars [{t0,t1}] -> merged pixel runs [[px0,px1], ...] over a plotW-column strip.
  // A column is covered when any bar overlaps it; runs separated by a gap < MERGE_PX merge (a sub-2px
  // gap cannot be told from aliasing), and every run is at least 1 px wide.
  function laneRuns(bars, T, plotW) {
    plotW = Math.max(1, Math.floor(+plotW || 0));
    if (!(T > 0) || !bars || !bars.length) return [];
    const cov = new Uint8Array(plotW);
    for (const b of bars) {
      let a = Math.floor((b.t0 / T) * plotW), z = Math.ceil((b.t1 / T) * plotW);
      a = Math.max(0, Math.min(plotW - 1, a));
      z = Math.max(a + 1, Math.min(plotW, z));
      for (let i = a; i < z; i++) cov[i] = 1;
    }
    const runs = [];
    let start = -1;
    for (let i = 0; i <= plotW; i++) {
      if (i < plotW && cov[i]) { if (start < 0) start = i; continue; }
      if (start >= 0) { runs.push([start, i]); start = -1; }
    }
    // merge runs separated by a sub-threshold gap
    const merged = [];
    for (const r of runs) {
      const last = merged[merged.length - 1];
      if (last && r[0] - last[1] < MERGE_PX) last[1] = r[1];
      else merged.push([r[0], r[1]]);
    }
    return merged;
  }

  // the battery min/max envelope: frames [{t0,t1,b0,b1}] (b = battery fraction at the frame's ends,
  // linear within the frame) -> per pixel column {min,max}; uncovered columns forward-fill so the
  // envelope is continuous. Returns an array of length plotW.
  function battEnvelope(frames, T, plotW) {
    plotW = Math.max(1, Math.floor(+plotW || 0));
    const mins = new Array(plotW).fill(Infinity), maxs = new Array(plotW).fill(-Infinity);
    if (T > 0 && frames && frames.length) {
      for (const f of frames) {
        const x0 = (f.t0 / T) * plotW, x1 = (f.t1 / T) * plotW;
        const a = Math.max(0, Math.floor(x0)), z = Math.min(plotW - 1, Math.ceil(x1));
        for (let j = a; j <= z; j++) {
          // the frame's battery values across this column's [j, j+1) span (linear in the frame)
          const u0 = x1 > x0 ? Math.min(1, Math.max(0, (j - x0) / (x1 - x0))) : 0;
          const u1 = x1 > x0 ? Math.min(1, Math.max(0, (j + 1 - x0) / (x1 - x0))) : 1;
          const b0 = f.b0 + (f.b1 - f.b0) * u0, b1 = f.b0 + (f.b1 - f.b0) * u1;
          const lo = Math.min(b0, b1), hi = Math.max(b0, b1);
          if (lo < mins[j]) mins[j] = lo;
          if (hi > maxs[j]) maxs[j] = hi;
        }
      }
    }
    const out = new Array(plotW);
    let prev = null;
    for (let j = 0; j < plotW; j++) {
      if (mins[j] !== Infinity) prev = { min: mins[j], max: maxs[j] };
      out[j] = prev ? { min: prev.min, max: prev.max } : { min: 0, max: 0 };
    }
    return out;
  }

  var API = { MERGE_PX: MERGE_PX, shouldDownsample: shouldDownsample,
              laneRuns: laneRuns, battEnvelope: battEnvelope };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_GANTT_DOWNSAMPLE = API;                                // browser (window)
})(typeof window !== "undefined" ? window : null);
