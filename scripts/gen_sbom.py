#!/usr/bin/env python3
"""OPS-03 (PRD §27.2.A / PO-05) — emit a CycloneDX 1.5 SBOM from the real dependency lock.

Generates a Software Bill of Materials directly from a pinned `requirements-*.lock`
(`uv pip compile --generate-hashes`). Every component is a package actually present in the lock,
with its pinned version and pinned SHA-256 hashes — no fabricated entries. A real CycloneDX library
is not a project dependency, so we emit the (small, well-specified) CycloneDX 1.5 JSON ourselves
rather than stub anything. The output validates against the CycloneDX 1.5 JSON shape consumed by
common scanners (grype/trivy/dependency-track).

Usage:
    python3 scripts/gen_sbom.py --lock requirements-dev.lock -o sbom.json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _deps_lock import LockedPackage, parse_lock  # noqa: E402

__all__ = ["LockedPackage", "parse_lock", "build_sbom", "main"]

_SPEC_VERSION = "1.5"
_TOOL_VERSION = "1.0.0"


def _project_version(root: str) -> str:
    """Read the stewie version from pyproject.toml (no fabricated version)."""
    pp = os.path.join(root, "pyproject.toml")
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - 3.10 path
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        with open(pp, "rb") as fh:
            return str(tomllib.load(fh).get("project", {}).get("version", "0"))
    except OSError:  # pragma: no cover - root without pyproject
        return "0"


def build_sbom(packages: list[LockedPackage], *, source_name: str,
               root: str | None = None) -> dict:
    """Assemble a CycloneDX 1.5 JSON document from parsed lock packages."""
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    components = []
    for p in packages:
        comp: dict = {
            "type": "library",
            "bom-ref": f"pkg:pypi/{p.name}@{p.version}",
            "name": p.name,
            "version": p.version,
            "purl": f"pkg:pypi/{p.name}@{p.version}",
        }
        if p.hashes:
            comp["hashes"] = [{"alg": "SHA-256", "content": h} for h in p.hashes]
        if p.marker:
            comp["properties"] = [{"name": "pep508:marker", "value": p.marker}]
        components.append(comp)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": _SPEC_VERSION,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": now,
            "tools": {
                "components": [
                    {"type": "application", "name": "gen_sbom", "version": _TOOL_VERSION,
                     "group": "stewie"},
                ]
            },
            "component": {
                "type": "application",
                "bom-ref": "stewie",
                "name": "stewie",
                "version": _project_version(root),
            },
            "properties": [
                {"name": "stewie:sbom:source", "value": source_name},
            ],
        },
        "components": components,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="emit a CycloneDX SBOM from a pinned requirements lock")
    ap.add_argument("--lock", required=True, help="path to a requirements-*.lock file")
    ap.add_argument("--name", default=None, help="logical source name recorded in the SBOM metadata")
    ap.add_argument("-o", "--output", default="-", help="output path ('-' = stdout)")
    args = ap.parse_args(argv)

    packages = parse_lock(args.lock)
    if not packages:
        print(f"ERROR: no pinned packages parsed from {args.lock}", file=sys.stderr)
        return 1
    doc = build_sbom(packages, source_name=args.name or os.path.basename(args.lock))
    text = json.dumps(doc, indent=2, sort_keys=False)
    if args.output == "-":
        print(text)
    else:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {len(doc['components'])} components -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
