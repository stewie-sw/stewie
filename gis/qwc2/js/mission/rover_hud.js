// VERBATIM LIFT of stewie/server/web/assets/rover_hud.js (STEWIE FS-24 pure render module).
// Copied unmodified into the QWC2 IDE so the MissionHUD plugin can bundle it via webpack.
// DO NOT edit the drawing logic here; the source of truth is stewie/server/web/assets/rover_hud.js.
// Exports (window.STEWIE_ROVER_HUD + module.exports): drawRoverHUD, teleSpark, telePush, teleChip, drawGantt.
// FS-24: the EXECUTION TELEMETRY visualization cluster -- the rover HUD (azimuth/battery/drum/pose),
// the telemetry sparkline + ring buffer, the per-channel telemetry chips, and the activity Gantt. All
// pure rendering over a passed-in <canvas> + payload (no DOM lookups, no module globals): the cockpit's
// thin wrappers resolve qel("hudcanvas") / qel("telespark") / qel("telerail") / $("gantt") and pass
// them in, per the existing window.STEWIE_* module pattern. Extracted verbatim from cockpit.js
// (PRD FS-24); behaviour is preserved exactly. node:test'able (a recording 2D context).
(function (root) {
  "use strict";

  // the telemetry SPARKLINE: three normalized channels (batt/mass/slip) over the ring buffer `buf`.
  function teleSpark(cv, buf) {
    if (!cv) return;
    const ctx = cv.getContext("2d");
    ctx.fillStyle = "#0a0a0c"; ctx.fillRect(0, 0, cv.width, cv.height);
    const series = [["batt", "#e8273f"], ["mass", "#e07b39"], ["slip", "#4f9cff"]];
    series.forEach(([k, col]) => {
      const b = buf[k]; if (b.length < 2) return;
      const mx = Math.max(...b, 1e-9);
      ctx.strokeStyle = col; ctx.lineWidth = 1; ctx.beginPath();
      b.forEach((v, i) => {
        const x = i / (b.length - 1) * (cv.width - 4) + 2;
        const y = cv.height - 3 - (v / mx) * (cv.height - 8);
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      ctx.stroke();
    });
  }

  // push one telemetry sample into the ring buffer (cap 240), then redraw the sparkline. `redraw` is
  // the bound teleSpark(cv, buf) the cockpit supplies.
  function telePush(buf, batt, mass, slip, redraw) {
    buf.batt.push(batt); buf.mass.push(mass); buf.slip.push(slip);
    Object.values(buf).forEach((b) => { if (b.length > 240) b.shift(); });
    if (redraw) redraw();
  }

  // a per-channel telemetry CHIP on the rail (created on first sight of `ch`, reused after). `markFresh`
  // is the cockpit's UI-5 freshness stamp (optional).
  function teleChip(rail, ch, text, ok, markFresh) {
    if (!rail) return;
    let el = rail.querySelector(`[data-ch="${ch}"]`);
    if (!el) {
      el = document.createElement("span");
      el.dataset.ch = ch;
      el.style.cssText = "font-size:9px;font-family:Orbitron,system-ui;letter-spacing:.06em;padding:2px 6px;border:1px solid var(--line);border-radius:4px";
      rail.appendChild(el);
    }
    el.textContent = `${ch.toUpperCase()} ${text}`;
    el.style.color = ok ? "var(--txt)" : "#e0564b";
    el.style.borderColor = ok ? "var(--line)" : "#e0564b";
    if (typeof markFresh === "function") markFresh(el);
  }

  // #184: the rover HUD -- azimuth compass, battery, front/rear drum weight, live pose. `s` is the HUD
  // state ({headingDeg, soc, frontKg, rearKg, x, y}); `drumCapKg` scales the drum-load bars.
  function drawRoverHUD(cv, s, drumCapKg) {
    if (!cv) return;
    const ctx = cv.getContext("2d"), W = cv.width, H = cv.height;
    ctx.clearRect(0, 0, W, H); ctx.fillStyle = "#0a0a0c"; ctx.fillRect(0, 0, W, H);
    ctx.font = "9px Orbitron, system-ui"; ctx.textBaseline = "middle";
    // azimuth compass (left): from-north-eastward (N up, E right) -- matches the ephemeris/shadow convention
    const cx = 46, cy = 44, r = 34;
    ctx.strokeStyle = "#2a2a36"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7); ctx.stroke();
    ctx.textAlign = "center";
    [["N", 0], ["E", 90], ["S", 180], ["W", 270]].forEach(([lab, az]) => {
      const a = az * Math.PI / 180;
      ctx.fillStyle = lab === "N" ? "#e0564b" : "#7a8290";
      ctx.fillText(lab, cx + (r - 7) * Math.sin(a), cy - (r - 7) * Math.cos(a));
    });
    if (s && s.headingDeg != null) {
      const a = s.headingDeg * Math.PI / 180;
      ctx.strokeStyle = "#35e0d0"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(cx, cy);
      ctx.lineTo(cx + (r - 5) * Math.sin(a), cy - (r - 5) * Math.cos(a)); ctx.stroke();
      ctx.fillStyle = "#35e0d0"; ctx.fillText(`${Math.round(s.headingDeg)}°`, cx, cy + r + 7);
    }
    // battery (middle)
    const bx = 100, bw = 24, bh = 56, by = 16;
    ctx.strokeStyle = "#2a2a36"; ctx.strokeRect(bx, by, bw, bh);
    const soc = (s && s.soc != null) ? Math.max(0, Math.min(1, s.soc)) : null;
    if (soc != null) {
      ctx.fillStyle = soc < 0.2 ? "#e0564b" : "#39ff14";
      ctx.fillRect(bx + 1, by + bh - bh * soc + 1, bw - 2, bh * soc - 2);
      ctx.fillStyle = "#c7d2e3"; ctx.fillText(`${Math.round(soc * 100)}%`, bx + bw / 2, by + bh + 8);
    }
    ctx.fillStyle = "#7a8290"; ctx.fillText("BATT", bx + bw / 2, by - 7);
    // front/rear drum weight (right)
    const dx = 144, dw = 158, dh = 15;
    [["FRONT", s && s.frontKg, 22], ["REAR", s && s.rearKg, 50]].forEach(([lab, kg, dy]) => {
      ctx.strokeStyle = "#2a2a36"; ctx.lineWidth = 1; ctx.strokeRect(dx, dy, dw, dh);
      const f = Math.max(0, Math.min(1, (kg || 0) / drumCapKg));
      ctx.fillStyle = "#e07b39"; ctx.fillRect(dx + 1, dy + 1, (dw - 2) * f, dh - 2);
      ctx.fillStyle = "#c7d2e3"; ctx.textAlign = "left"; ctx.fillText(`${lab} ${(kg || 0).toFixed(1)} kg`, dx + 4, dy + dh / 2);
    });
    if (s && s.x != null) { ctx.fillStyle = "#7a8290"; ctx.textAlign = "left";
      ctx.fillText(`pose ${Math.round(s.x)}, ${Math.round(s.y)} m`, dx + 4, 82); }
  }

  // UI-17: the activity Gantt -- one lane per phase kind, bars at [t0, t1], battery curve under. Reads
  // the typed TimelineFrame view model (adapters.js) when present, with the same inline fallback.
  // frontend-audit D (2026-07-01): at mission scale the per-frame bars aliased into a solid red mass --
  // long timelines now downsample to pixel-column runs per lane + a min/max ENVELOPE for the battery
  // curve (gantt_downsample.js, pure + tested); short runs keep the raw per-frame rendering. Red is
  // reserved for hazard marks: the lanes use categorical colors and the battery curve is cyan. A
  // 3-swatch inline legend names the two longest lanes + the battery band, and the right axis is
  // padded so the final tick label fits.
  var GD = (typeof window !== "undefined" && window.STEWIE_GANTT_DOWNSAMPLE)
    || (typeof require === "function" ? require("./gantt_downsample.js") : null);
  var BATT_COL = "#38bdf8";
  var GANTT_COLORS = { drive: "#4f9cff", dig: "#e0b300", cut: "#e0b300", dump: "#e07b39",
                       fill: "#e07b39", haul: "#9966dd", recharge: "#3fa34d", charge: "#3fa34d",
                       goto: "#7bd0d0" };
  function drawGantt(cv, rawFrames) {
    if (!cv) return;
    const A = (typeof window !== "undefined") ? window.STEWIE_ADAPTERS : null;
    const norm = (f) => A ? A.normalizeTimelineFrame({ timeline_frame: f })
                          : { phase: f.phase, t0: f.t0, t1: f.t1, batt0Frac: f.batt0_frac, batt1Frac: f.batt1_frac };
    const tl = (rawFrames || []).map(norm).filter(Boolean);
    const ctx = cv.getContext("2d");
    ctx.fillStyle = "#05060c"; ctx.fillRect(0, 0, cv.width, cv.height);
    if (!tl.length) {
      ctx.fillStyle = "#9ab"; ctx.font = "12px system-ui";
      ctx.fillText("plan a mission to populate the activity timeline", 16, 28);
      return;
    }
    const kinds = [...new Set(tl.map((p) => p.phase))];
    const T = Math.max(...tl.map((p) => p.t1)), L = 86, R = 30, TOP = 16;   // R pads the last axis tick
    const plotW = cv.width - L - R;
    const laneH = Math.min(34, (cv.height - 110) / Math.max(1, kinds.length));
    const X = (t) => L + (t / T) * plotW;
    const dense = !!(GD && GD.shouldDownsample(tl.length, plotW));
    ctx.font = "10px Orbitron, system-ui"; ctx.textBaseline = "middle";
    kinds.forEach((k, i) => {
      const y = TOP + i * laneH;
      ctx.fillStyle = "#9ab"; ctx.textAlign = "right";
      ctx.fillText(k.toUpperCase().slice(0, 9), L - 8, y + laneH / 2);
      ctx.strokeStyle = "rgba(255,255,255,.05)";
      ctx.beginPath(); ctx.moveTo(L, y + laneH); ctx.lineTo(cv.width - R, y + laneH); ctx.stroke();
      const bars = tl.filter((p) => p.phase === k);
      ctx.fillStyle = GANTT_COLORS[k] || "#c7d2e3";
      ctx.globalAlpha = .85;
      if (dense) {                                          // pixel-column runs (merged sub-2px bars/gaps)
        GD.laneRuns(bars, T, plotW).forEach((r) => {
          ctx.fillRect(L + r[0], y + 4, Math.max(1, r[1] - r[0]), laneH - 8);
        });
      } else {
        bars.forEach((p) => { ctx.fillRect(X(p.t0), y + 4, Math.max(2, X(p.t1) - X(p.t0)), laneH - 8); });
      }
      ctx.globalAlpha = 1;
    });
    // the battery curve under the lanes: raw polyline for short runs, min/max envelope band at scale
    const by0 = TOP + kinds.length * laneH + 14, bh = cv.height - by0 - 26;
    ctx.strokeStyle = "#3a3f4a";
    ctx.strokeRect(L, by0, cv.width - L - R, bh);
    if (dense) {
      const env = GD.battEnvelope(tl.map((p) => ({ t0: p.t0, t1: p.t1, b0: p.batt0Frac, b1: p.batt1Frac })), T, plotW);
      ctx.fillStyle = BATT_COL; ctx.globalAlpha = .30;      // the per-column min/max band
      env.forEach((c, j) => {
        const yTop = by0 + (1 - c.max) * bh;
        ctx.fillRect(L + j, yTop, 1, Math.max(1, (c.max - c.min) * bh));
      });
      ctx.globalAlpha = 1;
      ctx.strokeStyle = BATT_COL; ctx.lineWidth = 1; ctx.beginPath();   // the mid line through the band
      env.forEach((c, j) => {
        const ym = by0 + (1 - (c.min + c.max) / 2) * bh;
        if (j === 0) ctx.moveTo(L + j, ym); else ctx.lineTo(L + j, ym);
      });
      ctx.stroke();
    } else {
      ctx.strokeStyle = BATT_COL; ctx.lineWidth = 1.5; ctx.beginPath();
      tl.forEach((p, i) => {
        const y0 = by0 + (1 - p.batt0Frac) * bh, y1 = by0 + (1 - p.batt1Frac) * bh;
        if (i === 0) ctx.moveTo(X(p.t0), y0); else ctx.lineTo(X(p.t0), y0);
        ctx.lineTo(X(p.t1), y1);
      });
      ctx.stroke(); ctx.lineWidth = 1;
    }
    ctx.fillStyle = "#9ab"; ctx.textAlign = "right";
    ctx.fillText("BATT", L - 8, by0 + bh / 2);
    // 3-swatch inline legend (top strip): the two longest-duration lanes + the battery band
    const byDur = kinds.slice().sort((a, b) => {
      const dur = (k) => tl.filter((p) => p.phase === k).reduce((s, p) => s + (p.t1 - p.t0), 0);
      return dur(b) - dur(a);
    }).slice(0, 2);
    ctx.textAlign = "left"; ctx.font = "9px Orbitron, system-ui";
    let lx = L;
    byDur.concat(["batt"]).forEach((k) => {
      ctx.fillStyle = k === "batt" ? BATT_COL : (GANTT_COLORS[k] || "#c7d2e3");
      ctx.fillRect(lx, 4, 8, 8);
      ctx.fillStyle = "#9ab";
      const name = k.toUpperCase().slice(0, 9);
      ctx.fillText(name, lx + 11, 8);
      lx += 11 + name.length * 7 + 12;
    });
    ctx.font = "10px Orbitron, system-ui";
    // the time axis (R = 30 keeps the final tick label inside the pane)
    ctx.textAlign = "center";
    for (let h = 0; h <= T / 3600; h += Math.max(1, Math.round(T / 3600 / 6))) {
      ctx.fillText(`${h}h`, X(h * 3600), cv.height - 12);
    }
  }

  var API = { teleSpark: teleSpark, telePush: telePush, teleChip: teleChip,
              drawRoverHUD: drawRoverHUD, drawGantt: drawGantt };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_ROVER_HUD = API;                                       // browser (window)
})(typeof window !== "undefined" ? window : null);
