"""[REQ:BD-04] The body registry (`stewie.specs.bodies`) imports NO `stewie.physics` at module level — the
prerequisite for shipping `stewie-bodies` as a zero-STEWIE-dependency package. `params_for_body` remains a
working lazy compatibility wrapper with unchanged values + microgravity fail-closed behaviour (the
body->terramechanics conversion moved to `stewie.physics.body_params`, forge/physics -> bodies direction)."""
import subprocess
import sys

import pytest

from stewie.specs import bodies as B


def test_bodies_module_imports_no_stewie_physics():  # [REQ:BD-04]
    # in a FRESH interpreter, importing stewie.specs.bodies must NOT pull in stewie.physics (the inverted edge).
    code = ("import stewie.specs.bodies, sys; "
            "leak=[m for m in sys.modules if m == 'stewie.physics' or m.startswith('stewie.physics.')]; "
            "sys.exit('LEAK ' + ','.join(leak) if leak else 0)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, f"stewie.specs.bodies leaked a stewie.physics import: {r.stdout}{r.stderr}"


def test_params_for_body_compat_values_unchanged():  # [REQ:BD-04]
    # the lazy compat wrapper still returns the body's SOURCED params, values unchanged.
    p = B.params_for_body("moon")
    assert type(p).__name__ == "TerramechanicsParams"
    assert p.k_phi == 820000.0            # NASA LTV lunar value, carried through the wrapper unchanged


def test_microgravity_fail_closed_unchanged():  # [REQ:BD-04]
    with pytest.raises(ValueError):
        B.params_for_body("bennu")                     # microgravity refuses by default (out of regime)
    B.params_for_body("bennu", allow_analog=True)      # explicit analog is allowed (unchanged behaviour)
