#!/usr/bin/env python3
"""Assemble the sanitized PUBLIC cut of the STEWIE monorepo.

PUBLICATION BOUNDARY: everything listed in the DART provenance manifest (the research track fold),
the evaluation gates + evidence (stewie/eval), and files that ABSORBED research track code in the M3
merges are EXCLUDED. The output tree is the dustgym-heritage platform + John's demo + deploy/docs.
Run: python scripts/build_public_cut.py [dest]   (default ../public_cut, OUTSIDE the repo)
"""
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "..", "public_cut")
MANIFEST = os.path.join(ROOT, "..", "design", "SOLNAV_PROVENANCE_MANIFEST.md")

# research track-derived module paths (new-side column of the manifest table)
excluded = set()
for line in open(MANIFEST):
    m = re.match(r"\| \S+ \| (\S+\.py) \|", line)
    if m:
        excluded.add(m.group(1))
# files that ABSORBED research track code in M3 (split pending; excluded wholesale for v1)
excluded |= {"dart/localization.py", "stewie/twin/world_model.py"}
# their colocated tests + everything under stewie/eval + the research track-data dirs
EXCLUDE_DIRS = ("stewie/eval", "stewie/bridge", "stewie/sensors", ".git", "__pycache__",
                "papers", "viz/private")

INCLUDE_TOP = ["stewie", "dart", "lode", "leap", "forge", "dustgym", "scripts", "samples",
               "deploy", "docs", ".github", "PRD.md", "README.md", "LICENSE", "CITATION.cff",
               "pyproject.toml", "INTERFACE.md", "CONFIG.md", "CONTRIBUTING.md", "SECURITY.md",
               "AGENTS.md", "ARTIFACTS.md", "THIRD_PARTY.md", "ipex-terrain-sim-spec.md",
               "requirements_manifest.yaml", "validation"]

def want(rel):
    if any(rel == d or rel.startswith(d + "/") for d in EXCLUDE_DIRS):
        return False
    if rel in excluded:
        return False
    base = os.path.basename(rel)
    if base.startswith("test_") and rel.endswith(".py"):
        subject = rel.replace("test_", "", 1)
        if subject in excluded or subject.replace("_ported.py", ".py") in excluded:
            return False
        # a test whose imports reach an excluded module cannot stand in the cut
        try:
            head = open(os.path.join(ROOT, rel)).read(4000)
        except OSError:
            return True
        names = {os.path.splitext(os.path.basename(e))[0] for e in excluded}
        for n in names:
            if re.search(rf"\bimport {n}\b|\b{n} import\b|from dart import .*\b{n}\b", head):
                return False
        if "dart.geometry" in head or "from stewie.specs.profiles" in head or "stewie.eval" in head:
            return False
    return True

copied = skipped = 0
if os.path.isdir(DEST):
    shutil.rmtree(DEST)
for top in INCLUDE_TOP:
    src = os.path.join(ROOT, top)
    if not os.path.exists(src):
        continue
    if os.path.isfile(src):
        os.makedirs(DEST, exist_ok=True)
        shutil.copy2(src, os.path.join(DEST, top)); copied += 1
        continue
    for dirpath, dirnames, filenames in os.walk(src):
        rel_dir = os.path.relpath(dirpath, ROOT)
        dirnames[:] = [d for d in dirnames if want(os.path.join(rel_dir, d))]
        for fn in filenames:
            rel = os.path.join(rel_dir, fn)
            if want(rel):
                dst = os.path.join(DEST, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(os.path.join(ROOT, rel), dst); copied += 1
            else:
                skipped += 1
print(f"public cut -> {os.path.abspath(DEST)}: {copied} files copied, {skipped} excluded")
print("EXCLUDED CLASSES: provenance-manifest modules + tests, stewie/eval (gates+evidence),")
print("stewie/bridge + stewie/sensors (research track IO), M3-merged files (localization, world_model)")
