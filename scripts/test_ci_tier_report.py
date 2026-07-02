"""[REQ:PO-04] the gated tiers (chrono / godot / ros / gpu / ...) are a VISIBLE, checked CI
artifact, not silent skips: the tier report classifies the repo's REAL gate reasons, the
declared-gate census keeps the gated tiers non-empty (exactly what CI ``--require`` pins), and the
real ``--collect-only`` pass surfaces a module-level gate through the CLI. No fake execution — the
report itself is the honest artifact for tiers the runner cannot run."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_ROOT, "scripts", "ci_tier_report.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("ci_tier_report", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_classifier_buckets_the_repo_real_gate_reasons():
    """Every reason string here is verbatim from this tree's gates (not invented)."""
    mod = _load_module()
    assert mod.classify("could not import 'pychrono': No module named 'pychrono'") == "chrono"
    assert mod.classify("ROS 2 (rclpy) only present in the container") == "ros"
    assert mod.classify("no render egress (render with sidecar.tscn --cameras first)") == "godot"
    assert mod.classify("committed two-posture render-pair absent") == "godot"
    assert mod.classify("could not import 'torch': No module named 'torch'") == "gpu"
    assert mod.classify("Haworth sample not present") == "data"
    assert mod.classify("UDP sockets unavailable in this environment") == "network"
    assert mod.classify(
        "fresh-wheel smoke is opt-in (slow + network); set STEWIE_WHEEL_SMOKE=1") == "opt-in"


def test_declared_gate_census_keeps_the_gated_tiers_visible():
    """The exact property CI --require pins: each gated tier still declares >=1 real gate."""
    mod = _load_module()
    tiers = {mod.classify(reason) for _, reason in mod.scan_declared_gates()}
    assert {"chrono", "godot", "ros"} <= tiers, f"gated tier vanished from the tree: {tiers}"


def test_report_cli_surfaces_a_real_module_gate_and_requires_pass():
    """Real collect pass over the opt-in wheel smoke (deterministically gated without the env
    var): the module-level gate shows up as an env-skip, and the CI --require set passes."""
    env = {k: v for k, v in os.environ.items() if k != "STEWIE_WHEEL_SMOKE"}
    r = subprocess.run([sys.executable, _SCRIPT, "--require", "chrono", "--require", "godot",
                        "--require", "ros", "stewie/server/test_fresh_wheel.py"],
                       capture_output=True, text=True, cwd=_ROOT, env=env)
    assert r.returncode == 0, f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "[env-skip:opt-in] stewie/server/test_fresh_wheel.py" in r.stdout
    assert "OK: required tiers visible: chrono, godot, ros" in r.stdout


def test_require_fails_loud_on_a_missing_tier():
    r = subprocess.run([sys.executable, _SCRIPT, "--require", "warpdrive",
                        "stewie/server/test_fresh_wheel.py"],
                       capture_output=True, text=True, cwd=_ROOT)
    assert r.returncode != 0
    assert "warpdrive" in (r.stdout + r.stderr)
