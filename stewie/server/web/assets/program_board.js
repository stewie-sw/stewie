// PO lane: the /program board renderers. Pure functions (snapshot payload -> HTML strings) so the whole
// board is node:test'able without a browser; the only DOM code is the boot block at the bottom (fetch
// /program/snapshot -> innerHTML the mounts -> click-to-inspect delegation). Server-derived text is
// escaped via STEWIE_HTMLESC (CSP: external module, no inline JS on the page).
(function (root) {
  "use strict";

  // bucket -> {label, chip css class}. Colors are semantic and match the cockpit: done graphite-green,
  // buildable steel-cyan (a positive/ready state -- the accent red stays reserved for danger/CTA),
  // gated amber (blocked on a real resource), concurrent violet (owned by the live AS-lane agent).
  var BUCKETS = {
    done: { label: "verified done", cls: "b-done" },
    buildable: { label: "buildable now", cls: "b-build" },
    gated: { label: "gated (real resource missing)", cls: "b-gated" },
    concurrent: { label: "concurrent-owned (live agent lane)", cls: "b-conc" },
  };

  function bucketMeta(bucket) { return BUCKETS[bucket] || { label: bucket, cls: "b-unknown" }; }

  function pct(part, whole) { return whole ? Math.round((1000 * part) / whole) / 10 : 0; }

  // filter = {bucket: null|key, pri: null|"P0", q: ""}; null/"" = pass-through. q matches the row id
  // or the requirement text, case-insensitive. Pure -> the filter deck is unit-testable.
  function applyFilter(rows, f) {
    var q = (f && f.q ? String(f.q) : "").trim().toLowerCase();
    return rows.filter(function (r) {
      if (f && f.bucket && r.bucket !== f.bucket) return false;
      if (f && f.pri && r.pri !== f.pri) return false;
      if (q && (r.id + " " + r.text).toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
  }

  function countsByBucket(rows) {
    var c = { done: 0, buildable: 0, gated: 0, concurrent: 0 };
    rows.forEach(function (r) { if (c[r.bucket] !== undefined) c[r.bucket] += 1; });
    return c;
  }

  // the live "showing N of M" readout under the filter deck (aria-live region in the page).
  function resultsLine(shown, total) {
    return shown === total ? "all " + total + " requirements"
      : shown + " of " + total + " requirements match";
  }

  // headline stat chips + the provenance line (which committed PRD this board is looking at).
  function summaryHTML(snap, esc) {
    var s = snap.summary, b = s.buckets, p = snap.provenance;
    var chips = [
      ["rows", s.total], ["verified done", b.done + " (" + s.done_pct + "%)"],
      ["in-scope done", s.in_scope_done_pct + "%"], ["buildable now", b.buildable],
      ["gated", b.gated], ["concurrent-owned", b.concurrent],
      ["test-cited", s.cited], ["dispatch briefs", s.briefs],
    ].map(function (c) {
      return '<span class="chip"><b>' + esc(c[1]) + "</b> " + esc(c[0]) + "</span>";
    }).join("");
    return chips + '<div class="prov">snapshot of committed PRD §7 @ <code>'
      + esc(String(p.prd_commit).slice(0, 9)) + "</code> · sources sha "
      + esc(String(p.prd_sha256).slice(0, 12)) + " · regenerate: <code>scripts/gen_program_snapshot.py</code></div>";
  }

  // the six-slot ConOps spine the cockpit ships: the board's "why" strip, linking back to /app.
  function spineHTML(spine, esc) {
    return spine.map(function (step) { return '<span class="step">' + esc(step) + "</span>"; })
      .join('<span class="arrow">→</span>')
      + ' <a class="applink" href="/app">open the cockpit ↗</a>';
  }

  // per-priority rollup table (P0 first -- the honest "how much of the must-haves is real" view).
  function priorityHTML(snap, esc) {
    var byp = snap.summary.by_priority;
    return "<table><tr><th>priority</th><th>done / total</th><th></th></tr>"
      + Object.keys(byp).sort().map(function (k) {
          var v = byp[k], w = pct(v.done, v.total);
          return "<tr><td>" + esc(k) + "</td><td>" + v.done + " / " + v.total + "</td>"
            + '<td class="barcell"><span class="bar" style="width:' + w + '%"></span> ' + w + "%</td></tr>";
        }).join("") + "</table>";
  }

  // the lane board: one group per lane, chips colored by bucket, data-id for the inspect click.
  // `rows` defaults to the full matrix; pass applyFilter()'s output to render a filtered board.
  // `selectedId` keeps the inspected chip visibly selected across re-renders. Explicit empty state.
  function lanesHTML(snap, esc, rows, selectedId) {
    rows = rows || snap.rows;
    if (!rows.length) return '<p class="muted empty">No requirements match the current filters.</p>';
    var byLane = {};
    rows.forEach(function (r) { (byLane[r.lane] = byLane[r.lane] || []).push(r); });
    var i = 0;
    return Object.keys(byLane).sort().map(function (lane) {
      var laneRows = byLane[lane];
      var done = laneRows.filter(function (r) { return r.bucket === "done"; }).length;
      var w = pct(done, laneRows.length);
      var chips = laneRows.map(function (r) {
        return '<button class="rowchip ' + bucketMeta(r.bucket).cls
          + (r.id === selectedId ? " selected" : "") + '" data-id="' + esc(r.id)
          + '" title="' + esc(r.text) + '" aria-pressed="' + (r.id === selectedId) + '">'
          + esc(r.id) + "</button>";
      }).join("");
      return '<section class="lane" style="animation-delay:' + (28 * i++) + 'ms"><h3>' + esc(lane)
        + ' <span class="lanebar" aria-hidden="true"><span style="width:' + w + '%"></span></span>'
        + '<span class="lanecount">' + done + "/" + laneRows.length + " done</span></h3><div>"
        + chips + "</div></section>";
    }).join("");
  }

  // the inspect panel for one row: glyphs, bucket, gate reason, citation state, and the dispatch brief
  // (goal + test target) when the fan-out layer has one.
  function rowDetailHTML(row, esc) {
    if (!row) return '<span class="muted">Select a requirement chip to inspect it.</span>';
    var m = bucketMeta(row.bucket);
    var h = "<h3>" + esc(row.id) + " <small>(" + esc(row.pri) + " · lane " + esc(row.lane) + ")</small></h3>"
      + '<p class="status ' + m.cls + '">' + esc(m.label)
      + (row.gated_reason ? " — " + esc(row.gated_reason) : "") + "</p>"
      + "<p>" + esc(row.text) + "</p>"
      + '<p class="glyphs">I=<b>' + esc(row.I) + "</b> X=<b>" + esc(row.X) + "</b> V=<b>" + esc(row.V)
      + "</b> Q=<b>" + esc(row.Q) + "</b> · "
      + (row.cited ? "cited by a committed <code>[REQ:" + esc(row.id) + "]</code> test"
                   : "<b>not test-cited</b> (req_trace does not count it yet)") + "</p>";
    if (row.brief) {
      h += '<div class="brief"><h4>dispatch brief <small>(' + esc(row.brief.kind) + ")</small></h4>"
        + "<p><b>goal:</b> " + esc(row.brief.goal || "") + "</p>"
        + (row.brief.test_target ? "<p><b>test target:</b> <code>" + esc(row.brief.test_target) + "</code></p>" : "")
        + "</div>";
    }
    return h;
  }

  function findRow(snap, id) {
    for (var i = 0; i < snap.rows.length; i++) if (snap.rows[i].id === id) return snap.rows[i];
    return null;
  }

  var API = { summaryHTML: summaryHTML, spineHTML: spineHTML, priorityHTML: priorityHTML,
              lanesHTML: lanesHTML, rowDetailHTML: rowDetailHTML, bucketMeta: bucketMeta,
              findRow: findRow, applyFilter: applyFilter, countsByBucket: countsByBucket,
              resultsLine: resultsLine };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_PROGRAM_BOARD = API;                                    // browser (window)

  // browser boot: fetch the committed snapshot, render every mount, wire the filter deck (bucket +
  // priority toggles, live search) and click-to-inspect. All state lives here; renderers stay pure.
  if (root && root.document && root.document.getElementById("program-summary")) {
    var doc = root.document;
    var esc = root.STEWIE_HTMLESC.esc;
    var state = { bucket: null, pri: null, q: "", selected: null };

    fetch("/program/snapshot").then(function (r) {
      if (!r.ok) throw new Error("snapshot HTTP " + r.status);
      return r.json();
    }).then(function (snap) {
      var counts = countsByBucket(snap.rows);
      doc.getElementById("program-summary").innerHTML = summaryHTML(snap, esc);
      doc.getElementById("program-spine").innerHTML = spineHTML(snap.workflow_spine, esc);
      doc.getElementById("program-priority").innerHTML = priorityHTML(snap, esc);
      doc.getElementById("program-detail").innerHTML = rowDetailHTML(null, esc);
      // filter-deck counts on the bucket toggles
      Array.prototype.forEach.call(doc.querySelectorAll("[data-bucket]"), function (btn) {
        var n = counts[btn.getAttribute("data-bucket")];
        if (n !== undefined) btn.innerHTML += ' <span class="n">' + n + "</span>";
      });

      function redraw() {
        var rows = applyFilter(snap.rows, state);
        doc.getElementById("program-lanes").innerHTML = lanesHTML(snap, esc, rows, state.selected);
        doc.getElementById("program-results").textContent = resultsLine(rows.length, snap.rows.length);
      }

      function toggle(group, attr, key) {
        Array.prototype.forEach.call(doc.querySelectorAll(group), function (btn) {
          btn.addEventListener("click", function () {
            var v = btn.getAttribute(attr);
            state[key] = state[key] === v ? null : v;
            Array.prototype.forEach.call(doc.querySelectorAll(group), function (b) {
              b.setAttribute("aria-pressed", String(b.getAttribute(attr) === state[key]));
            });
            redraw();
          });
        });
      }
      toggle("[data-bucket]", "data-bucket", "bucket");
      toggle("[data-pri]", "data-pri", "pri");
      doc.getElementById("program-search").addEventListener("input", function (ev) {
        state.q = ev.target.value;
        redraw();
      });
      doc.getElementById("program-lanes").addEventListener("click", function (ev) {
        var id = ev.target && ev.target.getAttribute && ev.target.getAttribute("data-id");
        if (!id) return;
        state.selected = id;
        doc.getElementById("program-detail").innerHTML = rowDetailHTML(findRow(snap, id), esc);
        Array.prototype.forEach.call(doc.querySelectorAll("#program-lanes .rowchip"), function (b) {
          var on = b.getAttribute("data-id") === id;
          b.classList.toggle("selected", on);
          b.setAttribute("aria-pressed", String(on));
        });
      });
      redraw();
    }).catch(function (e) {
      // explicit error state (design contract: never a silent blank pane)
      doc.getElementById("program-summary").innerHTML =
        '<span class="err">Could not load the program snapshot: ' + esc(e.message) + "</span>";
    });
  }
})(typeof window !== "undefined" ? window : null);
