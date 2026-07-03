"""[REQ:BP-12] the PyPI publish workflow's release gate must install from the HASHED dev lock, exactly
like CI -- so the pre-release gate runs against the same dependency versions CI validated (a supply-chain
+ reproducibility control right before a public release). It must NOT fall back to an unpinned
`pip install -e .[dev]`."""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel: str) -> str:
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_publish_gate_installs_from_the_hashed_lock():
    text = _read(".github/workflows/publish-stewie.yml")
    assert "requirements-dev.lock" in text, "the publish gate must install from the hashed dev lock (BP-12)"
    assert "--require-hashes" in text, "the publish gate must use --require-hashes (supply-chain parity with CI)"
    assert "pip install -e . --no-deps" in text, "install the package with --no-deps after the locked deps"


def test_publish_gate_does_not_use_the_unpinned_extras_install():
    text = _read(".github/workflows/publish-stewie.yml")
    # the old unpinned form resolves fresh versions -> the gate could pass against different deps than CI.
    assert "pip install -e .[dev]" not in text, (
        "the unpinned `pip install -e .[dev]` in the publish gate is a supply-chain gap (BP-12)")


def test_publish_gate_runs_the_traceability_check_like_ci():
    # BP-12 recommendation: run req_trace in the publish gate too, matching the CI parity intent.
    text = _read(".github/workflows/publish-stewie.yml")
    assert "req_trace.py" in text, "the publish gate should run the requirements-traceability check (CI parity)"


def test_ci_and_publish_agree_on_the_lock_install():
    # both gates install the SAME way -> no drift between the CI validation and the release gate.
    ci = _read(".github/workflows/ci.yml")
    pub = _read(".github/workflows/publish-stewie.yml")
    for needle in ("--require-hashes -r requirements-dev.lock", "pip install -e . --no-deps"):
        assert needle in ci, f"CI is expected to already use `{needle}`"
        assert needle in pub, f"the publish gate must match CI's `{needle}` install (BP-12)"
