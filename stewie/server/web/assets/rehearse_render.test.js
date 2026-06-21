// REHEARSE (mission-ops screen 2, node:test): the Rehearse-and-compare candidate cards are PURE ->
// unit-testable without a browser. Run: node --test stewie/server/web/assets/rehearse_render.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const R = require("./rehearse_render.js");

// identity-ish escaper standing in for window.STEWIE_HTMLESC.esc (real one is tested in htmlesc.test.js).
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// a real /resync/compare payload shape (lode.resync.forward_compare), feasible-first ordered.
const FEASIBLE = {
  ok: true, objective: "duration", recommended: "nearest",
  futures: [
    { algorithm: "nearest", resolved: "nearest", optimality: "heuristic", objective_exact: false,
      time_s: 3600, energy_MJ: 4.2, recharges: 1, charges: 1, feasible: true, infeasible_reasons: [],
      return_to_lander: { feasible: true, margin_J: 5.0e5, return_distance_m: 42.0 },
      objectives_total: 4, blocked_legs: 0, hazard_flags: 0, wall_s: 0.18 },
    { algorithm: "two_opt", resolved: "two_opt", optimality: "heuristic", objective_exact: false,
      time_s: 4000, energy_MJ: 4.6, recharges: 1, charges: 1, feasible: true, infeasible_reasons: [],
      return_to_lander: { feasible: true, margin_J: 3.0e5, return_distance_m: 50.0 },
      objectives_total: 4, blocked_legs: 0, hazard_flags: 0, wall_s: 0.20 },
  ],
};

test("rehearseCardsHTML: honest empty state when no plan / no candidates", () => {
  assert.ok(R.rehearseCardsHTML(null, esc).includes("No candidates"));
  assert.ok(R.rehearseCardsHTML({ futures: [] }, esc).includes("No candidates"));
});

test("rehearseCardsHTML: one card per candidate, feasibility surfaced FIRST", () => {
  const html = R.rehearseCardsHTML(FEASIBLE, esc);
  assert.ok(html.includes("nearest"), "candidate algorithm rendered");
  assert.ok(html.includes("two_opt"), "second candidate rendered");
  // feasibility is the leading status badge text
  assert.ok(html.includes("FEASIBLE"), "feasible badge present");
  // the review's required fields: margins, completion, duration, energy, charge cycles, optimality
  assert.ok(html.includes("return-to-lander") || html.includes("return"), "return-to-lander margin shown");
  assert.ok(html.includes("4/4") || html.includes("objectives"), "objective completion shown");
  assert.ok(html.includes("MJ"), "energy shown");
  assert.ok(html.includes("charge") || html.includes("recharge"), "charge cycles shown");
  assert.ok(html.includes("heuristic"), "optimality claim shown");
  // the head of the feasible-first ranking is marked recommended
  assert.ok(html.includes("RECOMMENDED"), "recommended head marked");
});

test("rehearseCardsHTML: INVARIANT -- an infeasible card never sits above a feasible one", () => {
  // payload as the route returns it (already feasible-first ordered); render must PRESERVE that order
  // and never reorder a faster-but-infeasible candidate above a slower feasible one.
  const payload = {
    ok: true, objective: "duration", recommended: "feasible_slow",
    futures: [
      { algorithm: "feasible_slow", time_s: 9000, energy_MJ: 9, feasible: true, infeasible_reasons: [],
        return_to_lander: { feasible: true, margin_J: 1 }, objectives_total: 2, charges: 0,
        recharges: 0, blocked_legs: 0, hazard_flags: 0, optimality: "exact", wall_s: 0.1 },
      { algorithm: "fast_infeasible", time_s: 100, energy_MJ: 1, feasible: false,
        infeasible_reasons: ["1 route leg(s) have no safe corridor"],
        return_to_lander: { feasible: false, margin_J: -2 }, objectives_total: 2, charges: 0,
        recharges: 0, blocked_legs: 1, hazard_flags: 0, optimality: "heuristic", wall_s: 0.1 },
    ],
  };
  const html = R.rehearseCardsHTML(payload, esc);
  assert.ok(html.indexOf("feasible_slow") < html.indexOf("fast_infeasible"),
    "feasible candidate rendered ABOVE the faster infeasible one");
  assert.ok(html.includes("INFEASIBLE"), "infeasible badge present");
  assert.ok(html.includes("no safe corridor"), "infeasible reason surfaced");
});

test("rehearseCardsHTML: all-infeasible -> no recommendation, honest banner", () => {
  const payload = {
    ok: true, objective: "duration", recommended: null,
    futures: [
      { algorithm: "a", time_s: 5, energy_MJ: 1, feasible: false, infeasible_reasons: ["stranded"],
        return_to_lander: { feasible: false, margin_J: -1 }, objectives_total: 1, charges: 0,
        recharges: 0, blocked_legs: 0, hazard_flags: 0, optimality: "heuristic", wall_s: 0.1 },
    ],
  };
  const html = R.rehearseCardsHTML(payload, esc);
  assert.ok(!html.includes("RECOMMENDED"), "no recommended badge when nothing is feasible");
  assert.ok(html.includes("No feasible candidate"), "honest no-feasible banner");
});

test("rehearseCardsHTML: escapes candidate-derived text (no raw injection)", () => {
  const payload = {
    ok: true, objective: "duration", recommended: null,
    futures: [
      { algorithm: "<img src=x>", time_s: 5, energy_MJ: 1, feasible: false,
        infeasible_reasons: ["<script>alert(1)</script>"], return_to_lander: { feasible: false, margin_J: -1 },
        objectives_total: 1, charges: 0, recharges: 0, blocked_legs: 0, hazard_flags: 0,
        optimality: "heuristic", wall_s: 0.1 },
    ],
  };
  const html = R.rehearseCardsHTML(payload, esc);
  assert.ok(!html.includes("<img src=x>"), "raw algorithm not injected");
  assert.ok(!html.includes("<script>alert(1)</script>"), "raw reason not injected");
  assert.ok(html.includes("&lt;img src=x&gt;"), "algorithm escaped");
});
