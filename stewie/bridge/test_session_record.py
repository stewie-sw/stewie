"""B3.3 replay/debrief record (SessionRecord, PRD artifact 9): per-step the operator-DELIVERED view
plus the simulator TRUTH state, hash-anchored, with a replay function that reproduces the recorded run.

The training session records each leg as (truth, operator-seen) so the debrief can scrub seen-vs-actual
divergence; ``replay`` reproduces the recorded run from the record alone (a view over the artifact, not
a recomputation). Pure-python + numpy, deterministic; round-trips through JSON.
"""
import json

import numpy as np

from stewie.bridge import injector as inj
from stewie.bridge import session_record as sr
from stewie.bridge import telemetry as tl


def _run(injr, n_steps, seed=0):
    """Drive a recorded session: at each step the truth advances, telemetry is injected, and what
    the operator SEES is whatever survived the link. Returns the populated SessionRecord."""
    rng = np.random.default_rng(seed)
    rec = sr.SessionRecord(profile_name="test", seed=injr.seed)
    for k in range(n_steps):
        t_s = k * 1.0
        truth = {"step": k, "x": float(rng.normal()), "y": float(rng.normal())}
        msg = inj.OperatorMessage(t_s=t_s, payload_bytes=200, kind="pose", body=truth)
        result = injr.inject([msg])[0]
        seen = result.message.body if result.delivered else None
        rec.record_step(t_s=t_s, truth=truth, seen=seen, delivered=result.delivered,
                        reason=result.reason)
    return rec


def test_records_per_step_truth_and_operator_view():
    injr = inj.TelemetryInjector(tl.LinkProfile(drop_prob=0.3), seed=11)
    rec = _run(injr, n_steps=50)
    assert len(rec.steps) == 50
    # truth is recorded on every step; the seen view is None exactly when the leg was not delivered
    assert all(s.truth is not None for s in rec.steps)
    for s in rec.steps:
        assert (s.seen is None) == (not s.delivered)
    # divergence: at least one step the operator did not see (drop_prob=0.3 over 50 steps)
    assert any(not s.delivered for s in rec.steps)


def test_replay_reproduces_the_recorded_run():
    """replay(record) reproduces the recorded run step-for-step: same truth, same operator-seen
    view, same delivered/reason -- a view over the artifact, byte-identical to what was recorded."""
    injr = inj.TelemetryInjector(tl.LinkProfile(drop_prob=0.4, downlink_kbps=64.0), seed=5)
    rec = _run(injr, n_steps=80)
    played = sr.replay(rec)
    assert len(played) == len(rec.steps)
    for orig, rp in zip(rec.steps, played):
        assert rp.t_s == orig.t_s
        assert rp.truth == orig.truth
        assert rp.seen == orig.seen
        assert rp.delivered == orig.delivered
        assert rp.reason == orig.reason


def test_record_round_trips_through_json():
    injr = inj.TelemetryInjector(tl.LinkProfile(drop_prob=0.2), seed=9)
    rec = _run(injr, n_steps=30)
    blob = rec.to_json()
    back = sr.SessionRecord.from_json(blob)
    assert back.profile_name == rec.profile_name
    assert back.seed == rec.seed
    assert len(back.steps) == len(rec.steps)
    # a replay of the rebuilt record matches a replay of the original
    assert [(s.truth, s.seen, s.delivered) for s in sr.replay(back)] == \
           [(s.truth, s.seen, s.delivered) for s in sr.replay(rec)]
    json.loads(blob)                                         # is valid JSON


def test_debrief_summarizes_seen_vs_actual_divergence():
    injr = inj.TelemetryInjector(tl.LinkProfile(drop_prob=0.5), seed=2)
    rec = _run(injr, n_steps=100)
    deb = rec.debrief()
    assert deb["steps"] == 100
    assert deb["delivered"] + deb["not_delivered"] == 100
    assert deb["not_delivered"] == sum(1 for s in rec.steps if not s.delivered)
    assert 0.0 <= deb["delivery_fraction"] <= 1.0
    assert deb["delivered"] == sum(1 for s in rec.steps if s.delivered)


def test_record_is_hash_anchored_and_tamper_evident():
    """The record carries a content hash over its steps; mutating a recorded step is detectable."""
    injr = inj.TelemetryInjector(tl.LinkProfile(drop_prob=0.1), seed=4)
    rec = _run(injr, n_steps=20)
    h0 = rec.content_hash()
    assert h0 == rec.content_hash()                          # stable
    rec.steps[0].truth["x"] = 999.0                          # tamper
    assert rec.content_hash() != h0
