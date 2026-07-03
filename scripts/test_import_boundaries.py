"""[REQ:PX-05] Production physics import boundary. The production `stewie/physics` modules import NO `dart` or
`leap`, so the eventual `stewie-forge` package needs neither. This corrects the stale docs claim that
production physics imported dart/leap -- verified: only THREE test files couple (test_constrained_skill,
test_drum_sensing, test_slam04_fk_authority), and test files are outside the package unit gate. This is the
executable guard: a future production back-edge fails here.
"""
import ast
import pathlib
import re

_PHYS = pathlib.Path(__file__).resolve().parent.parent / "stewie" / "physics"
_BAD = re.compile(r"^\s*(?:from|import)\s+(dart|leap)\b", re.M)


def test_production_physics_imports_no_dart_or_leap():  # [REQ:PX-05]
    offenders = []
    for f in sorted(_PHYS.glob("*.py")):
        if f.name.startswith("test_"):          # test files are outside the stewie-forge package unit gate
            continue
        m = _BAD.search(f.read_text(encoding="utf-8"))
        if m:
            offenders.append(f"{f.name}: {m.group(0).strip()!r}")
    assert not offenders, (
        "production stewie/physics imports dart/leap (breaks the stewie-forge package boundary): "
        + "; ".join(offenders))


def test_bodies_registry_imports_no_stewie_physics():  # [REQ:PX-05]
    # cross-guard with BD-04: the body registry stays free of stewie.physics at module level.
    src = (_PHYS.parent / "specs" / "bodies.py").read_text(encoding="utf-8")
    # a runtime `import stewie.physics` line (NOT inside `if TYPE_CHECKING:`) would be a back-edge.
    runtime = [ln for ln in src.splitlines()
               if re.match(r"^(?:from|import)\s+stewie\.physics", ln)]
    assert not runtime, f"stewie.specs.bodies has a runtime stewie.physics import: {runtime}"


# ---- [REQ:AP-01] core <-> dart/leap cycle break -------------------------------------------------
_ROOT = pathlib.Path(__file__).resolve().parent.parent
_AP01_COMPOSERS = ["stewie/runtime/nav_loop.py", "stewie/runtime/replay_loop.py",
                   "stewie/server/routers/evidence.py", "stewie/server/routers/siteplan.py"]


def _module_level_pkg_imports(path: pathlib.Path, pkgs: set) -> list:
    """Top-level (module-LOAD) imports of any package in `pkgs`. AST-based on `tree.body`, so docstrings,
    comments, `if TYPE_CHECKING:` blocks, and function-level lazy imports are all correctly EXCLUDED (none
    of those live in the module body)."""
    bad = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in pkgs:
            bad.append(f"{path.name}: from {node.module}")
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in pkgs:
                    bad.append(f"{path.name}: import {a.name}")
    return bad


def test_ap01_app_composers_have_no_module_level_dart_leap():  # [REQ:AP-01]
    offenders = []
    for rel in _AP01_COMPOSERS:
        offenders += _module_level_pkg_imports(_ROOT / rel, {"dart", "leap"})
    assert not offenders, ("app-layer composer has a module-level dart/leap import (core<->dart/leap cycle): "
                           + "; ".join(offenders))


# ---- [REQ:PO-16] package import-DAG policy ------------------------------------------------------
def test_po16_forge_imports_only_bodies_and_numeric():  # [REQ:PO-16]
    """stewie-forge (forge/* +, later, the pure physics geotech) may import ONLY stewie-bodies + the numeric
    stack -- never dart/lode/leap or stewie-core/server. Encoded so the PO-17/18 extraction stays acyclic."""
    offenders = []
    for f in sorted((_ROOT / "forge").glob("*.py")):
        if f.name.startswith("test_"):
            continue
        for node in ast.parse(f.read_text(encoding="utf-8")).body:
            mods = ([node.module] if isinstance(node, ast.ImportFrom) and node.module
                    else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            for m in mods:
                top = m.split(".")[0]
                if top in ("dart", "lode", "leap"):
                    offenders.append(f"{f.name}: {m}")
                elif top == "stewie" and not m.startswith("stewie.specs"):
                    offenders.append(f"{f.name}: {m} (forge may import only stewie.specs bodies)")
    assert not offenders, "stewie-forge DAG violation (forge -> bodies+numeric only): " + "; ".join(offenders)


# ---- [REQ:PO-17] stewie-bodies extraction (standalone package + shim identity) ------------------
def test_po17_stewie_bodies_is_zero_stewie_dependency():  # [REQ:PO-17]
    """The extracted stewie-bodies package imports NOTHING from the STEWIE monorepo -- standalone + citable."""
    pkg = _ROOT / "packages" / "stewie-bodies" / "stewie_bodies"
    offenders = []
    for f in sorted(pkg.glob("*.py")):
        for node in ast.parse(f.read_text(encoding="utf-8")).body:
            mods = ([node.module] if isinstance(node, ast.ImportFrom) and node.module
                    else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            for m in mods:
                if m.split(".")[0] in ("stewie", "dart", "lode", "leap", "forge"):
                    offenders.append(f"{f.name}: {m}")
    assert not offenders, "stewie-bodies is not standalone (imports the monorepo): " + "; ".join(offenders)


def test_po17_shim_reexports_the_package_objects():  # [REQ:PO-17]
    """stewie.specs.bodies (shim) re-exports the SAME objects as stewie_bodies -- single source, no copy/drift."""
    import stewie_bodies
    from stewie.specs import bodies as shim
    assert shim.BODIES is stewie_bodies.BODIES
    assert shim.get_body is stewie_bodies.get_body
    assert shim.Body is stewie_bodies.Body
