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
    const COLORS = { drive: "#4f9cff", dig: "#e8273f", cut: "#e8273f", dump: "#e07b39",
                     fill: "#e07b39", haul: "#9966dd", recharge: "#3fa34d", goto: "#7bd0d0" };
    const T = Math.max(...tl.map((p) => p.t1)), L = 86, R = 12, TOP = 16;
    const laneH = Math.min(34, (cv.height - 110) / Math.max(1, kinds.length));
    const X = (t) => L + (t / T) * (cv.width - L - R);
    ctx.font = "10px Orbitron, system-ui"; ctx.textBaseline = "middle";
    kinds.forEach((k, i) => {
      const y = TOP + i * laneH;
      ctx.fillStyle = "#9ab"; ctx.textAlign = "right";
      ctx.fillText(k.toUpperCase().slice(0, 9), L - 8, y + laneH / 2);
      ctx.strokeStyle = "rgba(255,255,255,.05)";
      ctx.beginPath(); ctx.moveTo(L, y + laneH); ctx.lineTo(cv.width - R, y + laneH); ctx.stroke();
      tl.filter((p) => p.phase === k).forEach((p) => {
        ctx.fillStyle = COLORS[k] || "#c7d2e3";
        ctx.globalAlpha = .85;
        ctx.fillRect(X(p.t0), y + 4, Math.max(2, X(p.t1) - X(p.t0)), laneH - 8);
        ctx.globalAlpha = 1;
      });
    });
    // the battery curve under the lanes
    const by0 = TOP + kinds.length * laneH + 14, bh = cv.height - by0 - 26;
    ctx.strokeStyle = "#3a3f4a";
    ctx.strokeRect(L, by0, cv.width - L - R, bh);
    ctx.strokeStyle = "#e8273f"; ctx.lineWidth = 1.5; ctx.beginPath();
    tl.forEach((p, i) => {
      const y0 = by0 + (1 - p.batt0Frac) * bh, y1 = by0 + (1 - p.batt1Frac) * bh;
      if (i === 0) ctx.moveTo(X(p.t0), y0); else ctx.lineTo(X(p.t0), y0);
      ctx.lineTo(X(p.t1), y1);
    });
    ctx.stroke(); ctx.lineWidth = 1;
    ctx.fillStyle = "#9ab"; ctx.textAlign = "right";
    ctx.fillText("BATT", L - 8, by0 + bh / 2);
    // the time axis
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
