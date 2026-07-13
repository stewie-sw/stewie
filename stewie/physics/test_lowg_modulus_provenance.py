"""[REQ:PX-08] The low-gravity Bekker-modulus provenance lock: the shipped moduli ARE the sourced LUNAR
reference, and nothing may Lyasko-reduce them a second time.

Gate on exit code: pytest stewie/physics/test_lowg_modulus_provenance.py

WHY THIS FILE EXISTS. The repo carried a live contradiction about a single number (k_phi = 820 000):

  * `stewie/specs/constants.py` labelled it an "Earth/Apollo-era value" whose low-g drop was "NOT
    applied" -- i.e. a 1 g value still awaiting a reduction;
  * `stewie/physics/body_params.py` (PHYS-01, audit 2026-06-11) said it is ALREADY the lunar value and
    must NOT be reduced;
  * `TerramechanicsParams.lunar()` resolved the ambiguity the WRONG way -- it applied
    `lyasko_reduce(from_constants())` and its docstring said "Use for lunar runs".

`DEFERRED_FIXES.md` FIX-6 settles it from the source: the NASA LTV terramechanics white paper
(NTRS 20220010732) publishes k_phi=820 000 Pa/m^n, k_c=1400, n=1.0, c=170 Pa **as the LUNAR reference
values**. They are already lunar. So `from_constants()` is the correct lunar set, and reducing it again
double-counts gravity: `.lunar()` returned k_phi=614 624 (-25%) and cohesion=127.4 (-25%), which
UNDERSTATES the frictional modulus and therefore OVERSTATES sinkage on every absolute number the sim
reports (sinkage, slope limits, slip, entrapment). The drive path never called `.lunar()`, so the shipped
numbers were right -- but the footgun was one honest mistake away from silently corrupting all of them.

These are the invariants that keep that from coming back. They are cheap, and they protect every
absolute terramechanics figure the product publishes.
"""
from __future__ import annotations

import ast
from pathlib import Path

from stewie.physics import terramechanics as tm
from stewie.specs import constants as K

REPO = Path(__file__).resolve().parents[2]

#: The NASA LTV terramechanics white paper (NTRS 20220010732) LUNAR reference set. These are the values
#: the sim must run with -- unreduced. (Sourced, not [CALIB]-guessed; see DEFERRED_FIXES.md FIX-6.)
LTV_LUNAR = {"k_phi": 820_000.0, "k_c": 1400.0, "n_sinkage": 1.0, "cohesion": 170.0}


def test_shipped_constants_are_the_sourced_lunar_reference() -> None:
    """[REQ:PX-08] The constants ARE the NTRS 20220010732 lunar set (not an Earth-era set)."""
    assert K.K_PHI == LTV_LUNAR["k_phi"]
    assert K.K_C == LTV_LUNAR["k_c"]
    assert K.N_SINKAGE == LTV_LUNAR["n_sinkage"]
    assert K.COHESION == LTV_LUNAR["cohesion"]


def test_drive_path_default_params_are_lunar_and_not_reduced() -> None:
    """[REQ:PX-08] `from_constants()` is what the drive path uses when no params are passed
    (rover/drive default). It must equal the sourced LUNAR set, and must NOT already be Lyasko-reduced."""
    p = tm.TerramechanicsParams.from_constants()
    assert p.k_phi == LTV_LUNAR["k_phi"], "the drive path's default k_phi is not the sourced lunar value"
    assert p.cohesion == LTV_LUNAR["cohesion"]

    # Not-already-reduced: applying the correction WOULD move it (so the default is the unreduced set),
    # and the reduced set is strictly weaker -> more sinkage. If the default were silently pre-reduced,
    # k_phi would already sit at the reduced value and this would catch it.
    reduced = tm.lyasko_reduce(p)
    assert reduced.k_phi < p.k_phi, "lyasko_reduce is a no-op: the default may already be reduced"
    assert p.k_phi > reduced.k_phi and p.cohesion > reduced.cohesion


def test_the_double_reduce_footgun_constructor_is_gone() -> None:
    """[REQ:PX-08] `TerramechanicsParams.lunar()` applied the gravity correction to values that ALREADY
    encode it (a 25% k_phi understatement) while telling callers it was the lunar set. It must not exist:
    the lunar set IS `from_constants()`. Keep `lyasko_reduce()` itself -- it is a sourced, legitimate tool
    for an Earth-fit modulus set -- but no constructor may hand back a double-reduced 'lunar' set."""
    assert not hasattr(tm.TerramechanicsParams, "lunar"), (
        "TerramechanicsParams.lunar() is back. It double-counts gravity (FIX-6): the shipped constants are "
        "already the NTRS 20220010732 LUNAR reference, so the lunar set is from_constants(), unreduced.")


def test_no_production_code_lyasko_reduces_the_shipped_moduli() -> None:
    """[REQ:PX-08] The anti-regression lock. `lyasko_reduce` stays available as a tool, but NO production
    module may call it -- doing so would re-apply a gravity correction the shipped moduli already carry.
    (Tests and the module that DEFINES it are exempt. If a future body genuinely ships an Earth-fit modulus
    set that needs reducing, this guard is the place to make that a conscious, documented decision.)"""
    roots = [REPO / "stewie", REPO / "packages" / "stewie-forge", REPO / "lode", REPO / "dart", REPO / "leap"]
    definer = "terramechanics.py"          # the module that defines lyasko_reduce (and re-export shims)
    offenders: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for py in root.rglob("*.py"):
            parts = py.parts
            if any(p in ("build", ".venv", "__pycache__") for p in parts):
                continue
            if py.name.startswith("test_") or py.name == definer:
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = (fn.attr if isinstance(fn, ast.Attribute)
                        else fn.id if isinstance(fn, ast.Name) else None)
                if name == "lyasko_reduce":
                    offenders.append(f"{py.relative_to(REPO)}:{node.lineno}")
    assert offenders == [], (
        "production code applies lyasko_reduce to the shipped moduli, double-counting gravity (FIX-6) and "
        f"overstating sinkage/slip everywhere: {offenders}")
