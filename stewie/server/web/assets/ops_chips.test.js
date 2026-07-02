// frontend-audit C (node:test): the pure ops-chip formatters -- health / link-state / provenance /
// mission-time. Run: node --test stewie/server/web/assets/ops_chips.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const C = require("./ops_chips.js");

test("hhmm/solvedStamp/plannedStamp: wall-clock HH:MM from a timestamp", () => {
  const ts = new Date(2026, 6, 1, 14, 32, 9).getTime();     // 2026-07-01 14:32:09 local
  assert.strictEqual(C.hhmm(ts), "14:32");
  assert.strictEqual(C.solvedStamp(ts), "plan forecast · solved 14:32");
  assert.strictEqual(C.plannedStamp(ts), "planned 14:32");
  assert.strictEqual(C.hhmm(new Date(2026, 0, 5, 7, 5).getTime()), "07:05");   // zero-padded
});

test("fmtDur/missionClock: compact elapsed/total, whole hours past 100 h", () => {
  assert.strictEqual(C.fmtDur(0), "0h00m");
  assert.strictEqual(C.fmtDur(12 * 3600 + 4 * 60), "12h04m");
  assert.strictEqual(C.fmtDur(2449.3 * 3600), "2449h");     // mission scale collapses to hours
  assert.strictEqual(C.fmtDur(-5), "0h00m");                 // clamped, never negative
  assert.strictEqual(C.missionClock(0, 2449.3 * 3600), "T+0h00m / 2449h");
  assert.strictEqual(C.missionClock(3600 * 3 + 60, 3600 * 8), "T+3h01m / 8h00m");
});

test("fmtUp: minutes / hours / days tiers", () => {
  assert.strictEqual(C.fmtUp(59), "0m");
  assert.strictEqual(C.fmtUp(3 * 3600 + 12 * 60), "3h 12m");
  assert.strictEqual(C.fmtUp(2 * 86400 + 5 * 3600), "2d 5h");
});

test("healthChipView: ok / degraded(subsystems named) / unreachable", () => {
  const ok = C.healthChipView({ status: "ok", uptime_s: 11520, audit: { degraded: false }, revocation: { degraded: false } });
  assert.strictEqual(ok.level, "ok");
  assert.strictEqual(ok.text, "● OK · up 3h 12m");
  const deg = C.healthChipView({ status: "degraded", uptime_s: 60, audit: { degraded: true }, revocation: { degraded: false } });
  assert.strictEqual(deg.level, "degraded");
  assert.ok(deg.text.includes("DEGRADED (audit)"));
  assert.strictEqual(deg.color, "#e0b300");
  const both = C.healthChipView({ status: "degraded", uptime_s: 60, audit: { degraded: true }, revocation: { degraded: true } });
  assert.ok(both.text.includes("(audit+revocation)"));
  const down = C.healthChipView(null);
  assert.strictEqual(down.level, "down");
  assert.strictEqual(down.color, "#e8273f");
});

test("healthTransition: alerts fire only on a level CHANGE (never the first poll)", () => {
  assert.strictEqual(C.healthTransition(null, "ok"), null);          // first poll: quiet
  assert.strictEqual(C.healthTransition("ok", "ok"), null);          // steady state: quiet
  assert.strictEqual(C.healthTransition("ok", "degraded").sev, "warn");
  assert.strictEqual(C.healthTransition("ok", "down").sev, "error");
  assert.strictEqual(C.healthTransition("degraded", "ok").sev, "info");
});

test("linkChipView: NO LINK / CONNECTING / LIVE n Hz / DROPPED", () => {
  assert.deepStrictEqual(C.linkChipView("nolink", 1), { text: "NO LINK", color: "#8a8a93" });
  assert.strictEqual(C.linkChipView("connecting", 1).text, "CONNECTING…");
  assert.strictEqual(C.linkChipView("live", 1.0).text, "LIVE 1 Hz");
  assert.strictEqual(C.linkChipView("live", 0.2).text, "LIVE 5 Hz");
  assert.strictEqual(C.linkChipView("live", 2.0).text, "LIVE 0.5 Hz");
  const drop = C.linkChipView("dropped", 1);
  assert.ok(drop.text.startsWith("DROPPED"));
  assert.strictEqual(drop.color, "#e8273f");
});
