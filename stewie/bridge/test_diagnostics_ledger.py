"""[REQ:AS-14] diagnostics-ledger acceptance (§25 Phase 12): every autonomy failure path produces a
ledger event (severity + correlation id), and no secret or truth-denied field is ever emitted."""
from stewie.bridge import diagnostics_ledger as dl


def test_every_failure_path_has_a_ledger_event():
    # the PRD diagnostics set: lifecycle / latency / dropped frames / QoS / command eligibility /
    # SAFE / faults -- each is a FAILURE_EVENTS kind that yields a severity-carrying ledger event
    for ev in ("lifecycle_error", "latency_breach", "dropped_frame", "qos_warning",
               "command_ineligible", "safe_event", "fault"):
        assert dl.is_failure(ev)
        e = dl.ledger_event("planning", ev, correlation_id="cid-1")
        assert e["event"] == ev and e["correlation_id"] == "cid-1"
        assert e["severity"] in ("warn", "error", "critical")


def test_safe_and_fault_are_critical():
    assert dl.ledger_event("exec", "safe_event", correlation_id="c")["severity"] == "critical"
    assert dl.ledger_event("diag", "fault", correlation_id="c")["severity"] == "critical"


def test_secret_fields_are_redacted():
    e = dl.ledger_event("rc", "command_ineligible", correlation_id="c",
                        api_key="SK-LIVE-123", token="abc", note="ok")
    assert e["fields"]["api_key"] == "[redacted]"
    assert e["fields"]["token"] == "[redacted]"
    assert e["fields"]["note"] == "ok"                       # non-secret passes through


def test_truth_denied_fields_are_never_emitted():
    e = dl.ledger_event("localization", "fault", correlation_id="c",
                        rover={"x": 1.0}, true_pose=[1, 2, 3], camera_poses_in_world=[{}],
                        seen_vs_actual=0.4, cov_trace=2.1)
    for k in ("rover", "true_pose", "camera_poses_in_world", "seen_vs_actual"):
        assert e["fields"][k] == "[truth-denied]", k
    assert e["fields"]["cov_trace"] == 2.1                   # a legitimate diagnostic passes through


def test_truth_topic_derived_keys_are_denied():
    # a field keyed after an autonomy_contract truth channel (/stewie/truth/pose -> stewie_truth_pose)
    e = dl.ledger_event("mapping", "fault", correlation_id="c", stewie_truth_pose=[0, 0, 0])
    assert e["fields"]["stewie_truth_pose"] == "[truth-denied]"


def test_nested_secret_and_truth_are_redacted():
    e = dl.ledger_event("planning", "qos_warning", correlation_id="c",
                        ctx={"secret": "s", "rover": [1], "queue_depth": 5})
    inner = e["fields"]["ctx"]
    assert inner["secret"] == "[redacted]" and inner["rover"] == "[truth-denied]"
    assert inner["queue_depth"] == 5


def test_non_failure_event_defaults_to_info():
    e = dl.ledger_event("sensing", "frame_published", correlation_id="c")
    assert not dl.is_failure("frame_published") and e["severity"] == "info"
