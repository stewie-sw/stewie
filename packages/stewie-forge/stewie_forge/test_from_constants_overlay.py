"""SR-16 [REQ:PX-06]: TerramechanicsParams.from_constants() must actually read the constants.

It returned a bare `cls()` -- the forge-local literals -- so it silently ignored every overlay. Measured
by the 2026-07-28 review with `STEWIE_K_PHI=200000`:

    K.K_PHI                     -> 200000.0   (the overlay IS applied to constants)
    costmap sinkage z           -> 0.003154   (up 3.9x; lode/costmap_layers.py reads K.K_PHI directly)
    drive telemetry sinkage_m   -> 0.0020787124347399722   -- BIT-IDENTICAL to the un-overridden run

So the planner routed around soft ground the simulation never experienced, the two halves of the system
disagreed about the soil, and `/config` reported the override as applied. The dataclass comment even
asserted the overlay "still reaches the built params". It did not.

The package must stay standalone (bodies + numeric only), so STEWIE is a SOFT dependency: constants win
when importable, forge-local literals otherwise. Both paths are pinned here.

Run: <venv>/bin/python -m pytest packages/stewie-forge/stewie_forge/test_from_constants_overlay.py -q
"""
from __future__ import annotations

import subprocess
import sys

from stewie_forge import terramechanics as tm


def test_defaults_are_unchanged_without_an_overlay():
    """Back-compat: the canonical lunar values (constants.py provenance) still come out."""
    p = tm.TerramechanicsParams.from_constants()
    assert p.k_phi == 820000.0 and p.k_c == 1400.0 and p.cohesion == 170.0
    assert abs(p.phi_rad - 0.6457718232379019) < 1e-12      # 37 deg


def test_from_constants_tracks_the_constants_module(monkeypatch):
    """The mechanism: from_constants must READ stewie.specs.constants, not shadow it."""
    from stewie.specs import constants as K
    monkeypatch.setattr(K, "K_PHI", 200000.0)
    monkeypatch.setattr(K, "COHESION", 250.0)
    p = tm.TerramechanicsParams.from_constants()
    assert p.k_phi == 200000.0, "the constants overlay still does not reach the built params"
    assert p.cohesion == 250.0


def test_planner_and_drive_agree_about_the_soil(monkeypatch):
    """The actual requirement. The costmap reads K.K_PHI directly; the drive loop builds params here.
    Whatever the value, those two must be the SAME number -- that is what was broken."""
    from stewie.specs import constants as K
    monkeypatch.setattr(K, "K_PHI", 200000.0)
    assert tm.TerramechanicsParams.from_constants().k_phi == K.K_PHI


def test_sinkage_actually_responds_to_the_override(monkeypatch):
    """Not just the field -- the physics the drive loop reports must move with it.

    Softer ground (lower k_phi) must sink a wheel FURTHER under the same load; a bit-identical result
    is the exact symptom the review measured.
    """
    from stewie.specs import constants as K
    base = tm.wheel_static_sinkage(75.0, params=tm.TerramechanicsParams.from_constants())
    monkeypatch.setattr(K, "K_PHI", 200000.0)
    soft = tm.wheel_static_sinkage(75.0, params=tm.TerramechanicsParams.from_constants())
    assert soft != base, "sinkage is bit-identical under a 4.1x soil override -- the params are inert"
    assert soft > base, f"softer ground sank less ({soft} <= {base})"


def test_standalone_package_falls_back_to_its_own_literals():
    """stewie-forge must keep working with no STEWIE on the path -- that is why the literals exist."""
    code = (
        "import sys\n"
        "for m in [m for m in list(sys.modules) if m.startswith('stewie.')]: sys.modules.pop(m, None)\n"
        "import builtins\n"
        "_real = builtins.__import__\n"
        "def _blocked(name, *a, **k):\n"
        "    if name == 'stewie' or name.startswith('stewie.'): raise ImportError('no stewie here')\n"
        "    return _real(name, *a, **k)\n"
        "builtins.__import__ = _blocked\n"
        "from stewie_forge import terramechanics as tm\n"
        "p = tm.TerramechanicsParams.from_constants()\n"
        "print(p.k_phi, p.k_c, p.cohesion)\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"standalone import broke: {r.stderr[-800:]}"
    vals = r.stdout.split()
    assert vals[:3] == ["820000.0", "1400.0", "170.0"], r.stdout
