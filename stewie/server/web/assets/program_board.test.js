// PO lane (node:test): the /program board renderers are pure (snapshot -> HTML string), so they are
// asserted here against the REAL committed snapshot artifact (stewie/server/program_snapshot.json --
// real data, not a fabricated fixture) plus targeted single-row cases for the detail panel's states.
// Run: node --test stewie/server/web/assets/program_board.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const B = require("./program_board.js");
const { esc } = require("./htmlesc.js");

const snap = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "..", "program_snapshot.json"), "utf8"));

test("summaryHTML: headline chips carry the real totals + the provenance commit", () => {
  const h = B.summaryHTML(snap, esc);
  assert.ok(h.includes("<b>" + snap.summary.total + "</b> rows"));
  assert.ok(h.includes(snap.summary.in_scope_done_pct + "%"));
  assert.ok(h.includes(String(snap.provenance.prd_commit).slice(0, 9)));
  assert.ok(h.includes("gen_program_snapshot.py"));   // the regen path is on the page, not tribal
});

test("spineHTML: renders the six ConOps steps in order and links the cockpit", () => {
  const h = B.spineHTML(snap.workflow_spine, esc);
  const order = snap.workflow_spine.map((s) => h.indexOf(">" + s + "<"));
  assert.deepStrictEqual([...order].sort((a, b) => a - b), order);   // in document order
  assert.ok(order.every((i) => i >= 0));
  assert.ok(h.includes('href="/app"'));
});

