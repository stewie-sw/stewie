// FS-24 (node:test): the nav-pane stat lines are pure (payload -> HTML string), so unit-testable without
// a browser. The fetch + innerHTML + canvas plots stay in cockpit.js. Behavior preserved.
// Run: node --test stewie/server/web/assets/nav_stats_html.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const N = require("./nav_stats_html.js");
const esc = require("./htmlesc.js").esc;

test("driveStatsHTML: arrived run shows routed/ticks/recoveries/cross-track/stages", () => {
  const b = { arrived: true, routed_m: 42.5, n_ticks: 800, n_recoveries: 2,
              deviation: { mean_m: 0.12, max_m: 0.44 }, stages: ["route_leg", "track_plan"] };
  const h = N.driveStatsHTML(b, esc);
  assert.ok(h.includes("arrived") && h.includes("var(--accent)"));
  assert.ok(h.includes("routed <b>42.5 m</b>") && h.includes("800</b> control ticks"));
  assert.ok(h.includes("2</b> recoveries") && h.includes("0.12 m</b> / max <b>0.44 m"));
  assert.ok(h.includes("route_leg → track_plan"));
});

test("driveStatsHTML: not-arrived shows the red reason (escaped)", () => {
  const h = N.driveStatsHTML({ arrived: false, reason: "<stuck>", deviation: {}, stages: [] }, esc);
  assert.ok(h.includes("#e8273f") && h.includes("&lt;stuck&gt;"));
});

test("slamStatsHTML: fused ATE vs baseline with reduction factor", () => {
  const h = N.slamStatsHTML({ ate_aligned_m: 0.9, abs_max_err_m: 1.2, baseline_abs_max_err_m: 3.6, reduction_x: 3.0 });
  assert.ok(h.includes("fused ATE <b>0.9 m</b>") && h.includes("vs baseline <b>3.6 m</b>"));
  assert.ok(h.includes("3× tighter"));
});

test("leaveOneOutHTML: renders each fix's drift contribution", () => {
  const h = N.leaveOneOutHTML({ leave_one_out: { apriltag: { contribution_m: 0.5 }, dem: { contribution_m: 0.2 } } });
  assert.ok(h.includes("apriltag <b>+0.5 m</b>") && h.includes("dem <b>+0.2 m</b>"));
});

test("errLine: red span, escapes the message", () => {
  assert.ok(N.errLine("boom", esc).includes('color:#e8273f') && N.errLine("boom", esc).includes("boom"));
  assert.ok(N.errLine("<x>", esc).includes("&lt;x&gt;"));
});
