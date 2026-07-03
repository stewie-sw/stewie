"""[REQ:PX-05] Production physics import boundary. The production `stewie/physics` modules import NO `dart` or
`leap`, so the eventual `stewie-forge` package needs neither. This corrects the stale docs claim that
production physics imported dart/leap -- verified: only THREE test files couple (test_constrained_skill,
test_drum_sensing, test_slam04_fk_authority), and test files are outside the package unit gate. This is the
executable guard: a future production back-edge fails here.
"""
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
