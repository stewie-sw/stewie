// PO-11: multi-rover fleet PLAYBACK model. The single-rover execDraw animates ONE timeline with ONE
// marker; fleet playback must render EVERY rover on its OWN route with its OWN independent telemetry.
// This pure module maps a multi-vehicle PlanResult (totals.vehicles_detail + the per-trip, vehicle-tagged
// route geometry) into N independent per-rover TRACKS + N per-rover telemetry STREAMS, plus a pure
// per-frame interpolator so each rover advances on its OWN timeline (it finishes at its own time_s, not a
// shared clock). No DOM/canvas here -> node:test'able; cockpit.js plots the computed points.
(function (root) {
  "use strict";

  function _num(x, d) { var n = Number(x); return isFinite(n) ? n : (d || 0); }

  // normalize one trip entry to {vehicle, site:[x,y], t_start} -- accepts a bare trip or a {trip:{...}}
  // per-trip wrapper (the planner emits per_trip = {trip, t_start, t_end}, trips carry a .vehicle tag).
  function _trip(t) {
    var tr = t && t.trip ? t.trip : t;
    if (!tr || !tr.site) return null;
    var ts = (t && t.t_start != null) ? t.t_start : tr.t_start;
    return { vehicle: tr.vehicle, site: [_num(tr.site[0]), _num(tr.site[1])], t_start: _num(ts) };
  }

  // one telemetry STREAM per rover, straight off the real vehicles_detail (an independent per-rover channel).
  function _stream(d) {
    var soc = d.health && typeof d.health.min_batt_frac === "number" ? d.health.min_batt_frac : null;
    return { vehicle: d.vehicle, n_trips: _num(d.n_trips), time_s: _num(d.time_s),
             distance_m: _num(d.distance_m), energy_J: _num(d.energy_J), charges: _num(d.charges),
             min_batt_frac: soc, health: (d.health && d.health.health) || "nominal" };
  }

  // N per-rover TRACKS + N telemetry STREAMS from a multi-vehicle plan. `charger` (optional [x,y]) is the
  // shared start each rover departs from. Tracks and streams are aligned by index (same vehicle order).
  function fleetPlaybackModel(totals, trips, charger) {
    var t = totals || {};
    var detail = Array.isArray(t.vehicles_detail) ? t.vehicles_detail : [];
    var byV = {};
    (trips || []).forEach(function (raw) {
      var tp = _trip(raw); if (!tp || tp.vehicle == null) return;
      (byV[tp.vehicle] = byV[tp.vehicle] || []).push(tp);
    });
    var streams = detail.map(_stream);
    var tracks = detail.map(function (d) {
      // prefer the rover's own route as the planner emits it (vehicles_detail[i].track = charger start +
      // its sequenced sites); else reconstruct it by grouping the vehicle-tagged trips.
      if (Array.isArray(d.track) && d.track.length) {
        var wpt = d.track.map(function (p) { return [_num(p[0]), _num(p[1])]; });
        return { vehicle: d.vehicle, n_stops: Math.max(0, wpt.length - 1), waypoints: wpt };
      }
      var mine = (byV[d.vehicle] || []).slice();
      mine.sort(function (a, b) { return a.t_start - b.t_start; });   // the rover's own visit order
      var wp = [];
      if (charger && charger.length === 2) wp.push([_num(charger[0]), _num(charger[1])]);
      mine.forEach(function (tp) { wp.push(tp.site); });
      return { vehicle: d.vehicle, n_stops: mine.length, waypoints: wp };
    });
    return { tracks: tracks, streams: streams, count: detail.length };
  }

  // the marker position along a track at fraction f in [0,1] (uniform per leg -- the same interpolation
  // shape execDraw uses between frames). Each rover advances on ITS OWN track.
  function roverMarkerAt(track, f) {
    var wp = (track && track.waypoints) || [];
    if (!wp.length) return null;
    if (wp.length === 1) return wp[0].slice();
    f = Math.max(0, Math.min(1, _num(f)));
    var legs = wp.length - 1, pos = f * legs, i = Math.min(legs - 1, Math.floor(pos)), u = pos - i;
    return [wp[i][0] + (wp[i + 1][0] - wp[i][0]) * u, wp[i][1] + (wp[i + 1][1] - wp[i][1]) * u];
  }

  // one animation FRAME: each rover's current marker + progress at sim time simT. Each rover finishes at
  // its OWN time_s (independent timelines), so a fast rover reaches progress 1 while a slow one is mid-route.
  function playbackFrame(model, simT) {
    return (model.tracks || []).map(function (tr, i) {
      var st = (model.streams || [])[i] || {};
      var dur = st.time_s > 0 ? st.time_s : 1;
      var f = Math.max(0, Math.min(1, _num(simT) / dur));
      return { vehicle: tr.vehicle, marker: roverMarkerAt(tr, f), progress: f, telemetry: st };
    });
  }

  // a per-rover inline-SVG track (its own waypoints, normalized to a small viewbox) with its telemetry
  // stream chips -- N rovers render as N distinct track+telemetry blocks. Pure string builder (no DOM);
  // `esc` is the caller's HTML-escaper. `simT` (optional) places each rover's marker on its OWN timeline.
  function fleetPlaybackHTML(model, esc, simT) {
    esc = esc || function (s) { return String(s == null ? "" : s); };
    var tracks = (model && model.tracks) || [];
    if (!tracks.length) {
      return '<div class="empty">No fleet playback yet. Plan a mission with <b>≥1 rover</b>; each '
        + "rover's own route and independent telemetry replay here.</div>";
    }
    var frames = playbackFrame(model, simT || 0);
    var COLORS = ["#6ee7a8", "#4f9cff", "#e0b300", "#e07b39", "#c07bff", "#39d0e0"];
    var blocks = tracks.map(function (tr, i) {
      var color = COLORS[i % COLORS.length], st = model.streams[i] || {}, fr = frames[i] || {};
      var wp = tr.waypoints || [];
      // normalize the rover's own waypoints into a 120x60 viewbox (its own extent -> its own track)
      var xs = wp.map(function (p) { return p[0]; }), ys = wp.map(function (p) { return p[1]; });
      var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
      var y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
      var sx = (x1 - x0) > 1e-6 ? 116 / (x1 - x0) : 0, sy = (y1 - y0) > 1e-6 ? 56 / (y1 - y0) : 0;
      var s = Math.min(sx || 0.0001, sy || 0.0001);
      var PX = function (p) {
        return [2 + (p[0] - x0) * s, 58 - (p[1] - y0) * s];   // y up
      };
      var pts = wp.map(function (p) { var q = PX(p); return q[0].toFixed(1) + "," + q[1].toFixed(1); }).join(" ");
      var mk = fr.marker ? PX(fr.marker) : null;
      var soc = typeof st.min_batt_frac === "number" ? (st.min_batt_frac * 100).toFixed(0) + "%" : "—";
      var svg = '<svg width="120" height="60" viewBox="0 0 120 60" style="background:#05060c;border:1px solid var(--line);border-radius:4px">'
        + '<polyline points="' + pts + '" fill="none" stroke="' + color + '" stroke-width="1.2" opacity="0.8"/>'
        + (mk ? '<circle cx="' + mk[0].toFixed(1) + '" cy="' + mk[1].toFixed(1) + '" r="3" fill="' + color + '"/>' : "")
        + "</svg>";
      var chips = '<span style="font-variant-numeric:tabular-nums;font-size:10px;opacity:.85">'
        + "stops " + esc(tr.n_stops) + " · " + (st.distance_m / 1000 || 0).toFixed(2) + " km · "
        + (st.energy_J / 1e6 || 0).toFixed(1) + " MJ · SoC " + soc + " · " + esc(st.health || "nominal")
        + "</span>";
      return '<div class="fbrover" data-vehicle="' + esc(tr.vehicle) + '" style="display:flex;gap:8px;'
        + 'align-items:center;margin:4px 0">' + svg
        + '<div><div style="font-weight:600;color:' + color + '">' + esc(tr.vehicle) + "</div>" + chips + "</div></div>";
    }).join("");
    return '<div style="font-size:11px;color:var(--muted);margin-bottom:4px">' + esc(tracks.length)
      + " rovers · each on its own route + telemetry</div>" + blocks;
  }

  var API = { fleetPlaybackModel: fleetPlaybackModel, roverMarkerAt: roverMarkerAt,
              playbackFrame: playbackFrame, fleetPlaybackHTML: fleetPlaybackHTML };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_FLEET_PLAYBACK = API;                                  // browser (window)
})(typeof window !== "undefined" ? window : null);
