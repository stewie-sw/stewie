// [REQ:GW-10] the per-component monotonic request guard (hardens GW-02): a slow site-A load resolving
// after a switch to site-B must NOT overwrite B's raster/physics/inspector state. These node tests prove
// the guard's runtime behavior (the wrong-site race + per-component isolation); the static wiring gate —
// that reqGuard is actually held by the raster (MissionTerrain3D), physics/profile (MissionCrossSection),
// and inspector (SelectionInspector) surfaces — is stewie/server/test_gw10_request_guard.py, the python
// [REQ:GW-10] citation req_trace.py counts (req_trace scans python test_*.py, not the JS tier).
"use strict";
const assert = require("node:assert");
const { test } = require("node:test");
const { makeReqGuard } = require("./reqGuard.js");

test("current(tok) is true only for the latest issued token", () => {
    const g = makeReqGuard();
    const a = g.next();
    assert.strictEqual(g.current(a), true);
    const b = g.next();                          // a new load starts
    assert.strictEqual(g.current(a), false);     // the earlier token is now stale
    assert.strictEqual(g.current(b), true);
});

test("the wrong-site race: A(slow) then B(fast) -> B kept, A's late resolve dropped", () => {
    const g = makeReqGuard();
    const tokA = g.next();                        // fetch A starts (slow — site A)
    const tokB = g.next();                        // user switches -> fetch B starts (site B)
    assert.strictEqual(g.current(tokB), true);    // B resolves first: keep it
    assert.strictEqual(g.current(tokA), false);   // A resolves later: DROP (else it overwrites B with A's data)
});

test("bump() invalidates the in-flight token (unmount / explicit site change)", () => {
    const g = makeReqGuard();
    const tok = g.next();
    assert.strictEqual(g.current(tok), true);
    g.bump();
    assert.strictEqual(g.current(tok), false);
});

test("independent component guards do not interfere", () => {
    const g1 = makeReqGuard(), g2 = makeReqGuard();
    const t1 = g1.next(), t2 = g2.next();
    g1.next();                                    // bump g1 only
    assert.strictEqual(g1.current(t1), false);
    assert.strictEqual(g2.current(t2), true);     // g2's in-flight token is untouched
});
