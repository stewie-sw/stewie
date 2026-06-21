"""Shared lock + pyproject parsing for the OPS-03 dependency-hardening tools.

Parses `uv pip compile`-style `requirements-*.lock` files (pinned `name==version`, optional PEP 508
environment markers, indented `--hash=sha256:...` continuation lines) and the `[project]` dependency
declarations in `pyproject.toml`. No network, no install — pure text over the real checked-in
artifacts. Used by gen_sbom.py, check_deps_lock.py, and fresh_install_smoke.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

try:  # stdlib on >=3.11; the `tomli` backport is a declared dep for <3.11
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib  # type: ignore[no-redef]

# `name==version` optionally followed by ` ; <marker>` then a trailing ` \` line-continuation.
_PIN_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;\\]+)"
    r"(?:\s*;\s*(?P<marker>[^\\]+?))?\s*\\?\s*$"
)
_HASH_RE = re.compile(r"--hash=sha256:(?P<sha>[0-9a-f]{64})")
# strip a PEP 508 requirement string down to its normalized distribution name (+ optional marker)
_REQ_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def req_marker(req: str) -> str | None:
    """Return the PEP 508 environment marker of a requirement string, if any (text after ';')."""
    if ";" in req:
        return req.split(";", 1)[1].strip() or None
    return None


def marker_applies(marker: str | None) -> bool:
    """Evaluate a PEP 508 environment marker for the current interpreter.

    No marker -> applies. If `packaging` is unavailable or the marker is unparseable, default to
    True (do not false-exclude a dep). `packaging` ships with pip/setuptools in any real env.
    """
    if not marker:
        return True
    try:
        from packaging.markers import Marker  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover - packaging present in real envs
        return True
    try:
        return bool(Marker(marker).evaluate())
    except Exception:  # pragma: no cover - tolerate exotic markers rather than false-fail
        return True


def normalize(name: str) -> str:
    """PEP 503 normalized project name (lowercase, runs of -_. collapsed to a single -)."""
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass
class LockedPackage:
    name: str               # PEP 503 normalized
    version: str            # exact pin (no specifiers)
    marker: str | None = None
    hashes: list[str] = field(default_factory=list)   # sha256 hex digests


def parse_lock(path: str) -> list[LockedPackage]:
    """Parse a pinned requirements lock into deduplicated, name-sorted LockedPackage records.

    A pinned line opens a package; subsequent indented `--hash=` lines attach to it until the next
    pinned line. Comment lines (`#`, including the `# via ...` provenance) and blanks are ignored.
    """
    pkgs: dict[str, LockedPackage] = {}
    current: LockedPackage | None = None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _PIN_RE.match(line)
        if m and not line[:1].isspace():
            name = normalize(m.group("name"))
            marker = m.group("marker")
            current = pkgs.get(name)
            if current is None:
                current = LockedPackage(name=name, version=m.group("version"),
                                        marker=marker.strip() if marker else None)
                pkgs[name] = current
            continue
        # continuation: hash lines for the current package
        hm = _HASH_RE.search(stripped)
        if hm and current is not None:
            current.hashes.append(hm.group("sha"))
    return sorted(pkgs.values(), key=lambda p: p.name)


@dataclass
class PyprojectDeps:
    base: set[str]                  # normalized names from [project].dependencies
    extras: dict[str, set[str]]     # extra-name -> normalized dep names
    markers: dict[str, str | None] = field(default_factory=dict)  # normalized name -> marker text


def _req_to_name(req: str) -> str | None:
    m = _REQ_NAME_RE.match(req)
    return normalize(m.group(1)) if m else None


def parse_pyproject(path: str) -> PyprojectDeps:
    """Extract base + optional-dependency names (normalized) + per-dep env markers from pyproject."""
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    proj = data.get("project", {})
    markers: dict[str, str | None] = {}

    def _names(reqs: list[str]) -> set[str]:
        out: set[str] = set()
        for r in reqs:
            n = _req_to_name(r)
            if n:
                out.add(n)
                markers[n] = req_marker(r)
        return out

    base = _names(proj.get("dependencies", []))
    extras = {extra: _names(reqs) for extra, reqs in proj.get("optional-dependencies", {}).items()}
    return PyprojectDeps(base=base, extras=extras, markers=markers)
