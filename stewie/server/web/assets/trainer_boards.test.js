// TR-02/03/04 (node:test): the trainer board renderers are pure (esc injected) -> unit-testable
// without a browser. Run: node --test stewie/server/web/assets/trainer_boards.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const T = require("./trainer_boards.js");

const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function _history(extra) {
  return Object.assign({
    ok: true, is_director: true, count: 2,
    sessions: [
      { session_id: "aaaaaaaa1111", profile: "comm_dropout", objective: "time", recorded_at: 2,
        public: { completed: true, objectives_total: 2, legs_delivered: 3, legs_total: 5,
                  comm_delivered_frac: 0.6, energy_MJ: 1.234 },
        makespan: { makespan_s: 1200, optimal_s: 1000, makespan_ratio: 1.20 },
        truth: { energy_divergence_J: 4200, pose_divergence_mean_m: 1.5, pose_divergence_max_m: 3.2,
                 operator_missed_legs: ["legB", "legD"] } },
      { session_id: "bbbbbbbb2222", profile: "ideal", objective: "time", recorded_at: 1,
        public: { completed: true, objectives_total: 2, legs_delivered: 5, legs_total: 5,
                  comm_delivered_frac: 1.0, energy_MJ: 1.000 },
        makespan: { makespan_s: 1050, optimal_s: 1000, makespan_ratio: 1.05 },
        truth: { energy_divergence_J: 800, pose_divergence_mean_m: 0.4, pose_divergence_max_m: 0.9,
                 operator_missed_legs: [] } },
    ],
  }, extra);
}

// ---- TR-03 PROGRAM board --------------------------------------------------------------------------
test("programBoardHTML: empty state when no sessions recorded", () => {
  const html = T.programBoardHTML({ ok: true, is_director: false, count: 0, sessions: [] }, esc);
  assert.match(html, /No recorded sessions yet/);
});

test("programBoardHTML: leaderboard ranks closest-to-optimal first", () => {
  const html = T.programBoardHTML(_history(), esc);
  assert.match(html, /LEADERBOARD/);
  // the ideal run (1.05x) should rank ABOVE the comm_dropout run (1.20x): its 8-char id appears first
  assert.ok(html.indexOf("bbbbbbbb") < html.indexOf("aaaaaaaa"),
    "the lower makespan ratio must lead the leaderboard");
  assert.match(html, /1/);
});

test("programBoardHTML: history table lists every recorded session newest-first", () => {
  const html = T.programBoardHTML(_history(), esc);
  assert.match(html, /SESSION HISTORY/);
  assert.match(html, /aaaaaaaa/);
  assert.match(html, /bbbbbbbb/);
  // 2 recorded runs reported
  assert.match(html, /2 recorded runs/);
});

test("programBoardHTML: makespan trend names improving/regressing", () => {
  // history is newest-first: newest 1.20 > oldest 1.05 -> regressing
  const html = T.programBoardHTML(_history(), esc);
  assert.match(html, /regressing/);
  // reverse the order -> improving
  const h = _history();
  h.sessions.reverse();
  assert.match(T.programBoardHTML(h, esc), /improving/);
});

test("programBoardHTML: a slow run (>1.15x) is flagged red", () => {
  const html = T.programBoardHTML(_history(), esc);
  assert.match(html, /#e8273f/);   // the 1.20x run gets the warn color
});

// ---- TR-02 DIRECTOR truth board -------------------------------------------------------------------
test("truthBoardHTML: refuses for a non-director", () => {
  const html = T.truthBoardHTML(_history({ is_director: false }), esc);
  assert.match(html, /director-only/);
});

test("truthBoardHTML: shows believed-vs-true pose + energy divergence in magenta", () => {
  const html = T.truthBoardHTML(_history(), esc);
  assert.match(html, /pose err mean/);
  assert.match(html, /pose err max/);
  assert.match(html, /energy div/);
  assert.ok(html.includes(T.TRUTH), "truth values must be magenta (MO-04)");
  assert.match(html, /1\.50/);   // session aaaa mean pose error
  assert.match(html, /3\.20/);   // session aaaa max pose error
});

test("truthBoardHTML: empty state when no truth data", () => {
  const html = T.truthBoardHTML({ ok: true, is_director: true, count: 0, sessions: [] }, esc);
  assert.match(html, /No recorded sessions with truth/);
});

// ---- TR-04 DEBRIEF scrubber -----------------------------------------------------------------------
function _debrief() {
  return {
    session_id: "aaaaaaaa1111",
    legs: [
      { leg: "legA", bx: 1.0, by: 0.0, tx: 1.2, ty: 0.1, soc: 0.95, slip: 0.01, slope_deg: 3.0,
        true_J: 5200, nominal_J: 5000 },
      { leg: "legB", bx: 8.0, by: 4.0, tx: 9.5, ty: 5.2, soc: 0.80, slip: 0.22, slope_deg: 18.0,
        true_J: 9100, nominal_J: 8000 },
    ],
    operator_missed_legs: ["legB"],
    energy_divergence_J: 1300,
  };
}

test("debriefScrubberHTML: empty state when no run loaded", () => {
  assert.match(T.debriefScrubberHTML({ legs: [] }, 0, esc), /No recorded run loaded/);
});

test("debriefScrubberHTML: renders the indexed leg with seen/estimated/truth", () => {
  const html = T.debriefScrubberHTML(_debrief(), 0, esc);
  assert.match(html, /leg 1 \/ 2/);
  assert.match(html, /legA/);
  assert.match(html, /SEEN \(operator\)/);
  assert.match(html, /ESTIMATED pose/);
  assert.match(html, /TRUTH pose/);
  assert.ok(html.includes(T.TRUTH), "truth pose must be magenta");
  assert.match(html, /delivered to operator/);   // legA was not in missed
});

test("debriefScrubberHTML: a dropped leg is marked DROPPED", () => {
  const html = T.debriefScrubberHTML(_debrief(), 1, esc);
  assert.match(html, /leg 2 \/ 2/);
  assert.match(html, /legB/);
  assert.match(html, /DROPPED/);   // legB is in operator_missed_legs
});

test("debriefScrubberHTML: clamps the index into range", () => {
  const html = T.debriefScrubberHTML(_debrief(), 99, esc);
  assert.match(html, /leg 2 \/ 2/);   // clamped to the last leg
  const lo = T.debriefScrubberHTML(_debrief(), -5, esc);
  assert.match(lo, /leg 1 \/ 2/);
});

test("debriefScrubberHTML: pose error is the believed-vs-true gap", () => {
  // legB: believed (8,4) vs true (9.5,5.2) -> hypot(1.5,1.2)=1.92
  const html = T.debriefScrubberHTML(_debrief(), 1, esc);
  assert.match(html, /1\.92/);
});
