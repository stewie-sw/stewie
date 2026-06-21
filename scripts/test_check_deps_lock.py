"""OPS-03 (PRD §27.2.A / PO-05) — acceptance test for the dependency-lock consistency check.

`scripts/check_deps_lock.py` asserts that every runtime/dev dependency declared in `pyproject.toml`
is actually pinned in the corresponding `requirements-*.lock`. It fails on drift (a declared dep
missing from the lock), which is how a stale lock is caught in CI. Tests run against the real
checked-in pyproject + locks, plus tiny in-memory fixtures for the drift/clean branches.

[REQ:PO-05]
"""
from __future__ import annotations

import importlib.util
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CHECK = os.path.join(_ROOT, "scripts", "check_deps_lock.py")
_PYPROJECT = os.path.join(_ROOT, "pyproject.toml")
_DEV_LOCK = os.path.join(_ROOT, "requirements-dev.lock")
_SERVER_LOCK = os.path.join(_ROOT, "requirements-server.lock")


def _load_module():
    import sys
    spec = importlib.util.spec_from_file_location("check_deps_lock", _CHECK)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # so dataclasses can resolve cls.__module__ under PEP 563
    spec.loader.exec_module(mod)
    return mod


def test_parse_pyproject_deps_extracts_base_and_extras():
    mod = _load_module()
    deps = mod.parse_pyproject_deps(_PYPROJECT)
    # base runtime deps
    assert "numpy" in deps["base"]
    assert "gymnasium" in deps["base"]
    # extras are keyed by name
    assert "dev" in deps["extras"]
    assert "pytest" in deps["extras"]["dev"]
    assert "server" in deps["extras"]
    assert "fastapi" in deps["extras"]["server"]
    # names are PEP 503 normalized (no version specifiers, no markers)
    for grp in [deps["base"], *deps["extras"].values()]:
        for n in grp:
            assert n == n.lower()
            assert all(c not in n for c in "<>=~; ")


def test_real_dev_lock_covers_base_plus_dev_extra():
    """The shipped dev lock must cover base + the dev extra: no drift on the real artifacts."""
    mod = _load_module()
    result = mod.check_lock(_PYPROJECT, _DEV_LOCK, extras=["dev"])
    assert result.missing == [], f"dev lock missing declared deps: {result.missing}"
    assert result.ok


def test_real_server_lock_covers_base_plus_server_extra():
    mod = _load_module()
    result = mod.check_lock(_PYPROJECT, _SERVER_LOCK, extras=["server"])
    assert result.missing == [], f"server lock missing declared deps: {result.missing}"
    assert result.ok


def test_drift_is_detected(tmp_path):
    """A declared dep absent from the lock is flagged (the failure path CI relies on)."""
    mod = _load_module()
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        '[project]\n'
        'name = "x"\n'
        'version = "0"\n'
        'dependencies = ["numpy>=1.21", "scipy>=1.7", "totally-not-installed-pkg>=1.0"]\n'
    )
    lock = tmp_path / "req.lock"
    lock.write_text("numpy==1.26.4\nscipy==1.13.0\n")
    result = mod.check_lock(str(pp), str(lock), extras=[])
    assert not result.ok
    assert "totally-not-installed-pkg" in result.missing


def test_clean_when_lock_covers_all(tmp_path):
    mod = _load_module()
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        '[project]\n'
        'name = "x"\n'
        'version = "0"\n'
        'dependencies = ["numpy>=1.21", "scipy>=1.7"]\n'
    )
    lock = tmp_path / "req.lock"
    lock.write_text("numpy==1.26.4\nscipy==1.13.0\nextra-transitive==2.0\n")
    result = mod.check_lock(str(pp), str(lock), extras=[])
    assert result.ok
    assert result.missing == []


def test_main_passes_on_real_artifacts():
    mod = _load_module()
    rc = mod.main(["--pyproject", _PYPROJECT,
                   "--lock", _DEV_LOCK, "--extras", "dev"])
    assert rc == 0


def test_main_fails_on_drift(tmp_path):
    mod = _load_module()
    pp = tmp_path / "pyproject.toml"
    pp.write_text('[project]\nname="x"\nversion="0"\ndependencies = ["ghost-dep>=1"]\n')
    lock = tmp_path / "req.lock"
    lock.write_text("numpy==1.26.4\n")
    rc = mod.main(["--pyproject", str(pp), "--lock", str(lock)])
    assert rc == 1
