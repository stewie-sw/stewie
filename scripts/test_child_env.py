"""[REQ:AR-016] The minimal-allowlist child env keeps subprocess tests from leaking ambient credentials
into pytest failure output, and NO test in the code tree spawns a subprocess with the whole ambient
environment (the credential-exfiltration channel a 2026-07-16 review found and rotated over)."""
import re
import subprocess
import sys
from pathlib import Path

from scripts.child_env import child_env

_REPO = Path(__file__).resolve().parent.parent
_CANARY = "CANARY-do-not-propagate-3f9a2"


def test_child_env_drops_ambient_secrets_but_keeps_runtime_knobs(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", _CANARY)
    monkeypatch.setenv("STEWIE_API_KEY", _CANARY + "-2")
    e = child_env()
    assert "PATH" in e                                   # a real runtime knob is kept
    assert e["PYTHONNOUSERSITE"] == "1"                  # clean-import hardening (venv site-packages only)
    assert "ALPACA_API_KEY" not in e and "STEWIE_API_KEY" not in e
    assert not any(_CANARY in v for v in e.values())     # no ambient secret survives, by value either


def test_a_failing_child_never_renders_the_canary(monkeypatch):
    """The real exfiltration path: a child fails and pytest renders subprocess.run's kwargs. With child_env
    the ambient secret is not in that kwargs object, so it cannot appear in the failure text."""
    monkeypatch.setenv("ALPACA_API_SECRET", _CANARY)
    try:
        subprocess.run([sys.executable, "-c", "import sys; sys.exit(3)"],
                       env=child_env(), check=True, capture_output=True)
        raise AssertionError("the child was supposed to fail")
    except subprocess.CalledProcessError as e:
        assert _CANARY not in repr(e)                    # the exception pytest would render is clean
        assert _CANARY not in repr(vars(e))


def test_the_minimal_env_child_still_imports_the_workspace():
    """Non-vacuous: a minimal-env child still imports the workspace packages (the venv resolves the editable
    installs for its own interpreter), so the wrapper does not break the tests it replaces -- and it needs
    NO PYTHONPATH, which is what fixes the prior 'PYTHONPATH replaces the workspace' portability failure."""
    r = subprocess.run([sys.executable, "-c", "import stewie, stewie_bodies, dart, lode"],
                       env=child_env(), capture_output=True)
    assert r.returncode == 0, r.stderr.decode()


def test_no_unwrapped_whole_ambient_env_subprocess_in_the_repo():
    """[AR-016 acceptance] Repo scan: no *.py under the code tree hands the whole ambient environment to a
    subprocess (``env={**os.environ...}`` / ``env=os.environ`` / ``os.environ.copy()``). The approved
    constructor scripts/child_env.py is the ONLY sanctioned way to build a child env."""
    # the WHOLE-env leak forms only: the {**os.environ} splat, os.environ.copy(), or bare os.environ passed
    # as a subprocess env=. A single-value read (os.environ.get(...)/.pop(...)) is NOT a leak and is excluded.
    pat = re.compile(r"\{\s*\*\*\s*os\.environ\b|env\s*=\s*os\.environ(?:\.copy\(\))?\s*[,)]")
    offenders: list[str] = []
    for d in ("stewie", "dart", "lode", "leap", "forge", "scripts", "viz"):
        base = _REPO / d
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if p.name in ("child_env.py", "test_child_env.py"):   # the gate's own files reference the pattern
                continue
            txt = p.read_text(encoding="utf-8", errors="ignore")
            for m in pat.finditer(txt):
                ln = txt[: m.start()].count("\n") + 1
                offenders.append(f"{p.relative_to(_REPO)}:{ln}")
    assert not offenders, (
        "whole-ambient-env subprocess calls leak every secret when the child fails; route them through "
        "scripts.child_env.child_env(extra=...):\n  " + "\n  ".join(offenders))
