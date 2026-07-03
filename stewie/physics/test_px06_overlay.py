"""[REQ:PX-06] The terramechanics->constants edge-break with config-overlay PRESERVED via injection.

`stewie.physics.terramechanics` carries forge-local literal geotech defaults (so it imports no
`stewie.specs.constants` -> `stewie-forge` can be bodies+numeric only). The `stewie.specs.config` overlay that
`constants` applies is re-injected on the stewie side (`params_for_body`) at CALL time, so a config override of
a geotech constant still reaches the built params. Behavior is byte-identical for the no-override case (the
literals equal the current constants), and MORE robust for overrides (call-time vs import-time binding).
"""
import ast
import pathlib

from stewie.physics.terramechanics import TerramechanicsParams

_TERRA = pathlib.Path(__file__).resolve().parent / "terramechanics.py"


def test_px06_terramechanics_imports_no_constants():  # [REQ:PX-06]
    bad = []
    for node in ast.parse(_TERRA.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom):
            mod, names = node.module or "", [a.name for a in node.names]
            if (mod == "stewie.specs" and "constants" in names) or mod.startswith("stewie.specs.constants"):
                bad.append(f"from {mod} import {names}")
        elif isinstance(node, ast.Import):
            bad += [f"import {a.name}" for a in node.names if a.name.startswith("stewie.specs.constants")]
    assert not bad, f"terramechanics still imports stewie.specs.constants at module level: {bad}"


def test_px06_from_constants_values_unchanged():  # [REQ:PX-06]
    # byte-identical: the forge-local literals equal the constants.py values (no active override today).
    p = TerramechanicsParams.from_constants()
    assert (p.k_c, p.k_phi, p.n_sinkage) == (1400.0, 820000.0, 1.0)
    assert (p.cohesion, p.k_shear) == (170.0, 0.018)
    assert (p.slip_c1, p.slip_c2) == (0.4, 0.3)
    assert (p.rho_surface, p.rho_deep, p.rover_mass_dry_kg) == (1300.0, 1920.0, 30.0)


def test_px06_config_override_reaches_params_via_injection(monkeypatch):  # [REQ:PX-06]
    # k_shear is NOT body-overridden for the Moon, so it flows from the injected (config-overlayable) constants.
    from stewie.specs import bodies as B
    from stewie.specs import constants as K
    monkeypatch.setattr(K, "K_SHEAR", 0.999, raising=True)
    assert B.params_for_body("moon").k_shear == 0.999, "config override did not reach built params via injection"
