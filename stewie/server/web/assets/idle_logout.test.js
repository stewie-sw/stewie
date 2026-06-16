// #133 (node:test): the idle-logout state machine is PURE (injected clock + scheduler) -> unit-testable.
// The DOM activity listeners + the actual /auth/logout call live in cockpit.js (wireIdleLogout); this
// covers the clamp, the expiry predicate, and the monitor's start/touch/tick/stop behaviour.
// Run: node --test stewie/server/web/assets/idle_logout.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const I = require("./idle_logout.js");

test("clampMinutes: sensible default + floor/ceiling, rounds, rejects junk", () => {
  assert.strictEqual(I.clampMinutes(30), 30);
  assert.strictEqual(I.clampMinutes(0), I.DEFAULT_MIN);      // 0 -> default, never "log out instantly"
  assert.strictEqual(I.clampMinutes(-5), I.DEFAULT_MIN);
  assert.strictEqual(I.clampMinutes("nope"), I.DEFAULT_MIN);
  assert.strictEqual(I.clampMinutes(undefined), I.DEFAULT_MIN);
  assert.strictEqual(I.clampMinutes(0.4), 1);                // below floor -> 1 min floor
  assert.strictEqual(I.clampMinutes(9999), 240);            // above ceiling -> 240 min cap
  assert.strictEqual(I.clampMinutes(14.6), 15);             // rounds
});

test("isExpired: true only once elapsed reaches the idle window", () => {
  assert.strictEqual(I.isExpired(1000, 60000, 1000 + 59999), false);
  assert.strictEqual(I.isExpired(1000, 60000, 1000 + 60000), true);
  assert.strictEqual(I.isExpired(1000, 60000, 1000 + 60001), true);
});

// A controllable clock + scheduler so the monitor is fully deterministic (no real timers).
function fakeEnv() {
  let t = 0;
  const ivs = new Map();
  let nextId = 1;
  return {
    now: () => t,
    advance: (ms) => { t += ms; },
    setInterval: (fn, _ms) => { const id = nextId++; ivs.set(id, fn); return id; },
    clearInterval: (id) => { ivs.delete(id); },
    activeIntervals: () => ivs.size,
  };
}

test("monitor fires onIdle exactly once after the idle window with no activity", () => {
  const env = fakeEnv();
  let fired = 0;
  const m = I.IdleMonitor({ idleMinutes: 1, checkMs: 10000, onIdle: () => { fired++; },
    now: env.now, setInterval: env.setInterval, clearInterval: env.clearInterval });
  m.start();
  assert.strictEqual(m.isRunning(), true);
  env.advance(59000); m.tick(); assert.strictEqual(fired, 0);    // still within the 60s window
  env.advance(2000);  m.tick(); assert.strictEqual(fired, 1);    // crossed 60s -> fired
  env.advance(60000); m.tick(); assert.strictEqual(fired, 1);    // never fires twice
  assert.strictEqual(m.isRunning(), false);                      // stops itself after firing
  assert.strictEqual(env.activeIntervals(), 0);                  // and clears its interval
});

test("touch() resets the window so active use never logs out", () => {
  const env = fakeEnv();
  let fired = 0;
  const m = I.IdleMonitor({ idleMinutes: 1, onIdle: () => { fired++; },
    now: env.now, setInterval: env.setInterval, clearInterval: env.clearInterval });
  m.start();
  for (let i = 0; i < 10; i++) { env.advance(50000); m.touch(); m.tick(); }   // activity every 50s < 60s
  assert.strictEqual(fired, 0);
  env.advance(61000); m.tick();                                  // finally go idle
  assert.strictEqual(fired, 1);
});

test("stop() disarms; touch is ignored while stopped", () => {
  const env = fakeEnv();
  let fired = 0;
  const m = I.IdleMonitor({ idleMinutes: 1, onIdle: () => { fired++; },
    now: env.now, setInterval: env.setInterval, clearInterval: env.clearInterval });
  m.start();
  m.stop();
  assert.strictEqual(env.activeIntervals(), 0);
  env.advance(120000); m.touch(); m.tick();
  assert.strictEqual(fired, 0);                                  // a stopped monitor never fires
  assert.strictEqual(m.isRunning(), false);
});

test("setIdleMinutes reconfigures the window live (Settings change mid-session)", () => {
  const env = fakeEnv();
  let fired = 0;
  const m = I.IdleMonitor({ idleMinutes: 1, onIdle: () => { fired++; },
    now: env.now, setInterval: env.setInterval, clearInterval: env.clearInterval });
  m.start();
  m.setIdleMinutes(2);                                          // widen 1 -> 2 min, resets the window
  env.advance(61000); m.tick(); assert.strictEqual(fired, 0);   // 61s < 120s now -> not idle
  env.advance(60000); m.tick(); assert.strictEqual(fired, 1);   // crossed 120s -> fired
});

test("restart after firing re-arms cleanly (sign in -> idle -> sign in again)", () => {
  const env = fakeEnv();
  let fired = 0;
  const m = I.IdleMonitor({ idleMinutes: 1, onIdle: () => { fired++; },
    now: env.now, setInterval: env.setInterval, clearInterval: env.clearInterval });
  m.start(); env.advance(61000); m.tick(); assert.strictEqual(fired, 1);
  m.start();                                                     // signed in again
  assert.strictEqual(m.isRunning(), true);
  env.advance(61000); m.tick(); assert.strictEqual(fired, 2);
});