test("lanesHTML: every row renders exactly one chip, in its lane, with its bucket class", () => {
  const h = B.lanesHTML(snap, esc);
  for (const r of snap.rows) {
    const hits = h.split('data-id="' + r.id + '"').length - 1;
    assert.strictEqual(hits, 1, r.id + " must appear exactly once");
  }
  assert.strictEqual((h.match(/class="rowchip /g) || []).length, snap.rows.length);
  assert.strictEqual((h.match(/<section class="lane"/g) || []).length,
    Object.keys(snap.summary.by_lane).length);
});

test("priorityHTML: one bar row per priority with the real done/total", () => {
  const h = B.priorityHTML(snap, esc);
  for (const [p, v] of Object.entries(snap.summary.by_priority)) {
    assert.ok(h.includes("<td>" + p + "</td><td>" + v.done + " / " + v.total + "</td>"), p);
  }
});

test("rowDetailHTML: gated row surfaces its reason; uncited row says so; brief renders goal", () => {
  const gated = snap.rows.find((r) => r.bucket === "gated");
  assert.ok(gated, "the real snapshot has gated rows");
  const h = B.rowDetailHTML(gated, esc);
  assert.ok(h.includes(esc(gated.gated_reason)));
  const uncited = snap.rows.find((r) => !r.cited);
  assert.ok(B.rowDetailHTML(uncited, esc).includes("not test-cited"));
  const briefed = snap.rows.find((r) => r.brief);
  const bh = B.rowDetailHTML(briefed, esc);
  assert.ok(bh.includes("dispatch brief"));
  assert.ok(bh.includes(esc(briefed.brief.goal)));
});

test("rowDetailHTML: null row renders the explicit empty state; text is escaped", () => {
  assert.ok(B.rowDetailHTML(null, esc).includes("Select a requirement"));
  const xss = { id: "ZZ-99", pri: "P0", lane: "ZZ", text: '<img onerror="x">', I: "N", X: "N",
                V: "N", Q: "NA", bucket: "buildable", cited: false };
  const h = B.rowDetailHTML(xss, esc);
  assert.ok(!h.includes('<img onerror="x">'));
  assert.ok(h.includes("&lt;img"));
});

test("findRow + bucketMeta: lookup by id and a stable class per bucket", () => {
  assert.strictEqual(B.findRow(snap, snap.rows[0].id), snap.rows[0]);
  assert.strictEqual(B.findRow(snap, "no-such-id"), null);
  assert.strictEqual(B.bucketMeta("done").cls, "b-done");
  assert.strictEqual(B.bucketMeta("buildable").cls, "b-build");
  assert.strictEqual(B.bucketMeta("gated").cls, "b-gated");
  assert.strictEqual(B.bucketMeta("concurrent").cls, "b-conc");
  assert.strictEqual(B.bucketMeta("weird").cls, "b-unknown");
});

test("program.html color semantics match the cockpit: red stays danger-only, progress reads green", () => {
  // the audit finding: buildable (a positive state) must NOT wear the cockpit's danger/CTA red, and the
  // progress bars must not render completion as a crisis. Assert against the page the classes style.
  const html = fs.readFileSync(path.join(__dirname, "..", "program.html"), "utf8");
  const rule = (sel) => {
    const m = html.match(new RegExp("\n\\s*" + sel.replace(/[.]/g, "\\.") + "\\s+\\{[^}]*\\}"));
    assert.ok(m, sel + " rule must exist in program.html");
    return m[0];
  };
  assert.ok(!rule(".b-build").includes("var(--accent)"), "buildable must not borrow the danger accent");
  assert.ok(rule(".b-build").includes("#7fb6cc"), "buildable reads desaturated steel-cyan");
  assert.ok(!rule(".bar").includes("var(--accent)"), "priority progress must not render in danger red");
  assert.ok(rule(".bar").includes("#3fa34d"), "priority progress is green-on-graphite");
  assert.ok(!rule(".lanebar span").includes("var(--accent)"), "lane progress must not render in danger red");
  assert.ok(rule(".lanebar span").includes("#3fa34d"), "lane progress is green-on-graphite");
  // the rest of the semantic set holds: done green, gated amber, concurrent violet, .err keeps the red
  assert.ok(rule(".b-done").includes("#7fd191"));
  assert.ok(rule(".b-gated").includes("#e3b64f"));
  assert.ok(rule(".b-conc").includes("#b9a5ee"));
  assert.ok(rule(".err").includes("var(--accent)"), "danger keeps the accent");
});

test("applyFilter: bucket, priority, and text terms compose; empty filter passes all", () => {
  assert.strictEqual(B.applyFilter(snap.rows, {}).length, snap.rows.length);
  const done = B.applyFilter(snap.rows, { bucket: "done" });
  assert.strictEqual(done.length, snap.summary.buckets.done);
  assert.ok(done.every((r) => r.bucket === "done"));
  const p0gated = B.applyFilter(snap.rows, { bucket: "gated", pri: "P0" });
  assert.ok(p0gated.every((r) => r.bucket === "gated" && r.pri === "P0"));
  // text search hits id (case-insensitive) and requirement text
  const byId = B.applyFilter(snap.rows, { q: "fs-24" });
  assert.ok(byId.some((r) => r.id === "FS-24"));
  const term = snap.rows.find((r) => r.text.includes("conserves mass"));
  assert.ok(B.applyFilter(snap.rows, { q: "conserves mass" }).includes(term));
  assert.strictEqual(B.applyFilter(snap.rows, { q: "zz-no-such-term-zz" }).length, 0);
});

test("countsByBucket + resultsLine: legend counts match the summary; readout has both states", () => {
  assert.deepStrictEqual(B.countsByBucket(snap.rows), snap.summary.buckets);
  assert.strictEqual(B.resultsLine(188, 188), "all 188 requirements");
  assert.strictEqual(B.resultsLine(7, 188), "7 of 188 requirements match");
});

test("lanesHTML: filtered rows render only matching lanes, selected chip is marked, empty state explicit", () => {
  const gated = B.applyFilter(snap.rows, { bucket: "gated" });
  const h = B.lanesHTML(snap, esc, gated, gated[0].id);
  assert.strictEqual((h.match(/class="rowchip /g) || []).length, gated.length);
  assert.ok(h.includes('aria-pressed="true"'));
  assert.strictEqual((h.match(/ selected"/g) || []).length, 1);
  assert.ok(h.includes("lanebar"));   // per-lane completion bar
  assert.ok(B.lanesHTML(snap, esc, [], null).includes("No requirements match"));
});

test("lanesHTML: lanes wrap in ordered phase groups; restructure phases lead [board content rewrite]", () => {
  const h = B.lanesHTML(snap, esc);
  const labels = B.LANE_GROUPS.map((g) => esc(g.label)).filter((l) => h.includes(l));
  const positions = labels.map((l) => h.indexOf(l));
  assert.deepStrictEqual([...positions].sort((a, b) => a - b), positions, "groups render in taxonomy order");
  assert.ok(h.indexOf(esc("Restructure · edge breaks")) >= 0, "edge-breaks group renders");
  assert.strictEqual(B.groupOf("BD"), "Restructure · edge breaks");
  assert.strictEqual(B.groupOf("ZZ"), "Other lanes");   // an unmapped lane is never dropped
  const edge = snap.rows.filter((r) => ["BD", "PX", "AP"].includes(r.lane));
  const edgeDone = edge.filter((r) => r.bucket === "done").length;
  assert.ok(h.includes(edgeDone + "/" + edge.length + " · "), "edge-breaks group rollup present");
});

test("lanesHTML: every present lane belongs to exactly one rendered group; per-row invariant holds", () => {
  const h = B.lanesHTML(snap, esc);
  const lanes = [...new Set(snap.rows.map((r) => r.lane))];
  const groups = new Set(lanes.map((l) => B.groupOf(l)));
  assert.strictEqual((h.match(/class="lanegroup"/g) || []).length, groups.size, "one section per present group");
  assert.strictEqual((h.match(/class="rowchip /g) || []).length, snap.rows.length, "one chip per row under grouping");
});
